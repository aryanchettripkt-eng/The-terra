"""Unit tests for DataTrustContext and SchemaCapabilities (§2, §4.2)."""

import pytest
from unittest.mock import MagicMock
from api.services.chat.trust import (
    DataTrustContext,
    DistrictTrustMetrics,
    SchemaCapabilities,
    build_compact_context_block,
    fetch_data_trust_context,
    fetch_district_trust_metrics,
    probe_schema_capabilities,
)


def test_schema_capabilities_probing():
    """Probes runtime database schema capabilities gracefully."""
    mock_db = MagicMock()
    # Mocking information_schema query to report applied columns
    mock_db.execute.return_value.fetchall.return_value = [("hazard_regime",), ("relocation_pathway",)]

    caps = probe_schema_capabilities(mock_db)
    assert caps.has_habitation_regime_cols is True
    assert caps.has_pathway_col is True


def test_synthetic_urgent_detection_by_district():
    """Wayanad and Kodagu must report urgent_synthetic=True, Barpeta and Dholpur False (§2.3)."""
    # Wayanad: all urgent habitations are synthetic demo data
    wayanad = fetch_district_trust_metrics(None, "Wayanad")
    assert wayanad.urgent_synthetic is True
    assert wayanad.habitations_total == 279
    assert wayanad.tier_counts.get("immediate") == 2
    assert wayanad.tier_counts.get("short_term") == 2

    # Kodagu: urgent row is synthetic
    kodagu = fetch_district_trust_metrics(None, "Kodagu")
    assert kodagu.urgent_synthetic is True
    assert kodagu.tier_counts.get("immediate") == 1

    # Barpeta: derived pipeline data
    barpeta = fetch_district_trust_metrics(None, "Barpeta")
    assert barpeta.urgent_synthetic is False
    assert barpeta.tier_counts.get("short_term") == 16
    assert barpeta.regime_available is True  # Regimes exist for Barpeta

    # Dholpur: 0 urgent, 117 medium-term, 77 monitoring
    dholpur = fetch_district_trust_metrics(None, "Dholpur")
    assert dholpur.urgent_synthetic is False
    assert dholpur.tier_counts.get("immediate", 0) == 0
    assert dholpur.tier_counts.get("short_term", 0) == 0
    assert dholpur.tier_counts.get("medium_term") == 117
    assert dholpur.tier_counts.get("monitoring") == 77


def test_leh_trust_metrics():
    """Leh district has 0 habitations and flood_model_status='not_computed' (§2.1, §2.6)."""
    leh = fetch_district_trust_metrics(None, "Leh")
    assert leh.habitations_total == 0
    assert leh.flood_model_status == "not_computed"
    assert leh.sites_total == 0


def test_compact_context_block_formatting():
    """Verifies compact context block format for prompt injection (§7)."""
    trust = fetch_data_trust_context(None, ["Barpeta", "Wayanad"])
    block = build_compact_context_block(trust, ["Barpeta", "Wayanad"])

    assert "Barpeta: 253 habitations;" in block
    assert "16 short_term (derived)" in block
    assert "98 medium_term (derived)" in block
    assert "139 monitoring" in block
    assert "with regimes" in block

    assert "Wayanad: 279 habitations;" in block
    assert "2 immediate (synthetic)" in block
    assert "2 short_term (synthetic)" in block
