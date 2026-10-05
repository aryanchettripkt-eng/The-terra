"""Pydantic v2 schemas for Habitations, Prioritized Queues, and Risk Dossiers.

Endpoints: GET /habitations, GET /habitations/{id}/risk, GET /habitations/{id}/sites
Section refs: docs/PRD1.md §6.6, §6.7, §14.1
"""

from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pydantic import Field
from core.enums import HazardRegime, RelocationPathway, Tier
from core.schemas.common import BaseSchema, SCREENING_GRADE_NOTICE
from core.schemas.explanation import FeatureContributionDTO


class LossEventDTO(BaseSchema):
    id: int
    ts: date
    hazard_type: str
    fatalities: int = 0
    injured: int = 0
    houses_damaged: int = 0
    severity: float = 1.0
    source: str
    source_ref: Optional[str] = None


class VulnerabilityBreakdownDTO(BaseSchema):
    v_demographic: float = Field(ge=0.0, le=1.0)
    v_structural: float = Field(ge=0.0, le=1.0)
    v_access: float = Field(ge=0.0, le=1.0)
    v_economic: float = Field(ge=0.0, le=1.0)
    v_index: float = Field(ge=0.0, le=1.0)
    is_district_flat: bool = False
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Downscaling validation & PCA weights metadata")


class HabitationListItem(BaseSchema):
    """Item in prioritized habitation triage queue (GET /habitations)."""
    id: int
    lgd_code: Optional[int] = None
    name: str
    type: str = "village"
    admin_id: Optional[int] = None
    admin_name: Optional[str] = None
    population: int = 0
    households: int = 0
    priority_score: float = Field(description="Per-capita urgency score PS_j.")
    caseload_score: float = Field(description="Caseload urgency score PS_j * population.")
    tier: Optional[Tier] = Field(default=None, description="Four-tier triage category (None if unclassified/monitoring).")
    prz_overlap_pct: float = Field(ge=0.0, le=100.0, description="Percentage of built area inside PRZ.")
    dominant_hazard: str = "landslide"
    hazard_regime: Optional[HazardRegime] = Field(
        default=None, description="Flood hazard regime of the habitation's cell (None when the district has no regime layer)."
    )
    relocation_pathway: Optional[RelocationPathway] = Field(
        default=None, description="mainland_resettlement (char belt), in_situ_or_nearby (floodplain) or not_applicable."
    )
    centroid: list[float] = Field(description="[longitude, latitude]")
    model_version: str = "baseline-v1"
    scoring_version: str = "priority-v1.0"
    dataset_version: str = "v1.0"


class HabitationRiskDossier(BaseSchema):
    """Full risk dossier for a single habitation (GET /habitations/{id}/risk)."""
    id: int
    lgd_code: Optional[int] = None
    name: str
    type: str = "village"
    admin_id: Optional[int] = None
    admin_name: Optional[str] = None
    population: int
    households: int
    centroid: list[float]

    # Prioritization & Triage
    priority_score: float
    caseload_score: float
    tier: Optional[Tier] = Field(default=None, description="Four-tier triage category (None if unclassified/monitoring).")
    triage_rationale: str
    prz_overlap_pct: float
    hazard_intensity: float
    decayed_loss_score: float
    hazard_regime: Optional[HazardRegime] = None
    relocation_pathway: Optional[RelocationPathway] = None

    # Provenance & Quality
    model_version: str = "baseline-v1"
    scoring_version: str = "priority-v1.0"
    dataset_version: str = "v1.0"
    data_quality: str = "synthetic"
    confidence: float = 1.0
    calculated_at: Optional[datetime] = None

    # Risk Components
    vulnerability: VulnerabilityBreakdownDTO
    past_disasters: List[LossEventDTO] = Field(default_factory=list)
    top_contributing_factors: List[FeatureContributionDTO] = Field(default_factory=list)

    screening_grade: str = SCREENING_GRADE_NOTICE
