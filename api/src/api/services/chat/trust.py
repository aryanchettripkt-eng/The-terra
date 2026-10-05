"""Data trust, quality profiling, and schema capability probing for SETU-DRR chat orchestrator.

Computes DataTrustContext deterministically from live database metrics or verified
ground-truth fallbacks (§2), ensuring synthetic demo data is never presented as measured
and monitoring settlements are never described as safe or missing data.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.services.chat.entities import canonical_district_name
from api.services.chat_triage import URGENT_TIERS, fetch_tier_rows, tier_key
from core.config import settings

logger = logging.getLogger("setu_api.chat.trust")


class SchemaCapabilities(BaseModel):
    """Database schema capability flags probed at runtime (§2.7, §6)."""
    has_habitation_regime_cols: bool = True
    has_pathway_col: bool = True
    has_flood_channel_col: bool = True
    has_flood_distance_cols: bool = True


class DistrictTrustMetrics(BaseModel):
    """Granular data trust and quality profile for an administrative district (§4.2).

    ``status`` says whether the numbers can be used at all: ``ok``, ``unknown_district`` (not in
    ``admin_boundary``) or ``unavailable`` (the database could not be read). ``data_source`` is ``database`` for
    live figures and ``static_snapshot`` for the dated test fixture used only when no database is attached.
    """
    district: str
    status: str = "ok"  # "ok" | "unknown_district" | "unavailable"
    data_source: str = "database"  # "database" | "static_snapshot"
    habitations_total: int = 0
    tier_counts: Dict[str, int] = Field(default_factory=dict)  # includes "monitoring" and, when present, "unscored"
    tier_quality: Dict[str, Dict[str, int]] = Field(default_factory=dict)  # tier -> {data_quality: habitations}
    data_quality_counts: Dict[str, int] = Field(default_factory=dict)
    urgent_synthetic: bool = False
    hazard_layers: List[Dict[str, Any]] = Field(default_factory=list)
    flood_model_status: str = "computed"  # "computed" | "not_computed"
    regime_available: bool = False
    sites_total: int = 0
    sites_fully_assessed: int = 0
    sites_partial: int = 0
    dynamic_source: str = "unknown"  # hazard_dynamic.source value(s), "none" when empty, "unknown" if unreadable
    snapshot_age_hours: Optional[float] = None

    @property
    def usable(self) -> bool:
        return self.status == "ok"


class DataTrustContext(BaseModel):
    """Holistic data trust context feeding prompt context and deterministic Limits block."""
    districts: Dict[str, DistrictTrustMetrics] = Field(default_factory=dict)
    serving_version_ok: Optional[bool] = None  # None = could not be determined
    serving_version: Optional[str] = None
    schema_capabilities: SchemaCapabilities = Field(default_factory=SchemaCapabilities)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Static snapshot verified on 2026-10-05 (§2). Used ONLY when no database session is attached (unit tests, offline
# tooling). It is never a fallback for a database that failed: stale figures must not look like live ones.
VERIFIED_DB_GROUND_TRUTH: Dict[str, Dict[str, Any]] = {
    "Barpeta": {
        "habitations_total": 253,
        "tier_counts": {"short_term": 16, "medium_term": 98, "monitoring": 139},
        "data_quality_counts": {"derived": 253},
        "urgent_synthetic": False,
        "hazard_layers": [{"hazard_type": "riverine_flood", "model_version": "v0.2", "cells": 2948}],
        "flood_model_status": "computed",
        "regime_available": True,
        "sites_total": 514,
        "sites_fully_assessed": 0,
        "sites_partial": 514,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Wayanad": {
        "habitations_total": 279,
        "tier_counts": {"immediate": 2, "short_term": 2, "medium_term": 8, "monitoring": 267},
        "data_quality_counts": {"derived": 275, "synthetic": 4},
        "urgent_synthetic": True,
        "hazard_layers": [
            {"hazard_type": "riverine_flood", "model_version": "v0.1", "cells": 2516},
            {"hazard_type": "landslide", "model_version": "terrain-copernicus-v1.0", "cells": 2876},
        ],
        "flood_model_status": "computed",
        "regime_available": False,
        "sites_total": 6,
        "sites_fully_assessed": 5,
        "sites_partial": 1,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Kodagu": {
        "habitations_total": 3,
        "tier_counts": {"immediate": 1, "monitoring": 2},
        "data_quality_counts": {"synthetic": 1, "derived": 2},
        "urgent_synthetic": True,
        "hazard_layers": [
            {"hazard_type": "landslide", "model_version": "baseline-v1", "cells": 4126},
        ],
        "flood_model_status": "not_computed",
        "regime_available": False,
        "sites_total": 2,
        "sites_fully_assessed": 2,
        "sites_partial": 0,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Dholpur": {
        "habitations_total": 194,
        "tier_counts": {"medium_term": 117, "monitoring": 77},
        "data_quality_counts": {"derived": 194},
        "urgent_synthetic": False,
        "hazard_layers": [{"hazard_type": "riverine_flood", "model_version": "v0.1", "cells": 4105}],
        "flood_model_status": "computed",
        "regime_available": False,
        "sites_total": 290,
        "sites_fully_assessed": 0,
        "sites_partial": 290,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Morena": {
        "habitations_total": 429,
        "tier_counts": {"medium_term": 224, "monitoring": 205},
        "data_quality_counts": {"derived": 429},
        "urgent_synthetic": False,
        "hazard_layers": [{"hazard_type": "riverine_flood", "model_version": "v0.1", "cells": 6804}],
        "flood_model_status": "computed",
        "regime_available": False,
        "sites_total": 331,
        "sites_fully_assessed": 0,
        "sites_partial": 331,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Rudraprayag": {
        "habitations_total": 157,
        "tier_counts": {"monitoring": 157},
        "data_quality_counts": {"derived": 157},
        "urgent_synthetic": False,
        "hazard_layers": [{"hazard_type": "riverine_flood", "model_version": "v0.1", "cells": 2343}],
        "flood_model_status": "computed",
        "regime_available": False,
        "sites_total": 8,
        "sites_fully_assessed": 0,
        "sites_partial": 8,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Srinagar": {
        "habitations_total": 83,
        "tier_counts": {"medium_term": 29, "monitoring": 54},
        "data_quality_counts": {"derived": 83},
        "urgent_synthetic": False,
        "hazard_layers": [{"hazard_type": "riverine_flood", "model_version": "v0.1", "cells": 1285}],
        "flood_model_status": "computed",
        "regime_available": False,
        "sites_total": 560,
        "sites_fully_assessed": 0,
        "sites_partial": 560,
        "dynamic_source": "SYNTHETIC_DEMO",
    },
    "Leh": {
        "habitations_total": 0,
        "tier_counts": {},
        "data_quality_counts": {},
        "urgent_synthetic": False,
        "hazard_layers": [],
        "flood_model_status": "not_computed",
        "regime_available": False,
        "sites_total": 0,
        "sites_fully_assessed": 0,
        "sites_partial": 0,
        "dynamic_source": "none",
    },
}

# Caches, invalidated by TTL and by the serving version (§4.2)
_TRUST_CACHE: Dict[Tuple[str, Optional[str]], Tuple[float, DistrictTrustMetrics]] = {}
_FRESHNESS_CACHE: Optional[Tuple[float, "_Freshness"]] = None
_CAPS_CACHE: Optional[Tuple[float, SchemaCapabilities]] = None


class _Freshness(BaseModel):
    serving_version: Optional[str] = None
    serving_version_ok: Optional[bool] = None
    dynamic_source: str = "unknown"
    snapshot_age_hours: Optional[float] = None


def clear_trust_caches() -> None:
    """Drops all cached trust data (tests, and after a pipeline run)."""
    global _FRESHNESS_CACHE, _CAPS_CACHE
    _TRUST_CACHE.clear()
    _FRESHNESS_CACHE = None
    _CAPS_CACHE = None


_ERROR: Any = object()  # distinguishes "query failed" from "no rows" (None)


def _safe_scalar(db: Session, sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """First column of the first row; None when there are no rows; ``_ERROR`` if the query failed."""
    try:
        with db.begin_nested():
            row = db.execute(text(sql), params or {}).first()
        return row[0] if row else None
    except Exception as e:  # noqa: BLE001 - trust probing must never break the chat
        logger.warning("Trust probe failed: %s", e)
        return _ERROR


def probe_schema_capabilities(db: Session) -> SchemaCapabilities:
    """Probes runtime database schema to detect applied migration columns (§2.7, §6)."""
    global _CAPS_CACHE
    now = time.time()
    if _CAPS_CACHE and (now - _CAPS_CACHE[0]) < settings.CHAT_TRUST_CACHE_TTL_SECONDS:
        return _CAPS_CACHE[1]

    caps = SchemaCapabilities()
    try:
        with db.begin_nested():
            sql = text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'habitation_risk' AND column_name IN ('hazard_regime', 'relocation_pathway');
            """)
            cols = {row[0] for row in db.execute(sql).fetchall()}
        caps.has_habitation_regime_cols = "hazard_regime" in cols
        caps.has_pathway_col = "relocation_pathway" in cols
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not probe schema capabilities, assuming defaults: %s", e)

    _CAPS_CACHE = (now, caps)
    return caps


