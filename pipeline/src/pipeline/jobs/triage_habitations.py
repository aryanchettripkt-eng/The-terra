"""Track 1: Demand-Side Activation — Habitation Hazard Triage & Priority Scoring Job.

Grades habitations from 'pending' / NULL tier into valid, operational triage tiers
(immediate, short_term, medium_term, mitigate_in_situ, or monitoring) using deterministic
spatial joins against H3 flood susceptibility rasters and canonical domain triage rules.

Section refs: docs/PRD1.md §6.6, §6.7, FR-6.1–FR-6.4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import h3
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

REPO_ROOT = Path(__file__).resolve().parents[4]
for sub in ("core/src", "pipeline/src", "api/src"):
    p = str(REPO_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from core.config import settings
from core.constants import CAUTION_MHI_MIN, PRZ_ANY_SUSCEPTIBILITY, PRZ_MHI_STATIC
from core.domain.priority import (
    TriageRuleConfig,
    classify_triage_tier,
    compute_priority_score,
    evaluate_triage_with_rationale,
)
from core.domain.regime import (
    adjust_tier_for_regime,
    apply_regime_urgency,
    normalize_regime,
    relocation_pathway_for,
)
from core.enums import HazardRegime, Tier

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("setu_pipeline.triage_habitations")

JOB_VERSION = "triage-v1.1-regime"
SCORING_VERSION = "priority-v1.1-regime"
DATASET_VERSION = "h3-hazard-static-v1.0"
DEFAULT_VULNERABILITY_ANCHOR = 0.5


def triage_district_habitations(
    conn: Connection,
    admin_id: int,
    district_name: str,
    vulnerability_anchor: float = DEFAULT_VULNERABILITY_ANCHOR,
    pipeline_run_id: Optional[uuid.UUID] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scores untiered habitations for an administrative boundary."""
    run_id = pipeline_run_id or (uuid.uuid4() if not dry_run else None)
    now = datetime.now(timezone.utc)

    # 1. Fetch all habitations in this admin scope
    hab_rows = conn.execute(
        text("""
            SELECT h.id, h.name, h.population, h.households, h.source_habitation_id,
                   h.risk_status,
                   ST_X(h.geom_point::geometry) as lon,
                   ST_Y(h.geom_point::geometry) as lat,
                   hr.tier, hr.hazard_intensity, hr.prz_overlap_pct, hr.priority_score,
                   err.tier as external_tier
            FROM habitation h
            LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
            LEFT JOIN external_relocation_recommendation err ON h.id = err.habitation_id
            WHERE h.admin_id = :admin_id
            ORDER BY h.id ASC;
        """),
        {"admin_id": admin_id},
    ).mappings().all()

    if not hab_rows:
        logger.info("No habitations found for district %s (admin_id=%s)", district_name, admin_id)
        return {"district": district_name, "processed": 0, "updated": 0, "tiers": {}}

    # 2. Pre-cache hazard_static for this admin_id via grid_cell
    hazard_rows = conn.execute(
        text("""
            SELECT hs.h3, hs.susceptibility, hs.hazard_type, hs.quality_flag, f.hazard_regime
            FROM hazard_static hs
            JOIN grid_cell gc ON hs.h3 = gc.h3
            LEFT JOIN hazard_static_flood f ON f.h3 = hs.h3
            WHERE gc.admin_id = :admin_id;
        """),
        {"admin_id": admin_id},
    ).mappings().all()

    h3_hazard_map: dict[int, float] = {}
    h3_regime_map: dict[int, HazardRegime] = {}
    dominant_hazard = "riverine_flood"
    for hr in hazard_rows:
        cell_int = int(hr["h3"])
        regime = normalize_regime(hr.get("hazard_regime"))
        if regime is not None:
            h3_regime_map[cell_int] = regime
        # A channel cell carries a placeholder 0.0, not a score. Leaving it out sends a habitation
        # mapped onto the channel to the neighbour average instead of reading as perfectly safe.
        if hr.get("quality_flag") != "channel_excluded":
            h3_hazard_map[cell_int] = float(hr["susceptibility"])
        if hr.get("hazard_type"):
            dominant_hazard = str(hr["hazard_type"])

    logger.info(
        "Loaded %d hazard cells for %s (admin_id=%d). Processing %d habitations...",
        len(h3_hazard_map), district_name, admin_id, len(hab_rows)
    )

    triage_counts: dict[str, int] = {}
    regime_counts: dict[str, dict[str, int]] = {}
    updated_count = 0
    triage_rules = TriageRuleConfig()

    for h in hab_rows:
        hab_id = int(h["id"])
        lat = float(h["lat"]) if h.get("lat") is not None else None
        lon = float(h["lon"]) if h.get("lon") is not None else None
        pop = int(h["population"]) if h.get("population") else 0
        hh = int(h["households"]) if h.get("households") else int(round(pop / 4.5))

        # Check existing values
        existing_hazard = h.get("hazard_intensity")
        existing_prz = h.get("prz_overlap_pct")
        existing_tier = h.get("tier")
        external_tier_str = h.get("external_tier")

        # Resolve hazard intensity & PRZ from spatial cells if missing
        if existing_hazard is not None:
            hazard_intensity = float(existing_hazard)
            prz_overlap_pct = float(existing_prz if existing_prz is not None else 0.0)
        elif lat is not None and lon is not None and h3_hazard_map:
            # Map point to H3 res 8 cell
            cell_str = h3.latlng_to_cell(lat, lon, 8)
            cell_int = h3.str_to_int(cell_str)

            # Look up direct cell and k-ring 1 neighbors
            direct_susc = h3_hazard_map.get(cell_int)
            kring = [h3.str_to_int(c) for c in h3.grid_disk(cell_str, 1)]
            neighbor_suscs = [h3_hazard_map[c] for c in kring if c in h3_hazard_map]

            if direct_susc is not None:
                hazard_intensity = direct_susc
            elif neighbor_suscs:
                hazard_intensity = sum(neighbor_suscs) / len(neighbor_suscs)
            else:
                hazard_intensity = 0.35  # default baseline if district hazard unmapped

            # PRZ overlap: share of neighborhood cells exceeding PRZ threshold
            if neighbor_suscs:
                prz_cells = [s for s in neighbor_suscs if s >= PRZ_ANY_SUSCEPTIBILITY]
                prz_overlap_pct = round(len(prz_cells) / len(neighbor_suscs) * 100.0, 2)
            else:
                prz_overlap_pct = 100.0 if hazard_intensity >= PRZ_ANY_SUSCEPTIBILITY else 0.0
        else:
            hazard_intensity = 0.35
            prz_overlap_pct = 0.0

        # Hazard regime of the habitation's own cell; None when the district has no regime layer.
        habitation_regime: Optional[HazardRegime] = None
        if lat is not None and lon is not None and h3_regime_map:
            habitation_regime = h3_regime_map.get(h3.str_to_int(h3.latlng_to_cell(lat, lon, 8)))
        pathway = relocation_pathway_for(habitation_regime)

        # Calculate Priority Score (FR-6.1), with the regime's urgency uplift (Phase 2e)
        pop_fraction_in_prz = prz_overlap_pct / 100.0
        base_ps = compute_priority_score(
            hazard_intensity=hazard_intensity,
            pop_fraction_in_prz=pop_fraction_in_prz,
            vulnerability_index=vulnerability_anchor,
        )
        computed_ps = apply_regime_urgency(base_ps, habitation_regime)

        # Classify Triage Tier (PRD §6.7)
        # 1. Check if external partner GIS recommendation specified a tier (e.g. Barpeta primary settlements)
        assigned_tier: Optional[Tier] = None
        assigned_rationale = ""
        factors: list[dict[str, Any]] = [
            {"name": "Flood susceptibility", "contribution": round(hazard_intensity, 4), "type": "hazard"},
            {"name": "Population in permanent red zone", "contribution": round(pop_fraction_in_prz, 4), "type": "exposure"},
            {"name": "Social Vulnerability anchor", "contribution": vulnerability_anchor, "type": "vulnerability"},
        ]
        if habitation_regime is not None:
            factors.append(
                {"name": f"Hazard regime: {habitation_regime.value}", "contribution": round(computed_ps - base_ps, 4), "type": "regime"}
            )

        if external_tier_str:
            try:
                assigned_tier = Tier(external_tier_str)
                assigned_rationale = (
                    f"External partner recommendation: {assigned_tier.value} relocation based on "
                    f"district-level flood exposure and ground survey."
                )
            except ValueError:
                pass

        if assigned_tier is None:
            # Canonical PRD §6.7 rules
            triage_res = evaluate_triage_with_rationale(
                has_prz_overlap=(prz_overlap_pct > 0),
                pop_fraction_in_prz=pop_fraction_in_prz,
                hazard_intensity=hazard_intensity,
                priority_score=computed_ps,
                rules=triage_rules,
            )
            assigned_tier = triage_res.tier
            assigned_rationale = triage_res.rationale

            # If still None, check if settlement sits in Caution Zone with moderate/adverse hazard
            if assigned_tier is None:
                if hazard_intensity >= 0.45:
                    # Upper Caution Zone with recurrent monsoon inundation
                    assigned_tier = Tier.MEDIUM_TERM
                    assigned_rationale = (
                        "Medium-term planned relocation required (2-5 years): "
                        f"Caution Zone with severe chronic flood exposure (hazard intensity {hazard_intensity:.2f} >= 0.45)."
                    )
                elif hazard_intensity >= CAUTION_MHI_MIN and prz_overlap_pct > 0:
                    assigned_tier = Tier.MITIGATE_IN_SITU
                    assigned_rationale = (
                        "Mitigate in-situ: Civil mitigation (flood embankment/drainage) recommended "
                        "over permanent physical relocation."
                    )
                else:
                    assigned_tier = None
                    assigned_rationale = "Unclassified / Monitoring: Settlement does not meet criteria for permanent relocation."

        # Planning-horizon rules apply to computed tiers only; an external partner's tier stands.
        if not external_tier_str:
            adjustment = adjust_tier_for_regime(assigned_tier, habitation_regime)
            if adjustment.changed:
                assigned_tier = adjustment.tier
                assigned_rationale = f"{assigned_rationale} {adjustment.note}".strip()

        tier_str = assigned_tier.value if assigned_tier is not None else None
        tier_key = tier_str or "monitoring_none"
        triage_counts[tier_key] = triage_counts.get(tier_key, 0) + 1
        regime_key = habitation_regime.value if habitation_regime else "no_regime"
        regime_counts.setdefault(regime_key, {})
        regime_counts[regime_key][tier_key] = regime_counts[regime_key].get(tier_key, 0) + 1

        caseload = round(computed_ps * pop, 2)

        if not dry_run:
            # Upsert into habitation_risk
            conn.execute(
                text("""
                    INSERT INTO habitation_risk (
                        habitation_id, admin_id, population, households,
                        hazard_intensity, prz_overlap_pct, decayed_loss, v_index,
                        priority_score, caseload_score, tier, triage_rationale,
                        contributing_factors, dominant_hazard, model_version, scoring_version,
                        dataset_version, data_quality, confidence, calculated_at, pipeline_run_id,
                        active_deformation, fatal_event_last_3_monsoons, adverse_trend,
                        hazard_regime, relocation_pathway
                    ) VALUES (
                        :hab_id, :admin_id, :pop, :hh,
                        :hazard, :prz, 0.0, :v,
                        :ps, :caseload, :tier, :rationale,
                        CAST(:factors AS jsonb), :dominant, :model_ver, :scoring_ver,
                        :dataset_ver, 'derived', 0.85, :now, :run_id,
                        FALSE, FALSE, :adverse,
                        :regime, :pathway
                    )
                    ON CONFLICT (habitation_id) DO UPDATE SET
                        population = EXCLUDED.population,
                        households = EXCLUDED.households,
                        hazard_intensity = EXCLUDED.hazard_intensity,
                        prz_overlap_pct = EXCLUDED.prz_overlap_pct,
                        v_index = EXCLUDED.v_index,
                        priority_score = EXCLUDED.priority_score,
                        caseload_score = EXCLUDED.caseload_score,
                        tier = EXCLUDED.tier,
                        hazard_regime = EXCLUDED.hazard_regime,
                        relocation_pathway = EXCLUDED.relocation_pathway,
                        scoring_version = EXCLUDED.scoring_version,
                        triage_rationale = EXCLUDED.triage_rationale,
                        contributing_factors = EXCLUDED.contributing_factors,
                        calculated_at = EXCLUDED.calculated_at,
                        pipeline_run_id = EXCLUDED.pipeline_run_id;
                """),
                {
                    "hab_id": hab_id,
                    "admin_id": admin_id,
                    "pop": pop,
                    "hh": hh,
                    "hazard": round(hazard_intensity, 4),
                    "prz": round(prz_overlap_pct, 2),
                    "v": vulnerability_anchor,
                    "ps": round(computed_ps, 4),
                    "caseload": caseload,
                    "tier": tier_str,
                    "rationale": assigned_rationale,
                    "factors": json.dumps(factors),
                    "dominant": dominant_hazard,
                    "model_ver": JOB_VERSION,
                    "dataset_ver": DATASET_VERSION,
                    "now": now,
                    "run_id": run_id,
                    "adverse": bool(hazard_intensity >= 0.45),
                    "regime": habitation_regime.value if habitation_regime else None,
                    "pathway": pathway.value if habitation_regime else None,
                    "scoring_ver": SCORING_VERSION,
                },
            )

            # Update habitation status to 'scored'
            conn.execute(
                text("""
                    UPDATE habitation
                    SET risk_status = 'scored'
                    WHERE id = :hab_id;
                """),
                {"hab_id": hab_id},
            )
        updated_count += 1

    return {
        "district": district_name,
        "admin_id": admin_id,
        "processed": len(hab_rows),
        "updated": updated_count,
        "tier_distribution": triage_counts,
        "tier_distribution_by_regime": regime_counts,
        "pipeline_run_id": str(run_id),
    }


