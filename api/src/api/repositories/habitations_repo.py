"""Database repository for Habitations, Prioritized Queues, and Risk Dossiers."""

from __future__ import annotations

import json
from typing import Optional, Any, Sequence
from sqlalchemy import text
from sqlalchemy.orm import Session
from core.enums import Hazard, SortMode


class HabitationsRepository:
    """Repository handling database access for Habitations, Vulnerability, and Risk Profiles."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def query_habitations(
        self,
        admin_id: Optional[int] = None,
        tier: Optional[str] = None,
        sort: SortMode = SortMode.URGENCY,
        limit: Optional[int] = 50,
        offset: int = 0,
        regime: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Queries habitations in a single query using window count and indexed ordering."""
        conditions = ["1=1"]
        params: dict[str, Any] = {}

        if limit is not None:
            params["limit"] = limit
            limit_clause = "LIMIT :limit"
        else:
            limit_clause = ""

        if offset:
            params["offset"] = offset
            offset_clause = "OFFSET :offset"
        elif limit is not None:
            params["offset"] = 0
            offset_clause = "OFFSET :offset"
        else:
            offset_clause = ""

        if admin_id is not None:
            conditions.append("(h.admin_id = :admin_id OR a.lgd_code = :admin_id)")
            params["admin_id"] = admin_id

        if tier is not None:
            conditions.append("hr.tier = :tier")
            params["tier"] = tier

        if regime is not None:
            conditions.append("hr.hazard_regime = :regime")
            params["regime"] = regime

        where_clause = " AND ".join(conditions)

        # Allowlist-safe sort ordering
        if sort == SortMode.CASELOAD:
            order_clause = "COALESCE(hr.caseload_score, 0.0) DESC, h.id ASC"
        else:
            order_clause = "COALESCE(hr.priority_score, 0.0) DESC, h.id ASC"

        # Single round-trip query with count(*) OVER()
        query = text(f"""
            SELECT 
                h.id,
                h.lgd_code,
                h.name,
                h.type,
                h.admin_id,
                a.name as admin_name,
                h.population,
                h.households,
                ST_X(h.geom_point::geometry) as lon,
                ST_Y(h.geom_point::geometry) as lat,
                v.v_demographic,
                v.v_structural,
                v.v_access,
                v.v_economic,
                v.v_index,
                v.is_district_flat,
                v.metadata as vulnerability_metadata,
                hr.priority_score,
                hr.caseload_score,
                hr.tier,
                hr.hazard_regime,
                hr.relocation_pathway,
                hr.triage_rationale,
                hr.contributing_factors,
                hr.hazard_intensity,
                hr.prz_overlap_pct,
                hr.decayed_loss,
                hr.model_version,
                hr.scoring_version,
                hr.dataset_version,
                hr.data_quality,
                hr.confidence,
                hr.active_deformation,
                hr.fatal_event_last_3_monsoons,
                hr.mitigation_cost,
                hr.relocation_cost,
                hr.adverse_trend,
                hr.calculated_at,
                count(*) OVER() as full_count
            FROM habitation h
            LEFT JOIN admin_boundary a ON h.admin_id = a.id
            LEFT JOIN vulnerability v ON h.id = v.habitation_id
            LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
            WHERE {where_clause}
            ORDER BY {order_clause}
            {limit_clause} {offset_clause};
        """)

        results = self.db.execute(query, params).mappings().all()
        if not results:
            # Check if total is 0 or offset out of range
            count_query = text(f"""
                SELECT count(*) 
                FROM habitation h
                LEFT JOIN admin_boundary a ON h.admin_id = a.id
                LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
                WHERE {where_clause};
            """)
            total = self.db.execute(count_query, params).scalar() or 0
            return [], total

        total = int(results[0]["full_count"])
        return [dict(r) for r in results], total

    def get_habitation_by_id(self, habitation_id: int) -> Optional[dict[str, Any]]:
        """Queries a single habitation with its complete vulnerability and risk dossier."""
        query = text("""
            SELECT 
                h.id,
                h.lgd_code,
                h.name,
                h.type,
                h.admin_id,
                a.name as admin_name,
                h.population,
                h.households,
                ST_X(h.geom_point::geometry) as lon,
                ST_Y(h.geom_point::geometry) as lat,
                v.v_demographic,
                v.v_structural,
                v.v_access,
                v.v_economic,
                v.v_index,
                v.is_district_flat,
                v.metadata as vulnerability_metadata,
                hr.priority_score,
                hr.caseload_score,
                hr.tier,
                hr.hazard_regime,
                hr.relocation_pathway,
                hr.triage_rationale,
                hr.contributing_factors,
                hr.hazard_intensity,
                hr.prz_overlap_pct,
                hr.decayed_loss,
                hr.model_version,
                hr.scoring_version,
                hr.dataset_version,
                hr.data_quality,
                hr.confidence,
                hr.active_deformation,
                hr.fatal_event_last_3_monsoons,
                hr.mitigation_cost,
                hr.relocation_cost,
                hr.adverse_trend,
                hr.calculated_at
            FROM habitation h
            LEFT JOIN admin_boundary a ON h.admin_id = a.id
            LEFT JOIN vulnerability v ON h.id = v.habitation_id
            LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
            WHERE h.id = :id;
        """)

        result = self.db.execute(query, {"id": habitation_id}).mappings().first()
        if not result:
            return None
        return dict(result)

    def upsert_habitation_risk(self, risk_record: dict[str, Any]) -> None:
        """Upserts a computed HabitationRisk record atomically."""
        query = text("""
            INSERT INTO habitation_risk (
                habitation_id,
                admin_id,
                population,
                households,
                hazard_intensity,
                prz_overlap_pct,
                decayed_loss,
                v_index,
                priority_score,
                caseload_score,
                tier,
                triage_rationale,
                contributing_factors,
                dominant_hazard,
                model_version,
                scoring_version,
                dataset_version,
                data_quality,
                confidence,
                active_deformation,
                fatal_event_last_3_monsoons,
                mitigation_cost,
                relocation_cost,
                adverse_trend,
                calculated_at,
                pipeline_run_id
            ) VALUES (
                :habitation_id,
                :admin_id,
                :population,
                :households,
                :hazard_intensity,
                :prz_overlap_pct,
                :decayed_loss,
                :v_index,
                :priority_score,
                :caseload_score,
                :tier,
                :triage_rationale,
                :contributing_factors,
                :dominant_hazard,
                :model_version,
                :scoring_version,
                :dataset_version,
                :data_quality,
                :confidence,
                :active_deformation,
                :fatal_event_last_3_monsoons,
                :mitigation_cost,
                :relocation_cost,
                :adverse_trend,
                :calculated_at,
                :pipeline_run_id
            )
            ON CONFLICT (habitation_id) DO UPDATE SET
                admin_id = EXCLUDED.admin_id,
                population = EXCLUDED.population,
                households = EXCLUDED.households,
                hazard_intensity = EXCLUDED.hazard_intensity,
                prz_overlap_pct = EXCLUDED.prz_overlap_pct,
                decayed_loss = EXCLUDED.decayed_loss,
                v_index = EXCLUDED.v_index,
                priority_score = EXCLUDED.priority_score,
                caseload_score = EXCLUDED.caseload_score,
                tier = EXCLUDED.tier,
                triage_rationale = EXCLUDED.triage_rationale,
                contributing_factors = EXCLUDED.contributing_factors,
                dominant_hazard = EXCLUDED.dominant_hazard,
                model_version = EXCLUDED.model_version,
                scoring_version = EXCLUDED.scoring_version,
                dataset_version = EXCLUDED.dataset_version,
                data_quality = EXCLUDED.data_quality,
                confidence = EXCLUDED.confidence,
                active_deformation = EXCLUDED.active_deformation,
                fatal_event_last_3_monsoons = EXCLUDED.fatal_event_last_3_monsoons,
                mitigation_cost = EXCLUDED.mitigation_cost,
                relocation_cost = EXCLUDED.relocation_cost,
                adverse_trend = EXCLUDED.adverse_trend,
                calculated_at = EXCLUDED.calculated_at,
                pipeline_run_id = EXCLUDED.pipeline_run_id;
        """)
        factors = risk_record.get("contributing_factors", [])
        m_cost = risk_record.get("mitigation_cost")
        r_cost = risk_record.get("relocation_cost")
        params = {
            **risk_record,
            "mitigation_cost": float(m_cost) if m_cost is not None else None,
            "relocation_cost": float(r_cost) if r_cost is not None else None,
            "adverse_trend": bool(risk_record.get("adverse_trend", False)),
            "active_deformation": bool(risk_record.get("active_deformation", False)),
            "fatal_event_last_3_monsoons": bool(risk_record.get("fatal_event_last_3_monsoons", False)),
            "contributing_factors": json.dumps(factors) if isinstance(factors, list) else factors,
        }
        self.db.execute(query, params)

    def get_all_disaster_events(self) -> list[dict[str, Any]]:
        """Retrieves all disaster events with coordinates for fast in-memory spatial correlation."""
        query = text("""
            SELECT 
                id,
                ts,
                hazard_type,
                fatalities,
                injured,
                houses_damaged,
                severity,
                source,
                source_ref,
                ST_X(geom::geometry) as lon,
                ST_Y(geom::geometry) as lat
            FROM disaster_event
            ORDER BY ts DESC;
        """)
        results = self.db.execute(query).mappings().all()
        return [dict(r) for r in results]

    def get_nearby_disaster_events(self, lon: float, lat: float, radius_km: float = 15.0) -> list[dict[str, Any]]:
        """Queries historical disaster events within radius of a geographic coordinate."""
        query = text("""
            SELECT 
                id,
                ts,
                hazard_type,
                fatalities,
                injured,
                houses_damaged,
                severity,
                source,
                source_ref,
                ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) / 1000.0 as distance_km
            FROM disaster_event
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius_m
            )
            ORDER BY ts DESC;
        """)

        results = self.db.execute(
            query,
            {"lon": lon, "lat": lat, "radius_m": radius_km * 1000.0},
        ).mappings().all()
        return [dict(r) for r in results]

    def get_hazard_scores_for_habitations(
        self, habitation_ids: Sequence[int]
    ) -> dict[int, dict[Hazard, float]]:
        """Retrieves static hazard scores for habitations aggregated from underlying H3 grid cells.
        
        Follows PRD §10.4 aggregation semantics: mean susceptibility across intersecting cells.
        Point habitations map to their containing H3 cell.
        """
        if not habitation_ids:
            return {}
        query = text("""
            SELECT 
                h.id AS habitation_id,
                hs.hazard_type,
                AVG(hs.susceptibility) AS susceptibility
            FROM habitation h
            JOIN grid_cell gc ON (gc.habitation_id = h.id OR ST_Contains(gc.geom, h.geom_point))
            JOIN hazard_static hs ON gc.h3 = hs.h3 AND hs.quality_flag <> 'channel_excluded'
            WHERE h.id = ANY(:hab_ids)
            GROUP BY h.id, hs.hazard_type;
        """)
        rows = self.db.execute(query, {"hab_ids": list(habitation_ids)}).mappings().all()
        result: dict[int, dict[Hazard, float]] = {}
        for r in rows:
            h_id = int(r["habitation_id"])
            try:
                h_enum = Hazard(r["hazard_type"])
            except ValueError:
                continue
            if h_id not in result:
                result[h_id] = {}
            result[h_id][h_enum] = round(float(r["susceptibility"]), 4)
        return result