def _fetch_freshness(db: Session) -> _Freshness:
    """Serving version, dynamic-hazard source and snapshot age, read from the database (cached briefly)."""
    global _FRESHNESS_CACHE
    now = time.time()
    if _FRESHNESS_CACHE and (now - _FRESHNESS_CACHE[0]) < settings.CHAT_TRUST_CACHE_TTL_SECONDS:
        return _FRESHNESS_CACHE[1]

    fresh = _Freshness()
    try:
        with db.begin_nested():
            row = db.execute(text("""
                SELECT sv.pipeline_run_id::text, pr.status
                FROM serving_version sv JOIN pipeline_run pr ON pr.id = sv.pipeline_run_id
                ORDER BY sv.updated_at DESC LIMIT 1
            """)).first()
        if row:
            fresh.serving_version = str(row[0])
            fresh.serving_version_ok = str(row[1]).upper() == "READY"
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read serving_version: %s", e)

    sources = _safe_scalar(db, "SELECT string_agg(DISTINCT source, ',' ORDER BY source) FROM hazard_dynamic")
    fresh.dynamic_source = "unknown" if sources is _ERROR else (str(sources) if sources else "none")
    age = _safe_scalar(db, "SELECT EXTRACT(EPOCH FROM (now() - max(valid_at))) / 3600.0 FROM mhi_snapshot")
    fresh.snapshot_age_hours = round(float(age), 1) if age not in (None, _ERROR) else None

    _FRESHNESS_CACHE = (now, fresh)
    return fresh


