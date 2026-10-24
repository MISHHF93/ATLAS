"""/api/integrations/status: every third-party service, configured or not, reachable or not, paper or live-refused.
Never returns a secret value (names and booleans only). ``probe=true`` runs read-only calls; no order, no alert."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/status")
def integrations_status(probe: bool = Query(False)) -> dict[str, Any]:
    from atlas.integrations.registry import status
    return status(probe=probe)