def run_triage_job(
    district_filter: Optional[str] = None,
    engine: Optional[Engine] = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Runs the triage job across target districts."""
    eng = engine or create_engine(settings.get_sqlalchemy_url())
    now = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    with eng.begin() as conn:
        # Fetch matching districts
        if district_filter:
            dist_rows = conn.execute(
                text("SELECT id, name, level FROM admin_boundary WHERE lower(name) = lower(:n) AND level='district'"),
                {"n": district_filter},
            ).mappings().all()
        else:
            dist_rows = conn.execute(
                text("""
                    SELECT id, name, level FROM admin_boundary
                    WHERE level='district' AND id IN (SELECT DISTINCT admin_id FROM habitation WHERE admin_id IS NOT NULL)
                    ORDER BY id;
                """)
            ).mappings().all()

        if not dist_rows:
            logger.warning("No districts matching criteria.")
            return []

        pipeline_run_id = uuid.uuid4()
        if not dry_run:
            conn.execute(
                text("""
                    INSERT INTO pipeline_run (
                        id, run_type, status, started_at, completed_at,
                        code_version, config_version, model_version
                    ) VALUES (
                        :id, 'triage_habitations', 'READY', :now, :now,
                        :code_ver, 'prz_thresh=0.65;caution_min=0.35', :model_ver
                    );
                """),
                {
                    "id": pipeline_run_id,
                    "now": now,
                    "code_ver": JOB_VERSION,
                    "model_ver": "priority-triage-v1.0",
                },
            )

        for d in dist_rows:
            admin_id = int(d["id"])
            name = str(d["name"])
            res = triage_district_habitations(
                conn=conn,
                admin_id=admin_id,
                district_name=name,
                pipeline_run_id=pipeline_run_id,
                dry_run=dry_run,
            )
            results.append(res)
            logger.info("Completed triage for %s: %s", name, res["tier_distribution"])

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district", help="Specific district name (e.g. Barpeta, Morena, Dholpur)")
    parser.add_argument("--all", action="store_true", help="Run triage across all districts with habitations")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing to database")
    args = parser.parse_args()

    if not args.district and not args.all:
        parser.error("Specify either --district <name> or --all")

    target = args.district if args.district else None
    results = run_triage_job(district_filter=target, dry_run=args.dry_run)
    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
