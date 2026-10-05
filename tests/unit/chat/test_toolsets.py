"""Unit tests for toolset registry, least privilege filtering, and security enforcement (§4.5, §5)."""

import pytest
from unittest.mock import MagicMock
from api.services.chat.intents import Intent
from api.services.chat.toolsets import (
    ALL_SAFE_READ_TOOLS,
    enforce_toolset,
    filter_tools_spec,
    get_required_tools_for_intent,
    get_toolset_for_intent,
)
from api.services.chat_assistant_service import RelocationChatAssistantService


def test_toolset_mappings_least_privilege():
    """Each intent has strictly scoped toolset (§5)."""
    # District overview
    dist_tools = get_toolset_for_intent(Intent.DISTRICT_OVERVIEW)
    assert "list_urgent_villages" in dist_tools
    assert "get_village_priority" not in dist_tools
    assert "assess_candidate_sites_suitability" not in dist_tools

    # Habitation detail
    hab_tools = get_toolset_for_intent(Intent.HABITATION_DETAIL)
    assert "get_village_priority" in hab_tools
    assert "search_habitations" in hab_tools
    assert "list_urgent_villages" not in hab_tools

    # Site detail
    site_tools = get_toolset_for_intent(Intent.SITE_DETAIL)
    assert "get_candidate_site_details" in site_tools
    assert "get_missing_infrastructure" in site_tools
    assert "compare_relocation_plans" not in site_tools

    # Methodology, Refusals, Clarify have zero tools
    assert get_toolset_for_intent(Intent.METHODOLOGY) == []
    assert get_toolset_for_intent(Intent.DECISION_REQUEST) == []
    assert get_toolset_for_intent(Intent.PREDICTION_REQUEST) == []
    assert get_toolset_for_intent(Intent.CLARIFY) == []
    assert get_toolset_for_intent(Intent.OUT_OF_SCOPE) == []


def test_required_tools_for_quantitative_intents():
    """Quantitative intents require specific tools to be called (§5, §8)."""
    assert "list_urgent_villages" in get_required_tools_for_intent(Intent.DISTRICT_OVERVIEW)
    assert "get_village_priority" in get_required_tools_for_intent(Intent.HABITATION_DETAIL)
    assert "assess_candidate_sites_suitability" in get_required_tools_for_intent(Intent.SITE_SCREENING)
    assert "compare_relocation_plans" in get_required_tools_for_intent(Intent.PLAN_COMPARISON)


def test_enforce_toolset_permission_and_rejection():
    """Disallowed tools are rejected under policy guard (§4.5)."""
    allowed = ["get_village_priority", "search_habitations"]

    # Allowed call
    ok, err = enforce_toolset("get_village_priority", allowed)
    assert ok is True
    assert err is None

    # Disallowed call rejected
    ok2, err2 = enforce_toolset("list_urgent_villages", allowed)
    assert ok2 is False
    assert "Security violation" in err2
    assert "list_urgent_villages" in err2


def test_filter_tools_spec():
    """OpenAPI tools spec is strictly pruned down to allowed tools only (§4.5)."""
    all_specs = [
        {"type": "function", "function": {"name": "get_village_priority"}},
        {"type": "function", "function": {"name": "list_urgent_villages"}},
        {"type": "function", "function": {"name": "assess_candidate_sites_suitability"}},
    ]

    filtered = filter_tools_spec(all_specs, ["get_village_priority"])
    assert len(filtered) == 1
    assert filtered[0]["function"]["name"] == "get_village_priority"

    empty = filter_tools_spec(all_specs, [])
    assert empty == []


def test_service_execute_tool_rejects_disallowed_call():
    """RelocationChatAssistantService._execute_tool rejects disallowed tool calls with failed execution record."""
    mock_db = MagicMock()
    service = RelocationChatAssistantService(mock_db)

    # Allow only get_village_priority
    allowed = ["get_village_priority"]

    # Attempt to invoke list_urgent_villages
    data, cits, exec_rec = service._execute_tool(
        "list_urgent_villages",
        {"district": "Barpeta"},
        allowed_tools=allowed,
    )

    assert data.get("found") is False
    assert "error" in data
    assert "Security violation" in data["error"]
    assert cits == []
    assert exec_rec.status == "failed"
    assert exec_rec.data_source == "SETU Policy Guard"
