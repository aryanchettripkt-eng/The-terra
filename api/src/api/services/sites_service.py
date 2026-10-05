"""Service Layer for Candidate Relocation Sites & Carrying Capacity.

Section refs: docs/PRD1.md §6.8, §9.6
"""

from __future__ import annotations

from dataclasses import replace
import json
import math
from typing import Any, Optional
from sqlalchemy.orm import Session

from api.repositories.sites_repo import SitesRepository
from api.services.site_eligibility import evaluate_row_eligibility
from core.domain.capacity import (
    CapacityEngine,
    CapacityNormsConfig,
    CandidateSitePolicy,
    compute_carrying_capacity,
    compute_augmented_capacity,
)
from core.domain.regime import normalize_regime
from core.enums import BindingConstraint, TenureType
from core.errors import HabitationNotFoundError, SiteNotFoundError
from core.schemas.common import PaginatedResponse
from core.schemas.sites import (
    AugmentedCapacityDTO,
    CandidateSiteDetail,
    CandidateSiteItem,
    CapacityBreakdownDTO,
    OsmFacilityItemDTO,
    ScreeningInfrastructureDTO,
    SiteCapacityOverrideRequest,
    SiteCapacityOverrideResponse,
)


def _truncate(value: float, digits: int) -> float:
    """Truncates toward zero for values compared against a policy threshold.

    Rounding pushes a passing value onto its own gate: a site screened at MHI 0.24999 against the
    `< 0.25` rule reads as "0.250" and looks like a violation of the rule it satisfied. The same
    applies to a 14.96-degree slope against the 15-degree gate.
    """
    factor = 10 ** digits
    return math.trunc(value * factor) / factor


def _parse_screening_infra(r: dict[str, Any]) -> Optional[ScreeningInfrastructureDTO]:
    """Safely extracts and formats ScreeningInfrastructureDTO from row record."""
    raw = r.get("screening_infra")
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return ScreeningInfrastructureDTO(
            schools_count_3km=int(raw.get("schools_count_3km") or 0),
            nearest_school_dist_m=float(raw["nearest_school_dist_m"]) if raw.get("nearest_school_dist_m") is not None else None,
            health_centres_count_8km=int(raw.get("health_centres_count_8km") or 0),
            nearest_health_dist_m=float(raw["nearest_health_dist_m"]) if raw.get("nearest_health_dist_m") is not None else None,
            water_points_count_1km=int(raw.get("water_points_count_1km") or 0),
            nearest_water_dist_m=float(raw["nearest_water_dist_m"]) if raw.get("nearest_water_dist_m") is not None else None,
            estimated_school_headroom_hh=int(raw["estimated_school_headroom_hh"]) if raw.get("estimated_school_headroom_hh") is not None else None,
            estimated_health_headroom_hh=int(raw["estimated_health_headroom_hh"]) if raw.get("estimated_health_headroom_hh") is not None else None,
            harvested_at=str(raw.get("harvested_at")) if raw.get("harvested_at") else None,
            source=str(raw.get("source") or "HOT / OpenStreetMap via Overpass API"),
            status=str(raw.get("status") or r.get("infra_screening_status") or "unscreened"),
        )
    except Exception:
        return None



