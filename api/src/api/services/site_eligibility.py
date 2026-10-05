"""Single source of truth for resolving a candidate-site row into an H7 eligibility verdict.

Both the site-listing path (`sites_service`) and the allocation path (`allocation_service`)
must answer "is this site allocatable?" identically. Previously they did not: the listing path
omitted the environmental exclusion flags entirely and inherited
`evaluate_site_eligibility()`'s `False` defaults, while the allocation path read the same flags
out of the row's `metadata` JSON and passed `None` when they were absent. The same site was
reported `eligible / allocatable: true` by `GET /habitations/{id}/sites` and silently dropped by
`POST /plan/allocate`.

Section refs: docs/PRD1.md §6.8, FR-7.2, FR-7.3 (H7 candidate-site policy).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from core.domain.capacity import CandidateSitePolicy, CapacityEngine, EligibilityResult

# Row/metadata key aliases, in resolution order. The pipeline writes the `is_*` form; the
# aliases tolerate older fixture rows and external imports that used the bare noun.
_EXCLUSION_KEYS: dict[str, tuple[str, ...]] = {
    "is_forest": ("is_forest", "forest"),
    "is_protected_area": ("is_protected_area", "protected_area", "protected"),
    "is_crz": ("is_crz", "crz"),
    "is_water_body": ("is_water_body", "water_body", "water"),
}


def parse_bool(val: Any) -> Optional[bool]:
    """Coerces a JSON/SQL truthy value to bool, returning None for anything unrecognised.

    None means "not asserted by the data" and must stay distinct from False ("asserted safe"),
    because H7 rejects unverified sites rather than assuming they are safe.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.lower().strip()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return None
    if isinstance(val, (int, float)):
        if val == 1:
            return True
        if val == 0:
            return False
        return None
    return None


def coerce_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Returns the row's metadata JSON as a dict, whatever column alias or encoding it arrived in."""
    meta = row.get("metadata")
    if meta is None:
        meta = row.get("metadata_info")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            meta = {}
    return meta if isinstance(meta, dict) else {}


def extract_exclusion_flags(row: dict[str, Any]) -> dict[str, Optional[bool]]:
    """Resolves the four environmental exclusion flags from a candidate-site row.

    Looks at top-level columns first, then the metadata JSON. A flag absent from both stays
    None so the policy can reject the site as unverified instead of assuming it is safe.
    """
    meta = coerce_metadata(row)
    flags: dict[str, Optional[bool]] = {}

    for canonical, aliases in _EXCLUSION_KEYS.items():
        value: Optional[bool] = None
        for source in (row, meta):
            for alias in aliases:
                if alias in source:
                    value = parse_bool(source[alias])
                    if value is not None:
                        break
            if value is not None:
                break
        flags[canonical] = value

    return flags


def evaluate_row_eligibility(
    engine: CapacityEngine,
    row: dict[str, Any],
    policy: Optional[CandidateSitePolicy] = None,
    distance_km: Optional[float] = None,
    require_distance: bool = False,
) -> EligibilityResult:
    """Evaluates one candidate-site row against H7 policy.

    Physical attributes are passed through as-is — notably *not* coerced to 0.0 when missing,
    since a missing slope must read as unverified rather than as perfectly flat terrain.
    """
    mhi = row.get("mhi_max") if row.get("mhi_max") is not None else row.get("mhi_static")
    slope = row.get("slope_mean") if row.get("slope_mean") is not None else row.get("slope")
    area = row.get("area_ha") if row.get("area_ha") is not None else row.get("area")

    return engine.evaluate_site_eligibility(
        mhi_max=float(mhi) if mhi is not None else None,
        slope_mean=float(slope) if slope is not None else None,
        area_ha=float(area) if area is not None else None,
        tenure=row.get("tenure"),
        distance_km=distance_km,
        require_distance=require_distance,
        policy=policy,
        hazard_regime=row.get("hazard_regime"),
        **extract_exclusion_flags(row),
    )
