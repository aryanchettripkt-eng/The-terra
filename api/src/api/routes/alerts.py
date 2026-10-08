"""FastAPI Route Handlers for Active and Forecast Alert Zones (Day 6).

Endpoints:
- GET /alerts/active
- GET /alerts/forecast
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_serving_version
from api.routes.common import error_responses
from api.services.alerts_service import AlertsService
from core.constants import FORECAST_HORIZON_HOURS
from core.schemas.alerts import (
    ActiveAlertsResponse,
    ForecastAlertsResponse,
    ForecastPipelineStatusResponse,
    ForecastTriggerRequest,
    ForecastTriggerResponse,
)
from pipeline.hazard.forecast_config import FORECAST_DISTRICTS

logger = logging.getLogger("setu_api.alerts_router")

# Concurrency & debounce guards
_RUN_IN_PROGRESS = False
_LAST_RUN_STARTED_AT: Optional[datetime] = None


def _execute_forecast_background_task(
    run_id: str,
    target_districts: list[str],
    live: bool,
    dry_run: bool,
) -> None:
    """Worker function executed inside FastAPI BackgroundTasks."""
    global _RUN_IN_PROGRESS, _LAST_RUN_STARTED_AT
    try:
        logger.info(
            f"[Run {run_id}] Background forecast cycle started for {target_districts} (live={live}, dry_run={dry_run})."
        )
        from pipeline.jobs.run_district_forecast import run_all_districts
        results = run_all_districts(district_keys=target_districts, live=live, dry_run=dry_run)
        logger.info(
            f"[Run {run_id}] Background forecast cycle completed successfully across {len(results)} district(s)."
        )
    except Exception as exc:
        logger.exception(f"[Run {run_id}] Background forecast cycle encountered an unhandled error: {exc}")
    finally:
        _RUN_IN_PROGRESS = False
        _LAST_RUN_STARTED_AT = None


router = APIRouter(prefix="/alerts", tags=["Dynamic Alerts & Forecasts"])



@router.get(
    "/active",
    response_model=ActiveAlertsResponse,
    responses=error_responses(422, 500, 503),
    summary="Get active hazard alert zones exceeding emergency threshold",
    description=(
        "Retrieves H3 grid cells currently in Active Alert Zone state (MHI_live >= 0.75 and MHI_static < 0.75). "
        "Alerts are transient, driven by observed meteorological/hydrological triggers, and do not mutate permanent PRZ classifications."
    ),
)
def get_active_alerts(
    admin: Optional[int] = Query(
        None,
        description="Filter by Administrative Unit ID or LGD Code (e.g. 555 for Wayanad)",
    ),
    min_mhi: float = Query(
        0.75,
        ge=0.0,
        le=1.0,
        description="Minimum active MHI threshold (default 0.75).",
    ),
    hazard: Optional[str] = Query(
        None,
        description="Filter by dominant hazard type (landslide, flash_flood, riverine_flood).",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Maximum records to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset.",
    ),
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> ActiveAlertsResponse:
    service = AlertsService(db)
    return service.get_active_alerts(
        admin_id=admin,
        min_mhi=min_mhi,
        dominant_hazard=hazard,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/forecast",
    response_model=ForecastAlertsResponse,
    responses=error_responses(422, 500, 503),
    summary="Get forecast alert zones predicted to cross threshold within 72 hours",
    description=(
        "Retrieves H3 grid cells predicted to cross the hazard threshold (MHI_fcst >= 0.75) within a configurable horizon (1-72h). "
        "Represents meteorological forecast threshold crossing (ECMWF Open Data) and does not predict disasters or alter permanent relocation triage."
    ),
)
def get_forecast_alerts(
    horizon: int = Query(
        72,
        ge=1,
        le=FORECAST_HORIZON_HOURS,
        description="Forecast horizon in hours (maximum 72 hours).",
    ),
    admin: Optional[int] = Query(
        None,
        description="Filter by Administrative Unit ID or LGD Code (e.g. 555 for Wayanad)",
    ),
    min_mhi: float = Query(
        0.75,
        ge=0.0,
        le=1.0,
        description="Minimum forecast MHI threshold (default 0.75).",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Maximum records to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset.",
    ),
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> ForecastAlertsResponse:
    service = AlertsService(db)
    return service.get_forecast_alerts(
        horizon_hours=horizon,
        admin_id=admin,
        min_mhi=min_mhi,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/forecast/trigger",
    response_model=ForecastTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(400, 409, 422, 500, 503),
    summary="Trigger an immediate multi-district forecast ingestion cycle",
    description=(
        "Dispatches an asynchronous Route 1 forecast ingestion run across specified or all operational districts. "
        "Returns HTTP 202 Accepted immediately. Concurrency locks prevent duplicate overlapping runs."
    ),
)
def trigger_forecast_cycle(
    payload: ForecastTriggerRequest,
    background_tasks: BackgroundTasks,
    _sv: uuid.UUID = Depends(require_serving_version),
) -> ForecastTriggerResponse:
    global _RUN_IN_PROGRESS, _LAST_RUN_STARTED_AT

    # Check and self-heal zombie lock if running for > 5 minutes or missing timestamp
    now = datetime.now(timezone.utc)
    if _RUN_IN_PROGRESS:
        if _LAST_RUN_STARTED_AT is None or (now - _LAST_RUN_STARTED_AT).total_seconds() > 300:
            logger.warning("Resetting stale forecast run lock (exceeded 5m timeout or missing timestamp).")
            _RUN_IN_PROGRESS = False
            _LAST_RUN_STARTED_AT = None

    if _RUN_IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A forecast ingestion cycle is currently executing in the background. Please retry shortly.",
        )

    # Validate target districts
    if payload.district:
        target_slug = payload.district.strip().lower()
        if target_slug not in FORECAST_DISTRICTS:
            valid_keys = ", ".join(FORECAST_DISTRICTS.keys())
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown district '{payload.district}'. Registered districts: {valid_keys}",
            )
        target_districts = [target_slug]
    else:
        target_districts = list(FORECAST_DISTRICTS.keys())

    run_id = str(uuid.uuid4())
    _RUN_IN_PROGRESS = True
    _LAST_RUN_STARTED_AT = now

    background_tasks.add_task(
        _execute_forecast_background_task,
        run_id=run_id,
        target_districts=target_districts,
        live=payload.live,
        dry_run=payload.dry_run,
    )

    return ForecastTriggerResponse(
        status="ACCEPTED",
        message=f"Forecast ingestion dispatched for {len(target_districts)} district(s).",
        run_id=run_id,
        target_districts=target_districts,
        enqueued_at=now,
    )


@router.get(
    "/forecast/status",
    response_model=ForecastPipelineStatusResponse,
    responses=error_responses(500, 503),
    summary="Get multi-district forecast telemetry, scheduler health, and per-district states",
    description=(
        "Retrieves real-time operational status for all 7 registered districts, including latest forecast cycle timestamps, "
        "active danger cell counts, weather state (CLEAR vs ALERT_ACTIVE vs STALE), and scheduler health."
    ),
)
def get_forecast_pipeline_status(
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> ForecastPipelineStatusResponse:
    global _RUN_IN_PROGRESS
    service = AlertsService(db)
    return service.get_forecast_pipeline_status(is_run_in_progress=_RUN_IN_PROGRESS)

