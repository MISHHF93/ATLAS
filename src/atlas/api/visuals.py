"""API endpoint for delivering Price Action visual markers to the frontend.

Provides the coordinates for Opening, Breakout, Anchor, and Event boxes,
as well as Snapback setup states, allowing the frontend to render
overlays on top of the TradingView charts.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException

from atlas.features.zones import ZoneType
from atlas.models.schemas import Record
from atlas.strategies.coordinator import OpportunityCoordinator
from atlas.strategies.snapback import SnapbackState

router = APIRouter(prefix="/api/visuals", tags=["visuals"])
_COORDINATOR: OpportunityCoordinator | None = None


def register_coordinator(coordinator: OpportunityCoordinator | None) -> None:
    """Called by the strategy runner so the chart overlay reads the live (paper) zone engines."""
    global _COORDINATOR
    _COORDINATOR = coordinator


def get_coordinator() -> OpportunityCoordinator:
    if _COORDINATOR is None:
        raise HTTPException(status_code=404, detail="No strategy runner is active; no price-action overlays yet")
    return _COORDINATOR


class ChartMarker(Record):
    """A visual marker to be rendered on the chart."""
    type: Literal["box", "line", "label"]
    label: str
    color: str
    coords: dict[str, Any] # e.g., {"x1": ts, "y1": price, "x2": ts, "y2": price}
    metadata: dict[str, Any] = {}
    execution_permission: Literal["none"] = "none"


class ChartOverlayPayload(Record):
    """The complete set of overlays for a given symbol."""
    symbol: str
    markers: list[ChartMarker]
    active_setup_state: Optional[str] = None
    recommended_action: Optional[str] = None
    execution_permission: Literal["none"] = "none"


@router.get("/overlays/{symbol}", response_model=ChartOverlayPayload)
async def get_chart_overlays(
    symbol: str, 
    coordinator: OpportunityCoordinator = Depends(get_coordinator)
):
    """
    Returns current Price Action zones and setup states as chart markers.
    """
    sym = symbol.upper()
    if sym not in coordinator.zone_engines:
        # In a real scenario, we would trigger a quick scan of recent data here
        raise HTTPException(status_code=404, detail="No active zones for symbol")

    zone_engine = coordinator.zone_engines[sym]
    detector = coordinator.detectors[sym]
    
    markers = []
    
    # 1. Convert active zones to markers
    for z_type, zone in zone_engine.active_zones.items():
        if zone is None:
            continue
            
        color = {
            ZoneType.OPENING: "#3b82f6", # Blue
            ZoneType.BREAKOUT: "#ef4444", # Red
            ZoneType.ANCHOR: "#10b981",   # Green
            ZoneType.EVENT: "#f59e0b",    # Orange
        }.get(z_type, "#ffffff")
        
        markers.append(ChartMarker(
            type="box",
            label=f"{z_type.name} Box",
            color=color,
            coords={
                "start_time": zone.start_time.isoformat(),
                "end_time": zone.end_time.isoformat(),
                "high": zone.boundary.high,
                "low": zone.boundary.low
            },
            metadata={"direction": zone.direction.name}
        ))

    # 2. Add setup state marker
    setup_state = None
    if detector.active_setup:
        setup = detector.active_setup
        setup_state = setup.state.name
        
        # Draw a line for the a qualified entry level
        if setup.state == SnapbackState.QUALIFIED:
            markers.append(ChartMarker(
                type="line",
                label="Snapback Entry",
                color="#facc15", # Yellow
                coords={
                    "price": setup.initial_box.boundary.high if setup.direction == "long" else setup.initial_box.boundary.low
                },
                metadata={"action": "candidate_entry"}
            ))

    return ChartOverlayPayload(
        symbol=sym,
        markers=markers,
        active_setup_state=setup_state,
        execution_permission="none"
    )
