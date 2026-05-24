import re
from urllib.parse import urlparse
from pydantic import BaseModel, field_validator
from typing import Optional, List, Literal

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


# ── P2.5 typed expected_outputs ──────────────────────────────────────────────
#
# Background: the May-04 scGPT smoke test had Coder trying to download "Fig 2b"
# as a file path because expected_outputs was List[str]. Each entry is now a
# typed (label, category) pair so the Coder can partition correctly without
# guessing.

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_GEO_RE = re.compile(r"^(GSE\d+|GSM\d+|E-[A-Z]+-\d+)$", re.IGNORECASE)
_FIG_RE = re.compile(r"^(Figure|Fig|Table|Supplementary)\b", re.IGNORECASE)
_FILE_RE = re.compile(r"^[\w./\- ]+\.[A-Za-z0-9]{1,8}$")


def classify_expected_output(label: str) -> str:
    """Categorize a free-text expected_outputs entry into one of:
    file_path, directory_path, paper_deliverable, geo_accession, url, unresolved.

    Heuristic ordering matters: URL → GEO accession → figure/table caption →
    explicit file path → directory path → free-text description (likely
    paper-level claim) → unresolved.
    """
    s = (label or "").strip()
    if not s:
        return "unresolved"
    if _URL_RE.match(s):
        return "url"
    if _GEO_RE.match(s):
        return "geo_accession"
    if _FIG_RE.match(s):
        return "paper_deliverable"
    if _FILE_RE.match(s):
        return "file_path"
    if s.startswith(("/", "./", "../")) and "." in s.rsplit("/", 1)[-1]:
        return "file_path"
    if "/" in s and not s.endswith((".", "?")):
        return "directory_path"
    # Free-text descriptions like "A foundation model for single-cell biology"
    # — paper-level claim, not an artifact path.
    if " " in s and len(s) > 10:
        return "paper_deliverable"
    return "unresolved"


class ExpectedOutput(BaseModel):
    """A typed expected output: the LLM extracts the raw label from the paper,
    and either it OR our classifier assigns the category. The Coder then
    partitions on .category and never re-guesses at consume time."""
    label: str
    category: Literal[
        "file_path", "directory_path", "paper_deliverable",
        "geo_accession", "url", "unresolved",
    ] = "unresolved"


class ReproducibilityTarget(BaseModel):
    paper_title: str
    paper_source: str
    github_url: Optional[str] = None
    requirements_file: Optional[str] = None
    data_download_urls: List[str] = []
    main_script: Optional[str] = None
    expected_outputs: List[ExpectedOutput] = []
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

    @field_validator("expected_outputs", mode="before")
    @classmethod
    def _normalize_expected_outputs(cls, v):
        """Accept legacy List[str] or new List[ExpectedOutput-shaped dict].
        Each string is auto-classified; each dict missing 'category' gets
        it auto-classified from the label. The validator is intentionally
        permissive so on-disk protocols written before this change still load.
        """
        if not isinstance(v, list):
            return v
        out = []
        for entry in v:
            if isinstance(entry, str):
                out.append({
                    "label": entry,
                    "category": classify_expected_output(entry),
                })
            elif isinstance(entry, dict):
                if "category" not in entry and "label" in entry:
                    entry = {
                        **entry,
                        "category": classify_expected_output(entry["label"]),
                    }
                out.append(entry)
            else:
                # Already-instantiated ExpectedOutput or unknown type;
                # let Pydantic decide.
                out.append(entry)
        return out
