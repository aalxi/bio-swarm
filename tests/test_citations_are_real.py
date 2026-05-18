"""Meta-feature: every registry entry with quoted_text must locate that text
on the live URL. Marked `network` so CI can gate it. Skipped offline."""
import pytest

from tools.citation_registry import REGISTRY, _fetch, _normalize


pytestmark = pytest.mark.network


@pytest.mark.parametrize("key", sorted(REGISTRY.keys()))
def test_quoted_text_is_actually_on_the_page(key):
    c = REGISTRY[key]
    if c.url is None or c.quoted_text is None:
        pytest.skip(f"{key}: nothing verifiable")
    try:
        body = _fetch(c.url, timeout=15.0)
    except Exception as e:
        pytest.skip(f"{key}: unreachable ({type(e).__name__}: {e})")
    needle = _normalize(c.quoted_text)
    haystack = _normalize(body)
    assert needle in haystack, (
        f"{key}: quoted_text not found on {c.url}.\n"
        f"  needle (normalized): {needle!r}"
    )
