"""Intent enumeration and rules-based intent classifier for SETU-DRR chat orchestrator.

Classifies incoming user messages deterministically using ordered patterns,
keyword cues, entity presence, and ambiguity signals.
"""

from __future__ import annotations

from enum import Enum
import logging
import re
from typing import Any, Dict, Optional, Tuple

from api.services.chat.entities import ResolvedEntities

logger = logging.getLogger("setu_api.chat.intents")


class Intent(str, Enum):
    """Categorical intent for user queries within the relocation decision support domain."""
    DISTRICT_OVERVIEW = "district_overview"
    HABITATION_DETAIL = "habitation_detail"
    SITE_DETAIL = "site_detail"
    SITE_SCREENING = "site_screening"
    PLAN_COMPARISON = "plan_comparison"
    FLOOD_EXPOSURE = "flood_exposure"
    CROSS_DISTRICT_COMPARE = "cross_district_compare"
    METHODOLOGY = "methodology"
    DECISION_REQUEST = "decision_request"
    PREDICTION_REQUEST = "prediction_request"
    CLARIFY = "clarify"
    OUT_OF_SCOPE = "out_of_scope"


# -----------------------------------------------------------------------------
# Regex Rules for Intent Classification
# -----------------------------------------------------------------------------

# Invariant: never make or endorse an executive decision. Patterns are deliberately broad: a missed refusal is
# worse than a spurious one, because nothing downstream of the classifier catches it yet.
_VERB = r"(?:relocat\w*|evacuat\w*|resettl\w*)"
DECISION_PATTERNS = [
    rf"\b(?:should|must|shall|ought\s+to)\s+(?:\w+\s+){{1,3}}?(?:relocate|evacuate|resettle)\b",
    r"\b(?:we|i|they)\s+(?:need|have)\s+to\s+(?:relocate|evacuate|resettle)\b",
    r"\brecommend\s+(?:whether|if\s+we\s+should)\s+(?:to\s+)?(?:relocate|evacuate)\b",
    r"\bdecide\s+(?:whether|if)\s+to\s+(?:relocate|evacuate)\b",
    r"\bdo\s+you\s+recommend\s+(?:relocating|evacuating)\b",
    r"\bmake\s+a\s+decision\s+on\s+(?:relocation|evacuation)\b",
    r"\bis\s+(?:relocation|evacuation)\s+(?:mandatory|necessary|recommended|approved|required|advisable|needed)\b",
    rf"\bis\s+it\s+(?:necessary|advisable|mandatory|required|recommended|time)\s+(?:to\s+)?{_VERB}",
]
# Passive / "need to" forms; skipped for plain counting questions ("how many households need to be relocated").
DECISION_PATTERNS_GUARDED = [
    rf"\bdoes?\s+(?:\w+\s+){{1,3}}?(?:need|have)\s+to\s+(?:be\s+)?{_VERB}",
    rf"\bshould\s+(?:\w+\s+){{0,3}}?be\s+(?:relocated|evacuated|resettled)\b",
]
COUNTING_LEAD = re.compile(r"^\s*how\s+(?:many|much)\b")

# Invariant: no forecasts. Susceptibility is not prediction (§3), so "will it flood ..." is refused.
_NOT_A_LAYER = r"(?![\s-]+(?:model|prone|susceptib\w*|layer|regime|map|data|exposure|zone|summary|status))"
PREDICTION_PATTERNS = [
    r"\bwhere\s+will\s+it\s+flood\s+next\b",
    r"\bwhen\s+will\s+(?:it|the\s+next)\s+(?:flood|landslide)\b",
    r"\bpredict\w*\s+(?:the\s+next|when|where|future)?\s*(?:disaster|flood|landslide)",
    r"\bforecast\s+(?:the\s+)?next\s+(?:flood|landslide|disaster)\b",
    rf"\bwill\b[^.?!]{{0,60}}?\b(?:floods?|flooded|flooding|inundat\w*|landslides?|overflow\w*|submerg\w*){_NOT_A_LAYER}",
    r"\bwill\s+(?:there\s+be\s+a\s+flood|another\s+disaster\s+occur)\b",
    r"\b(?:going|likely|expected|set)\s+to\s+(?:flood|be\s+flooded|inundate)\b",
    r"\bnext\s+(?:big\s+)?(?:flood|landslide|disaster)\b",
    r"\b(?:probability|chance|likelihood)\s+of\s+(?:a\s+)?(?:flood|landslide)\b",
]

