"""Tool registry, least-privilege scoping, and toolset enforcement (§4.5, §5).

Restricts the tools exposed and executable to strictly those authorized for the
classified intent and query plan.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from api.services.chat.intents import Intent
from core.config import settings

logger = logging.getLogger("setu_api.chat.toolsets")

# Broad toolset for low confidence queries (§4.4)
# Names must match the tools the service exposes (tests assert this). `get_triage_summary` arrives in Phase 2;
# until then `list_urgent_villages` already returns the full tier summary.
ALL_SAFE_READ_TOOLS: List[str] = [
    "list_urgent_villages",
    "get_district_hazard_summary",
    "get_village_priority",
    "search_habitations",
    "get_candidate_sites_for_habitation",
    "get_candidate_site_details",
    "get_missing_infrastructure",
    "assess_candidate_sites_suitability",
    "compare_relocation_plans",
    "calculate",
]

# Per-intent least-privilege toolsets (§5)
INTENT_TOOLSETS: Dict[Intent, List[str]] = {
    Intent.DISTRICT_OVERVIEW: [
        "list_urgent_villages",
        "get_district_hazard_summary",
        "calculate",
    ],
    Intent.HABITATION_DETAIL: [
        "search_habitations",
        "get_village_priority",
        "get_candidate_sites_for_habitation",
        "calculate",
    ],
    Intent.SITE_DETAIL: [
        "get_candidate_site_details",
        "get_missing_infrastructure",
        "calculate",
    ],
    Intent.SITE_SCREENING: [
        "assess_candidate_sites_suitability",
        "get_candidate_site_details",
        "calculate",
    ],
    Intent.PLAN_COMPARISON: [
        "compare_relocation_plans",
        "calculate",
    ],
    Intent.FLOOD_EXPOSURE: [
        "get_district_hazard_summary",
        "calculate",
    ],
    # Union of the per-topic toolsets: a comparison may be about triage, hazard, sites or plans (§5).
    Intent.CROSS_DISTRICT_COMPARE: list(ALL_SAFE_READ_TOOLS),
    Intent.METHODOLOGY: [],
    Intent.DECISION_REQUEST: [],
    Intent.PREDICTION_REQUEST: [],
    Intent.CLARIFY: [],
    Intent.OUT_OF_SCOPE: [],
}

# Required tools per quantitative intent (§5, §8). Contract: a quantitative answer must call AT LEAST ONE of
# the listed tools (see `required_tools_satisfied`); the list is not "all of these".
INTENT_REQUIRED_TOOLS: Dict[Intent, List[str]] = {
    Intent.DISTRICT_OVERVIEW: ["list_urgent_villages"],
    Intent.HABITATION_DETAIL: ["get_village_priority"],
    Intent.SITE_DETAIL: ["get_candidate_site_details", "get_missing_infrastructure"],
    Intent.SITE_SCREENING: ["assess_candidate_sites_suitability"],
    Intent.PLAN_COMPARISON: ["compare_relocation_plans"],
    Intent.FLOOD_EXPOSURE: ["get_district_hazard_summary"],
    Intent.CROSS_DISTRICT_COMPARE: ["list_urgent_villages", "get_district_hazard_summary"],
    Intent.METHODOLOGY: [],
    Intent.DECISION_REQUEST: [],
    Intent.PREDICTION_REQUEST: [],
    Intent.CLARIFY: [],
    Intent.OUT_OF_SCOPE: [],
}


def get_toolset_for_intent(intent: Intent, confidence: float = 1.0) -> List[str]:
    """Retrieves allowed tool names for an intent under least privilege (§4.5).

    If confidence is below CHAT_CONFIDENCE_THRESHOLD, falls back to the broad safe toolset.
    """
    if confidence < settings.CHAT_CONFIDENCE_THRESHOLD:
        logger.info(
            "Low confidence (%.2f < %.2f) for intent %s. Using broad toolset.",
            confidence,
            settings.CHAT_CONFIDENCE_THRESHOLD,
            intent.value,
        )
        return list(ALL_SAFE_READ_TOOLS)

    return list(INTENT_TOOLSETS.get(intent, []))


def get_required_tools_for_intent(intent: Intent) -> List[str]:
    """Retrieves tools that MUST be executed for a quantitative answer to pass verification."""
    return list(INTENT_REQUIRED_TOOLS.get(intent, []))


def required_tools_satisfied(required_tools: List[str], tools_called: List[str]) -> bool:
    """True when no tool is required, or at least one required tool was called (§5, §8)."""
    return not required_tools or any(t in tools_called for t in required_tools)


def enforce_toolset(tool_name: str, allowed_tools: List[str]) -> Tuple[bool, Optional[str]]:
    """Enforces that an invoked tool is explicitly authorized in the active query plan (§4.5).

    Returns:
        (True, None) if permitted, or (False, error_message) if disallowed.
    """
    if tool_name in allowed_tools:
        return True, None

    error_msg = (
        f"Security violation: Tool '{tool_name}' is not permitted under the active query plan. "
        f"Permitted tools: {allowed_tools}"
    )
    logger.warning(error_msg)
    return False, error_msg


def filter_tools_spec(
    all_tools_spec: List[Dict[str, Any]],
    allowed_tools: List[str],
) -> List[Dict[str, Any]]:
    """Filters the OpenAPI / Groq tool specification schema to expose ONLY permitted tools."""
    if not allowed_tools:
        return []

    filtered: List[Dict[str, Any]] = []
    for spec in all_tools_spec:
        fn_name = spec.get("function", {}).get("name")
        if fn_name in allowed_tools:
            filtered.append(spec)

    return filtered
