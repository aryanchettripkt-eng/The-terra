"""Service layer for Habitations triage queue and Risk Dossiers.

Section refs: docs/PRD1.md §6.6, §6.7, §14.1
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Optional, Any
from sqlalchemy.orm import Session

from core.domain.regime import normalize_regime, relocation_pathway_for
from core.enums import HazardRegime, RelocationPathway, Tier, SortMode
from core.errors import HabitationNotFoundError
from core.domain.priority import (
    PriorityScoringConfig,
    PriorityScoringEngine,
    TriageRuleConfig,
    compute_time_decayed_loss,
    check_fatal_event_last_3_monsoons,
    check_loss_frequency_rising,
)
from core.domain.vulnerability import compute_vulnerability_index, VulnerabilityConfig
from core.domain.explanation import normalize_feature_contributions
from core.schemas.common import PaginatedResponse
from core.schemas.explanation import FeatureContributionDTO
from core.schemas.habitations import (
    HabitationListItem,
    HabitationRiskDossier,
    VulnerabilityBreakdownDTO,
    LossEventDTO,
)
from api.repositories.habitations_repo import HabitationsRepository


class HabitationsService:
    """Business logic service for Habitation risk scoring, triage queues, and dossiers."""

    def __init__(
        self,
        db: Session,
        scoring_config: Optional[PriorityScoringConfig] = None,
        vulnerability_config: Optional[VulnerabilityConfig] = None,
    ) -> None:
        self.db = db
        self.repo = HabitationsRepository(db)
        self.scoring_config = scoring_config or PriorityScoringConfig()
        self.vulnerability_config = vulnerability_config or VulnerabilityConfig()
        self.engine = PriorityScoringEngine(
            scoring_config=self.scoring_config,
            triage_config=TriageRuleConfig(),
        )

    @staticmethod
    def _pathway(row: dict[str, Any]) -> Optional[RelocationPathway]:
        """Persisted pathway, else the one implied by the regime; None when the row has no regime."""
        persisted = row.get("relocation_pathway")
        if persisted:
            try:
                return RelocationPathway(persisted)
            except ValueError:
                pass
        regime = normalize_regime(row.get("hazard_regime"))
        return relocation_pathway_for(regime) if regime else None

    def get_habitations(
        self,
        admin: Optional[int] = None,
        tier: Optional[Tier] = None,
        sort: SortMode = SortMode.URGENCY,
        limit: int = 50,
        offset: int = 0,
        regime: Optional[HazardRegime] = None,
    ) -> PaginatedResponse[HabitationListItem]:
        """Returns prioritized queue of habitations with dual urgency/caseload sorting."""
        clamped_limit = min(max(1, limit), 200)
        tier_str = tier.value if tier else None

        # 1. Query repository directly with SQL-level ordering & pagination
        raw_items, total = self.repo.query_habitations(
            admin_id=admin,
            tier=tier_str,
            sort=sort,
            limit=clamped_limit,
            offset=offset,
            regime=regime.value if regime else None,
        )

        items = []
        for r in raw_items:
            pop = int(r.get("population") if r.get("population") is not None else 0)
            
            # Trust persisted scoring whenever habitation_risk carries a score. A NULL tier is a
            # legitimate persisted outcome, not missing data: classify_triage_tier() returns None
            # when a habitation satisfies none of the four PRD tiers. Requiring a tier here sent
            # those rows down the fallback path, which silently recomputed an already-audited
            # score and relabelled its provenance.
            if r.get("priority_score") is not None:
                ps = float(r["priority_score"])
                caseload = float(r.get("caseload_score") if r.get("caseload_score") is not None else (ps * pop))
                tier_class = Tier(r["tier"]) if isinstance(r["tier"], str) else r["tier"]
                prz_overlap = float(r.get("prz_overlap_pct") if r.get("prz_overlap_pct") is not None else 0.0)
                dominant_hazard = r.get("dominant_hazard") or "landslide"
                model_ver = r.get("model_version") or "baseline-v1"
                scoring_ver = r.get("scoring_version") or self.scoring_config.scoring_version
                dataset_ver = r.get("dataset_version") or "v1.0"
            else:
                # On-the-fly fallback evaluation
                v_demo = float(r.get("v_demographic") if r.get("v_demographic") is not None else 0.5)
                v_struct = float(r.get("v_structural") if r.get("v_structural") is not None else 0.5)
                v_access = float(r.get("v_access") if r.get("v_access") is not None else 0.5)
                v_econ = float(r.get("v_economic") if r.get("v_economic") is not None else 0.5)
                v_index = float(
                    r.get("v_index")
                    if r.get("v_index") is not None
                    else compute_vulnerability_index(v_demo, v_struct, v_access, v_econ, self.vulnerability_config)
                )
                active_def = bool(r.get("active_deformation", False))
                fatal_3_monsoons = bool(r.get("fatal_event_last_3_monsoons", False))
                m_cost = r.get("mitigation_cost")
                r_cost = r.get("relocation_cost")
                adv_trend = r.get("adverse_trend")
                raw_hi = r.get("hazard_intensity")
                hazard_intensity = float(raw_hi if raw_hi is not None else 0.45)
                raw_prz = r.get("prz_overlap_pct")
                prz_overlap = float(raw_prz if raw_prz is not None else 25.0)
                decayed_loss = float(r.get("decayed_loss") if r.get("decayed_loss") is not None else 0.0)

                eval_result = self.engine.evaluate_habitation(
                    hazard_intensity=hazard_intensity,
                    pop_fraction_in_prz=prz_overlap / 100.0,
                    vulnerability_index=v_index,
                    decayed_loss=decayed_loss,
                    population=pop,
                    active_deformation=active_def,
                    fatal_event_last_3_monsoons=fatal_3_monsoons,
                    mitigation_cost=float(m_cost) if m_cost is not None else None,
                    relocation_cost=float(r_cost) if r_cost is not None else None,
                    adverse_trend=bool(adv_trend) if adv_trend is not None else None,
                    regime=r.get("hazard_regime"),
                )

                ps = eval_result["priority_score"]
                caseload = eval_result["caseload_score"]
                tier_class = eval_result["tier"]
                # Only fall back to the pilot default when the row genuinely names no hazard.
                dominant_hazard = r.get("dominant_hazard") or "landslide"
                model_ver = r.get("model_version") or "baseline-v1"
                scoring_ver = self.scoring_config.scoring_version
                dataset_ver = "v1.0"

            items.append(
                HabitationListItem(
                    id=r["id"],
                    lgd_code=r["lgd_code"],
                    name=r["name"],
                    type=r["type"],
                    admin_id=r["admin_id"],
                    admin_name=r["admin_name"],
                    population=pop,
                    households=int(r.get("households") if r.get("households") is not None else 0),
                    priority_score=ps,
                    caseload_score=caseload,
                    tier=tier_class,
                    prz_overlap_pct=prz_overlap,
                    dominant_hazard=dominant_hazard,
                    hazard_regime=normalize_regime(r.get("hazard_regime")),
                    relocation_pathway=self._pathway(r),
                    centroid=[r["lon"], r["lat"]],
                    model_version=model_ver,
                    scoring_version=scoring_ver,
                    dataset_version=dataset_ver,
                )
            )

        return PaginatedResponse(
            items=items,
            total=total,
            limit=clamped_limit,
            offset=offset,
            has_more=(offset + clamped_limit) < total,
        )

    def get_habitation_risk_dossier(self, habitation_id: int) -> HabitationRiskDossier:
        """Retrieves complete risk dossier for a single habitation."""
        r = self.repo.get_habitation_by_id(habitation_id)
        if not r:
            raise HabitationNotFoundError(habitation_id)

        pop = int(r.get("population") if r.get("population") is not None else 0)
        v_demo = float(r.get("v_demographic") if r.get("v_demographic") is not None else 0.5)
        v_struct = float(r.get("v_structural") if r.get("v_structural") is not None else 0.5)
        v_access = float(r.get("v_access") if r.get("v_access") is not None else 0.5)
        v_econ = float(r.get("v_economic") if r.get("v_economic") is not None else 0.5)
        v_index = float(
            r.get("v_index")
            if r.get("v_index") is not None
            else compute_vulnerability_index(v_demo, v_struct, v_access, v_econ, self.vulnerability_config)
        )

        # Disaster history
        nearby_events = self.repo.get_nearby_disaster_events(r["lon"], r["lat"], radius_km=15.0)
        decayed_loss = compute_time_decayed_loss(
            nearby_events,
            reference_date=date.today(),
            half_life_years=self.scoring_config.loss_half_life_years,
        )

        raw_hi = r.get("hazard_intensity")
        hazard_intensity = float(raw_hi if raw_hi is not None else 0.45)
        raw_prz = r.get("prz_overlap_pct")
        prz_overlap = float(raw_prz if raw_prz is not None else 25.0)

        active_def = bool(r.get("active_deformation", False))
        if r.get("fatal_event_last_3_monsoons") is not None:
            fatal_3_monsoons = bool(r["fatal_event_last_3_monsoons"])
        else:
            # Canonical derivation from nearby disaster events
            fatal_3_monsoons = check_fatal_event_last_3_monsoons(nearby_events, reference_date=date.today())

        m_cost = r.get("mitigation_cost")
        r_cost = r.get("relocation_cost")
        if r.get("adverse_trend") is not None:
            adv_trend = bool(r["adverse_trend"])
        else:
            adv_trend = check_loss_frequency_rising(nearby_events, reference_date=date.today())

        eval_result = self.engine.evaluate_habitation(
            hazard_intensity=hazard_intensity,
            pop_fraction_in_prz=prz_overlap / 100.0,
            vulnerability_index=v_index,
            decayed_loss=decayed_loss,
            population=pop,
            active_deformation=active_def,
            fatal_event_last_3_monsoons=fatal_3_monsoons,
            mitigation_cost=float(m_cost) if m_cost is not None else None,
            relocation_cost=float(r_cost) if r_cost is not None else None,
            adverse_trend=adv_trend,
            regime=r.get("hazard_regime"),
        )

        raw_ps = r.get("priority_score")
        ps = float(raw_ps if raw_ps is not None else eval_result["priority_score"])
        raw_caseload = r.get("caseload_score")
        caseload = float(raw_caseload if raw_caseload is not None else eval_result["caseload_score"])
        tier_class = Tier(r["tier"]) if r.get("tier") else eval_result["tier"]
        triage_rationale = r.get("triage_rationale") or eval_result["triage_rationale"]
        top_factors_raw = r.get("contributing_factors") or eval_result["contributing_factors"]
        if isinstance(top_factors_raw, str):
            import json
            top_factors_raw = json.loads(top_factors_raw)
        top_factors = normalize_feature_contributions(
            top_factors_raw or [],
            default_method="heuristic",
            max_factors=5,
        )

        loss_dtos = [
            LossEventDTO(
                id=ev["id"],
                ts=ev["ts"],
                hazard_type=ev["hazard_type"],
                fatalities=ev.get("fatalities") if ev.get("fatalities") is not None else 0,
                injured=ev.get("injured") if ev.get("injured") is not None else 0,
                houses_damaged=ev.get("houses_damaged") if ev.get("houses_damaged") is not None else 0,
                severity=float(ev.get("severity") if ev.get("severity") is not None else 1.0),
                source=ev["source"],
                source_ref=ev.get("source_ref"),
            )
            for ev in nearby_events
        ]

        v_meta = r.get("vulnerability_metadata") or {}
        if isinstance(v_meta, str):
            import json
            v_meta = json.loads(v_meta)

        return HabitationRiskDossier(
            id=r["id"],
            lgd_code=r["lgd_code"],
            name=r["name"],
            type=r["type"],
            admin_id=r["admin_id"],
            admin_name=r["admin_name"],
            population=pop,
            households=int(r.get("households") if r.get("households") is not None else 0),
            centroid=[r["lon"], r["lat"]],
            priority_score=ps,
            caseload_score=caseload,
            tier=tier_class,
            triage_rationale=triage_rationale,
            prz_overlap_pct=prz_overlap,
            hazard_intensity=hazard_intensity,
            decayed_loss_score=decayed_loss,
            hazard_regime=normalize_regime(r.get("hazard_regime")),
            relocation_pathway=self._pathway(r),
            model_version=r.get("model_version") or "baseline-v1",
            scoring_version=r.get("scoring_version") or self.scoring_config.scoring_version,
            dataset_version=r.get("dataset_version") or "v1.0",
            data_quality=r.get("data_quality") or "synthetic",
            confidence=float(r.get("confidence") if r.get("confidence") is not None else 1.0),
            calculated_at=r.get("calculated_at") or datetime.now(timezone.utc),
            vulnerability=VulnerabilityBreakdownDTO(
                v_demographic=v_demo,
                v_structural=v_struct,
                v_access=v_access,
                v_economic=v_econ,
                v_index=v_index,
                is_district_flat=bool(r.get("is_district_flat") or False),
                metadata=v_meta,
            ),
            past_disasters=loss_dtos,
            top_contributing_factors=top_factors,
        )
