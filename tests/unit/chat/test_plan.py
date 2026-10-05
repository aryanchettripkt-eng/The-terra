"""Unit tests for QueryPlan and build_query_plan (§4.1)."""

import pytest
from core.schemas.chat import ChatMessage, RelocationChatRequest
from api.services.chat.intents import Intent
from api.services.chat.plan import RefusalReason, TemplateId, build_query_plan


def test_build_query_plan_district_overview():
    """Generates plan for district overview with proper toolsets and trust metrics."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="How many people are in danger in Barpeta?")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.DISTRICT_OVERVIEW
    assert "Barpeta" in plan.entities.districts
    assert "list_urgent_villages" in plan.toolset
    assert plan.needs_clarification is None
    assert plan.refusal is None
    assert plan.trust is not None
    assert "Barpeta" in plan.trust.districts


def test_build_query_plan_habitation_detail():
    """Generates plan for specific habitation query."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="Why was village #775 prioritized for relocation?")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.HABITATION_DETAIL
    assert 775 in plan.entities.habitation_ids
    assert "get_village_priority" in plan.toolset
    assert "get_village_priority" in plan.required_tools


def test_build_query_plan_vague_village_clarification():
    """Vague village query produces clarify plan without calling LLM (§4.3)."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="Why is this village a priority?")],
        district="Wayanad",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.CLARIFY
    assert plan.template == TemplateId.CLARIFY
    assert plan.needs_clarification is not None
    assert "specify the habitation" in plan.needs_clarification.lower()
    assert plan.toolset == []


def test_build_query_plan_decision_request_refusal():
    """Decision requests mandate deterministic refusal plan (§3 invariants)."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="Should we relocate village #775 immediately?")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.DECISION_REQUEST
    assert plan.refusal == RefusalReason.DECISION_REQUEST
    assert plan.template == TemplateId.REFUSAL
    assert plan.toolset == []


def test_build_query_plan_prediction_request_refusal():
    """Disaster prediction requests mandate deterministic refusal plan (§3 invariants)."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="Where will it flood next year in Barpeta?")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.PREDICTION_REQUEST
    assert plan.refusal == RefusalReason.PREDICTION_REQUEST
    assert plan.template == TemplateId.REFUSAL
    assert plan.toolset == []


def test_build_query_plan_out_of_scope_refusal():
    """Unrelated questions mandate out-of-scope refusal plan."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="What is the capital of France?")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.OUT_OF_SCOPE
    assert plan.refusal == RefusalReason.OUT_OF_SCOPE
    assert plan.toolset == []


def test_build_query_plan_cross_district_compare():
    """Cross district comparison plan contains all target districts and appropriate toolsets."""
    req = RelocationChatRequest(
        messages=[ChatMessage(role="user", content="Compare Barpeta and Wayanad exposure")],
        district="Barpeta",
    )
    plan = build_query_plan(req)

    assert plan.intent == Intent.CROSS_DISTRICT_COMPARE
    assert plan.entities.districts == ["Barpeta", "Wayanad"]
    assert "list_urgent_villages" in plan.toolset
    assert "Barpeta" in plan.trust.districts
    assert "Wayanad" in plan.trust.districts