# Methodology & statutory legal gate explanations
METHODOLOGY_PATTERNS = [
    r"\bwhat\s+is\s+(?:the\s+)?h7(?:\s+gate)?\b",
    r"\bwhat\s+is\s+section\s+6\.8\b",
    r"\bhow\s+does\s+(?:the\s+)?h7\s+gate\s+work\b",
    r"\bhow\s+is\s+prz\s+calculated\b",
    r"\bwhat\s+is\s+prz\b",
    r"\bwhat\s+does\s+mhi\s+mean\b",
    r"\bwhat\s+is\s+mhi\b",
    r"\bhow\s+does\s+triage\s+work\b",
    r"\bwhat\s+is\s+the\s+methodology\b",
    r"\bexplain\s+(?:the\s+)?(?:h7|methodology|scoring\s+formula|caseload\s+score|priority\s+score|triage\s+algorithm)\b",
    r"\bwhat\s+are\s+the\s+hard\s+gates\b",
]

# Side-by-side plan comparisons
PLAN_COMPARISON_PATTERNS = [
    r"\bcompare\s+setu\s+vs\b",
    r"\bcompare\b[^.?!]{0,50}\b(?:external|partner)\b",
    r"\b(?:vs|versus|against)\s+(?:the\s+)?(?:external|partner)\b",
    r"\bcompare\s+(?:the\s+)?(?:external|partner)\s+plan\b",
    r"\bsetu\s+vs\s+partner\b",
    r"\bsetu\s+vs\s+external\b",
    r"\bbenchmark\s+comparison\b",
    r"\bpartner\s+recommendation\b",
    r"\bexternal\s+gis\s+recommendation\b",
    r"\bwhy\s+does\s+setu\s+reject\s+partner\b",
    r"\brelocation\s+plans?\s+comparison\b",
]

# Multi-district comparison
CROSS_DISTRICT_PATTERNS = [
    r"\bwhich\s+district\s+has\s+(?:the\s+)?most\s+people\s+in\s+danger\b",
    r"\brank\s+districts(?:\s+by\s+risk)?\b",
    r"\bcompare\s+all\s+districts\b",
    r"\bcross[- ]district\s+(?:comparison|ranking|exposure)\b",
    r"\bwhich\s+district\s+is\s+(?:most\s+vulnerable|highest\s+risk)\b",
    r"\bhighest\s+risk\s+district\b",
]

# Candidate site screening across parcels
SITE_SCREENING_PATTERNS = [
    r"\bwhich\s+sites\s+are\s+safest\b",
    r"\bsafest\s+candidate\s+sites\b",
    r"\bbest\s+relocation\s+sites\b",
    r"\bscreen\s+(?:candidate\s+)?(?:relocation\s+)?sites\b",
    r"\bsuitable\s+(?:candidate\s+)?sites\b",
    r"\brank\s+(?:candidate\s+)?sites\b",
    r"\bassess\s+candidate\s+sites\b",
    r"\bfind\s+(?:safe\s+)?candidate\s+sites\b",
]

# Specific candidate parcel detail
SITE_DETAIL_PATTERNS = [
    r"\bwhat(?:'s|\s+is)\s+missing\s+at\s+site\b",
    r"\bmissing\s+infrastructure\s+at\s+site\b",
    r"\bcarrying\s+capacity\s+of\s+site\b",
    r"\bdetails?\s+(?:for|on|about)\s+site\b",
    r"\bsite\s+#?\d+\b",
    r"\bcandidate\s+site\s+#?\d+\b",
]

