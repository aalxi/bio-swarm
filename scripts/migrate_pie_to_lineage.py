"""One-off migration: rewrite existing PIE field_confidence / field_sources
dicts as FieldLineage(source_type='enricher_fill') records on each step.

L18: citations stays empty. The Tavily URL goes inline in EnricherFillDetail.
tavily_url. No registry pollution with auto-created enricher_url_<hash>
entries — the follow-up backfill script (v2) handles that.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, UTC

from schemas.lineage_schema import EnricherFillDetail, FieldLineage


def _build_lineage(field: str, value, confidence: float, url: str | None
                   ) -> dict:
    fl = FieldLineage(
        value=value,
        placed_at=datetime.now(UTC),
        source_type="enricher_fill",
        enricher_fill=EnricherFillDetail(
            phase="tavily", confidence=float(confidence), tavily_url=url,
        ),
        citations=[],
        iteration_index=None,
    )
    return fl.model_dump(mode="json")


def migrate_one(path: str) -> None:
    with open(path) as f:
        proto = json.load(f)

    for step in proto.get("sequential_steps", []):
        confidences = step.pop("field_confidence", None) or {}
        sources = step.pop("field_sources", None) or {}
        step.setdefault("field_lineage", {})
        for field, conf in confidences.items():
            if field not in step or step.get(field) is None:
                continue
            url = sources.get(field)
            step["field_lineage"][field] = _build_lineage(
                field, step[field], conf, url,
            )

    with open(path, "w") as f:
        json.dump(proto, f, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--glob", default="workspace/extracted_protocols/protocol_*.json",
    )
    args = parser.parse_args()
    paths = glob.glob(args.glob)
    if not paths:
        print(f"[migrate] no files match {args.glob}", file=sys.stderr)
        return 1
    for p in paths:
        print(f"[migrate] rewriting {p}", flush=True)
        migrate_one(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
