"""Pure domain logic for carrying capacity assessment, binding constraints, augmentation, and site eligibility.

Section refs: docs/PRD1.md §6.8, §14.1
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional, Sequence

from core.constants import (
    AREA_PER_HOUSEHOLD_M2,
    INFRA_OVERHEAD,
    LPCD_RURAL,
    LPCD_URBAN_SEWERED,
    PHC_POP_HILLY_TRIBAL,
    PHC_POP_PLAINS,
    PLOT_AREA_M2,
    SITE_MAX_MHI_STATIC,
    SITE_MAX_SLOPE_DEG,
    SITE_MIN_AREA_HA,
    SITE_SEARCH_RADIUS_KM,
)
from core.enums import BindingConstraint, EligibilityStatus, TenureType


class CapacityDataQuality(StrEnum):
    """Data quality and completeness status for site carrying capacity inputs."""
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CapacityNormsConfig:
    """Configurable normative parameters for carrying capacity calculations.
    
    Decouples government policy norms (e.g. plot area, LPCD, school/health norms)
    from serving layer and database structures.
    """
    plot_area_m2: float = PLOT_AREA_M2
    infra_overhead: float = INFRA_OVERHEAD
    non_residential_overhead_pct: float = INFRA_OVERHEAD
    lpcd_rural: int = LPCD_RURAL
    lpcd_urban_sewered: int = LPCD_URBAN_SEWERED
    lpcd_urban: int = LPCD_URBAN_SEWERED
    hh_size: float = 4.5
    persons_per_hh: float = 4.5
    children_per_hh: float = 1.2
    students_per_hh: float = 1.2
    phc_pop_plains: int = PHC_POP_PLAINS
    phc_norm_pop_plain: int = PHC_POP_PLAINS
    phc_pop_hilly_tribal: int = PHC_POP_HILLY_TRIBAL
    phc_norm_pop_hilly_tribal: int = PHC_POP_HILLY_TRIBAL
    default_livelihood_multiplier: float = 1.0
    livelihood_multiplier_min: float = 0.6
    livelihood_multiplier_max: float = 1.0
    policy_version: str = "capacity-norms-v1.0"
    calculation_version: str = "calc-v1.0"

    @property
    def area_per_hh_m2(self) -> float:
        """Derived effective land area per household including infrastructure overhead."""
        return round(self.plot_area_m2 * (1.0 + self.infra_overhead), 2)


@dataclass(frozen=True)
class CandidateSitePolicy:
    """Configurable spatial eligibility rules for candidate relocation sites.
    
    Section refs: PRD §6.8, FR-7.1, FR-7.2
    """
    search_radius_km: float = SITE_SEARCH_RADIUS_KM
    max_static_mhi: float = SITE_MAX_MHI_STATIC
    max_slope_deg: float = SITE_MAX_SLOPE_DEG
    min_contiguous_area_ha: float = SITE_MIN_AREA_HA
    exclude_forest: bool = True
    exclude_protected_area: bool = True
    exclude_crz_i_ii: bool = True
    exclude_water_body: bool = True
    #: Screening mode. When True, land whose tenure is unverified or unknown stays eligible and
    #: the gap is reported instead of rejecting the parcel. Order-grade mode leaves this False,
    #: preserving the H7 invariant that a site may not be allotted without proven tenure.
    #: Plan §Step 12 sanctions this as the ONLY relaxation of "missing data is not safe".
    allow_unverified_tenure: bool = False
    #: Screening mode. When True, a site whose lifeline capacities (water / school / health) are
    #: unmeasured is offered to the solver at its land capacity, labelled as a provisional
    #: land-only upper bound. Order-grade mode leaves this False so an unmeasured lifeline never
    #: reads as unlimited capacity. `cc_final` itself is never overwritten.
    allow_land_only_capacity: bool = False
    #: Screening mode. When True, candidate sites whose multi-hazard index (MHI) is unmeasured
    #: (honest data gap) are admitted for exploratory screening only, stamped with mandatory
    #: hazard verification caveats. Order-grade mode leaves this False so unmeasured hazard is
    #: never assumed safe.
    allow_unmeasured_hazard: bool = False
    #: A relocation destination may not sit in these hazard regimes: a char belt or river channel
    #: is the source of the problem, not a place to resettle onto. A site with no regime (district
    #: without a regime layer) is not blocked. Mirrors `RegimePolicyConfig.blocked_destination_regimes`.
    blocked_hazard_regimes: tuple[str, ...] = ("char_belt", "channel")
    policy_version: str = "site-eligibility-v1.2"


#: Policy for land with no cadastral or statutory-overlay source (derived parcels). Protected-area
#: and CRZ layers are absent, so those exclusions are disabled and recorded per site in
#: `data_gaps`; forest and water-body exclusions stay on because tree-cover and permanent-water
#: layers exist. Shared by the derivation job (which stamps sites under it) and the allocation
#: path (which must read them under the same rules), so the two cannot drift apart.
SCREENING_SITE_POLICY = CandidateSitePolicy(
    exclude_forest=True,
    exclude_water_body=True,
    exclude_protected_area=False,
    exclude_crz_i_ii=False,
    allow_unverified_tenure=True,
    allow_land_only_capacity=True,
    allow_unmeasured_hazard=True,
    policy_version="site-eligibility-v1.2-screening",
)


@dataclass(frozen=True)
class EligibilityResult:
    """Evaluation result of spatial, hazard, and environmental eligibility."""
    is_eligible: bool
    rejection_reasons: list[str] = field(default_factory=list)
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE

    @property
    def exclusion_reasons(self) -> list[str]:
        return self.rejection_reasons


@dataclass(frozen=True)
class AugmentedCapacityResult:
    """Result of augmenting the binding capacity constraint via targeted investment."""
    relieved_constraint: BindingConstraint
    augmented_capacity: int
    next_binding_constraint: Optional[BindingConstraint] = None
    indicative_intervention: str = ""
    indicative_cost_inr_lakhs: Optional[float] = None  # None indicates cost data is currently unavailable


@dataclass(frozen=True)
class CapacityEvaluationResult:
    """Complete, structured carrying capacity evaluation for a candidate site."""
    cc_land: int
    cc_water: Optional[int]
    cc_school: Optional[int]
    cc_health: Optional[int]
    livelihood_multiplier: float
    cc_final: Optional[int]
    binding_constraint: Optional[BindingConstraint]
    tied_constraints: list[BindingConstraint] = field(default_factory=list)
    augmented: Optional[AugmentedCapacityResult] = None
    data_quality: CapacityDataQuality = CapacityDataQuality.COMPLETE
    data_gaps: list[str] = field(default_factory=list)
    policy_version: str = "capacity-norms-v1.0"
    calculation_version: str = "calc-v1.0"


class CapacityEngine:
    """Domain calculation engine for carrying capacity, bottleneck detection, and augmentation."""

    def __init__(
        self,
        norms_config: Optional[CapacityNormsConfig] = None,
        site_policy: Optional[CandidateSitePolicy] = None,
    ) -> None:
        self.norms = norms_config or CapacityNormsConfig()
        self.policy = site_policy or CandidateSitePolicy()

    def calculate_land_capacity(
        self,
        area_developable_m2: float,
        plot_area_m2: Optional[float] = None,
        infra_overhead: Optional[float] = None,
    ) -> int:
        """Calculates household capacity supported by developable land area.
        
        Formula: floor(area_developable_m2 / (plot_area_m2 * (1 + infra_overhead)))
        """
        if area_developable_m2 <= 0.0:
            return 0
        plot_m2 = plot_area_m2 if plot_area_m2 is not None else self.norms.plot_area_m2
        overhead = infra_overhead if infra_overhead is not None else self.norms.infra_overhead
        effective_area_per_hh = plot_m2 * (1.0 + overhead)
        if effective_area_per_hh <= 0.0:
            return 0
        return math.floor(area_developable_m2 / effective_area_per_hh)

    def calculate_water_capacity(
        self,
        yield_liters_per_day: float,
        lpcd: Optional[int] = None,
        hh_size: Optional[float] = None,
        is_urban: bool = False,
    ) -> int:
        """Calculates household capacity supported by sustainable potable water yield.
        
        Formula: floor(yield_liters_per_day / (LPCD * hh_size))
        """
        if yield_liters_per_day <= 0.0:
            return 0
        active_lpcd = lpcd if lpcd is not None else (
            self.norms.lpcd_urban_sewered if is_urban else self.norms.lpcd_rural
        )
        active_hh_size = hh_size if hh_size is not None else self.norms.hh_size
        if active_lpcd <= 0 or active_hh_size <= 0.0:
            return 0
        daily_water_per_hh = active_lpcd * active_hh_size
        return math.floor(yield_liters_per_day / daily_water_per_hh)

    def calculate_school_capacity(
        self,
        spare_seats: int,
        children_per_hh: Optional[float] = None,
    ) -> int:
        """Calculates household capacity supported by spare school seating capacity.
        
        Formula: floor(spare_seats / children_per_hh)
        """
        if spare_seats <= 0:
            return 0
        c_per_hh = children_per_hh if children_per_hh is not None else self.norms.children_per_hh
        if c_per_hh <= 0.0:
            return 0
        return math.floor(spare_seats / c_per_hh)

    def calculate_health_capacity(
        self,
        catchment_pop: int = 0,
        phc_norm_pop: Optional[int] = None,
        hh_size: Optional[float] = None,
        is_hilly_or_tribal: bool = True,
    ) -> int:
        """Calculates household capacity supported by spare primary healthcare capacity.
        
        Formula: floor(max(0, phc_norm_pop - catchment_pop) / hh_size)
        """
        norm_pop = phc_norm_pop if phc_norm_pop is not None else (
            self.norms.phc_pop_hilly_tribal if is_hilly_or_tribal else self.norms.phc_pop_plains
        )
        active_hh_size = hh_size if hh_size is not None else self.norms.hh_size
        if active_hh_size <= 0.0:
            return 0
        spare_health_pop = max(0, norm_pop - max(0, catchment_pop))
        return math.floor(spare_health_pop / active_hh_size)

    def determine_binding_constraint(
        self,
        cc_land: Optional[int] = None,
        cc_water: Optional[int] = None,
        cc_school: Optional[int] = None,
        cc_health: Optional[int] = None,
    ) -> tuple[Optional[int], Optional[BindingConstraint], list[BindingConstraint]]:
        """Determines the limiting capacity bottleneck via strict argmin with deterministic tie-breaking.
        
        If all lifelines (water, school, health) are unmeasured, returns (None, None, []) to preserve
        honest data gaps rather than prematurely assuming land is the final bottleneck.
        Deterministic tie-breaking priority order: LAND -> WATER -> SCHOOL -> HEALTH.
        """
        if cc_water is None and cc_school is None and cc_health is None:
            return None, None, []

        available: list[tuple[int, BindingConstraint]] = []
        if cc_land is not None:
            available.append((max(0, cc_land), BindingConstraint.LAND))
        if cc_water is not None:
            available.append((max(0, cc_water), BindingConstraint.WATER))
        if cc_school is not None:
            available.append((max(0, cc_school), BindingConstraint.SCHOOL))
        if cc_health is not None:
            available.append((max(0, cc_health), BindingConstraint.HEALTH))

        if not available:
            return None, None, []

        min_val = min(c[0] for c in available)
        tied = [c[1] for c in available if c[0] == min_val]
        primary_binding = tied[0]

        return min_val, primary_binding, tied

    def calculate_final_capacity(
        self,
        cc_land: Optional[int] = None,
        cc_water: Optional[int] = None,
        cc_school: Optional[int] = None,
        cc_health: Optional[int] = None,
        livelihood_multiplier: Optional[float] = None,
    ) -> tuple[Optional[int], Optional[BindingConstraint], list[BindingConstraint]]:
        """Calculates final carrying capacity = min(CC_land, CC_water, CC_school, CC_health) * mu_livelihood.
        
        Returns (None, None, []) if all lifelines are unmeasured, preserving honest data gaps.
        Invariant (FR-7.4): Constraints are NEVER averaged.
        """
        if cc_water is None and cc_school is None and cc_health is None:
            return None, None, []

        min_val, primary_binding, tied = self.determine_binding_constraint(
            cc_land, cc_water, cc_school, cc_health
        )
        if min_val is None or primary_binding is None:
            return None, None, []

        mu = livelihood_multiplier if livelihood_multiplier is not None else self.norms.default_livelihood_multiplier
        mu_clamped = min(max(mu, self.norms.livelihood_multiplier_min), self.norms.livelihood_multiplier_max)
        final_cc = math.floor(min_val * mu_clamped)

        return final_cc, primary_binding, tied

    def calculate_augmented_capacity(
        self,
        cc_land: Optional[int] = None,
        cc_water: Optional[int] = None,
        cc_school: Optional[int] = None,
        cc_health: Optional[int] = None,
        binding_constraint: BindingConstraint = BindingConstraint.LAND,
        relieved_capacity: Optional[int] = None,
        livelihood_multiplier: Optional[float] = None,
    ) -> AugmentedCapacityResult:
        """Computes capacity and the secondary bottleneck after relieving the primary constraint."""
        known_values = [v for v in (cc_land, cc_water, cc_school, cc_health) if v is not None]
        surrogate_high = max(known_values + [1000]) * 2
        effective_relieved = relieved_capacity if relieved_capacity is not None else surrogate_high

        c_land = effective_relieved if binding_constraint == BindingConstraint.LAND else cc_land
        c_water = effective_relieved if binding_constraint == BindingConstraint.WATER else cc_water
        c_school = effective_relieved if binding_constraint == BindingConstraint.SCHOOL else cc_school
        c_health = effective_relieved if binding_constraint == BindingConstraint.HEALTH else cc_health

        aug_final, next_binding, _ = self.calculate_final_capacity(
            c_land, c_water, c_school, c_health, livelihood_multiplier
        )

        intervention_descriptions = {
            BindingConstraint.LAND: "Land boundary consolidation and slope stabilization for developable plot expansion",
            BindingConstraint.WATER: "Dedicated piped water supply scheme / piped deep borewell with filtration storage",
            BindingConstraint.SCHOOL: "Sanction additional classroom infrastructure and teacher intake in nearby government school",
            BindingConstraint.HEALTH: "Upgrade Primary Health Centre sub-centre facility and sanctioned staff capacity",
        }

        return AugmentedCapacityResult(
            relieved_constraint=binding_constraint,
            augmented_capacity=aug_final,
            next_binding_constraint=next_binding,
            indicative_intervention=intervention_descriptions.get(
                binding_constraint, "Targeted public infrastructure augmentation"
            ),
            indicative_cost_inr_lakhs=None,  # Explicitly None: Do not invent unverified financial figures
        )

    def evaluate_site_eligibility(
        self,
        mhi_static: Optional[float] = None,
        slope_mean: Optional[float] = None,
        area_ha: Optional[float] = None,
        is_forest: Optional[bool] = False,
        is_protected_area: Optional[bool] = False,
        is_crz: Optional[bool] = False,
        is_water_body: Optional[bool] = False,
        tenure: Optional[TenureType | str] = None,
        slope_mean_deg: Optional[float] = None,
        mhi_max: Optional[float] = None,
        distance_km: Optional[float] = None,
        require_distance: bool = False,
        policy: Optional[CandidateSitePolicy] = None,
        hazard_regime: Optional[str] = None,
    ) -> EligibilityResult:
        """Evaluates candidate site against deterministic policy eligibility criteria.
        
        Section refs: PRD §6.8, FR-7.2, FR-7.3:
        - MHI_static < 0.25 (Missing MHI is not assumed safe)
        - slope < 15 degrees (Missing slope is not assumed flat)
        - contiguous area >= 2 ha (Missing area is rejected)
        - not forest / protected / CRZ / water body
        - tenure is explicitly known and valid (government_revenue or private; unverified/unknown rejected)
        - within search radius (when distance_km is specified or require_distance is True)
        """
        p = policy or self.policy
        rejection_reasons: list[str] = []

        active_mhi = mhi_max if mhi_max is not None else mhi_static
        active_slope = slope_mean_deg if slope_mean_deg is not None else slope_mean
        active_area = area_ha

        # Check missing values explicitly (Audit Requirement 9: Missing data != safe)
        if active_mhi is None:
            if not p.allow_unmeasured_hazard:
                rejection_reasons.append("Multi-hazard index (MHI) data is missing or unverified")
        elif active_mhi >= p.max_static_mhi:
            rejection_reasons.append(f"Static MHI {active_mhi:.2f} >= threshold {p.max_static_mhi:.2f}")

        if active_slope is None:
            rejection_reasons.append("Terrain slope data is missing or unverified")
        elif active_slope >= p.max_slope_deg:
            rejection_reasons.append(f"Mean slope {active_slope:.1f}° >= threshold {p.max_slope_deg:.1f}°")

        if active_area is None:
            rejection_reasons.append("Contiguous area data is missing or unverified")
        elif active_area < p.min_contiguous_area_ha:
            rejection_reasons.append(f"Contiguous area {active_area:.2f} ha < minimum {p.min_contiguous_area_ha:.2f} ha")

        # Tenure validation (FR-7.3, H7: must be explicitly valid government_revenue or private)
        if tenure is None:
            # Absent and "unverified" are the same epistemic state, so screening mode treats
            # them alike; order-grade mode rejects both.
            if not p.allow_unverified_tenure:
                rejection_reasons.append("Land tenure data is missing or unknown")
        else:
            tenure_val: Optional[TenureType] = None
            if isinstance(tenure, TenureType):
                tenure_val = tenure
            elif isinstance(tenure, str):
                try:
                    tenure_val = TenureType(tenure.lower().strip())
                except ValueError:
                    tenure_val = None

            if tenure_val is None:
                rejection_reasons.append("Land tenure is unknown or invalid")
            elif tenure_val == TenureType.TENURE_UNVERIFIED:
                if not p.allow_unverified_tenure:
                    rejection_reasons.append("Land tenure is unverified")
            elif tenure_val not in (TenureType.GOVERNMENT_REVENUE, TenureType.PRIVATE):
                rejection_reasons.append("Land tenure is unknown or invalid")

        # Environmental & land-cover exclusions
        # Each exclusion is checked only while it is enforced. A disabled rule makes its
        # attribute irrelevant, so an unknown value must not reject: otherwise turning a rule
        # off would reject everything instead of ignoring the field. Wherever a rule IS on,
        # missing data still rejects — the audit invariant is unchanged.
        if p.exclude_forest:
            if is_forest is None:
                if not p.allow_unmeasured_hazard:
                    rejection_reasons.append("Forest exclusion status is missing or unverified")
            elif is_forest:
                rejection_reasons.append("Site overlaps designated forest land")

        if p.exclude_protected_area:
            if is_protected_area is None:
                if not p.allow_unmeasured_hazard:
                    rejection_reasons.append("Protected area status is missing or unverified")
            elif is_protected_area:
                rejection_reasons.append("Site overlaps protected ecological area / sanctuary")

        if p.exclude_crz_i_ii:
            if is_crz is None:
                if not p.allow_unmeasured_hazard:
                    rejection_reasons.append("Coastal Regulation Zone (CRZ) status is missing or unverified")
            elif is_crz:
                rejection_reasons.append("Site overlaps Coastal Regulation Zone (CRZ-I/II)")

        if p.exclude_water_body:
            if is_water_body is None:
                if not p.allow_unmeasured_hazard:
                    rejection_reasons.append("Surface water body status is missing or unverified")
            elif is_water_body:
                rejection_reasons.append("Site overlaps surface water body")

        # Hazard regime: never resettle onto a char belt or channel (Phase 2e)
        if hazard_regime is not None and str(hazard_regime) in p.blocked_hazard_regimes:
            rejection_reasons.append(
                f"Site lies in the {str(hazard_regime).replace('_', ' ')} hazard regime, which is not a viable resettlement destination"
            )

        # Spatial search radius check
        if distance_km is None:
            if require_distance:
                rejection_reasons.append("Site distance to target habitations is missing or unverified")
        elif distance_km > p.search_radius_km:
            rejection_reasons.append(f"Site distance {distance_km:.2f} km > search radius {p.search_radius_km:.1f} km")

        is_eligible = len(rejection_reasons) == 0
        if is_eligible:
            elig_status = EligibilityStatus.ELIGIBLE
        elif any("missing" in r.lower() or "unverified" in r.lower() or "unknown" in r.lower() for r in rejection_reasons):
            elig_status = EligibilityStatus.UNKNOWN
        else:
            elig_status = EligibilityStatus.INELIGIBLE

        return EligibilityResult(
            is_eligible=is_eligible,
            rejection_reasons=rejection_reasons,
            eligibility_status=elig_status,
        )

    def evaluate_site_capacity(
        self,
        area_developable_m2: float,
        water_yield_liters_per_day: Optional[float] = None,
        spare_school_seats: Optional[int] = None,
        spare_health_capacity_pop: Optional[int] = None,
        livelihood_multiplier: Optional[float] = None,
        is_urban: bool = False,
        is_hilly_or_tribal: bool = True,
        norms_override: Optional[CapacityNormsConfig] = None,
    ) -> CapacityEvaluationResult:
        """Evaluates complete carrying capacity, bottlenecks, and augmentation for a site."""
        active_norms = norms_override or self.norms

        # Determine data quality and gaps
        has_water = water_yield_liters_per_day is not None
        has_school = spare_school_seats is not None
        has_health = spare_health_capacity_pop is not None
        data_gaps: list[str] = []

        if not has_water:
            data_gaps.append("Water Yield")
        if not has_school:
            data_gaps.append("School Seating")
        if not has_health:
            data_gaps.append("Health Catchment")

        if has_water and has_school and has_health:
            quality = CapacityDataQuality.COMPLETE
        elif has_water or has_school or has_health:
            quality = CapacityDataQuality.PARTIAL
        else:
            quality = CapacityDataQuality.UNAVAILABLE

        cc_land = self.calculate_land_capacity(area_developable_m2, active_norms.plot_area_m2, active_norms.infra_overhead)

        cc_water = (
            self.calculate_water_capacity(
                water_yield_liters_per_day,
                active_norms.lpcd_rural,
                active_norms.hh_size,
                is_urban,
            )
            if has_water
            else None
        )
        cc_school = (
            self.calculate_school_capacity(
                spare_school_seats,
                active_norms.children_per_hh,
            )
            if has_school
            else None
        )
        cc_health = (
            self.calculate_health_capacity(
                catchment_pop=0,
                phc_norm_pop=spare_health_capacity_pop,
                hh_size=active_norms.hh_size,
                is_hilly_or_tribal=is_hilly_or_tribal,
            )
            if has_health
            else None
        )

        mu = livelihood_multiplier if livelihood_multiplier is not None else active_norms.default_livelihood_multiplier
        if quality == CapacityDataQuality.UNAVAILABLE:
            # Honest gap: all lifelines are unmeasured. Do not claim final capacity or fake binding constraint.
            cc_final = None
            binding = None
            tied: list[BindingConstraint] = []
            augmented = None
        else:
            cc_final, binding, tied = self.calculate_final_capacity(cc_land, cc_water, cc_school, cc_health, mu)
            augmented = self.calculate_augmented_capacity(
                cc_land, cc_water, cc_school, cc_health, binding, livelihood_multiplier=mu
            )

        return CapacityEvaluationResult(
            cc_land=cc_land,
            cc_water=cc_water,
            cc_school=cc_school,
            cc_health=cc_health,
            livelihood_multiplier=mu,
            cc_final=cc_final,
            binding_constraint=binding,
            tied_constraints=tied,
            augmented=augmented,
            data_quality=quality,
            data_gaps=data_gaps,
            policy_version=active_norms.policy_version,
            calculation_version=active_norms.calculation_version,
        )


# ====================================================================
# Backward-Compatible Helper Functions
# ====================================================================

_default_engine = CapacityEngine()


def compute_land_capacity(
    area_developable_m2: float,
    area_per_hh_m2: float = AREA_PER_HOUSEHOLD_M2,
) -> int:
    """Computes land capacity = floor(A_developable / a_hh)."""
    if area_developable_m2 <= 0.0 or area_per_hh_m2 <= 0.0:
        return 0
    return math.floor(area_developable_m2 / area_per_hh_m2)


def compute_water_capacity(
    yield_liters_per_day: float,
    lpcd: int = LPCD_RURAL,
    hh_size: float = 4.5,
) -> int:
    """Computes water capacity = floor(W_yield / (LPCD * hh_size))."""
    if yield_liters_per_day <= 0.0 or lpcd <= 0 or hh_size <= 0.0:
        return 0
    return math.floor(yield_liters_per_day / (lpcd * hh_size))


def compute_school_capacity(
    spare_seats: int,
    children_per_hh: float = 1.2,
) -> int:
    """Computes school capacity = floor(spare_seats / children_per_hh)."""
    if spare_seats <= 0 or children_per_hh <= 0.0:
        return 0
    return math.floor(spare_seats / children_per_hh)


def compute_health_capacity(
    catchment_pop: int = 0,
    norm_pop: Optional[int] = None,
    hh_size: float = 4.5,
    phc_norm_pop: Optional[int] = None,
) -> int:
    """Computes health capacity = floor(max(0, norm_pop - catchment_pop) / hh_size)."""
    if hh_size <= 0.0:
        return 0
    active_norm = phc_norm_pop if phc_norm_pop is not None else (norm_pop if norm_pop is not None else PHC_POP_HILLY_TRIBAL)
    spare_pop = max(0, active_norm - max(0, catchment_pop))
    return math.floor(spare_pop / hh_size)


def compute_carrying_capacity(
    cc_land: Optional[int] = None,
    cc_water: Optional[int] = None,
    cc_school: Optional[int] = None,
    cc_health: Optional[int] = None,
    livelihood_multiplier: float = 1.0,
) -> tuple[int, BindingConstraint]:
    """Computes bottleneck capacity = min(L, W, S, H) * mu."""
    final_cc, binding, _ = _default_engine.calculate_final_capacity(
        cc_land, cc_water, cc_school, cc_health, livelihood_multiplier
    )
    return final_cc, binding


def compute_augmented_capacity(
    cc_land: Optional[int] = None,
    cc_water: Optional[int] = None,
    cc_school: Optional[int] = None,
    cc_health: Optional[int] = None,
    binding_constraint: Optional[BindingConstraint] = None,
    relieved_capacity: Optional[int] = None,
    livelihood_multiplier: float = 1.0,
    relieved_constraint: Optional[BindingConstraint] = None,
    relieved_value: Optional[int] = None,
) -> tuple[int, BindingConstraint]:
    """Computes augmented capacity and secondary constraint."""
    active_binding = relieved_constraint or binding_constraint or BindingConstraint.LAND
    active_relieved = relieved_value if relieved_value is not None else relieved_capacity
    res = _default_engine.calculate_augmented_capacity(
        cc_land, cc_water, cc_school, cc_health, active_binding, active_relieved, livelihood_multiplier
    )
    return (
        res.augmented_capacity,
        res.next_binding_constraint or active_binding,
    )
