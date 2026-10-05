"""Tier accounting, data-quality labelling and prompt hygiene for the relocation assistant.

Fixtures mirror the live distribution observed on 2026-10-05 (Wayanad: all urgent rows synthetic; Dholpur: no
urgent rows, many monitoring rows) without touching a database or the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.services import chat_assistant_service as svc_module
from api.services.chat_assistant_service import SYSTEM_PROMPT, RelocationChatAssistantService
from api.services.chat_triage import (
    MONITORING_KEY,
    MONITORING_NOTE,
    SYNTHETIC_NOTICE,
    TIER_ORDER,
    quality_provenance,
    render_tier_table,
    summarize_by_district,
    summarize_tier_rows,
    tier_label,
)
from core.config import settings
from core.schemas.chat import ChatMessage, RelocationChatRequest


@pytest.fixture(autouse=True)
def no_live_groq_key():
    with patch.object(settings, "GROQ_API_KEY", None):
        yield


def row(tier, quality, habs, pop, hh, *, scored=True, district="Wayanad"):
    return {
        "district_name": district,
        "tier": tier,
        "scored": scored,
        "data_quality": quality,
        "habitations": habs,
        "population": pop,
        "households": hh,
    }


WAYANAD_ROWS = [
    row("immediate", "synthetic", 2, 5990, 1350),
    row("short_term", "synthetic", 2, 24000, 5350),
    row("medium_term", "derived", 8, 3068, 682),
    row(None, "derived", 265, 864000, 192000),
    row(None, "synthetic", 2, 2800, 711),
]
DHOLPUR_ROWS = [
    row("medium_term", "derived", 117, 682076, 151573, district="Dholpur"),
    row(None, "derived", 77, 399980, 88887, district="Dholpur"),
]


class TestSummarizeTierRows:
    def test_every_tier_is_listed_in_order_including_zero_counts(self):
        summary = summarize_tier_rows(DHOLPUR_ROWS)
        assert [t["tier"] for t in summary["tiers"]] == list(TIER_ORDER)
        by_tier = {t["tier"]: t for t in summary["tiers"]}
        assert by_tier["immediate"]["habitations"] == 0
        assert by_tier["short_term"]["habitations"] == 0
        assert by_tier["medium_term"]["habitations"] == 117
        assert by_tier[MONITORING_KEY]["habitations"] == 77

    def test_urgent_totals_cover_only_immediate_and_short_term(self):
        summary = summarize_tier_rows(WAYANAD_ROWS)
        assert summary["urgent"]["habitations"] == 4
        assert summary["urgent"]["population"] == 29990
        assert summary["urgent"]["households"] == 6700
        # urgent figures must not be mistaken for the district total
        assert summary["totals"]["population"] == 5990 + 24000 + 3068 + 864000 + 2800

    def test_no_urgent_rows_is_an_explicit_zero_not_a_missing_value(self):
        summary = summarize_tier_rows(DHOLPUR_ROWS)
        assert summary["urgent"]["population"] == 0
        assert summary["totals"]["population"] == 682076 + 399980
        # ...and the exposure that sits outside the urgent tiers is still visible
        assert {t["tier"]: t["population"] for t in summary["tiers"]}["medium_term"] == 682076

    def test_synthetic_rows_are_flagged_and_noticed(self):
        summary = summarize_tier_rows(WAYANAD_ROWS)
        assert summary["has_synthetic"] is True
        assert summary["urgent"]["has_synthetic"] is True
        assert SYNTHETIC_NOTICE in summary["notes"]
        by_tier = {t["tier"]: t for t in summary["tiers"]}
        assert by_tier["immediate"]["data_quality"] == {"synthetic": 2}
        assert by_tier[MONITORING_KEY]["data_quality"] == {"derived": 265, "synthetic": 2}

    def test_derived_only_district_has_no_synthetic_notice(self):
        summary = summarize_tier_rows(DHOLPUR_ROWS)
        assert summary["has_synthetic"] is False
        assert SYNTHETIC_NOTICE not in summary["notes"]

    def test_null_tier_is_monitoring_not_missing_data(self):
        summary = summarize_tier_rows(DHOLPUR_ROWS)
        monitoring = next(t for t in summary["tiers"] if t["tier"] == MONITORING_KEY)
        assert monitoring["stored_as_null"] is True
        assert "Monitoring" in monitoring["label"]
        assert MONITORING_NOTE in summary["notes"]

    def test_habitation_without_a_risk_row_is_not_scored_and_not_monitoring(self):
        rows = DHOLPUR_ROWS + [row(None, "unknown", 3, 900, 200, scored=False, district="Dholpur")]
        summary = summarize_tier_rows(rows)
        by_tier = {t["tier"]: t for t in summary["tiers"]}
        assert by_tier["unscored"]["habitations"] == 3
        assert by_tier[MONITORING_KEY]["habitations"] == 77  # unchanged: a data gap is not "monitoring"

    def test_no_rows_means_district_not_found(self):
        summary = summarize_tier_rows([])
        assert summary["found"] is False
        assert summary["totals"]["habitations"] == 0

    def test_summarize_by_district_keeps_districts_apart(self):
        result = summarize_by_district(WAYANAD_ROWS + DHOLPUR_ROWS)
        assert set(result) == {"Wayanad", "Dholpur"}
        assert result["Wayanad"]["urgent"]["population"] == 29990
        assert result["Dholpur"]["urgent"]["population"] == 0


class TestLabelsAndTable:
    def test_labels(self):
        assert tier_label("immediate") == "Immediate"
        assert tier_label(None) == "Monitoring (no relocation tier)"
        assert tier_label(None, scored=False) == "Not scored (no triage result)"

    def test_quality_provenance_never_authoritative_for_synthetic(self):
        assert quality_provenance(True) == "synthetic_demo"
        assert quality_provenance(False) == "authoritative"

    def test_table_shows_zero_rows_and_data_quality(self):
        table = render_tier_table(summarize_tier_rows(WAYANAD_ROWS))
        assert "| **Immediate** |" in table
        assert "| **Mitigate in situ** |" in table  # zero row still shown
        assert "synthetic 2" in table
        assert "**All habitations**" in table


class TestPromptHygiene:
    @pytest.mark.parametrize("figure", ["24,759", "29,990", "4,100", "899,858", "5,502", "6,700"])
    def test_no_hardcoded_district_figures(self, figure):
        assert figure not in SYSTEM_PROMPT

    def test_gate_thresholds_come_from_constants(self):
        assert "< 0.25" in SYSTEM_PROMPT and "< 15 degrees" in SYSTEM_PROMPT

    def test_does_not_tell_the_model_to_hide_gaps_or_make_recommendations(self):
        lowered = SYSTEM_PROMPT.lower()
        assert "never state that population is" not in lowered
        assert "data not disclosed" not in lowered
        assert "operational recommendations" not in lowered
        assert "legal resettlement advisor" not in lowered

    def test_prompt_states_the_data_quality_and_monitoring_rules(self):
        assert "synthetic" in SYSTEM_PROMPT
        assert "Monitoring" in SYSTEM_PROMPT and "NOT a finding that the settlement is safe" in SYSTEM_PROMPT
        assert "every tier" in SYSTEM_PROMPT.lower()


def make_service() -> RelocationChatAssistantService:
    return RelocationChatAssistantService(MagicMock())


def wayanad_urgent_payload():
    summary = summarize_tier_rows(WAYANAD_ROWS)
    return {
        "district": "Wayanad",
        "district_found": True,
        "urgent_count": 4,
        "total_population_at_risk": 29990,
        "total_households_at_risk": 6700,
        "urgent_has_synthetic": True,
        "has_synthetic": True,
        "tier_summary": summary["tiers"],
        "tier_totals": summary["totals"],
        "notes": summary["notes"],
        "tier_breakdown": [],
        "urgent_habitations": [
            {
                "id": 1, "name": "Mundakkai", "population": 5990, "households": 1350, "tier": "immediate",
                "hazard_intensity": 0.9, "dominant_hazard": "landslide", "data_quality": "synthetic",
            }
        ],
    }


class TestListUrgentVillages:
    def test_returns_full_tier_summary_and_synthetic_flag(self):
        service = make_service()
        urgent_rows = [
            {"id": 1, "name": "A", "population": 5990, "households": 1350, "tier": "immediate",
             "hazard_intensity": 0.9, "prz_overlap_pct": 60.0, "priority_score": 0.8, "caseload_score": 1.0,
             "dominant_hazard": "landslide", "data_quality": "synthetic"},
        ]
        service.db.execute.return_value.mappings.return_value.all.return_value = urgent_rows
        with patch.object(svc_module, "fetch_tier_rows", return_value=WAYANAD_ROWS):
            result = service.list_urgent_villages("Wayanad")
        assert result["district_found"] is True
        assert result["urgent_has_synthetic"] is True
        assert [t["tier"] for t in result["tier_summary"]] == list(TIER_ORDER)
        assert result["total_population_at_risk"] == 5990  # urgent rows returned by the query only
        assert any("Urgent = immediate + short-term" in n for n in result["notes"])

    def test_unknown_district_is_reported_not_zeroed(self):
        service = make_service()
        service.db.execute.return_value.mappings.return_value.all.return_value = []
        with patch.object(svc_module, "fetch_tier_rows", return_value=[]):
            result = service.list_urgent_villages("Leh")
        assert result["district_found"] is False
        assert "No habitations are loaded" in result["notes"][0]


class TestDataNotices:
    def test_appends_missing_tiers_and_synthetic_notice(self):
        service = make_service()
        payload = wayanad_urgent_payload()
        reply = "There are 4 urgent habitations in the short-term and immediate tiers."
        out = service._append_data_notices(reply, {"list_urgent_villages": payload})
        assert out.startswith(reply)
        assert "Complete tier breakdown (Wayanad)" in out
        assert "Monitoring (no relocation tier)" in out
        assert SYNTHETIC_NOTICE in out

    def test_leaves_a_complete_reply_untouched(self):
        service = make_service()
        payload = wayanad_urgent_payload()
        reply = (
            "Immediate, short-term, medium-term and monitoring habitations are all listed; "
            "the urgent rows are synthetic demo data."
        )
        assert service._append_data_notices(reply, {"list_urgent_villages": payload}) == reply

    def test_synthetic_flag_is_found_inside_nested_results(self):
        service = make_service()
        nested = {"habitation": {"id": 1, "data_quality": "synthetic"}}
        out = service._append_data_notices("Tier: immediate.", {"get_village_priority": nested})
        assert SYNTHETIC_NOTICE in out

    def test_no_notice_when_all_data_is_derived(self):
        service = make_service()
        nested = {"habitation": {"id": 1, "data_quality": "derived"}}
        assert service._append_data_notices("Tier: short-term.", {"get_village_priority": nested}) == "Tier: short-term."

    def test_finalize_handles_empty_model_content(self):
        service = make_service()
        assert service._finalize_reply(None, [], {}) == ""


class TestFallbackRenderers:
    def test_district_overview_lists_every_tier_and_has_no_hardcoded_guidance(self):
        service = make_service()
        service.list_urgent_villages = MagicMock(return_value=wayanad_urgent_payload())
        req = RelocationChatRequest(
            messages=[ChatMessage(role="user", content="How many people are in danger in Wayanad?")],
            district="Wayanad",
        )
        res = service._offline_fallback_synthesis(req)
        assert res.fallback_used is True
        for label in ("Immediate", "Short-term", "Medium-term", "Monitoring (no relocation tier)"):
            assert label in res.reply
        assert SYNTHETIC_NOTICE in res.reply
        assert "Operational Guidance" not in res.reply
        assert "pre-monsoon" not in res.reply

    def test_district_with_no_habitations_says_so(self):
        service = make_service()
        service.list_urgent_villages = MagicMock(
            return_value={"district": "Leh", "district_found": False, "urgent_count": 0,
                          "total_population_at_risk": 0, "total_households_at_risk": 0,
                          "urgent_habitations": [], "notes": ["No habitations are loaded for district 'Leh'."]}
        )
        req = RelocationChatRequest(
            messages=[ChatMessage(role="user", content="How many people are in danger in Leh?")],
            district="Leh",
        )
        res = service._offline_fallback_synthesis(req)
        assert "No habitations are loaded" in res.reply
        assert "0 persons" not in res.reply

    def test_cross_district_uses_data_not_hardcoded_findings(self):
        service = make_service()
        service.get_district_hazard_summary = MagicMock(
            return_value={
                "districts": [
                    {"district_name": "Dholpur", "urgent_habitations": 0, "urgent_population": 0, "urgent_households": 0,
                     "immediate_population": 0, "short_term_population": 0, "medium_term_habitations": 117,
                     "medium_term_population": 682076, "monitoring_habitations": 77, "monitoring_population": 399980,
                     "urgent_has_synthetic": False},
                    {"district_name": "Wayanad", "urgent_habitations": 4, "urgent_population": 29990, "urgent_households": 6700,
                     "immediate_population": 5990, "short_term_population": 24000, "medium_term_habitations": 8,
                     "medium_term_population": 3068, "monitoring_habitations": 267, "monitoring_population": 866800,
                     "urgent_has_synthetic": True},
                ],
                "total_districts": 2,
                "total_urgent_population": 29990,
                "total_urgent_households": 6700,
                "urgent_has_synthetic": True,
                "has_synthetic": True,
                "notes": [MONITORING_NOTE, SYNTHETIC_NOTICE],
            }
        )
        req = RelocationChatRequest(
            messages=[ChatMessage(role="user", content="Which district has the most people in danger?")],
        )
        res = service._offline_fallback_synthesis(req)
        assert "| **Dholpur** | 0 |" in res.reply  # a district with no urgent rows is still listed
        assert "682,076" in res.reply and "synthetic demo data" in res.reply
        assert "Key Operational Findings" not in res.reply

    def test_village_with_no_tier_is_monitoring_not_none(self):
        service = make_service()
        service.get_village_priority = MagicMock(
            return_value={
                "found": True,
                "has_synthetic": False,
                "notes": [MONITORING_NOTE],
                "habitation": {
                    "id": 99, "name": "Settlement 099", "district_name": "Dholpur", "tier": None,
                    "tier_label": tier_label(None), "population": 1200, "households": 260, "hazard_intensity": 0.41,
                    "prz_overlap_pct": 0.0, "priority_score": 0.1, "caseload_score": 120.0, "dominant_hazard": None,
                    "triage_rationale": "Unclassified / Monitoring: Settlement does not meet criteria for permanent relocation.",
                    "data_quality": "derived",
                },
            }
        )
        req = RelocationChatRequest(
            messages=[ChatMessage(role="user", content="Why is village #99 a priority?")], district="Dholpur"
        )
        res = service._offline_fallback_synthesis(req)
        assert "Monitoring (no relocation tier)" in res.reply
        assert "NONE" not in res.reply
        assert "not a finding that the settlement is safe" in res.reply


class TestCitations:
    def test_synthetic_results_are_not_cited_as_authoritative(self):
        service = make_service()
        service.list_urgent_villages = MagicMock(return_value=wayanad_urgent_payload())
        _, citations, _ = service._execute_tool("list_urgent_villages", {"district": "Wayanad"})
        assert citations[0].provenance == "synthetic_demo"
        assert "synthetic" in (citations[0].metric or "")

    def test_derived_results_stay_authoritative(self):
        service = make_service()
        payload = wayanad_urgent_payload()
        payload["urgent_has_synthetic"] = False
        service.list_urgent_villages = MagicMock(return_value=payload)
        _, citations, _ = service._execute_tool("list_urgent_villages", {"district": "Barpeta"})
        assert citations[0].provenance == "authoritative"