def _snapshot_metrics(district: str) -> DistrictTrustMetrics:
    """Static snapshot for a known district; unknown names are reported as unknown, never as another district."""
    gt = VERIFIED_DB_GROUND_TRUTH.get(district)
    if gt is None:
        return DistrictTrustMetrics(district=district, status="unknown_district", data_source="static_snapshot")
    quality = {
        tier: {("synthetic" if tier in URGENT_TIERS and gt["urgent_synthetic"] else "derived"): n}
        for tier, n in gt["tier_counts"].items()
    }
    return DistrictTrustMetrics(district=district, data_source="static_snapshot", tier_quality=quality, **gt)


def fetch_district_trust_metrics(db: Optional[Session], district: str) -> DistrictTrustMetrics:
    """Trust and quality metrics for one district, read from the database.

    Without a database session the dated static snapshot is used (and labelled as such). If the database is
    attached but cannot be read, the result is ``status="unavailable"``: callers must not state counts.
    """
    name = canonical_district_name(district)
    if db is None:
        return _snapshot_metrics(name)

    fresh = _fetch_freshness(db)
    cache_key = (name, fresh.serving_version)
    now = time.time()
    cached = _TRUST_CACHE.get(cache_key)
    if cached and (now - cached[0]) < settings.CHAT_TRUST_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        with db.begin_nested():
            exists = db.execute(
                text("SELECT 1 FROM admin_boundary WHERE LOWER(name) = LOWER(:d) LIMIT 1"), {"d": name}
            ).first()
        if not exists:
            return DistrictTrustMetrics(district=name, status="unknown_district")

        habitations_total = 0
        tier_counts: Dict[str, int] = {}
        tier_quality: Dict[str, Dict[str, int]] = {}
        dq_counts: Dict[str, int] = {}
        urgent_synthetic = False
        with db.begin_nested():
            tier_rows = fetch_tier_rows(db, name)
        for r in tier_rows:
            key = tier_key(r["tier"], scored=bool(r["scored"]))  # NULL tier -> monitoring; no risk row -> unscored
            dq = str(r["data_quality"] or "unknown")
            n = int(r["habitations"])
            habitations_total += n
            tier_counts[key] = tier_counts.get(key, 0) + n
            tier_quality.setdefault(key, {})[dq] = tier_quality.get(key, {}).get(dq, 0) + n
            dq_counts[dq] = dq_counts.get(dq, 0) + n
            if key in URGENT_TIERS and dq == "synthetic":
                urgent_synthetic = True

        with db.begin_nested():
            site_rows = db.execute(text("""
                SELECT cs.assessment_status, COUNT(*) AS cnt
                FROM candidate_site cs JOIN admin_boundary ab ON ab.id = cs.admin_id
                WHERE LOWER(ab.name) = LOWER(:d) GROUP BY cs.assessment_status
            """), {"d": name}).fetchall()
        sites_total = sum(int(r[1]) for r in site_rows)
        sites_fully_assessed = sum(int(r[1]) for r in site_rows if r[0] == "fully_assessed")

        with db.begin_nested():
            hazard_rows = db.execute(text("""
                SELECT hs.hazard_type, hs.model_version, COUNT(*) AS cells,
                       bool_or(f.hazard_regime IS NOT NULL) AS has_regime
                FROM hazard_static hs
                JOIN grid_cell g ON g.h3 = hs.h3
                JOIN admin_boundary ab ON ab.id = g.admin_id
                LEFT JOIN hazard_static_flood f ON f.h3 = hs.h3 AND hs.hazard_type = 'riverine_flood'
                WHERE LOWER(ab.name) = LOWER(:d)
                GROUP BY hs.hazard_type, hs.model_version
            """), {"d": name}).fetchall()
        layers = [{"hazard_type": r[0], "model_version": r[1], "cells": int(r[2])} for r in hazard_rows]
        flood_computed = any(l["hazard_type"] == "riverine_flood" for l in layers)
        regime_available = any(bool(r[3]) for r in hazard_rows if r[0] == "riverine_flood")

        metrics = DistrictTrustMetrics(
            district=name,
            habitations_total=habitations_total,
            tier_counts=tier_counts,
            tier_quality=tier_quality,
            data_quality_counts=dq_counts,
            urgent_synthetic=urgent_synthetic,
            hazard_layers=layers,
            flood_model_status="computed" if flood_computed else "not_computed",
            regime_available=regime_available,
            sites_total=sites_total,
            sites_fully_assessed=sites_fully_assessed,
            sites_partial=sites_total - sites_fully_assessed,
            dynamic_source=fresh.dynamic_source,
            snapshot_age_hours=fresh.snapshot_age_hours,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Error querying trust metrics for district %r: %s", name, e)
        return DistrictTrustMetrics(district=name, status="unavailable")

    _TRUST_CACHE[cache_key] = (now, metrics)
    return metrics


def fetch_data_trust_context(
    db: Optional[Session],
    districts: List[str],
) -> DataTrustContext:
    """Builds a DataTrustContext for the requested districts (none requested -> no district metrics)."""
    caps = probe_schema_capabilities(db) if db else SchemaCapabilities()
    fresh = _fetch_freshness(db) if db else _Freshness()
    district_metrics: Dict[str, DistrictTrustMetrics] = {}
    for d in districts:
        district_metrics[d] = fetch_district_trust_metrics(db, d)

    return DataTrustContext(
        districts=district_metrics,
        serving_version_ok=fresh.serving_version_ok,
        serving_version=fresh.serving_version,
        schema_capabilities=caps,
    )


def _describe_quality(quality: Dict[str, int]) -> str:
    if not quality:
        return "unknown"
    if len(quality) == 1:
        return next(iter(quality))
    return "mixed: " + ", ".join(f"{k} {v}" for k, v in sorted(quality.items()))


def build_compact_context_block(trust: DataTrustContext, districts: List[str]) -> str:
    """Generates compact factual block for prompt injection (§7).

    Example output:
    Barpeta: 253 habitations; 16 short_term (derived), 98 medium_term (derived), 139 monitoring (derived);
    flood model computed (with regimes); 514 candidate sites (0 fully assessed, 514 partial/unknown).
    """
    lines: List[str] = []
    target_districts = districts if districts else list(trust.districts.keys())

    for d in target_districts:
        m = trust.districts.get(d)
        if not m:
            continue

        if m.status == "unknown_district":
            lines.append(f"{m.district}: not a district loaded in this database; state no figures for it.")
            continue
        if m.status == "unavailable":
            lines.append(f"{m.district}: trust data could not be read (database error); do not state counts for it.")
            continue
        if m.habitations_total == 0:
            lines.append(f"{m.district}: 0 habitations loaded in database.")
            continue

        tiers_desc_parts: List[str] = []
        for tier_key_ in ["immediate", "short_term", "medium_term", "mitigate_in_situ", "monitoring", "unscored"]:
            cnt = m.tier_counts.get(tier_key_, 0)
            if cnt > 0:
                label = "not scored" if tier_key_ == "unscored" else tier_key_
                tiers_desc_parts.append(f"{cnt} {label} ({_describe_quality(m.tier_quality.get(tier_key_, {}))})")
        tiers_desc = ", ".join(tiers_desc_parts) if tiers_desc_parts else "no tier data"

        regime_str = "with regimes" if m.regime_available else "regimes not computed"
        flood_str = f"flood model {m.flood_model_status} ({regime_str})"
        sites_str = (
            f"{m.sites_total} candidate sites ({m.sites_fully_assessed} fully assessed, {m.sites_partial} partial/unknown)"
            if m.sites_total > 0
            else "0 candidate sites"
        )
        suffix = " [static snapshot, not live data]" if m.data_source == "static_snapshot" else ""
        lines.append(f"{m.district}: {m.habitations_total} habitations; {tiers_desc}; {flood_str}; {sites_str}.{suffix}")

    return "\n".join(lines)
