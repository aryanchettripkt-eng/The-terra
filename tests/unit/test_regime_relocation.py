"""Phase 2e: hazard-regime policy in priority scoring, triage, eligibility and allocation."""

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from core.domain.allocation import (
    AllocationConfig,
    CandidateSiteCapacity,
    HabitationDemand,
    HabitationSiteDistance,
    MinCostFlowAllocationSolver,
    summarize_allocation_by_regime,
)
from core.domain.capacity import CandidateSitePolicy, CapacityEngine
from core.domain.priority import PriorityScoringEngine
from core.domain.regime import (
    RegimePolicyConfig,
    adjust_tier_for_regime,
    apply_regime_urgency,
    is_destination_regime_allowed,
    normalize_regime,
    relocation_pathway_for,
)
from core.enums import HazardRegime, RelocationPathway, Tier
from pipeline.relocation.eligibility_mask import EligibilityMaskConfig, build_eligibility_mask
from pipeline.relocation.regime_mask import rasterize_blocked_regimes


# --- regime policy ---------------------------------------------------------------------------

def test_char_belt_priority_is_uplifted_and_other_regimes_are_not():
    assert apply_regime_urgency(0.2, "char_belt") == pytest.approx(0.25)
    assert apply_regime_urgency(0.2, "floodplain") == 0.2
    assert apply_regime_urgency(0.2, "channel") == 0.2
    assert apply_regime_urgency(0.2, None) == 0.2
    assert apply_regime_urgency(0.2, "char_belt", RegimePolicyConfig(char_belt_urgency_multiplier=2.0)) == 0.4


def test_char_belt_planning_horizon_shortens_and_in_situ_is_dropped():
    medium = adjust_tier_for_regime(Tier.MEDIUM_TERM, "char_belt")
    assert medium.tier == Tier.SHORT_TERM and medium.changed and "6-24 months" in medium.note

    in_situ = adjust_tier_for_regime(Tier.MITIGATE_IN_SITU, "char_belt")
    assert in_situ.tier == Tier.SHORT_TERM and "not viable" in in_situ.note

    # Immediate stays reserved for evidence-based criteria; short-term is already as short as it goes.
    assert adjust_tier_for_regime(Tier.IMMEDIATE, "char_belt").tier == Tier.IMMEDIATE
    assert not adjust_tier_for_regime(Tier.SHORT_TERM, "char_belt").changed
    assert adjust_tier_for_regime(None, "char_belt").tier is None


def test_floodplain_keeps_in_situ_mitigation_and_its_tier():
    assert adjust_tier_for_regime(Tier.MITIGATE_IN_SITU, "floodplain").tier == Tier.MITIGATE_IN_SITU
    assert adjust_tier_for_regime(Tier.MEDIUM_TERM, "floodplain").tier == Tier.MEDIUM_TERM
    assert adjust_tier_for_regime(Tier.MITIGATE_IN_SITU, None).tier == Tier.MITIGATE_IN_SITU


def test_policy_can_keep_in_situ_viable_for_char_belt():
    policy = RegimePolicyConfig(char_belt_in_situ_viable=True)
    assert adjust_tier_for_regime(Tier.MITIGATE_IN_SITU, "char_belt", policy).tier == Tier.MITIGATE_IN_SITU


def test_pathways_and_destination_rules():
    assert relocation_pathway_for("char_belt") == RelocationPathway.MAINLAND_RESETTLEMENT
    assert relocation_pathway_for("floodplain") == RelocationPathway.IN_SITU_OR_NEARBY
    assert relocation_pathway_for("channel") == RelocationPathway.NOT_APPLICABLE
    assert relocation_pathway_for(None) == RelocationPathway.NOT_APPLICABLE

    assert not is_destination_regime_allowed("char_belt")
    assert not is_destination_regime_allowed("channel")
    assert is_destination_regime_allowed("floodplain")
    assert is_destination_regime_allowed(None)  # no regime layer: not blocked
    assert normalize_regime("lava") is None


def test_engine_scores_and_tiers_char_belt_differently_from_floodplain():
    engine = PriorityScoringEngine()
    args = dict(hazard_intensity=0.7, pop_fraction_in_prz=0.5, vulnerability_index=0.5, population=100)
    base = engine.evaluate_habitation(**args)
    char = engine.evaluate_habitation(**args, regime="char_belt")
    plain = engine.evaluate_habitation(**args, regime="floodplain")

    assert plain["priority_score"] == base["priority_score"]
    assert char["priority_score"] == pytest.approx(base["priority_score"] * 1.25, abs=1e-3)
    assert char["relocation_pathway"] == RelocationPathway.MAINLAND_RESETTLEMENT
    assert plain["relocation_pathway"] == RelocationPathway.IN_SITU_OR_NEARBY


def test_engine_moves_a_char_belt_in_situ_habitation_to_short_term():
    engine = PriorityScoringEngine()
    args = dict(
        hazard_intensity=0.5, pop_fraction_in_prz=0.1, vulnerability_index=0.5,
        in_situ_cost_cheaper=True, mitigation_cost=1.0, relocation_cost=5.0,
    )
    assert engine.evaluate_habitation(**args, regime="floodplain")["tier"] == Tier.MITIGATE_IN_SITU
    char = engine.evaluate_habitation(**args, regime="char_belt")
    assert char["tier"] == Tier.SHORT_TERM and "not viable" in char["triage_rationale"]


