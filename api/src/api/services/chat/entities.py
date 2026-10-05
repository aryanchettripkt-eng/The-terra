"""Deterministic entity resolution for the SETU-DRR chat orchestrator.

Resolves districts, habitations, candidate sites, and years deterministically
(never using an LLM) with explicit ambiguity detection and candidate listing.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.services.chat_triage import tier_label

logger = logging.getLogger("setu_api.chat.entities")

CANONICAL_DISTRICTS: List[str] = [
    "Barpeta",
    "Dholpur",
    "Kodagu",
    "Morena",
    "Rudraprayag",
    "Srinagar",
    "Wayanad",
    "Leh",
]

# Common aliases and typos for supported districts
DISTRICT_ALIASES: Dict[str, str] = {
    "wayand": "Wayanad",
    "waynad": "Wayanad",
    "wynad": "Wayanad",
    "kodgu": "Kodagu",
    "coorg": "Kodagu",
    "barpatta": "Barpeta",
    "barpetaa": "Barpeta",
    "dholpore": "Dholpur",
    "dholpure": "Dholpur",
    "moraina": "Morena",
    "rudra prayag": "Rudraprayag",
    "rudra-prayag": "Rudraprayag",
    "rudraprayage": "Rudraprayag",
    "srinager": "Srinagar",
}

# Real habitation names known in the database (verified from §2.4)
KNOWN_REAL_HABITATIONS: Dict[str, str] = {
    "howly": "Barpeta",
    "bohori": "Barpeta",
    "pathsala": "Barpeta",
    "sarupeta": "Barpeta",
    "barpeta": "Barpeta",
    "mundakkai": "Wayanad",
    "chooralmala": "Wayanad",
    "meppadi": "Wayanad",
    "vythiri": "Wayanad",
    "vellamunda": "Wayanad",
    "mananthavady": "Wayanad",
    "kalpetta": "Wayanad",
}


def canonical_district_name(raw: str) -> str:
    """Canonical spelling for a district name or known alias; unknown names are title-cased, not rejected."""
    clean = raw.strip()
    alias = DISTRICT_ALIASES.get(clean.lower())
    if alias:
        return alias
    return next((d for d in CANONICAL_DISTRICTS if d.lower() == clean.lower()), clean.title())


class AmbiguityInfo(BaseModel):
    """Details when an entity reference cannot be uniquely resolved."""
    is_ambiguous: bool = True
    entity_type: str = "habitation"  # "habitation" | "district" | "site"
    query: str = ""
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = ""


class ResolvedEntities(BaseModel):
    """Structured entities extracted deterministically from user input and context.

    ``habitation_ids`` / ``site_ids`` hold only ids the user named (or a deictic "this village" that the page
    context resolves). A page-selected id the user did not refer to is kept apart in ``context_*_id`` because it
    is a hint, never an override (§4.3).
    """
    districts: List[str] = Field(default_factory=list)
    district_source: Optional[str] = None  # "message" | "page" | None
    habitation_ids: List[int] = Field(default_factory=list)
    habitation_names: List[str] = Field(default_factory=list)
    site_ids: List[int] = Field(default_factory=list)
    context_habitation_id: Optional[int] = None
    context_site_id: Optional[int] = None
    years: List[int] = Field(default_factory=list)
    ambiguity: Optional[AmbiguityInfo] = None
    notes: List[str] = Field(default_factory=list)


class EntityResolver:
    """Deterministic entity resolver for chat queries."""

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db

    def resolve(
        self,
        message: str,
        page_district: Optional[str] = None,
        page_habitation_id: Optional[int] = None,
        page_site_id: Optional[int] = None,
    ) -> ResolvedEntities:
        """Resolves entities from message text and page context with strict precedence."""
        entities = ResolvedEntities()
        text_lower = message.lower()

        # ---------------------------------------------------------------------
        # 1. District Resolution
        # ---------------------------------------------------------------------
        # We search for all district names and aliases, tracking their first appearance
        district_matches: List[tuple[int, str]] = []

        # Canonical names
        for d in CANONICAL_DISTRICTS:
            pattern = rf"\b{re.escape(d.lower())}\b"
            for match in re.finditer(pattern, text_lower):
                district_matches.append((match.start(), d))

        # Aliases / typos
        for alias, target in DISTRICT_ALIASES.items():
            pattern = rf"\b{re.escape(alias)}\b"
            for match in re.finditer(pattern, text_lower):
                district_matches.append((match.start(), target))

        # Sort by order of appearance in the user message
        district_matches.sort(key=lambda x: x[0])
        seen_districts: Set[str] = set()
        resolved_districts: List[str] = []
        for _, dist in district_matches:
            if dist not in seen_districts:
                seen_districts.add(dist)
                resolved_districts.append(dist)

        # Precedence: Explicit message district > Page context district
        if resolved_districts:
            entities.districts = resolved_districts
            entities.district_source = "message"
        elif page_district and page_district.strip():
            entities.districts = [canonical_district_name(page_district)]
            entities.district_source = "page"

        # District-specific operational notes (§2.1)
        for d in entities.districts:
            if d.lower() == "leh":
                entities.notes.append("Leh district has no habitations loaded in the database.")
            elif d.lower() == "srinagar":
                entities.notes.append("Srinagar admin boundary has no state column in admin_boundary.")

        # ---------------------------------------------------------------------
        # 2. Candidate Sites first, so "site #1752" is never read as habitation #1752
        # ---------------------------------------------------------------------
        found_site_ids: List[int] = []
        for match in re.finditer(r"\b(?:candidate\s+site|site|parcel)\s+#?(\d+)\b", text_lower):
            found_site_ids.append(int(match.group(1)))
        masked_text = re.sub(r"\b(?:candidate\s+site|site|parcel)\s+#?\d+\b", " ", text_lower)

        # ---------------------------------------------------------------------
        # 3. Habitation Resolution
        # ---------------------------------------------------------------------
        # Numeric ids: "habitation 775", "village #99", bare "#775". "Settlement 042" is a generic NAME, not an id.
        found_hab_ids: List[int] = []
        for pat in (r"\b(?:habitation|village)\s+#?(\d+)\b", r"#(\d+)\b"):
            for match in re.finditer(pat, masked_text):
                found_hab_ids.append(int(match.group(1)))

        found_generic_names: List[str] = [
            m.group(1).title() for m in re.finditer(r"\b(settlement\s+\d+)\b", masked_text)
        ]

        found_real_names: List[str] = []
        for real_name, default_dist in KNOWN_REAL_HABITATIONS.items():
            # A district name is not a habitation name unless the user says "village <name>"
            if real_name.title() in resolved_districts and not re.search(
                rf"\b(?:village|town|habitation)\s+{re.escape(real_name)}\b", text_lower
            ):
                continue
            if re.search(rf"\b{re.escape(real_name)}\b", text_lower):
                found_real_names.append(real_name.title())
                # With no district named in the message, a unique real name determines the district
                if not resolved_districts:
                    entities.districts = [default_dist]
                    entities.district_source = "message"

        entities.habitation_names = list(dict.fromkeys(found_real_names + found_generic_names))
        entities.habitation_ids = list(dict.fromkeys(found_hab_ids))
        entities.context_habitation_id = page_habitation_id
        entities.context_site_id = page_site_id
        entities.site_ids = list(dict.fromkeys(found_site_ids))

        # ---------------------------------------------------------------------
        # 4. Deictic references ("this village", "this site"): page context may resolve them, else clarify
        # ---------------------------------------------------------------------
        vague_village = bool(
            re.search(r"\b(?:this|that|the\s+selected|the\s+current)\s+(?:village|habitation|settlement)\b|\bthe\s+(?:village|habitation)\b", text_lower)
            and not entities.habitation_ids
            and not entities.habitation_names
        )
        vague_site = bool(
            re.search(r"\b(?:this|that|the\s+selected|the\s+current)\s+(?:candidate\s+)?(?:site|parcel)\b", text_lower)
            and not entities.site_ids
        )
        if vague_village:
            if page_habitation_id is not None:
                entities.habitation_ids = [page_habitation_id]
                entities.notes.append("'this village' resolved to the habitation selected on the page.")
            else:
                entities.ambiguity = AmbiguityInfo(
                    entity_type="habitation",
                    query="this village",
                    message="Please specify the habitation ID or village name to check its priority rationale.",
                )
        if vague_site:
            if page_site_id is not None:
                entities.site_ids = [page_site_id]
                entities.notes.append("'this site' resolved to the candidate site selected on the page.")
            elif entities.ambiguity is None:
                entities.ambiguity = AmbiguityInfo(
                    entity_type="site",
                    query="this site",
                    message="Please specify the candidate site ID you mean.",
                )

        # ---------------------------------------------------------------------
        # 5. Generic "Settlement NNN" names exist in several districts (§2.4): resolve through the database,
        #    scoped by the district when one is known, otherwise ask. Never guess and never invent candidates.
        # ---------------------------------------------------------------------
        if found_generic_names and entities.ambiguity is None:
            self._resolve_generic_names(entities, found_generic_names, entities.districts)

        # ---------------------------------------------------------------------
        # 6. Year Resolution (Stats & Historical Queries)
        # ---------------------------------------------------------------------
        years_found = [int(m.group(1)) for m in re.finditer(r"\b(19\d\d|20\d\d)\b", text_lower)]
        entities.years = list(dict.fromkeys(years_found))

        return entities

    def _resolve_generic_names(
        self,
        entities: ResolvedEntities,
        names: List[str],
        scope_districts: List[str],
    ) -> None:
        """Resolves generic settlement names to a habitation id, or sets an ambiguity/clarification."""
        scope = scope_districts[0] if len(scope_districts) == 1 else None
        for name in names:
            candidates = self._lookup_habitations_by_name(name, scope)
            if candidates is None:
                # Database unavailable: without a district we cannot tell which settlement is meant.
                if scope is None:
                    entities.ambiguity = AmbiguityInfo(
                        entity_type="habitation",
                        query=name,
                        message=(
                            f"'{name}' is a generic settlement name used in several districts. "
                            f"Please give the district (for example '{name} in Dholpur') or the habitation ID."
                        ),
                    )
                    return
                continue  # district known but unverified: keep the name, tools will search within the district
            if len(candidates) == 0:
                where = f"in {scope}" if scope else "in the database"
                entities.notes.append(f"No habitation named '{name}' was found {where}.")
            elif len(candidates) == 1:
                cand = candidates[0]
                entities.habitation_ids = list(dict.fromkeys(entities.habitation_ids + [int(cand["id"])]))
                if not entities.districts:
                    entities.districts = [str(cand["district_name"])]
                    entities.district_source = "message"
            else:
                cand_summaries = [
                    f"#{c['id']} in {c['district_name']} ({tier_label(c.get('tier'), scored=bool(c.get('scored', True)))}, "
                    f"population {int(c['population']):,})"
                    for c in candidates
                ]
                entities.ambiguity = AmbiguityInfo(
                    entity_type="habitation",
                    query=name,
                    candidates=candidates,
                    message=f"'{name}' matches more than one habitation. Please say which one you mean:\n- "
                    + "\n- ".join(cand_summaries),
                )
                return

    def _lookup_habitations_by_name(self, name: str, district: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """Habitations with this exact name (optionally within one district).

        Returns ``None`` when the database is unavailable or the query fails, so callers can tell "no rows"
        from "could not look".
        """
        if not self.db:
            return None
        try:
            where_district = "AND LOWER(ab.name) = LOWER(:d)" if district else ""
            sql = text(f"""
                SELECT h.id, h.name, ab.name AS district_name, hr.tier,
                       (hr.habitation_id IS NOT NULL) AS scored,
                       COALESCE(h.population, 0) AS population
                FROM habitation h
                JOIN admin_boundary ab ON h.admin_id = ab.id
                LEFT JOIN habitation_risk hr ON h.id = hr.habitation_id
                WHERE LOWER(h.name) = LOWER(:n) {where_district}
                ORDER BY ab.name, h.id
                LIMIT 10;
            """)
            params: Dict[str, Any] = {"n": name}
            if district:
                params["d"] = district
            return [dict(r) for r in self.db.execute(sql, params).mappings().all()]
        except Exception as e:
            logger.warning("Failed to look up habitations named %r: %s", name, e)
            return None
