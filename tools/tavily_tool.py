from __future__ import annotations

import os
from tavily import TavilyClient, MissingAPIKeyError, InvalidAPIKeyError, UsageLimitExceededError

_client = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _client


def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "advanced",
    include_raw_content: bool = False,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """
    Returns list of dicts, each with keys: url, title, content, score, raw_content (if requested).
    search_depth: "basic" (faster, cheaper) or "advanced" (deeper, more relevant — use this).
    include_raw_content: set True to get full page text in each result's raw_content field.
    include_domains: whitelist of domains to restrict results to (general topic only).
    exclude_domains: blacklist of domains to suppress from results.
    """
    try:
        kwargs: dict = dict(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_raw_content=include_raw_content,
            include_answer=False,
        )
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains
        response = _get_client().search(**kwargs)
        return response["results"]
    except MissingAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY not set in environment")
    except InvalidAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY is invalid")
    except UsageLimitExceededError:
        raise RuntimeError("Tavily usage limit exceeded — check account credits")
    except Exception as e:
        raise RuntimeError(f"Tavily search failed: {e}")


def extract_url(url: str) -> str:
    """
    Fetches and returns the full cleaned text of a specific URL.
    Use this when search gives a URL and you need the complete page content.
    """
    try:
        response = _get_client().extract(url)
        return response["results"][0].get("raw_content", "")
    except MissingAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY not set in environment")
    except InvalidAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY is invalid")
    except UsageLimitExceededError:
        raise RuntimeError("Tavily usage limit exceeded — check account credits")
    except Exception as e:
        raise RuntimeError(f"Tavily extract failed: {e}")


def extract_urls_bulk(
    urls: list[str],
    extract_depth: str = "advanced",
    query: str | None = None,
) -> list[dict]:
    """
    Extract full content from multiple URLs in a single Tavily call (up to 20 URLs).
    Uses extract_depth="advanced" by default to capture embedded tables and JS-rendered pages.
    Returns list of {url, raw_content} dicts for successful extractions.
    query: optional hint for relevance-reranking the extracted chunks.
    """
    if not urls:
        return []
    try:
        kwargs: dict = dict(
            urls=urls[:20],
            extract_depth=extract_depth,
            format="markdown",
        )
        if query:
            kwargs["query"] = query
        response = _get_client().extract(**kwargs)
        return response.get("results", [])
    except MissingAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY not set in environment")
    except InvalidAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY is invalid")
    except UsageLimitExceededError:
        raise RuntimeError("Tavily usage limit exceeded — check account credits")
    except Exception as e:
        raise RuntimeError(f"Tavily bulk extract failed: {e}")


def crawl_site(
    url: str,
    instructions: str | None = None,
    max_depth: int = 2,
    limit: int = 10,
) -> list[dict]:
    """
    Crawl a site from a root URL using breadth-first traversal.
    Returns list of {url, raw_content} dicts for all crawled pages.
    Use for protocols.io and openwetware pages where method detail is in subpages.
    instructions: natural-language guidance for which pages to prioritize.
    """
    try:
        kwargs: dict = dict(
            url=url,
            max_depth=max_depth,
            max_breadth=5,
            limit=limit,
            extract_depth="advanced",
            format="markdown",
        )
        if instructions:
            kwargs["instructions"] = instructions
        response = _get_client().crawl(**kwargs)
        return response.get("results", [])
    except MissingAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY not set in environment")
    except InvalidAPIKeyError:
        raise RuntimeError("TAVILY_API_KEY is invalid")
    except UsageLimitExceededError:
        raise RuntimeError("Tavily usage limit exceeded — check account credits")
    except Exception as e:
        raise RuntimeError(f"Tavily crawl failed: {e}")
