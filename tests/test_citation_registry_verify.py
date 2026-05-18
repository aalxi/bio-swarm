"""Whitespace normalization + three-state verification.

These tests do NOT hit the network — they call _normalize directly and stub
the HTTP fetch. The network-hitting test lives in test_citations_are_real.py.
"""
from tools.citation_registry import _normalize, _verify_one, Citation


def test_normalize_collapses_whitespace_and_smart_chars():
    raw = "Inhibition testing­ (Cq dilutions,​ spike or other)"
    assert _normalize(raw) == "inhibition testing (cq dilutions, spike or other)"


def test_normalize_handles_smart_quotes_and_dashes():
    raw = "“matrix–specific”  protocols"
    assert _normalize(raw) == '"matrix-specific" protocols'


def test_verify_one_reports_verified_when_quoted_text_present(monkeypatch):
    citation = Citation(
        key="x", citation_type="paper", full_text="x",
        url="http://example.com", quoted_text="needle in haystack",
    )

    def fake_fetch(url, timeout):
        return "lots of words and a needle in haystack hidden inside"

    monkeypatch.setattr("tools.citation_registry._fetch", fake_fetch)
    assert _verify_one(citation, timeout_s=1.0) == "verified"


def test_verify_one_reports_content_mismatch_when_text_absent(monkeypatch):
    citation = Citation(
        key="x", citation_type="paper", full_text="x",
        url="http://example.com", quoted_text="absent phrase",
    )
    monkeypatch.setattr(
        "tools.citation_registry._fetch", lambda u, t: "totally unrelated"
    )
    assert _verify_one(citation, timeout_s=1.0) == "content_mismatch"


def test_verify_one_reports_unreachable_on_network_error(monkeypatch):
    citation = Citation(
        key="x", citation_type="paper", full_text="x",
        url="http://example.com", quoted_text="anything",
    )

    def boom(url, timeout):
        raise OSError("network down")

    monkeypatch.setattr("tools.citation_registry._fetch", boom)
    assert _verify_one(citation, timeout_s=1.0) == "unreachable"


def test_verify_one_skips_when_no_url():
    citation = Citation(key="x", citation_type="common_practice", full_text="x")
    assert _verify_one(citation, timeout_s=1.0) == "verified"
