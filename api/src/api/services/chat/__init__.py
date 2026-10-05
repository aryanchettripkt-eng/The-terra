"""Chat orchestrator core package for SETU-DRR.

Provides deterministic entity resolution, intent classification, least-privilege
toolset management, data trust context, and query planning.
"""

from api.services.chat.entities import (
    AmbiguityInfo,
    CANONICAL_DISTRICTS,
    EntityResolver,
    ResolvedEntities,
)
from api.services.chat.intents import (
    Intent,
    classify_intent,
)
from api.services.chat.plan import (
    QueryPlan,
    RefusalReason,
    TemplateId,
    build_query_plan,
)
from api.services.chat.toolsets import (
    ALL_SAFE_READ_TOOLS,
    INTENT_REQUIRED_TOOLS,
    INTENT_TOOLSETS,
    enforce_toolset,
    filter_tools_spec,
    get_required_tools_for_intent,
    get_toolset_for_intent,
    required_tools_satisfied,
)
from api.services.chat.trust import (
    DataTrustContext,
    DistrictTrustMetrics,
    SchemaCapabilities,
    build_compact_context_block,
    clear_trust_caches,
    fetch_data_trust_context,
    probe_schema_capabilities,
)

__all__ = [
    "AmbiguityInfo",
    "CANONICAL_DISTRICTS",
    "EntityResolver",
    "ResolvedEntities",
    "Intent",
    "classify_intent",
    "QueryPlan",
    "RefusalReason",
    "TemplateId",
    "build_query_plan",
    "ALL_SAFE_READ_TOOLS",
    "INTENT_REQUIRED_TOOLS",
    "INTENT_TOOLSETS",
    "enforce_toolset",
    "filter_tools_spec",
    "get_required_tools_for_intent",
    "get_toolset_for_intent",
    "required_tools_satisfied",
    "DataTrustContext",
    "DistrictTrustMetrics",
    "SchemaCapabilities",
    "build_compact_context_block",
    "clear_trust_caches",
    "fetch_data_trust_context",
    "probe_schema_capabilities",
]
