"""QueryPlan definition and deterministic planner for SETU-DRR chat orchestrator (§4.1).

Constructs the execution plan before any LLM is called, resolving entities,
classifying intent, assigning least-privilege toolsets, and attaching data trust context.
"""

from __future__ import annotations

from enum import Enum
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.services.chat.entities import CANONICAL_DISTRICTS, EntityResolver, ResolvedEntities
from api.services.chat.intents import Intent, classify_intent
from api.services.chat.toolsets import (
    get_required_tools_for_intent,
    get_toolset_for_intent,
)
from api.services.chat.trust import DataTrustContext, fetch_data_trust_context
from core.config import settings
from core.schemas.chat import RelocationChatRequest

logger = logging.getLogger("setu_api.chat.plan")


class RefusalReason(str, Enum):
    """Categorical reasons for mandatory non-LLM refusals (§3 invariants)."""
    DECISION_REQUEST = "decision_request"
    PREDICTION_REQUEST = "prediction_request"
    OUT_OF_SCOPE = "out_of_scope"


class TemplateId(str, Enum):
    """Identifier for structured response layout (§5)."""
    DISTRICT_OVERVIEW = "district_overview"
    HABITATION_DETAIL = "habitation_detail"
    SITE_DETAIL = "site_detail"
    SITE_SCREENING = "site_screening"
    PLAN_COMPARISON = "plan_comparison"
    FLOOD_EXPOSURE = "flood_exposure"
    CROSS_DISTRICT_COMPARE = "cross_district_compare"
    METHODOLOGY = "methodology"
    CLARIFY = "clarify"
    REFUSAL = "refusal"


class QueryPlan(BaseModel):
    """Execution plan governing LLM tool calling, least privilege, and verification (§4.1)."""
    intent: Intent
    confidence: float = 1.0
    entities: ResolvedEntities = Field(default_factory=ResolvedEntities)
    toolset: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    prompt_modules: List[str] = Field(default_factory=list)
    prefetch: List[Dict[str, Any]] = Field(default_factory=list)
    trust: Optional[DataTrustContext] = None
    template: Optional[TemplateId] = None
    max_rounds: int = 3
    needs_clarification: Optional[str] = None
    refusal: Optional[RefusalReason] = None
    screening_mode: bool = False
    summary: Dict[str, Any] = Field(default_factory=dict)


# Intents that cannot be answered without knowing the district
DISTRICT_REQUIRED_INTENTS = frozenset(
    {Intent.DISTRICT_OVERVIEW, Intent.FLOOD_EXPOSURE, Intent.SITE_SCREENING, Intent.PLAN_COMPARISON}
)


def _which_district_message(unknown: Optional[str] = None) -> str:
    supported = ", ".join(CANONICAL_DISTRICTS)
    if unknown:
        return f"'{unknown}' is not a district loaded in this system. Which district do you mean? Available: {supported}."
    return f"Which district do you mean? Available: {supported}."


def _trust_districts(intent: Intent, entities: ResolvedEntities) -> List[str]:
    """Districts whose trust data the plan needs; a district-less cross-district question needs all of them."""
    if entities.districts:
        return list(entities.districts)
    if intent == Intent.CROSS_DISTRICT_COMPARE:
        return list(CANONICAL_DISTRICTS)
    return []


def build_query_plan(
    request: RelocationChatRequest,
    db: Optional[Session] = None,
    trust_context: Optional[DataTrustContext] = None,
) -> QueryPlan:
    """Builds a deterministic QueryPlan from user messages and active page context.

    Steps:
      1. Extract latest user query.
      2. Deterministically resolve entities (districts, habitations, sites, years).
      3. Classify intent via deterministic rule matcher.
      4. Detect clarification or mandatory refusal requirements.
      5. Fetch or attach DataTrustContext for resolved districts.
      6. Select least-privilege toolset and required tools.
    """
    # 1. Extract latest user message
    latest_user_text = ""
    for m in reversed(request.messages):
        if m.role == "user":
            latest_user_text = m.content
            break

    # 2. Deterministic Entity Resolution
    resolver = EntityResolver(db)
    entities = resolver.resolve(
        message=latest_user_text,
        page_district=request.district,
        page_habitation_id=request.habitation_id,
        page_site_id=request.site_id,
    )

    page_ctx = {
        "district": request.district,
        "habitation_id": request.habitation_id,
        "site_id": request.site_id,
        "screening_mode": request.screening_mode,
    }

    # 3. Intent Classification
    intent, confidence = classify_intent(latest_user_text, entities, page_ctx)

    # 4. Clarification and Refusal handling
    needs_clarification: Optional[str] = None
    refusal: Optional[RefusalReason] = None
    template: Optional[TemplateId] = None

    if intent == Intent.CLARIFY:
        needs_clarification = (
            entities.ambiguity.message
            if entities.ambiguity
            else "Please provide more details on which specific district or habitation you would like to analyze."
        )
    elif intent == Intent.DECISION_REQUEST:
        refusal = RefusalReason.DECISION_REQUEST
    elif intent == Intent.PREDICTION_REQUEST:
        refusal = RefusalReason.PREDICTION_REQUEST
    elif intent == Intent.OUT_OF_SCOPE:
        refusal = RefusalReason.OUT_OF_SCOPE
    elif intent in DISTRICT_REQUIRED_INTENTS and not entities.districts:
        # No explicit district and no page context: ask, never default to a district (§4.3)
        intent = Intent.CLARIFY
        needs_clarification = _which_district_message()

    # 5. Data Trust Context (skipped for refusals and clarifications: no data is shown)
    trust: DataTrustContext
    if trust_context is not None:
        trust = trust_context
    elif needs_clarification or refusal or intent == Intent.METHODOLOGY:
        trust = DataTrustContext()
    else:
        trust = fetch_data_trust_context(db, _trust_districts(intent, entities))
        unknown = [m.district for m in trust.districts.values() if m.status == "unknown_district"]
        if unknown:
            intent = Intent.CLARIFY
            needs_clarification = _which_district_message(unknown=unknown[0])

    if needs_clarification:
        template = TemplateId.CLARIFY
    elif refusal:
        template = TemplateId.REFUSAL
    else:
        try:
            template = TemplateId(intent.value)
        except ValueError:
            template = TemplateId.DISTRICT_OVERVIEW

    # 6. Toolset and Required Tools
    toolset = get_toolset_for_intent(intent, confidence)
    required_tools = get_required_tools_for_intent(intent)

    # Prompt modules: base + intent-specific + context
    prompt_modules = ["base", intent.value]

    plan_summary = {
        "intent": intent.value,
        "confidence": confidence,
        "districts": entities.districts,
        "habitation_ids": entities.habitation_ids,
        "site_ids": entities.site_ids,
        "toolset": toolset,
        "required_tools": required_tools,
        "needs_clarification": bool(needs_clarification),
        "refusal": refusal.value if refusal else None,
        "screening_mode": request.screening_mode,
    }

    return QueryPlan(
        intent=intent,
        confidence=confidence,
        entities=entities,
        toolset=toolset,
        required_tools=required_tools,
        prompt_modules=prompt_modules,
        trust=trust,
        template=template,
        max_rounds=settings.CHAT_MAX_ROUNDS,
        needs_clarification=needs_clarification,
        refusal=refusal,
        screening_mode=request.screening_mode,
        summary=plan_summary,
    )
