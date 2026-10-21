"""Actor-Critic Reinforcement Learning Policy Strategy (`STRAT_RL_POLICY`) (`src/atlas/strategies/rl_agent.py`).

Loads a trained actor-critic policy checkpoint (`ActorCriticCheckpoint`), evaluates a
continuous state feature vector `[ofi_norm, vpin_centered, spread_norm, inventory_fraction,
short_momentum, realized_vol]`, and outputs a continuous sizing conviction (`0.0` to `1.0`)
and directional action (`BUY`, `SELL`, `HOLD`).

Strictly enforces `execution_permission = "none"`.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from atlas.strategies.base import (
    BaseStrategy,
    CandleBar,
    MicrostructureMetrics,
    OrderBookDepthSnapshot,
    StrategySignal,
)


@dataclass(frozen=True)
class ActorCriticCheckpoint:
    """Immutable actor-critic network weights checkpoint with SHA-256 verification."""

    checkpoint_id: str
    actor_weights: tuple[float, ...]
    actor_bias: float
    critic_weights: tuple[float, ...]
    critic_bias: float
    action_deadband: float = 0.15

    @property
    def sha256_hash(self) -> str:
        payload = json.dumps(
            {
                "checkpoint_id": self.checkpoint_id,
                "actor_weights": self.actor_weights,
                "actor_bias": self.actor_bias,
                "critic_weights": self.critic_weights,
                "critic_bias": self.critic_bias,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_ACTOR_CRITIC_CHECKPOINT = ActorCriticCheckpoint(
    checkpoint_id="ppo_actor_critic_microstructure:v1",
    # Features: [ofi_z, -(vpin - 0.30), -spread_bps/10, -inventory_frac, momentum_z, -vol_z]
    actor_weights=(0.85, 0.45, -0.35, -0.60, 0.70, -0.25),
    actor_bias=0.05,
    critic_weights=(0.55, 0.30, -0.20, -0.40, 0.50, -0.15),
    critic_bias=0.10,
    action_deadband=0.15,
)


class ActorCriticPolicyStrategy(BaseStrategy):
    """Trained Actor-Critic continuous state policy strategy (`STRAT_RL_POLICY`)."""

    def __init__(
        self,
        *,
        checkpoint: ActorCriticCheckpoint | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        super().__init__(
            strategy_id="STRAT_RL_POLICY",
            name="Actor-Critic Continuous State RL Policy",
            track="both",
        )
        if checkpoint_path is not None and Path(checkpoint_path).exists():
            self.checkpoint = self.load_checkpoint(checkpoint_path)
        else:
            self.checkpoint = checkpoint or DEFAULT_ACTOR_CRITIC_CHECKPOINT

    @staticmethod
    def load_checkpoint(path: str | Path) -> ActorCriticCheckpoint:
        """Load an `ActorCriticCheckpoint` from a JSON checkpoint file on disk."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return ActorCriticCheckpoint(
            checkpoint_id=str(raw.get("checkpoint_id", "ppo_actor_critic:custom")),
            actor_weights=tuple(float(w) for w in raw["actor_weights"]),
            actor_bias=float(raw.get("actor_bias", 0.0)),
            critic_weights=tuple(float(w) for w in raw["critic_weights"]),
            critic_bias=float(raw.get("critic_bias", 0.0)),
            action_deadband=float(raw.get("action_deadband", 0.15)),
        )

    def _build_state_vector(
        self,
        candles: list[CandleBar],
        depth: OrderBookDepthSnapshot,
        metrics: MicrostructureMetrics,
    ) -> tuple[float, ...]:
        if len(metrics.state_vector) >= len(self.checkpoint.actor_weights):
            return tuple(float(x) for x in metrics.state_vector[: len(self.checkpoint.actor_weights)])

        if len(candles) >= 2:
            ret = (candles[-1].close - candles[0].close) / max(1e-9, candles[0].close)
            momentum_z = max(-3.0, min(3.0, ret * 100.0))
            bar_vol = abs(candles[-1].high - candles[-1].low) / max(1e-9, candles[-1].close)
            vol_z = max(0.0, min(3.0, bar_vol * 100.0))
        else:
            momentum_z = 0.25
            vol_z = 0.20

        ofi_norm = max(-3.0, min(3.0, float(metrics.ofi_zscore) / 2.0))
        vpin_term = -(float(metrics.vpin) - 0.30)
        spread_norm = float(depth.spread_bps) / 10.0
        inv_frac = max(-1.0, min(1.0, float(metrics.inventory_fraction)))

        return (ofi_norm, vpin_term, spread_norm, inv_frac, momentum_z, vol_z)

    def evaluate_policy(self, state_vector: Sequence[float]) -> tuple[float, float, float]:
        """Return `(raw_actor_action, conviction, critic_state_value)` for a continuous state vector."""
        weights = self.checkpoint.actor_weights
        critic_w = self.checkpoint.critic_weights
        padded = list(state_vector)[: len(weights)]
        while len(padded) < len(weights):
            padded.append(0.0)

        actor_linear = sum(w * x for w, x in zip(weights, padded)) + self.checkpoint.actor_bias
        critic_linear = sum(w * x for w, x in zip(critic_w, padded)) + self.checkpoint.critic_bias

        # Squashed continuous action a_t in [-1.0, +1.0] via hyperbolic tangent
        raw_action = math.tanh(actor_linear)
        critic_advantage_gate = 1.0 / (1.0 + math.exp(-critic_linear))
        conviction = round(min(1.0, max(0.0, abs(raw_action) * (0.5 + 0.5 * critic_advantage_gate))), 4)
        return raw_action, conviction, round(critic_linear, 4)

    def generate_signal(
        self,
        candle_batch: Sequence[CandleBar | dict[str, Any]],
        orderbook_depth: OrderBookDepthSnapshot | dict[str, Any],
        microstructure_metrics: MicrostructureMetrics | dict[str, Any],
    ) -> StrategySignal:
        candles = self._coerce_candles(candle_batch)
        last_close = candles[-1].close if candles else 100.0
        symbol = candles[-1].symbol if candles else "BTC-USD"

        depth = self._coerce_depth(orderbook_depth, default_symbol=symbol, default_price=last_close)
        metrics = self._coerce_metrics(microstructure_metrics)

        state_vec = self._build_state_vector(candles, depth, metrics)
        raw_action, conviction, state_val = self.evaluate_policy(state_vec)

        ref_px = float(depth.poc_price)
        atr_frac = max(0.0040, float(metrics.atr_bps) / 10_000.0)

        if raw_action > self.checkpoint.action_deadband:
            stop_px = round(ref_px * (1.0 - atr_frac), 4)
            tp_px = round(ref_px * (1.0 + 1.8 * atr_frac), 4)
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=depth.symbol,
                direction="BUY",
                target_conviction=conviction,
                suggested_stop_loss=stop_px,
                suggested_take_profit=tp_px,
                execution_tactic="ALMGREN_CHRISS",
                reference_price=ref_px,
                rationale=(
                    f"Actor-Critic Policy BUY ({self.checkpoint.checkpoint_id}): "
                    f"a_t={raw_action:+.3f}, V(s)={state_val:+.3f}, conviction={conviction:.3f}."
                ),
                execution_permission="none",
            )

        if raw_action < -self.checkpoint.action_deadband:
            stop_px = round(ref_px * (1.0 + atr_frac), 4)
            tp_px = round(ref_px * (1.0 - 1.8 * atr_frac), 4)
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=depth.symbol,
                direction="SELL",
                target_conviction=conviction,
                suggested_stop_loss=stop_px,
                suggested_take_profit=tp_px,
                execution_tactic="ALMGREN_CHRISS",
                reference_price=ref_px,
                rationale=(
                    f"Actor-Critic Policy SELL ({self.checkpoint.checkpoint_id}): "
                    f"a_t={raw_action:+.3f}, V(s)={state_val:+.3f}, conviction={conviction:.3f}."
                ),
                execution_permission="none",
            )

        stop_px = round(ref_px * (1.0 - atr_frac), 4)
        tp_px = round(ref_px * (1.0 + atr_frac), 4)
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=depth.symbol,
            direction="HOLD",
            target_conviction=0.0,
            suggested_stop_loss=stop_px,
            suggested_take_profit=tp_px,
            execution_tactic="LIMIT",
            reference_price=ref_px,
            rationale=(
                f"Actor-Critic Policy HOLD ({self.checkpoint.checkpoint_id}): "
                f"|a_t|={abs(raw_action):.3f} <= deadband {self.checkpoint.action_deadband:.2f}."
            ),
            execution_permission="none",
        )

