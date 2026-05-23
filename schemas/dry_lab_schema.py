from urllib.parse import urlparse
from pydantic import BaseModel, field_validator
from typing import Optional, List

# Bare service name tokens that are not real URLs
_BARE_SERVICE_NAMES = frozenset({
    "google drive", "zenodo", "figshare", "osf", "dataverse",
    "github", "bitbucket", "gitlab", "dropbox", "box", "s3",
    "mendeley data", "dryad", "harvard dataverse",
})


def _filter_placeholder_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    """Split *urls* into (kept, rejected) based on placeholder-detection heuristics.

    Rejection criteria (any one is sufficient):
    1. Contains ``??``
    2. Contains ``<placeholder>``, ``<TODO>``, or ``<...>`` (angle-bracket markers)
    3. ``urlparse`` yields an empty ``scheme`` OR empty ``netloc``
    4. Ends with ``/...`` literally (LLM continuation marker)
    5. Is a bare service name (e.g. "Google Drive", "Zenodo") without a real path

    The function is intentionally conservative: a URL passes if none of the
    five criteria match, even if it cannot be fetched.  Callers are responsible
    for surfacing rejected URLs in ``extraction_notes``.
    """
    kept: list[str] = []
    rejected: list[str] = []

    for url in urls:
        stripped = url.strip()

        # Criterion 1: literal ??
        if "??" in stripped:
            rejected.append(url)
            continue

        # Criterion 2: angle-bracket placeholder markers
        angle_markers = ("<placeholder>", "<TODO>", "<...>")
        if any(m in stripped for m in angle_markers):
            rejected.append(url)
            continue

        # Criterion 5: bare service name (check before urlparse to catch no-scheme strings)
        if stripped.lower() in _BARE_SERVICE_NAMES:
            rejected.append(url)
            continue

        # Criterion 3: must have both scheme and netloc
        parsed = urlparse(stripped)
        if not parsed.scheme or not parsed.netloc:
            rejected.append(url)
            continue

        # Criterion 4: ends with /... (continuation marker)
        if stripped.endswith("/..."):
            rejected.append(url)
            continue

        # Criterion 5 extended: scheme://netloc/ with empty path beyond root
        path = parsed.path
        if not path or path == "/":
            # scheme://netloc/ with no real path — treat as placeholder
            rejected.append(url)
            continue

        kept.append(url)

    return kept, rejected


def _filter_placeholder_github_url(url: Optional[str]) -> Optional[str]:
    """Return *url* unchanged if it passes placeholder checks, else None."""
    if url is None:
        return None
    kept, _ = _filter_placeholder_urls([url])
    return kept[0] if kept else None


class ReproducibilityTarget(BaseModel):
    paper_title: str
    paper_source: str
    github_url: Optional[str] = None
    requirements_file: Optional[str] = None
    data_download_urls: List[str] = []
    main_script: Optional[str] = None
    expected_outputs: List[str] = []
    extraction_notes: List[str] = []

    @field_validator("data_download_urls", mode="before")
    @classmethod
    def _drop_placeholder_download_urls(cls, v):
        if not isinstance(v, list):
            return v
        kept, _ = _filter_placeholder_urls([str(u) for u in v])
        return kept

    @field_validator("github_url", mode="before")
    @classmethod
    def _drop_placeholder_github_url(cls, v):
        if v is None:
            return None
        return _filter_placeholder_github_url(str(v))