# --- candidate-site eligibility ----------------------------------------------------------------

SCREENING = CandidateSitePolicy(allow_unverified_tenure=True, allow_unmeasured_hazard=True)
GOOD_SITE = dict(mhi_max=0.1, slope_mean=2.0, area_ha=5.0, tenure="private", distance_km=3.0)


@pytest.mark.parametrize("regime", ["char_belt", "channel"])
def test_a_site_in_a_blocked_regime_is_rejected_even_when_otherwise_perfect(regime):
    result = CapacityEngine().evaluate_site_eligibility(**GOOD_SITE, hazard_regime=regime, policy=SCREENING)
    assert not result.is_eligible
    assert any("hazard regime" in reason for reason in result.rejection_reasons)


@pytest.mark.parametrize("regime", ["floodplain", None])
def test_floodplain_and_unknown_regime_sites_stay_eligible(regime):
    result = CapacityEngine().evaluate_site_eligibility(**GOOD_SITE, hazard_regime=regime, policy=SCREENING)
    assert result.is_eligible


# --- allocation solver -------------------------------------------------------------------------

def _plan(site_regimes, hab_regime="char_belt"):
    habs = [HabitationDemand(id=1, name="Char village", demand_households=10, priority_score=0.8,
                             tier=Tier.SHORT_TERM, regime=hab_regime)]
    sites = [
        CandidateSiteCapacity(id=i, name=f"S{i}", capacity_households=20, suitability=80, regime=r)
        for i, r in site_regimes.items()
    ]
    dists = [HabitationSiteDistance(habitation_id=1, site_id=i, distance_km=2.0 + i) for i in site_regimes]
    result = MinCostFlowAllocationSolver(AllocationConfig()).solve(habs, sites, dists)
    return habs, result


def test_solver_never_resettles_onto_a_char_belt_even_if_it_is_nearest():
    habs, result = _plan({0: "char_belt", 1: "channel", 2: "floodplain"})
    assert {a.site_id for a in result.assignments} == {2}
    assert result.unmet_demand_households == 0
    assert result.assignments[0].pathway == RelocationPathway.MAINLAND_RESETTLEMENT
    assert result.assignments[0].site_regime == "floodplain"


def test_char_belt_households_are_unmet_when_only_char_sites_exist():
    habs, result = _plan({0: "char_belt", 1: "char_belt"})
    assert result.assignments == [] and result.unmet_demand_households == 10
    summary = summarize_allocation_by_regime(habs, result.assignments)
    assert summary[0].regime == "char_belt" and summary[0].unmet_households == 10


def test_site_with_no_regime_is_still_usable():
    _, result = _plan({0: None})
    assert result.total_relocated_households == 10


def test_regime_summary_orders_char_belt_first_and_counts_relocated():
    habs = [
        HabitationDemand(id=1, name="A", demand_households=6, priority_score=0.5, tier=Tier.SHORT_TERM, regime="floodplain"),
        HabitationDemand(id=2, name="B", demand_households=4, priority_score=0.9, tier=Tier.SHORT_TERM, regime="char_belt"),
    ]
    sites = [CandidateSiteCapacity(id=9, name="M", capacity_households=100, suitability=70, regime="floodplain")]
    dists = [HabitationSiteDistance(habitation_id=h.id, site_id=9, distance_km=1.0) for h in habs]
    result = MinCostFlowAllocationSolver(AllocationConfig()).solve(habs, sites, dists)
    summary = summarize_allocation_by_regime(habs, result.assignments)
    assert [s.regime for s in summary] == ["char_belt", "floodplain"]
    assert [s.relocated_households for s in summary] == [4, 6]


# --- pipeline eligibility mask -----------------------------------------------------------------

def test_blocked_regime_pixels_are_rejected_by_their_own_gate():
    shape = (4, 4)
    ok = np.zeros(shape, dtype=np.float32)
    blocked = np.zeros(shape, dtype=bool)
    blocked[:, :2] = True
    mask, stats = build_eligibility_mask(
        susceptibility=ok, slope=ok, tree_cover_fraction=ok, built_up_fraction=ok,
        permanent_water=ok, blocked_regime_mask=blocked, config=EligibilityMaskConfig(),
    )
    assert mask[:, 2:].all() and not mask[:, :2].any()
    assert stats.rejected["hazard_regime"] == 8


def test_without_a_regime_mask_nothing_is_gated():
    ok = np.zeros((2, 2), dtype=np.float32)
    mask, stats = build_eligibility_mask(
        susceptibility=ok, slope=ok, tree_cover_fraction=ok, built_up_fraction=ok, permanent_water=ok,
    )
    assert mask.all() and "hazard_regime" not in stats.rejected


def test_rasterize_blocked_regimes_marks_only_char_and_channel_cells():
    cells = gpd.GeoDataFrame(
        {"hazard_regime": ["char_belt", "floodplain", "channel"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
        crs="EPSG:4326",
    )
    transform = rasterio.transform.from_bounds(0, 0, 3, 1, 3, 1)
    out = rasterize_blocked_regimes(cells, (1, 3), transform, "EPSG:4326")
    assert out.tolist() == [[True, False, True]]
