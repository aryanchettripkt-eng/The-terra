"""PostGIS Repository for Habitation Relocation Allocation (Day 6).

Section refs: docs/PRD1.md §6.9, §9.5, §9.6, FR-8.1–FR-8.3
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from sqlalchemy import text
from sqlalchemy.orm import Session
from api.repositories.site_regime_sql import SITE_REGIME_JOIN
from core.domain.capacity import CandidateSitePolicy


class AllocationRepository:
    """PostGIS data access for allocation solver inputs and result persistence."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_habitations_for_allocation(
        self,
        admin_id: Optional[int] = None,
        target_tiers: Optional[Sequence[str]] = None,
    ) -> list[dict[str, Any]]:
        """Queries habitations eligible for relocation allocation."""
        where_clauses = ["h.households > 0"]
        params: dict[str, Any] = {}

        if admin_id is not None:
            where_clauses.append("(h.admin_id = :admin_id OR a.lgd_code = :admin_id)")
            params["admin_id"] = int(admin_id)

        if target_tiers:
            where_clauses.append("hr.tier = ANY(:target_tiers)")
            params["target_tiers"] = list(target_tiers)

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                h.id,
                h.name,
                h.households,
                h.population,
                hr.tier,
                hr.hazard_regime,
                hr.relocation_pathway,
                COALESCE(hr.priority_score, 0.5) as priority_score,
                ST_X(h.geom_point::geometry) as lon,
                ST_Y(h.geom_point::geometry) as lat
            FROM habitation h
            LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
            LEFT JOIN admin_boundary a ON h.admin_id = a.id
            WHERE {where_sql}
            ORDER BY hr.priority_score DESC, h.households DESC, h.id ASC;
        """

        rows = self.db.execute(text(sql), params).mappings().fetchall()
        return [dict(r) for r in rows]

    def get_candidate_sites_and_distances(
        self,
        habitation_ids: Sequence[int],
        max_radius_m: float = 15000.0,
        min_suitability: Optional[int] = None,
        policy: Optional[CandidateSitePolicy] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Queries candidate relocation sites within search radius of target habitations enforcing H7 eligibility."""
        if not habitation_ids:
            return [], []

        p = policy or CandidateSitePolicy()

        # Capacity the solver may rely on. `cc_final` is NULL whenever a lifeline is unmeasured;
        # only a screening policy may fall back to the land-only figure, and the basis is
        # reported so the result is never mistaken for a fully verified capacity.
        if p.allow_land_only_capacity:
            capacity_sql = "COALESCE(cs.cc_final, cs.cc_land)"
        else:
            capacity_sql = "cs.cc_final"

        # Tenure gate mirrors CapacityEngine.evaluate_site_eligibility: unverified tenure is
        # admitted only when the policy says so, never by default.
        tenures = ["government_revenue", "private"]
        if p.allow_unverified_tenure:
            tenures.append("tenure_unverified")

        # Hazard constraint: order-grade requires verified safe MHI (< max_static_mhi).
        # Screening policy with allow_unmeasured_hazard admits sites where MHI is unmeasured,
        # never assuming safe (MHI remains NULL in database) but stamping screening caveats.
        if p.allow_unmeasured_hazard:
            hazard_sql = "(cs.mhi_max IS NULL OR cs.mhi_max < :max_static_mhi)"
        else:
            hazard_sql = "cs.mhi_max < :max_static_mhi"

        where_clauses = [
            "h.id = ANY(:hab_ids)",
            "ST_DWithin(h.geom_point::geography, cs.centroid::geography, :radius_m)",
            f"{capacity_sql} > 0",
            # H7 Hard Eligibility Constraints on canonical table columns parameterized from CandidateSitePolicy
            hazard_sql,
            "cs.slope_mean < :max_slope_deg",
            "cs.area_ha >= :min_area_ha",
            "cs.tenure = ANY(:tenures)",
        ]
        params: dict[str, Any] = {
            "hab_ids": list(habitation_ids),
            "radius_m": float(max_radius_m),
            "max_static_mhi": p.max_static_mhi,
            "max_slope_deg": p.max_slope_deg,
            "min_area_ha": p.min_contiguous_area_ha,
            "tenures": tenures,
        }

        if min_suitability is not None:
            where_clauses.append("cs.suitability >= :min_suitability")
            params["min_suitability"] = int(min_suitability)

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                h.id as habitation_id,
                cs.id as site_id,
                COALESCE(cs.metadata->>'name', 'Site #' || cs.id) as site_name,
                {capacity_sql} as capacity,
                CASE WHEN cs.cc_final IS NULL THEN 'land_only_provisional' ELSE 'final' END as capacity_basis,
                CASE WHEN cs.mhi_max IS NULL THEN 'unmeasured' ELSE 'measured' END as hazard_basis,
                cs.suitability,
                cs.area_ha,
                cs.tenure,
                cs.slope_mean,
                cs.mhi_max,
                cs.metadata as metadata_info,
                reg.hazard_regime,
                ST_X(cs.centroid::geometry) as site_lon,
                ST_Y(cs.centroid::geometry) as site_lat,
                ST_Distance(h.geom_point::geography, cs.centroid::geography) / 1000.0 as distance_km
            FROM habitation h
            JOIN candidate_site cs ON true
            {SITE_REGIME_JOIN}
            WHERE {where_sql}
            ORDER BY cs.id ASC;
        """

        rows = self.db.execute(text(sql), params).mappings().fetchall()
        if not rows:
            return [], []

        # Deduplicate sites
        sites_seen: dict[int, dict[str, Any]] = {}
        distances: list[dict[str, Any]] = []

        for r in rows:
            s_id = r["site_id"]
            if s_id not in sites_seen:
                sites_seen[s_id] = {
                    "id": s_id,
                    "name": r["site_name"],
                    "capacity": r["capacity"],
                    "capacity_basis": r["capacity_basis"],
                    "suitability": r["suitability"],
                    "lat": r["site_lat"],
                    "lon": r["site_lon"],
                    "area_ha": float(r["area_ha"]) if r.get("area_ha") is not None else None,
                    "tenure": r.get("tenure"),
                    "slope_mean": float(r["slope_mean"]) if r.get("slope_mean") is not None else None,
                    "mhi_max": float(r["mhi_max"]) if r.get("mhi_max") is not None else None,
                    "metadata": r.get("metadata_info"),
                    "hazard_regime": r.get("hazard_regime"),
                }
            distances.append({
                "habitation_id": r["habitation_id"],
                "site_id": s_id,
                "distance_km": float(r["distance_km"]),
            })

        return list(sites_seen.values()), distances

    def save_allocation_run(
        self,
        run_id: uuid.UUID,
        admin_id: Optional[int],
        solver_latency_ms: float,
        total_relocated: int,
        assignments: Sequence[dict[str, Any]],
    ) -> None:
        """Persists the allocation run and generated relocation plan records."""
        now = datetime.now(timezone.utc)

        # 1. Insert AllocationRun
        self.db.execute(
            text("""
                INSERT INTO allocation_run (
                    id, admin_id, status, solver_latency_ms, total_households_relocated, created_at
                ) VALUES (
                    :id, :admin_id, 'COMPLETED', :latency, :relocated, :created_at
                );
            """),
            {
                "id": run_id,
                "admin_id": admin_id,
                "latency": solver_latency_ms,
                "relocated": total_relocated,
                "created_at": now,
            },
        )

        # 2. Insert RelocationPlan assignments
        if assignments:
            insert_stmt = text("""
                INSERT INTO relocation_plan (
                    allocation_run_id, habitation_id, site_id, households,
                    tier, priority_score, rationale, has_group_split, status, created_at
                ) VALUES (
                    :run_id, :hab_id, :site_id, :hh,
                    :tier, :ps, CAST(:rationale AS jsonb), :split, 'PROPOSED', :created_at
                );
            """)

            for a in assignments:
                self.db.execute(
                    insert_stmt,
                    {
                        "run_id": run_id,
                        "hab_id": a["habitation_id"],
                        "site_id": a["site_id"],
                        "hh": a["households"],
                        "tier": a["tier"],
                        "ps": a["priority_score"],
                        "rationale": json.dumps({"distance_km": a.get("site_distance_km", 0.0), "split_details": a.get("split_details")}),
                        "split": a.get("has_group_split", False),
                        "created_at": now,
                    },
                )

        self.db.commit()