# Specific habitation priority detail
HABITATION_DETAIL_PATTERNS = [
    r"\bwhy\s+is\s+(?:village|habitation|settlement)\s+#?\d+\b",
    r"\bwhy\s+was\s+(?:village|habitation|settlement)\s+#?\d+\b",
    r"\bwhy\s+is\s+#\d+\s+prioritized\b",
    r"\btriage\s+rationale\s+for\b",
    r"\bpriority\s+(?:score|rationale)\s+for\b",
    r"\bdetails?\s+(?:for|on|about)\s+(?:habitation|village|settlement)\b",
    r"\b(?:village|habitation)\s+#?\d+\b",
    r"\bsettlement\s+\d+\b",
]

# Flood and hazard exposure inquiry
FLOOD_EXPOSURE_PATTERNS = [
    r"\bflood[- ]prone\b",
    r"\bflood\s+susceptibility\b",
    r"\bhow\s+susceptible\b",
    r"\bhazard\s+exposure\b",
    r"\blandslide\s+susceptibility\b",
    r"\blandslide\s+risk\b",
    r"\bflood\s+model(?:\s+status)?\b",
    r"\bhazard\s+regime\b",
    r"\bhazard\s+layers?\b",
    r"\briverine\s+flood\b",
    r"\bflash\s+flood\b",
    r"\bhow\s+flood[- ]prone\s+is\b",
]

# Macro district exposure and triage summary
DISTRICT_OVERVIEW_PATTERNS = [
    r"\bpeople\s+in\s+danger\b",
    r"\bpopulation\s+at\s+risk\b",
    r"\btriage\s+summary\b",
    r"\bhow\s+many\s+people\s+(?:are\s+)?(?:in\s+danger|at\s+risk)\b",
    r"\bhow\s+many\s+habitations\b",
    r"\bhow\s+many\s+households\s+at\s+risk\b",
    r"\bvillages\s+in\s+danger\b",
    r"\burgent\s+(?:villages|habitations|triage)\b",
    r"\boverview\s+of\b",
    r"\bexposure\s+summary\b",
]

# Prompt-injection style requests are refused no matter what else the message mentions.
INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|all)\s+instructions\b",
    r"\b(?:disregard|forget)\s+(?:all|your|the\s+previous)\b",
    r"\b(?:reveal|show|print)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?prompt\b",
    r"\byou\s+are\s+now\b",
]

# General off-topic requests. Only applied when the message names no district, habitation or site, so a
# DRR question that happens to contain "who is" is not refused.
OUT_OF_SCOPE_PATTERNS = [
    r"\bcapital\s+of\b",
    r"\bwho\s+(?:is|was)\s+the\s+(?:president|prime\s+minister|ceo|founder)\b",
    r"\bwho\s+won\b",
    r"\bwrite\s+a\s+(?:poem|essay|code|python\s+script|joke)\b",
    r"\brecipe\s+for\b",
    r"\bweather\s+(?:today|tomorrow)\b",
    r"\bstock\s+price\b",
    r"\bcricket\s+(?:score|world\s+cup)\b",
]

# Words that mark a question as being about the DRR domain even when no rule matches.
DRR_CUES = (
    "risk", "danger", "disaster", "village", "habitation", "settlement", "site", "flood", "landslide", "hazard",
    "triage", "safe", "relocat", "evacuat", "population", "household", "susceptib", "tier", "exposure",
)

# Confidence levels emitted by the classifier. Anything below CHAT_CONFIDENCE_THRESHOLD (0.7) gets the broad
# toolset (§4.4), so DRR-flavoured but unrecognised questions are answered rather than refused.
CONF_RULE = 1.0
CONF_DISTRICT_ONLY = 0.9
CONF_DRR_UNRECOGNISED = 0.6
CONF_NO_SIGNAL = 0.5