class SitesService:
    """Business logic service for candidate relocation site queries and capacity simulations."""

    def __init__(
        self,
        db: Session,
        engine: Optional[CapacityEngine] = None,
        policy: Optional[CandidateSitePolicy] = None,
    ) -> None:
        self.db = db
        self.repo = SitesRepository(db)
        self.engine = engine or CapacityEngine()
        self.policy = policy or CandidateSitePolicy()

    def get_candidate_sites_for_habitation(
        self,
        habitation_id: int,
        radius_km: Optional[float] = None,
        min_suitability: Optional[int] = None,
        include_screening: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedResponse[CandidateSiteItem]:
        """Retrieves ranked candidate relocation sites within search radius of a habitation.
        
        Evaluates canonical CandidateSitePolicy in domain layer.
        If include_screening=False, filters to only allocatable (eligible) sites.
        If include_screening=True, includes screening_only/unknown sites with honest gaps.
        """
        # 1. Verify habitation exists
        if not self.repo.check_habitation_exists(habitation_id):
            raise HabitationNotFoundError(habitation_id)

        # 2. Determine search radius in meters
        active_radius_km = radius_km if radius_km is not None else self.policy.search_radius_km
        radius_m = active_radius_km * 1000.0

        clamped_limit = min(max(1, limit), 200)

        # 3. Query repository for spatial candidates
        active_policy = replace(self.policy, search_radius_km=active_radius_km)
        raw_result = self.repo.query_candidate_sites_for_habitation(
            habitation_id=habitation_id,
            radius_m=radius_m,
            min_suitability=min_suitability,
            policy=active_policy,
        )
        raw_sites = raw_result[0] if isinstance(raw_result, tuple) else raw_result

        all_items: list[CandidateSiteItem] = []
        for r in raw_sites:
            tenure_str = str(r.get("tenure") or "tenure_unverified")
            try:
                tenure_enum = TenureType(tenure_str)
            except ValueError:
                tenure_enum = TenureType.TENURE_UNVERIFIED

            # Canonical policy evaluation
            eligibility = evaluate_row_eligibility(
                engine=self.engine,
                row=r,
                policy=active_policy,
            )

            # Unless screening is explicitly requested, filter out non-eligible candidates
            if not include_screening and not eligibility.is_eligible:
                continue

            # Parse augmented capacity from JSONB
            aug_data = r.get("augmented") or {}
            if isinstance(aug_data, str):
                try:
                    aug_data = json.loads(aug_data)
                except Exception:
                    aug_data = {}

            augmented_dto = None
            if aug_data and "relieved_constraint" in aug_data and aug_data.get("augmented_capacity") is not None:
                augmented_dto = AugmentedCapacityDTO(
                    relieved_constraint=BindingConstraint(aug_data["relieved_constraint"]),
                    augmented_capacity=int(aug_data["augmented_capacity"]),
                    next_binding_constraint=BindingConstraint(aug_data["next_binding_constraint"])
                    if aug_data.get("next_binding_constraint")
                    else None,
                    indicative_intervention=str(
                        aug_data.get("indicative_intervention")
                        or "Targeted public infrastructure augmentation"
                    ),
                    indicative_cost_inr_lakhs=float(aug_data["indicative_cost_inr_lakhs"])
                    if aug_data.get("indicative_cost_inr_lakhs") is not None
                    else None,
                )

            # Metadata provenance
            meta = r.get("metadata_info") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}

            # Build capacity breakdown
            binding_str = r.get("binding_constraint")
            binding_enum = None
            if binding_str:
                try:
                    binding_enum = BindingConstraint(str(binding_str))
                except ValueError:
                    binding_enum = None

            cc_water_raw = r.get("cc_water")
            cc_school_raw = r.get("cc_school")
            cc_health_raw = r.get("cc_health")
            cc_final_raw = r.get("cc_final")
            cc_land_raw = int(r.get("cc_land") if r.get("cc_land") is not None else 0)

            h_fac_id = int(r["primary_health_facility_id"]) if r.get("primary_health_facility_id") is not None else None
            h_fac_name = str(r["health_facility_name"]) if r.get("health_facility_name") is not None else None
            h_fac_type = str(r["health_facility_type"]) if r.get("health_facility_type") is not None else None
            h_dist = round(float(r["health_distance_km"]), 2) if r.get("health_distance_km") is not None else None
            h_time_hrs = float(r["health_travel_time_hours"]) if r.get("health_travel_time_hours") is not None else None
            h_time_mins = int(round(h_time_hrs * 60)) if h_time_hrs is not None else None

            capacity_dto = CapacityBreakdownDTO(
                cc_land=cc_land_raw,
                land_screening_capacity=cc_land_raw,
                cc_water=int(cc_water_raw) if cc_water_raw is not None else None,
                cc_school=int(cc_school_raw) if cc_school_raw is not None else None,
                cc_health=int(cc_health_raw) if cc_health_raw is not None else None,
                health_facility_id=h_fac_id,
                health_facility_name=h_fac_name,
                health_facility_type=h_fac_type,
                health_distance_km=h_dist,
                health_travel_time_minutes=h_time_mins,
                livelihood_multiplier=float(meta.get("livelihood_multiplier") if meta.get("livelihood_multiplier") is not None else 1.0),
                cc_final=int(cc_final_raw) if cc_final_raw is not None else None,
                binding_constraint=binding_enum,
                tied_constraints=[binding_enum] if binding_enum else [],
                assessment_status=str(r.get("assessment_status") or "screening_only"),
                data_quality=str(meta.get("data_quality") or ("complete" if cc_final_raw is not None else "unavailable")),
                screening_infra=_parse_screening_infra(r),
                policy_version=str(meta.get("policy_version") or self.engine.norms.policy_version),
                calculation_version=str(meta.get("calculation_version") or self.engine.norms.calculation_version),
            )

            suitability_val = int(r["suitability"]) if r.get("suitability") is not None else None

            item = CandidateSiteItem(
                id=int(r["id"]),
                source_site_id=r.get("source_site_id"),
                distance_km=round(float(r.get("distance_km") if r.get("distance_km") is not None else 0.0), 2),
                area_ha=round(float(r.get("area_ha") if r.get("area_ha") is not None else 0.0), 2),
                tenure=tenure_enum,
                hazard_regime=normalize_regime(r.get("hazard_regime")),
                slope_mean=_truncate(float(r.get("slope_mean") if r.get("slope_mean") is not None else 0.0), 1),
                mhi_max=_truncate(float(r["mhi_max"]), 3) if r.get("mhi_max") is not None else None,
                suitability=suitability_val,
                assessment_status=str(r.get("assessment_status") or "screening_only"),
                eligibility_status=eligibility.eligibility_status.value,
                allocatable=eligibility.is_eligible,
                rejection_reasons=eligibility.rejection_reasons,
                capacity=capacity_dto,
                augmented=augmented_dto,
                centroid=[
                    round(float(r["lon"] if r.get("lon") is not None else 0.0), 5),
                    round(float(r["lat"] if r.get("lat") is not None else 0.0), 5),
                ],
            )
            all_items.append(item)

        total = len(all_items)
        paged_items = all_items[offset : offset + clamped_limit]

        return PaginatedResponse(
            items=paged_items,
            total=total,
            limit=clamped_limit,
            offset=offset,
            has_more=(offset + len(paged_items) < total),
        )

    def get_candidate_site_detail(self, site_id: int) -> CandidateSiteDetail:
        """Retrieves full candidate site profile including GeoJSON polygon boundary."""
        r = self.repo.get_candidate_site_by_id(site_id)
        if not r:
            raise SiteNotFoundError(site_id)

        # Parse GeoJSON
        geojson_geom = None
        if r.get("geojson_geom"):
            try:
                geojson_geom = json.loads(r["geojson_geom"])
            except Exception:
                geojson_geom = None

        # Parse augmented
        aug_data = r.get("augmented") or {}
        if isinstance(aug_data, str):
            try:
                aug_data = json.loads(aug_data)
            except Exception:
                aug_data = {}

        augmented_dto = None
        if aug_data and "relieved_constraint" in aug_data and aug_data.get("augmented_capacity") is not None:
            augmented_dto = AugmentedCapacityDTO(
                relieved_constraint=BindingConstraint(aug_data["relieved_constraint"]),
                augmented_capacity=int(aug_data.get("augmented_capacity") if aug_data.get("augmented_capacity") is not None else 0),
                next_binding_constraint=BindingConstraint(aug_data["next_binding_constraint"])
                if aug_data.get("next_binding_constraint")
                else None,
                indicative_intervention=str(aug_data.get("indicative_intervention") or ""),
                indicative_cost_inr_lakhs=float(aug_data["indicative_cost_inr_lakhs"])
                if aug_data.get("indicative_cost_inr_lakhs") is not None
                else None,
            )

        meta = r.get("metadata_info") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        cc_water_raw = r.get("cc_water")
        cc_school_raw = r.get("cc_school")
        cc_health_raw = r.get("cc_health")
        cc_final_raw = r.get("cc_final")
        cc_land_raw = int(r.get("cc_land") if r.get("cc_land") is not None else 0)

        binding_str = r.get("binding_constraint")
        binding_enum = None
        if binding_str:
            try:
                binding_enum = BindingConstraint(str(binding_str))
            except ValueError:
                binding_enum = None

        h_fac_id = int(r["primary_health_facility_id"]) if r.get("primary_health_facility_id") is not None else None
        h_fac_name = str(r["health_facility_name"]) if r.get("health_facility_name") is not None else None
        h_fac_type = str(r["health_facility_type"]) if r.get("health_facility_type") is not None else None
        h_dist = round(float(r["health_distance_km"]), 2) if r.get("health_distance_km") is not None else None
        h_time_hrs = float(r["health_travel_time_hours"]) if r.get("health_travel_time_hours") is not None else None
        h_time_mins = int(round(h_time_hrs * 60)) if h_time_hrs is not None else None

        capacity_dto = CapacityBreakdownDTO(
            cc_land=cc_land_raw,
            land_screening_capacity=cc_land_raw,
            cc_water=int(cc_water_raw) if cc_water_raw is not None else None,
            cc_school=int(cc_school_raw) if cc_school_raw is not None else None,
            cc_health=int(cc_health_raw) if cc_health_raw is not None else None,
            health_facility_id=h_fac_id,
            health_facility_name=h_fac_name,
            health_facility_type=h_fac_type,
            health_distance_km=h_dist,
            health_travel_time_minutes=h_time_mins,
            livelihood_multiplier=float(meta.get("livelihood_multiplier") if meta.get("livelihood_multiplier") is not None else 1.0),
            cc_final=int(cc_final_raw) if cc_final_raw is not None else None,
            binding_constraint=binding_enum,
            tied_constraints=[binding_enum] if binding_enum else [],
            assessment_status=str(r.get("assessment_status") or "screening_only"),
            data_quality=str(meta.get("data_quality") or ("complete" if cc_final_raw is not None else "unavailable")),
            screening_infra=_parse_screening_infra(r),
            policy_version=str(meta.get("policy_version") or self.engine.norms.policy_version),
            calculation_version=str(meta.get("calculation_version") or self.engine.norms.calculation_version),
        )

        suitability_val = int(r["suitability"]) if r.get("suitability") is not None else None

        tenure_str = str(r.get("tenure") or "tenure_unverified")
        try:
            tenure_enum = TenureType(tenure_str)
        except ValueError:
            tenure_enum = TenureType.TENURE_UNVERIFIED

        eligibility = evaluate_row_eligibility(
            engine=self.engine,
            row=r,
            policy=self.policy,
        )

        return CandidateSiteDetail(
            id=int(r["id"]),
            source_site_id=r.get("source_site_id"),
            distance_km=0.0,
            area_ha=round(float(r.get("area_ha") if r.get("area_ha") is not None else 0.0), 2),
            tenure=tenure_enum,
            slope_mean=_truncate(float(r.get("slope_mean") if r.get("slope_mean") is not None else 0.0), 1),
            mhi_max=_truncate(float(r["mhi_max"]), 3) if r.get("mhi_max") is not None else None,
            suitability=suitability_val,
            assessment_status=str(r.get("assessment_status") or "screening_only"),
            eligibility_status=eligibility.eligibility_status.value,
            allocatable=eligibility.is_eligible,
            rejection_reasons=eligibility.rejection_reasons,
            capacity=capacity_dto,
            augmented=augmented_dto,
            centroid=[
                round(float(r["lon"] if r.get("lon") is not None else 0.0), 5),
                round(float(r["lat"] if r.get("lat") is not None else 0.0), 5),
            ],
            geometry=geojson_geom,
        )

    def recompute_site_capacity(
        self,
        site_id: int,
        overrides: SiteCapacityOverrideRequest,
    ) -> SiteCapacityOverrideResponse:
        """Simulates candidate site carrying capacity under overridden policy norms / resource inputs."""
        r = self.repo.get_candidate_site_by_id(site_id)
        if not r:
            raise SiteNotFoundError(site_id)

        # Baseline capacity
        base_cc_land = int(r.get("cc_land") if r.get("cc_land") is not None else 0)
        base_cc_water = int(r["cc_water"]) if r.get("cc_water") is not None else None
        base_cc_school = int(r["cc_school"]) if r.get("cc_school") is not None else None
        base_cc_health = int(r["cc_health"]) if r.get("cc_health") is not None else None
        base_cc_final = int(r.get("cc_final") if r.get("cc_final") is not None else 0)
        base_binding = BindingConstraint(r.get("binding_constraint") or "land")

        screening_infra_dto = _parse_screening_infra(r)

        base_capacity = CapacityBreakdownDTO(
            cc_land=base_cc_land,
            cc_water=base_cc_water,
            cc_school=base_cc_school,
            cc_health=base_cc_health,
            livelihood_multiplier=1.0,
            cc_final=base_cc_final,
            binding_constraint=base_binding,
            data_quality="complete",
            screening_infra=screening_infra_dto,
            policy_version=self.engine.norms.policy_version,
            calculation_version=self.engine.norms.calculation_version,
        )

        # Build overridden norms
        area_ha = float(r.get("area_ha") if r.get("area_ha") is not None else 2.0)
        area_m2 = area_ha * 10000.0

        # Apply overrides
        new_plot_area = overrides.plot_area_m2 if overrides.plot_area_m2 is not None else self.engine.norms.plot_area_m2
        scen_cc_land = self.engine.calculate_land_capacity(area_m2, plot_area_m2=new_plot_area)

        if overrides.daily_water_yield_liters is not None:
            scen_cc_water = self.engine.calculate_water_capacity(
                yield_liters_per_day=overrides.daily_water_yield_liters,
                lpcd=overrides.water_lpcd,
            )
        elif overrides.water_lpcd is not None and base_cc_water is not None:
            # Scale base water capacity with LPCD ratio
            lpcd_ratio = float(self.engine.norms.lpcd_rural) / max(1, overrides.water_lpcd)
            scen_cc_water = max(0, int(base_cc_water * lpcd_ratio))
        else:
            scen_cc_water = base_cc_water

        # Check for OSM screening estimates when requested
        if overrides.use_osm_screening and screening_infra_dto:
            default_osm_school_headroom = screening_infra_dto.estimated_school_headroom_hh
            default_osm_health_headroom = screening_infra_dto.estimated_health_headroom_hh
        else:
            default_osm_school_headroom = None
            default_osm_health_headroom = None

        if overrides.spare_school_seats is not None:
            scen_cc_school = self.engine.calculate_school_capacity(overrides.spare_school_seats)
        elif default_osm_school_headroom is not None:
            scen_cc_school = default_osm_school_headroom
        else:
            scen_cc_school = base_cc_school

        if overrides.spare_health_capacity_pop is not None:
            scen_cc_health = self.engine.calculate_health_capacity(catchment_pop=0, phc_norm_pop=overrides.spare_health_capacity_pop)
        elif default_osm_health_headroom is not None:
            scen_cc_health = default_osm_health_headroom
        else:
            scen_cc_health = base_cc_health

        mu = overrides.livelihood_multiplier if overrides.livelihood_multiplier is not None else 1.0
        scen_final, scen_binding, scen_tied = self.engine.calculate_final_capacity(
            scen_cc_land, scen_cc_water, scen_cc_school, scen_cc_health, mu
        )

        scen_capacity = CapacityBreakdownDTO(
            cc_land=scen_cc_land,
            cc_water=scen_cc_water,
            cc_school=scen_cc_school,
            cc_health=scen_cc_health,
            livelihood_multiplier=mu,
            cc_final=scen_final,
            binding_constraint=scen_binding,
            tied_constraints=scen_tied,
            data_quality="complete",
            screening_infra=screening_infra_dto,
            policy_version="scenario-override-v1.0",
            calculation_version=self.engine.norms.calculation_version,
        )

        # Augmented relief options
        aug_res = self.engine.calculate_augmented_capacity(
            scen_cc_land, scen_cc_water, scen_cc_school, scen_cc_health, scen_binding, livelihood_multiplier=mu
        )
        aug_dto = None
        if aug_res and aug_res.relieved_constraint is not None and aug_res.augmented_capacity is not None:
            aug_dto = AugmentedCapacityDTO(
                relieved_constraint=aug_res.relieved_constraint,
                augmented_capacity=aug_res.augmented_capacity,
                next_binding_constraint=aug_res.next_binding_constraint,
                indicative_intervention=aug_res.indicative_intervention,
                indicative_cost_inr_lakhs=aug_res.indicative_cost_inr_lakhs,
            )

        delta = (scen_final if scen_final is not None else 0) - (base_cc_final if base_cc_final is not None else 0)

        return SiteCapacityOverrideResponse(
            site_id=site_id,
            base_capacity=base_capacity,
            scenario_capacity=scen_capacity,
            delta_households=delta,
            augmented_options=[aug_dto] if aug_dto is not None else [],
        )

    def get_site_infrastructure_facilities(
        self, site_id: int, radius_m: float = 8000.0
    ) -> list[OsmFacilityItemDTO]:
        """Retrieves nearby OSM facilities for a candidate site."""
        if not self.repo.get_candidate_site_by_id(site_id):
            raise SiteNotFoundError(site_id)
        raw_facilities = self.repo.get_site_infrastructure_facilities(site_id, radius_m=radius_m)
        items: list[OsmFacilityItemDTO] = []
        for f in raw_facilities:
            tags = f.get("tags") or {}
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            items.append(
                OsmFacilityItemDTO(
                    id=int(f["id"]),
                    osm_id=int(f["osm_id"]),
                    osm_type=str(f["osm_type"]),
                    facility_type=str(f["facility_type"]),
                    name=f.get("name"),
                    operator_type=str(f.get("operator_type") or "unknown"),
                    distance_m=round(float(f["distance_m"]), 1) if f.get("distance_m") is not None else None,
                    coordinates=[float(f["lon"]), float(f["lat"])],
                    tags=tags,
                )
            )
        return items

