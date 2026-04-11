import os
from tavily import TavilyClient, MissingAPIKeyError, InvalidAPIKeyError, UsageLimitExceededError

_client = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _client


def search_web(query: str, max_results: int = 5, search_depth: str = "advanced") -> list[dict]:
    """
    Returns list of dicts, each with keys: url, title, content, score, raw_content (if requested).
    search_depth: "basic" (faster, cheaper) or "advanced" (deeper, more relevant — use this).
    """
    try:
        response = _get_client().search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_raw_content=True,
            include_answer=False,
        )
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
