"""Uncertainty calibration integration with existing probability calibration.

Implements:
- Integration of Transformer prediction intervals with existing ProbabilityCalibrator
- Temperature scaling for interval calibration
- Conformal prediction for adaptive intervals
- Uncertainty-aware probability calibration
- Calibration metrics and diagnostics

All outputs retain execution_permission: none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, Field

from atlas.ai.models.evaluation import ProbabilityCalibrator
from atlas.schemas import Probability, Record, Text


@dataclass(frozen=True)
class CalibrationConfig:
    """Configuration for uncertainty calibration."""
    
    method: Literal["temperature_scaling", "conformal", "isotonic"] = "conformal"
    alpha: float = 0.1  # For conformal prediction (1 - coverage)
    n_calibration_samples: int = 1000
    temperature_init: float = 1.0


class IntervalCalibrator(Record):
    """Calibrator for prediction intervals."""
    
    calibrator_id: Text
    instrument_id: Text
    horizon_id: Text
    model_revision: Text
    target: Text
    unit: Text
    fitted_through: AwareDatetime
    method: Literal["temperature_scaling", "conformal", "isotonic"]
    calibration_scores: tuple[float, ...]
    quantiles: tuple[float, ...]
    temperature: float = 1.0
    execution_permission: Literal["none"] = "none"
    
    @classmethod
    def fit_conformal(
        cls,
        *,
        predictions: np.ndarray,
        actuals: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        alpha: float = 0.1,
        **metadata,
    ) -> "IntervalCalibrator":
        """Fit conformal prediction calibrator.
        
        Args:
            predictions: Point predictions
            actuals: Actual values
            lower_bounds: Lower prediction bounds
            upper_bounds: Upper prediction bounds
            alpha: Significance level (1 - desired coverage)
            **metadata: Additional metadata
        
        Returns:
            Fitted IntervalCalibrator
        """
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        predictions = np.asarray(predictions, dtype=float)
        actuals = np.asarray(actuals, dtype=float)
        lower_bounds = np.asarray(lower_bounds, dtype=float)
        upper_bounds = np.asarray(upper_bounds, dtype=float)
        if not (
            predictions.shape
            == actuals.shape
            == lower_bounds.shape
            == upper_bounds.shape
        ):
            raise ValueError("Calibration arrays must share one shape")
        if len(actuals) < 2:
            raise ValueError("At least two calibration samples are required")
        if np.any(upper_bounds < lower_bounds):
            raise ValueError("upper_bounds must not be below lower_bounds")

        # Conformity score: how far the actual falls outside the interval.
        scores = np.maximum(actuals - upper_bounds, lower_bounds - actuals)
        scores = np.maximum(scores, 0.0)

        n = len(scores)
        quantile_level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
        quantile = float(np.quantile(scores, quantile_level))

        return cls(
            calibrator_id=f"interval_{metadata['model_revision']}",
            instrument_id=metadata["instrument_id"],
            horizon_id=metadata["horizon_id"],
            model_revision=metadata["model_revision"],
            target=metadata["target"],
            unit=metadata["unit"],
            fitted_through=metadata["fitted_through"],
            method="conformal",
            calibration_scores=tuple(float(score) for score in scores),
            quantiles=(quantile,),
        )
    
    def calibrate_interval(
        self,
        lower: float,
        upper: float,
        prediction: float,
    ) -> tuple[float, float]:
        """Calibrate a prediction interval.
        
        Args:
            lower: Lower bound
            upper: Upper bound
            prediction: Point prediction
        
        Returns:
            (calibrated_lower, calibrated_upper)
        """
        if self.method == "conformal" and self.quantiles:
            q = self.quantiles[0]
            # Adjust intervals by quantile
            calibrated_lower = lower - q
            calibrated_upper = upper + q
            return calibrated_lower, calibrated_upper
        
        return lower, upper
    
    def apply(
        self,
        lower: float,
        upper: float,
        prediction: float,
        *,
        as_of: datetime,
        instrument_id: str,
        horizon_id: str,
        model_revision: str,
        target: str,
        unit: str,
    ) -> tuple[float, float]:
        """Apply calibration with scope validation."""
        if as_of <= self.fitted_through:
            raise ValueError("Calibration leakage: as_of must be after fitted_through")
        
        if (instrument_id, horizon_id, model_revision, target, unit) != (
            self.instrument_id,
            self.horizon_id,
            self.model_revision,
            self.target,
            self.unit,
        ):
            raise ValueError("Calibration scope mismatch")
        
        return self.calibrate_interval(lower, upper, prediction)


class TemperatureScalingCalibrator(Record):
    """Temperature scaling for probability calibration."""
    
    calibrator_id: Text
    instrument_id: Text
    horizon_id: Text
    model_revision: Text
    target: Text
    unit: Text
    fitted_through: AwareDatetime
    temperature: float
    execution_permission: Literal["none"] = "none"
    
    @classmethod
    def fit(
        cls,
        *,
        probabilities: np.ndarray,
        outcomes: np.ndarray,
        temperature_init: float = 1.0,
        **metadata,
    ) -> "TemperatureScalingCalibrator":
        """Fit temperature scaling calibrator.
        
        Args:
            probabilities: Predicted probabilities
            outcomes: Binary outcomes (0 or 1)
            temperature_init: Initial temperature value
            **metadata: Additional metadata
        
        Returns:
            Fitted TemperatureScalingCalibrator
        """
        probabilities = np.asarray(probabilities, dtype=float)
        outcomes = np.asarray(outcomes, dtype=float)
        if probabilities.shape != outcomes.shape:
            raise ValueError("probabilities and outcomes must share one shape")
        if len(probabilities) < 2:
            raise ValueError("At least two calibration samples are required")
        if np.any(~np.isfinite(probabilities)) or np.any(
            (probabilities < 0) | (probabilities > 1)
        ):
            raise ValueError("probabilities must be finite and in [0, 1]")
        if np.any((outcomes != 0) & (outcomes != 1)):
            raise ValueError("outcomes must be binary")

        def brier(temperature_value: float) -> float:
            scaled = cls._scale_probabilities(
                np.clip(probabilities, 1e-8, 1 - 1e-8),
                temperature_value,
            )
            return float(np.mean((scaled - outcomes) ** 2))

        candidates = np.geomspace(0.05, 20.0, 81)
        losses = np.asarray([brier(float(value)) for value in candidates])
        best_index = int(np.argmin(losses))
        temperature = float(candidates[best_index])

        # Refine around the best grid point with a bounded golden-section search.
        lower = float(candidates[max(0, best_index - 1)])
        upper = float(candidates[min(len(candidates) - 1, best_index + 1)])
        phi = (math.sqrt(5.0) - 1.0) / 2.0
        c = upper - phi * (upper - lower)
        d = lower + phi * (upper - lower)
        for _ in range(40):
            if brier(c) < brier(d):
                upper = d
            else:
                lower = c
            c = upper - phi * (upper - lower)
            d = lower + phi * (upper - lower)
        refined = (lower + upper) / 2.0
        temperature = min(
            (temperature, float(temperature_init)),
            key=brier,
        ) if temperature_init and temperature_init > 0 else temperature
        if brier(refined) < brier(temperature):
            temperature = refined

        return cls(
            calibrator_id=f"temp_{metadata['model_revision']}",
            instrument_id=metadata["instrument_id"],
            horizon_id=metadata["horizon_id"],
            model_revision=metadata["model_revision"],
            target=metadata["target"],
            unit=metadata["unit"],
            fitted_through=metadata["fitted_through"],
            temperature=float(temperature),
        )
    
    @staticmethod
    def _scale_probabilities(probabilities: np.ndarray, temperature: float) -> np.ndarray:
        """Apply temperature scaling to probabilities."""
        # Logits = log(p / (1-p))
        logits = np.log(probabilities / (1 - probabilities + 1e-10))
        # Scale logits
        scaled_logits = logits / temperature
        # Convert back to probabilities
        scaled_probs = 1 / (1 + np.exp(-scaled_logits))
        return np.clip(scaled_probs, 0, 1)
    
    def apply(self, probability: float) -> float:
        """Apply temperature scaling to a probability."""
        scaled = self._scale_probabilities(np.array([probability]), self.temperature)
        return float(scaled[0])


class UncertaintyAwareCalibration(Record):
    """Combined calibration for both probabilities and intervals."""
    
    calibration_id: Text
    instrument_id: Text
    horizon_id: Text
    model_revision: Text
    probability_calibrator: ProbabilityCalibrator | None
    interval_calibrator: IntervalCalibrator | None
    temperature_calibrator: TemperatureScalingCalibrator | None
    fitted_through: AwareDatetime
    execution_permission: Literal["none"] = "none"
    
    def calibrate_forecast(
        self,
        probability_up: float | None,
        lower: float | None,
        upper: float | None,
        prediction: float,
    ) -> tuple[float | None, float | None, float | None]:
        """Calibrate a complete forecast.
        
        Args:
            probability_up: Probability of upward movement
            lower: Lower prediction bound
            upper: Upper prediction bound
            prediction: Point prediction
        
        Returns:
            (calibrated_probability, calibrated_lower, calibrated_upper)
        """
        calibrated_prob = probability_up
        calibrated_lower = lower
        calibrated_upper = upper
        
        # Calibrate probability
        if probability_up is not None and self.temperature_calibrator:
            calibrated_prob = self.temperature_calibrator.apply(probability_up)
        elif probability_up is not None and self.probability_calibrator:
            calibrated_prob = self.probability_calibrator.apply(
                probability_up,
                as_of=datetime.now(timezone.utc),
                instrument_id=self.instrument_id,
                horizon_id=self.horizon_id,
                model_revision=self.model_revision,
                target="return",
                unit="fraction",
            )
        
        # Calibrate interval
        if lower is not None and upper is not None and self.interval_calibrator:
            calibrated_lower, calibrated_upper = self.interval_calibrator.apply(
                lower,
                upper,
                prediction,
                as_of=datetime.now(timezone.utc),
                instrument_id=self.instrument_id,
                horizon_id=self.horizon_id,
                model_revision=self.model_revision,
                target="price",
                unit="usd",
            )
        
        return calibrated_prob, calibrated_lower, calibrated_upper
    
    @classmethod
    def fit(
        cls,
        *,
        probabilities: np.ndarray | None,
        outcomes: np.ndarray | None,
        predictions: np.ndarray,
        actuals: np.ndarray,
        lower_bounds: np.ndarray | None,
        upper_bounds: np.ndarray | None,
        config: CalibrationConfig,
        **metadata,
    ) -> "UncertaintyAwareCalibration":
        """Fit combined calibration system.
        
        Args:
            probabilities: Predicted probabilities (optional)
            outcomes: Binary outcomes (optional)
            predictions: Point predictions
            actuals: Actual values
            lower_bounds: Lower prediction bounds (optional)
            upper_bounds: Upper prediction bounds (optional)
            config: Calibration configuration
            **metadata: Additional metadata
        
        Returns:
            Fitted UncertaintyAwareCalibration
        """
        prob_calibrator = None
        temp_calibrator = None
        interval_calibrator = None
        
        # Fit probability calibration
        if probabilities is not None and outcomes is not None:
            if config.method == "temperature_scaling":
                temp_calibrator = TemperatureScalingCalibrator.fit(
                    probabilities=probabilities,
                    outcomes=outcomes,
                    temperature_init=config.temperature_init,
                    **metadata,
                )
            else:
                prob_calibrator = ProbabilityCalibrator.fit(
                    probabilities=probabilities,
                    outcomes=outcomes,
                    bins=5,
                    **metadata,
                )
        
        # Fit interval calibration
        if lower_bounds is not None and upper_bounds is not None:
            interval_calibrator = IntervalCalibrator.fit_conformal(
                predictions=predictions,
                actuals=actuals,
                lower_bounds=lower_bounds,
                upper_bounds=upper_bounds,
                alpha=config.alpha,
                **metadata,
            )
        
        return cls(
            calibration_id=f"uncertainty_{metadata['model_revision']}",
            instrument_id=metadata["instrument_id"],
            horizon_id=metadata["horizon_id"],
            model_revision=metadata["model_revision"],
            probability_calibrator=prob_calibrator,
            interval_calibrator=interval_calibrator,
            temperature_calibrator=temp_calibrator,
            fitted_through=metadata["fitted_through"],
        )


class CalibrationDiagnostics(Record):
    """Diagnostics for calibration quality."""
    
    calibration_id: Text
    expected_coverage: float
    actual_coverage: float
    coverage_error: float
    mean_interval_width: float
    sharpness: float
    reliability_diagram: tuple[tuple[float, float], ...]
    timestamp: AwareDatetime
    execution_permission: Literal["none"] = "none"
    
    @classmethod
    def compute(
        cls,
        calibration_id: str,
        predictions: np.ndarray,
        actuals: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        expected_coverage: float = 0.90,
    ) -> "CalibrationDiagnostics":
        """Compute calibration diagnostics.
        
        Args:
            calibration_id: Calibration identifier
            predictions: Point predictions
            actuals: Actual values
            lower_bounds: Lower prediction bounds
            upper_bounds: Upper prediction bounds
            expected_coverage: Expected coverage probability
        
        Returns:
            CalibrationDiagnostics report
        """
        # Compute actual coverage
        in_interval = (actuals >= lower_bounds) & (actuals <= upper_bounds)
        actual_coverage = np.mean(in_interval)
        coverage_error = abs(actual_coverage - expected_coverage)
        
        # Compute mean interval width
        interval_widths = upper_bounds - lower_bounds
        mean_width = np.mean(interval_widths)
        
        # Compute sharpness (inverse of width)
        sharpness = 1.0 / (mean_width + 1e-6)
        
        # Coverage by normalized interval-width decile. This is an interval
        # diagnostic, not a probability reliability curve.
        reliability_points = []
        scale = np.maximum(np.abs(predictions), 1e-12)
        normalized_width = interval_widths / scale
        if len(normalized_width) >= 10:
            edges = np.quantile(normalized_width, np.linspace(0, 1, 11))
            edges = np.unique(edges)
            for lower_edge, upper_edge in zip(edges[:-1], edges[1:]):
                mask = (
                    (normalized_width >= lower_edge)
                    & (normalized_width <= upper_edge)
                )
                if np.any(mask):
                    reliability_points.append(
                        (
                            float((lower_edge + upper_edge) / 2.0),
                            float(np.mean(in_interval[mask])),
                        )
                    )
        
        return cls(
            calibration_id=calibration_id,
            expected_coverage=expected_coverage,
            actual_coverage=float(actual_coverage),
            coverage_error=float(coverage_error),
            mean_interval_width=float(mean_width),
            sharpness=float(sharpness),
            reliability_diagram=tuple(reliability_points),
            timestamp=datetime.now(timezone.utc),
        )
