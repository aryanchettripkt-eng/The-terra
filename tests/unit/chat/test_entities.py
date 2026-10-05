"""Unit tests for deterministic EntityResolver in SETU-DRR chat orchestrator (§4.3)."""

import pytest
from unittest.mock import MagicMock
from api.services.chat.entities import EntityResolver, ResolvedEntities, CANONICAL_DISTRICTS


def test_canonical_districts_list():
    """Verifies all 8 canonical districts from §2.1 are recognized."""
    expected = {"Barpeta", "Dholpur", "Kodagu", "Morena", "Rudraprayag", "Srinagar", "Wayanad", "Leh"}
    assert set(CANONICAL_DISTRICTS) == expected


def test_district_extraction_and_alias_correction():
    """Verifies typo correction and alias mapping."""
    resolver = EntityResolver()

    # Typo: wayand -> Wayanad
    res1 = resolver.resolve("What is the flood exposure in wayand?")
    assert res1.districts == ["Wayanad"]

    # Typo: waynad -> Wayanad
    res2 = resolver.resolve("Show me habitations at risk in waynad")
    assert res2.districts == ["Wayanad"]

    # Alias: coorg -> Kodagu
    res3 = resolver.resolve("How many people at risk in coorg?")
    assert res3.districts == ["Kodagu"]

    # Typo: barpatta -> Barpeta
    res4 = resolver.resolve("Overview of barpatta district")
    assert res4.districts == ["Barpeta"]

    # Typo: rudra prayag -> Rudraprayag
    res5 = resolver.resolve("What is happening in rudra prayag?")
    assert res5.districts == ["Rudraprayag"]

    # Typo: srinager -> Srinagar
    res6 = resolver.resolve("Exposure in srinager")
    assert res6.districts == ["Srinagar"]


def test_multi_district_order_preservation():
    """Multi-district queries preserve exact order of appearance (§4.3)."""
    resolver = EntityResolver()

    res1 = resolver.resolve("Compare Barpeta and Wayanad")
    assert res1.districts == ["Barpeta", "Wayanad"]

    res2 = resolver.resolve("Compare Wayanad and Barpeta")
    assert res2.districts == ["Wayanad", "Barpeta"]

    res3 = resolver.resolve("Exposure across Dholpur, Morena and Kodagu")
    assert res3.districts == ["Dholpur", "Morena", "Kodagu"]


def test_precedence_message_over_page_context():
    """Explicit district in message takes precedence over page context district (§4.3)."""
    resolver = EntityResolver()

    # Message specifies Wayanad, page context has Barpeta
    res = resolver.resolve("What is the situation in Wayanad?", page_district="Barpeta")
    assert res.districts == ["Wayanad"]

    # Message has no district, page context district is used
    res_page = resolver.resolve("What is the situation here?", page_district="Morena")
    assert res_page.districts == ["Morena"]


def test_special_district_notes():
    """Leh and Srinagar have verified architectural caveats attached as operational notes (§2.1)."""
    resolver = EntityResolver()

    # Leh: 0 habitations loaded in database
    res_leh = resolver.resolve("How many villages are in Leh?")
    assert "Leh" in res_leh.districts
    assert any("no habitations loaded" in n.lower() for n in res_leh.notes)

    # Srinagar: admin boundary has no state column
    res_sri = resolver.resolve("Triage overview for Srinagar")
    assert "Srinagar" in res_sri.districts
    assert any("no state column" in n.lower() for n in res_sri.notes)


def test_habitation_id_and_real_names_extraction():
    """Extracts numeric habitation IDs and real village names (§2.4)."""
    resolver = EntityResolver()

    # Numeric ID with hash
    res1 = resolver.resolve("Why was village #775 prioritized?")
    assert 775 in res1.habitation_ids

    # Numeric ID without hash
    res2 = resolver.resolve("Show details for habitation 99")
    assert 99 in res2.habitation_ids

    # Real village name: Chooralmala
    res3 = resolver.resolve("Why is Chooralmala at extreme risk?")
    assert "Chooralmala" in res3.habitation_names
    assert "Wayanad" in res3.districts  # Inferred district from unique real name

    # Real village name: Howly
    res4 = resolver.resolve("Status of Howly village")
    assert "Howly" in res4.habitation_names
    assert "Barpeta" in res4.districts


def test_vague_village_reference_triggers_ambiguity():
    """Vague reference without ID or name triggers ambiguity clarification (§4.3)."""
    resolver = EntityResolver()

    res = resolver.resolve("Why is this village a priority?", page_district="Wayanad")
    assert res.ambiguity is not None
    assert res.ambiguity.is_ambiguous is True
    assert "specify the habitation" in res.ambiguity.message.lower()


def test_generic_settlement_without_district_asks_and_invents_no_candidates():
    """Without a district (and no database) a generic name triggers a clarification, never invented candidates."""
    res = EntityResolver().resolve("Tell me about Settlement 002")
    assert res.ambiguity is not None
    assert res.ambiguity.is_ambiguous is True
    assert res.ambiguity.candidates == []  # no fabricated ids/populations
    assert "Settlement 002" in res.ambiguity.message
    assert "district" in res.ambiguity.message.lower()
    assert res.habitation_ids == []


def test_generic_settlement_with_district_is_not_ambiguous_and_not_an_id():
    res = EntityResolver().resolve("Tell me about Settlement 002 in Morena")
    assert res.ambiguity is None
    assert "Morena" in res.districts
    assert "Settlement 002" in res.habitation_names
    assert res.habitation_ids == []  # the number in a name is not a habitation id


def test_candidate_site_and_year_extraction():
    """Extracts candidate site IDs and 4-digit years (§4.3)."""
    resolver = EntityResolver()

    res = resolver.resolve("What infrastructure is missing at Candidate Site #1752 from 2024 data?")
    assert 1752 in res.site_ids
    assert 2024 in res.years