def _any(patterns: list, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify_intent(
    message: str,
    entities: Optional[ResolvedEntities] = None,
    page_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Intent, float]:
    """Classifies user query intent using deterministic rule matching.

    Returns:
        (Intent, confidence_score). 1.0 for an explicit rule hit; lower values mean the rules only guessed, and
        the caller then exposes the broad toolset instead of a narrowed one.
    """
    text_lower = message.lower().strip()
    ents = entities or ResolvedEntities()
    names_entity = bool(
        ents.district_source == "message" or ents.habitation_ids or ents.habitation_names or ents.site_ids
    )

    # Rule 1: injection attempts are never answered
    if _any(INJECTION_PATTERNS, text_lower):
        return Intent.OUT_OF_SCOPE, CONF_RULE

    # Rule 2: decision and prediction requests (mandatory refusals)
    if _any(DECISION_PATTERNS, text_lower):
        return Intent.DECISION_REQUEST, CONF_RULE
    if not COUNTING_LEAD.match(text_lower) and _any(DECISION_PATTERNS_GUARDED, text_lower):
        return Intent.DECISION_REQUEST, CONF_RULE
    if _any(PREDICTION_PATTERNS, text_lower):
        return Intent.PREDICTION_REQUEST, CONF_RULE

    # Rule 3: general off-topic requests, only when the message names nothing from the domain
    if not names_entity and _any(OUT_OF_SCOPE_PATTERNS, text_lower):
        return Intent.OUT_OF_SCOPE, CONF_RULE

    # Rule 4: methodology and legal gates
    if _any(METHODOLOGY_PATTERNS, text_lower):
        return Intent.METHODOLOGY, CONF_RULE

    # Rule 5: an unresolved reference needs a question back
    if ents.ambiguity and ents.ambiguity.is_ambiguous:
        return Intent.CLARIFY, CONF_RULE

    # Rule 6: an explicit topic wins over a plain multi-district comparison (the tools take a district argument)
    if _any(PLAN_COMPARISON_PATTERNS, text_lower):
        return Intent.PLAN_COMPARISON, CONF_RULE
    if _any(SITE_SCREENING_PATTERNS, text_lower):
        return Intent.SITE_SCREENING, CONF_RULE

    # Rule 7: cross-district comparison
    if len(ents.districts) >= 2 and ents.district_source == "message" and any(
        re.search(rf"\b{word}\b", text_lower)
        for word in ["compare", "vs", "versus", "and", "between", "difference", "ranking"]
    ):
        return Intent.CROSS_DISTRICT_COMPARE, CONF_RULE
    if _any(CROSS_DISTRICT_PATTERNS, text_lower):
        return Intent.CROSS_DISTRICT_COMPARE, CONF_RULE

    # Rule 8: a specific candidate site
    if ents.site_ids or _any(SITE_DETAIL_PATTERNS, text_lower):
        return Intent.SITE_DETAIL, CONF_RULE

    # Rule 9: questions about "sites"/"parcels" in a named district
    if ents.district_source == "message" and re.search(r"\b(?:sites?|parcels?)\b", text_lower):
        return Intent.SITE_SCREENING, CONF_DISTRICT_ONLY

    # Rule 10: district overview patterns
    if _any(DISTRICT_OVERVIEW_PATTERNS, text_lower):
        return Intent.DISTRICT_OVERVIEW, CONF_RULE

    # Rule 11: a specific habitation (ids and names the user wrote, or "this village" resolved from the page)
    if ents.habitation_ids or (ents.habitation_names and len(ents.districts) <= 1):
        return Intent.HABITATION_DETAIL, CONF_RULE
    if _any(HABITATION_DETAIL_PATTERNS, text_lower):
        return Intent.HABITATION_DETAIL, CONF_RULE

    # Rule 12: flood and hazard exposure
    if _any(FLOOD_EXPOSURE_PATTERNS, text_lower):
        return Intent.FLOOD_EXPOSURE, CONF_RULE

    # A district the user named, with nothing more specific, is an overview request
    if ents.district_source == "message":
        return Intent.DISTRICT_OVERVIEW, CONF_DISTRICT_ONLY

    # Domain vocabulary but no recognised shape: low confidence, broad toolset. Page context alone never
    # makes a message in scope ("hello" on the Barpeta page is not a Barpeta question).
    if any(cue in text_lower for cue in DRR_CUES):
        return Intent.DISTRICT_OVERVIEW, CONF_DRR_UNRECOGNISED

    return Intent.OUT_OF_SCOPE, CONF_NO_SIGNAL
