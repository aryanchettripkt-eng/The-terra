"""Domain enums for SETU-DRR.

Single source of truth for all enumeration types across core, pipeline, and API.
"""

from enum import StrEnum


class Hazard(StrEnum):
    """Supported hazard types (PRD §5.1, §6.3)."""
    LANDSLIDE = "landslide"
    FLASH_FLOOD = "flash_flood"
    STORM_SURGE = "storm_surge"
    RIVERINE_FLOOD = "riverine_flood"
    COASTAL_EROSION = "coastal_erosion"
    CLOUDBURST = "cloudburst"


class CoverageFlag(StrEnum):
    """Zonal coverage class for an aggregated H3 cell (Step 10 §10.3).

    CRITICAL RENDERING RULE:
    A NO_COVERAGE cell carries susceptibility 0.0 because `apply_quality_flags()` fills
    NaN with zero — not because it was measured as safe. It must never be drawn with the
    same treatment as a genuine FR-3.17 hard-zero cell.

    A CHANNEL_EXCLUDED cell is active river channel (flood model v0.2 regime split). It carries
    susceptibility 0.0 only because the column is NOT NULL; it is not terrestrial land, so it is
    left out of quantile breaks, band shares, habitation averages and triage.
    """
    FULL = "full"
    LOW_COVERAGE = "low_coverage"
    NO_COVERAGE = "no_coverage"
    CHANNEL_EXCLUDED = "channel_excluded"


class HazardRegime(StrEnum):
    """Flood hazard regime of an H3 cell (flood model v0.2, Phase 2).

    CHAR_BELT cells are river sandbar islands: highly exposed, but their water is partly
    normal river presence, so v0.2 susceptibility there reads lower than the exposure.
    Render the regime alongside the score instead of letting the score stand alone.
    """
    FLOODPLAIN = "floodplain"
    CHAR_BELT = "char_belt"
    CHANNEL = "channel"


class RelocationPathway(StrEnum):
    """How a habitation's hazard regime shapes what can be done for it (flood model v0.2, Phase 2e)."""
    MAINLAND_RESETTLEMENT = "mainland_resettlement"
    IN_SITU_OR_NEARBY = "in_situ_or_nearby"
    NOT_APPLICABLE = "not_applicable"


class ZoneClass(StrEnum):
    """Hazard zone classifications (PRD §6.3)."""
    PERMANENT_RED = "permanent_red"
    CAUTION = "caution"
    ACTIVE_ALERT = "active_alert"
    FORECAST_ALERT = "forecast_alert"
    NONE = "none"


class Tier(StrEnum):
    """Four-tier triage categorization for relocation planning (PRD §6.7)."""
    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    MITIGATE_IN_SITU = "mitigate_in_situ"


class TenureType(StrEnum):
    """Land tenure status for candidate relocation sites (PRD §6.8, FR-7.3)."""
    GOVERNMENT_REVENUE = "government_revenue"
    PRIVATE = "private"
    TENURE_UNVERIFIED = "tenure_unverified"


class BindingConstraint(StrEnum):
    """Binding capacity constraints for destination sites (PRD §6.8)."""
    LAND = "land"
    WATER = "water"
    SCHOOL = "school"
    HEALTH = "health"


class AssessmentStatus(StrEnum):
    """Assessment completeness for candidate relocation sites."""
    FULLY_ASSESSED = "fully_assessed"
    PARTIAL = "partial"
    SCREENING_ONLY = "screening_only"


class EligibilityStatus(StrEnum):
    """Eligibility status resulting from candidate site policy evaluation."""
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNKNOWN = "unknown"


class RiskStatus(StrEnum):
    """Status of habitation risk assessment."""
    SCORED = "scored"
    PARTIAL = "partial"
    PENDING = "pending"


class ImportRunStatus(StrEnum):
    """Lifecycle statuses for data import runs."""
    STAGED = "STAGED"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class OriginType(StrEnum):
    """Source origin of relocation recommendations or plans."""
    SETU = "setu"
    EXTERNAL = "external"


class DecisionStatus(StrEnum):
    """Legal/authority status of relocation decisions."""
    RECOMMENDATION = "recommendation"
    AUTHORITATIVE = "authoritative"


class SortMode(StrEnum):
    """Sort modes for prioritized habitation queues (PRD §6.6, FR-6.3)."""
    URGENCY = "urgency"
    CASELOAD = "caseload"


class PipelineRunStatus(StrEnum):
    """Lifecycle statuses for pipeline versioning runs."""
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class RunType(StrEnum):
    """Types of pipeline processing executions."""
    FULL = "FULL"
    GRID = "GRID"
    HAZARD_STATIC = "HAZARD_STATIC"
    HAZARD_DYNAMIC = "HAZARD_DYNAMIC"
    EXPOSURE = "EXPOSURE"
    CAPACITY = "CAPACITY"
    ALLOCATION = "ALLOCATION"


class AdminLevel(StrEnum):
    """Administrative hierarchy levels (LGD standard)."""
    COUNTRY = "country"
    STATE = "state"
    DISTRICT = "district"
    SUBDISTRICT = "subdistrict"
    VILLAGE = "village"


class DataQuality(StrEnum):
    """Data quality and provenance classification across pipeline and API data (Day 6-7).
    
    Preserves all 7 distinct states:
    - VALID: Real-world observation meeting all quality controls
    - PARTIAL: Degraded spatial/temporal coverage or incomplete observation
    - STALE: Retained past expiry due to upstream feed latency or outage
    - FALLBACK: Secondary provider invoked due to primary feed exhaustion or failure
    - MISSING: Sensor/pipeline coverage absent; never silently cast to safe/zero
    - INVALID: Failed schema/range check; never treated as safe/no-risk
    - SYNTHETIC: Deterministic demo fixture or synthetic simulation
    """
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    FALLBACK = "fallback"
    MISSING = "missing"
    INVALID = "invalid"
    SYNTHETIC = "synthetic"


class Role(StrEnum):
    """User identity roles for SETU-DRR authentication."""
    CIVILIAN = "CIVILIAN"
    GOVERNMENT_OFFICIAL = "GOVERNMENT_OFFICIAL"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class FacilityType(StrEnum):
    """Supported facility types from OpenStreetMap / Humanitarian OpenStreetMap."""
    SCHOOL = "school"
    HEALTH = "health"
    WATER = "water"
    ROAD = "road"


class InfraScreeningStatus(StrEnum):
    """Civic infrastructure screening status for candidate relocation parcels."""
    UNSCREENED = "unscreened"
    SCREENED = "screened"
    SURVEY_VERIFIED = "survey_verified"


