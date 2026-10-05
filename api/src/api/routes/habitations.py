"""FastAPI Route Handlers for Habitations Triage Queue, Risk Dossiers & Candidate Sites (L5).

Endpoints:
- GET /habitations?admin=&tier=&sort=&limit=&offset=
- GET /habitations/{id}/risk
- GET /habitations/{id}/sites
"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_serving_version
from api.routes.common import error_responses
from api.services.habitations_service import HabitationsService
from api.services.sites_service import SitesService
from core.enums import HazardRegime, Tier, SortMode
from core.schemas.common import PaginatedResponse
from core.schemas.habitations import HabitationListItem, HabitationRiskDossier
from core.schemas.sites import CandidateSiteItem

router = APIRouter(prefix="/habitations", tags=["Habitations & Triage"])


@router.get(
    "",
    response_model=PaginatedResponse[HabitationListItem],
    responses=error_responses(422, 500, 503),
    summary="Get prioritized habitation triage queue",
    description=(
        "Returns a paginated list of habitations ranked by Per-Capita Urgency or Caseload. "
        "Supports filtering by Administrative Boundary (LGD Code) and 4-tier Triage Category."
    ),
)
def get_habitations(
    admin: Optional[int] = Query(
        None,
        description="Filter by Administrative Unit ID or LGD Code (e.g. 555 for Wayanad)",
    ),
    tier: Optional[Tier] = Query(
        None,
        description="Filter by Triage Tier (Immediate, Short-term, Medium-term, Mitigate in situ)",
    ),
    regime: Optional[HazardRegime] = Query(
        None,
        description="Filter by flood hazard regime of the habitation's cell (floodplain, char_belt, channel).",
    ),
    sort: SortMode = Query(
        SortMode.URGENCY,
        description="Ranking mode: 'urgency' (PS_j) or 'caseload' (PS_j * population)",
    ),
    limit: int = Query(
        50,
        description="Number of records per page (max 200).",
        ge=1,
        le=200,
    ),
    offset: int = Query(
        0,
        description="Pagination offset.",
        ge=0,
    ),
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> PaginatedResponse[HabitationListItem]:
    service = HabitationsService(db)
    return service.get_habitations(
        admin=admin,
        tier=tier,
        sort=sort,
        limit=limit,
        offset=offset,
        regime=regime,
    )


@router.get(
    "/{id}/risk",
    response_model=HabitationRiskDossier,
    responses=error_responses(404, 422, 500, 503),
    summary="Get complete risk dossier for a habitation",
    description="Retrieves vulnerability breakdown (SoVI), time-decayed loss history, and priority score explanation.",
)
def get_habitation_risk_dossier(
    id: int = Path(
        ...,
        description="Habitation ID (integer primary key).",
        examples=[1],
    ),
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> HabitationRiskDossier:
    service = HabitationsService(db)
    return service.get_habitation_risk_dossier(id)


@router.get(
    "/{id}/sites",
    response_model=PaginatedResponse[CandidateSiteItem],
    responses=error_responses(404, 422, 500, 503),
    summary="Get ranked candidate relocation sites for a habitation",
    description=(
        "Retrieves candidate relocation sites within search radius (default 15 km) "
        "ranked by suitability, carrying capacity, and distance. Includes full resource capacity breakdowns and binding constraints."
    ),
)
def get_habitation_candidate_sites(
    id: int = Path(
        ...,
        description="Habitation ID (integer primary key).",
        examples=[1],
    ),
    radius_km: Optional[float] = Query(
        None,
        gt=0.0,
        le=100.0,
        description="Configurable search radius around habitation in kilometers (default 15 km).",
    ),
    min_suitability: Optional[int] = Query(
        None,
        ge=0,
        le=100,
        description="Filter by minimum composite suitability score (0-100).",
    ),
    include_screening: bool = Query(
        False,
        description="Whether to include unverified screening-grade candidate sites (default False).",
    ),
    limit: int = Query(
        50,
        description="Number of records per page (max 200).",
        ge=1,
        le=200,
    ),
    offset: int = Query(
        0,
        description="Pagination offset.",
        ge=0,
    ),
    db: Session = Depends(get_db),
    _sv: uuid.UUID = Depends(require_serving_version),
) -> PaginatedResponse[CandidateSiteItem]:
    service = SitesService(db)
    return service.get_candidate_sites_for_habitation(
        habitation_id=id,
        radius_km=radius_km,
        min_suitability=min_suitability,
        include_screening=include_screening,
        limit=limit,
        offset=offset,
    )
