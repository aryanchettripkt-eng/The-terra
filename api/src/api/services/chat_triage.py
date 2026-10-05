"""Triage-tier accounting for the relocation assistant.

Shows every tier (including the monitoring bucket and zero counts) next to the data quality of the rows
behind it, so urgent-only figures are never read as a district's total exposure and synthetic demo data is
never presented as measured.

Semantics (verified against the triage job, ``priority.evaluate_triage`` and the live database):
- ``habitation_risk.tier`` is NULL when triage evaluated the settlement and it did not meet any relocation
  tier ("Unclassified / Monitoring: Settlement does not meet criteria for permanent relocation."). It is stored
  as NULL but is reported here as the ``monitoring`` bucket. It is neither "no data" nor a finding of safety.
- A habitation with no ``habitation_risk`` row at all has not been scored; that is the separate ``unscored``
  bucket (empty today) so a true data gap is never folded into "monitoring".
- ``habitation_risk.data_quality`` is ``derived`` (pipeline output) or ``synthetic`` (demo data).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

MONITORING_KEY = "monitoring"
UNSCORED_KEY = "unscored"
URGENT_TIERS = ("immediate", "short_term")

# Order in which tiers are always listed. ``unscored`` is appended only when it has rows.
TIER_ORDER = ("immediate", "short_term", "medium_term", "mitigate_in_situ", MONITORING_KEY)

TIER_LABELS: Dict[str, str] = {
    "immediate": "Immediate",
    "short_term": "Short-term",
    "medium_term": "Medium-term",
    "mitigate_in_situ": "Mitigate in situ",
    MONITORING_KEY: "Monitoring (no relocation tier)",
    UNSCORED_KEY: "Not scored (no triage result)",
}

TIER_WINDOWS: Dict[str, str] = {
    "immediate": "0–6 months",
    "short_term": "6–24 months",
    "medium_term": "2–5 years",
    "mitigate_in_situ": "civil protection in place",
    MONITORING_KEY: "no relocation window",
    UNSCORED_KEY: "n/a",
}

SYNTHETIC_NOTICE = (
    "Some of these figures come from synthetic demo data (`data_quality = synthetic`), not from measured or "
    "pipeline-derived records. Treat them as illustrative."
)
MONITORING_NOTE = (
    "\"Monitoring\" means triage evaluated the settlement and it did not meet a relocation tier. "
    "It is not a finding that the settlement is safe."
)
URGENT_SCOPE_NOTE = (
    "Urgent = immediate + short-term tiers only. Medium-term and monitoring habitations are listed separately "
    "and are not included in the urgent totals."
)


def tier_key(tier: Optional[str], *, scored: bool = True) -> str:
    """Maps a stored tier value to its reporting bucket."""
    if not scored:
        return UNSCORED_KEY
    return tier if tier else MONITORING_KEY


def tier_label(tier: Optional[str], *, scored: bool = True) -> str:
    key = tier_key(tier, scored=scored)
    return TIER_LABELS.get(key, key.replace("_", " ").title())


def quality_provenance(has_synthetic: bool, default: str = "authoritative") -> str:
    """Citation provenance grade: synthetic rows are never labelled authoritative."""
    return "synthetic_demo" if has_synthetic else default


def fetch_tier_rows(db: Session, district: Optional[str] = None) -> List[Dict[str, Any]]:
    """Habitation counts grouped by district, tier bucket inputs and data quality."""
    where = "WHERE LOWER(ab.name) = LOWER(:d)" if district else ""
    sql = text(f"""
        SELECT ab.name AS district_name,
               hr.tier AS tier,
               (hr.habitation_id IS NOT NULL) AS scored,
               COALESCE(hr.data_quality, 'unknown') AS data_quality,
               COUNT(*) AS habitations,
               COALESCE(SUM(h.population), 0) AS population,
               COALESCE(SUM(h.households), 0) AS households
        FROM habitation h
        JOIN admin_boundary ab ON ab.id = h.admin_id
        LEFT JOIN habitation_risk hr ON hr.habitation_id = h.id
        {where}
        GROUP BY ab.name, hr.tier, (hr.habitation_id IS NOT NULL), COALESCE(hr.data_quality, 'unknown')
        ORDER BY ab.name;
    """)
    params = {"d": district.strip()} if district else {}
    return [dict(r) for r in db.execute(sql, params).mappings().all()]


def _empty_bucket(key: str) -> Dict[str, Any]:
    return {
        "tier": key,
        "label": TIER_LABELS.get(key, key.replace("_", " ").title()),
        "window": TIER_WINDOWS.get(key, ""),
        "stored_as_null": key == MONITORING_KEY,
        "habitations": 0,
        "population": 0,
        "households": 0,
        "data_quality": {},
        "has_synthetic": False,
    }


def summarize_tier_rows(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregates grouped rows (one district or many) into a full tier summary.

    Every tier in ``TIER_ORDER`` is always present, with explicit zeros, so a reader sees what is *not* there.
    """
    buckets: Dict[str, Dict[str, Any]] = {key: _empty_bucket(key) for key in TIER_ORDER}
    row_count = 0
    for r in rows:
        row_count += 1
        key = tier_key(r.get("tier"), scored=bool(r.get("scored", True)))
        b = buckets.setdefault(key, _empty_bucket(key))
        n = int(r.get("habitations") or 0)
        b["habitations"] += n
        b["population"] += int(r.get("population") or 0)
        b["households"] += int(r.get("households") or 0)
        dq = str(r.get("data_quality") or "unknown")
        b["data_quality"][dq] = b["data_quality"].get(dq, 0) + n
        if dq == "synthetic" and n > 0:
            b["has_synthetic"] = True

    # Listed tiers always appear (zeros included); extra buckets such as `unscored` only when non-empty.
    tiers = [buckets[k] for k in TIER_ORDER] + [
        b for k, b in buckets.items() if k not in TIER_ORDER and b["habitations"]
    ]

    def _sum(keys: Iterable[str], field: str) -> int:
        return sum(buckets[k][field] for k in keys if k in buckets)

    urgent_keys = list(URGENT_TIERS)
    has_synthetic = any(b["has_synthetic"] for b in tiers)
    urgent_has_synthetic = any(buckets[k]["has_synthetic"] for k in urgent_keys)
    notes = [URGENT_SCOPE_NOTE]
    if buckets[MONITORING_KEY]["habitations"]:
        notes.append(MONITORING_NOTE)
    if has_synthetic:
        notes.append(SYNTHETIC_NOTICE)

    return {
        "found": row_count > 0,
        "tiers": tiers,
        "totals": {
            "habitations": sum(b["habitations"] for b in tiers),
            "population": sum(b["population"] for b in tiers),
            "households": sum(b["households"] for b in tiers),
        },
        "urgent": {
            "habitations": _sum(urgent_keys, "habitations"),
            "population": _sum(urgent_keys, "population"),
            "households": _sum(urgent_keys, "households"),
            "has_synthetic": urgent_has_synthetic,
        },
        "has_synthetic": has_synthetic,
        "notes": notes,
    }


def summarize_by_district(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-district tier summaries keyed by district name."""
    by_district: Dict[str, List[Mapping[str, Any]]] = {}
    for r in rows:
        by_district.setdefault(str(r.get("district_name")), []).append(r)
    return {name: summarize_tier_rows(rs) for name, rs in by_district.items()}


def render_tier_table(summary: Mapping[str, Any]) -> str:
    """Markdown table of every tier with population, households and data quality."""
    lines = [
        "| Tier | Window | Habitations | Population | Households | Data quality |",
        "| :--- | :--- | ---: | ---: | ---: | :--- |",
    ]
    for t in summary.get("tiers", []):
        dq = ", ".join(f"{k} {v}" for k, v in sorted(t["data_quality"].items())) or "–"
        lines.append(
            f"| **{t['label']}** | {t['window']} | {t['habitations']:,} | {t['population']:,} | "
            f"{t['households']:,} | {dq} |"
        )
    totals = summary.get("totals", {})
    lines.append(
        f"| **All habitations** | | **{totals.get('habitations', 0):,}** | **{totals.get('population', 0):,}** | "
        f"**{totals.get('households', 0):,}** | |"
    )
    return "\n".join(lines)
