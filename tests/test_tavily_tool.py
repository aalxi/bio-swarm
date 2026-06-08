"""tavily_tool.py — zero coverage before this file. No network calls.

The tool wraps the third-party TavilyClient and translates its exceptions into
RuntimeError with stable messages. We test that translation and the argument
shaping, since callers (researcher, enricher) depend on both.
"""
import pytest
from tavily import InvalidAPIKeyError, MissingAPIKeyError, UsageLimitExceededError

from tools import tavily_tool


class FakeClient:
    """Test double that records calls and returns canned responses."""

    def __init__(self, search_response=None, extract_response=None, crawl_response=None,
                 raise_on=None):
        self.search_response = search_response or {"results": []}
        self.extract_response = extract_response or {"results": []}
        self.crawl_response = crawl_response or {"results": []}
        self.raise_on = raise_on
        self.search_calls = []
        self.extract_calls = []
        self.crawl_calls = []

    def search(self, **kwargs):
        if self.raise_on:
            raise self.raise_on
        self.search_calls.append(kwargs)
        return self.search_response

    def extract(self, *args, **kwargs):
        if self.raise_on:
            raise self.raise_on
        self.extract_calls.append((args, kwargs))
        return self.extract_response

    def crawl(self, **kwargs):
        if self.raise_on:
            raise self.raise_on
        self.crawl_calls.append(kwargs)
        return self.crawl_response


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    monkeypatch.setattr(tavily_tool, "_client", None)


def _install_fake(monkeypatch, fake):
    monkeypatch.setattr(tavily_tool, "_client", fake)


# ── search_web ───────────────────────────────────────────────────────────────


def test_search_web_returns_results_list(monkeypatch):
    fake = FakeClient(search_response={"results": [{"url": "u", "title": "t"}]})
    _install_fake(monkeypatch, fake)
    out = tavily_tool.search_web("query")
    assert out == [{"url": "u", "title": "t"}]


def test_search_web_passes_optional_domain_filters_only_when_provided(monkeypatch):
    """include_domains / exclude_domains are forwarded only when non-empty —
    enricher relies on this for open-access filtering."""
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.search_web("q", include_domains=["pmc.ncbi.nlm.nih.gov"])
    assert fake.search_calls[0]["include_domains"] == ["pmc.ncbi.nlm.nih.gov"]
    assert "exclude_domains" not in fake.search_calls[0]


def test_search_web_omits_domain_filters_when_none(monkeypatch):
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.search_web("q")
    assert "include_domains" not in fake.search_calls[0]
    assert "exclude_domains" not in fake.search_calls[0]


def test_search_web_translates_missing_api_key(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=MissingAPIKeyError()))
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY not set"):
        tavily_tool.search_web("q")


def test_search_web_translates_invalid_api_key(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=InvalidAPIKeyError("bad")))
    with pytest.raises(RuntimeError, match="invalid"):
        tavily_tool.search_web("q")


def test_search_web_translates_usage_limit(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=UsageLimitExceededError("over")))
    with pytest.raises(RuntimeError, match="usage limit"):
        tavily_tool.search_web("q")


def test_search_web_wraps_generic_exception(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=ConnectionError("dns")))
    with pytest.raises(RuntimeError, match="search failed"):
        tavily_tool.search_web("q")


# ── extract_url ──────────────────────────────────────────────────────────────


def test_extract_url_returns_raw_content_of_first_result(monkeypatch):
    fake = FakeClient(extract_response={"results": [{"raw_content": "PAGE TEXT"}]})
    _install_fake(monkeypatch, fake)
    assert tavily_tool.extract_url("http://x") == "PAGE TEXT"


def test_extract_url_returns_empty_string_when_field_missing(monkeypatch):
    """Tavily sometimes returns results without raw_content; callers expect ''."""
    fake = FakeClient(extract_response={"results": [{}]})
    _install_fake(monkeypatch, fake)
    assert tavily_tool.extract_url("http://x") == ""


def test_extract_url_wraps_exceptions(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=ConnectionError("boom")))
    with pytest.raises(RuntimeError, match="extract failed"):
        tavily_tool.extract_url("http://x")


# ── extract_urls_bulk ────────────────────────────────────────────────────────


def test_extract_urls_bulk_returns_empty_for_empty_input_without_api_call(monkeypatch):
    """No URLs → no billable API call. Guarded so enricher can shortcut."""
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    assert tavily_tool.extract_urls_bulk([]) == []
    assert fake.extract_calls == []


def test_extract_urls_bulk_truncates_to_20_urls(monkeypatch):
    """Tavily's per-call limit is 20; the wrapper enforces it client-side."""
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    urls = [f"http://u/{i}" for i in range(30)]
    tavily_tool.extract_urls_bulk(urls)
    _, kwargs = fake.extract_calls[0]
    assert len(kwargs["urls"]) == 20


def test_extract_urls_bulk_passes_query_when_provided(monkeypatch):
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.extract_urls_bulk(["http://x"], query="hint")
    _, kwargs = fake.extract_calls[0]
    assert kwargs["query"] == "hint"


def test_extract_urls_bulk_omits_query_when_none(monkeypatch):
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.extract_urls_bulk(["http://x"])
    _, kwargs = fake.extract_calls[0]
    assert "query" not in kwargs


# ── crawl_site ───────────────────────────────────────────────────────────────


def test_crawl_site_returns_results_list(monkeypatch):
    fake = FakeClient(crawl_response={"results": [{"url": "u", "raw_content": "x"}]})
    _install_fake(monkeypatch, fake)
    out = tavily_tool.crawl_site("http://root")
    assert out == [{"url": "u", "raw_content": "x"}]


def test_crawl_site_passes_instructions_only_when_provided(monkeypatch):
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.crawl_site("http://root", instructions="prioritize methods")
    assert fake.crawl_calls[0]["instructions"] == "prioritize methods"


def test_crawl_site_omits_instructions_when_none(monkeypatch):
    fake = FakeClient()
    _install_fake(monkeypatch, fake)
    tavily_tool.crawl_site("http://root")
    assert "instructions" not in fake.crawl_calls[0]


def test_crawl_site_wraps_exceptions(monkeypatch):
    _install_fake(monkeypatch, FakeClient(raise_on=RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="crawl failed"):
        tavily_tool.crawl_site("http://root")
