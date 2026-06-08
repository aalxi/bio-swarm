"""enricher._build_queries — query template expansion.

This is the only enricher function that the PIE Tavily budget depends on:
  - 2 queries per gap, never more (budget cap)
  - search_hint and assay_type are substituted; empty quoted strings are stripped
  - unknown fields fall back to generic templates (not a crash)

Each test catches a different way the query budget can blow up or the queries
can become useless.
"""
from agents.enricher import _build_queries


def test_returns_at_most_two_queries_per_gap():
    """Enricher's MAX_QUERIES / 2 budget split assumes this cap."""
    gap = {"field": "volume_ul", "search_hint": "qPCR Cq dilution"}
    protocol = {"protocol_name": "Some long protocol name with many words"}
    assert len(_build_queries(gap, protocol)) <= 2


def test_unknown_field_uses_generic_fallback_template():
    """Adding a new schema field must not crash query generation."""
    gap = {"field": "novel_field_not_in_templates", "search_hint": "hint"}
    queries = _build_queries(gap, {"protocol_name": "p"})
    assert queries  # non-empty
    assert all("hint" in q for q in queries)


def test_substitutes_search_hint_into_known_templates():
    gap = {"field": "volume_ul", "search_hint": "qPCR master mix"}
    queries = _build_queries(gap, {"protocol_name": "Whatever"})
    assert any("qPCR master mix" in q for q in queries)


def test_substitutes_assay_type_from_first_four_protocol_name_words():
    gap = {"field": "pipettes", "search_hint": ""}
    protocol = {"protocol_name": "TaqMan qPCR for SARS-CoV-2 detection (Liu et al. 2020)"}
    queries = _build_queries(gap, protocol)
    joined = " ".join(queries)
    assert "TaqMan qPCR for SARS-CoV-2" in joined


def test_strips_empty_quoted_strings_when_search_hint_is_blank():
    """An empty search_hint must not leave '""' garbage in the query string —
    Tavily treats those as exact-match-empty and returns nothing."""
    gap = {"field": "volume_ul", "search_hint": ""}
    queries = _build_queries(gap, {"protocol_name": "x"})
    assert all('""' not in q for q in queries)


def test_falls_back_to_search_hint_when_protocol_name_missing():
    """assay_type derives from protocol_name OR search_hint when name is empty."""
    gap = {"field": "pipettes", "search_hint": "qPCR inhibition"}
    queries = _build_queries(gap, {"protocol_name": ""})
    joined = " ".join(queries)
    assert "qPCR inhibition" in joined
