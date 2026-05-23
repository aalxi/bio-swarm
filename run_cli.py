#!/usr/bin/env python3
"""CLI runner for BioSwarm — runs the full pipeline without Streamlit."""

import argparse
import json
import os
import sys
import uuid

# Ensure working directory is project root (workspace/ paths are relative)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

# Create workspace dirs (mirrors main.py startup)
for d in [
    "workspace",
    "workspace/raw_research",
    "workspace/extracted_protocols",
    "workspace/generated_code",
    "workspace/final_reports",
]:
    os.makedirs(d, exist_ok=True)

from agents.supervisor import run_pipeline, _demo_slug

# Best-effort citation-registry verification at boot (L16 warn-and-flag).
try:
    from tools.citation_registry import verify_at_startup as _verify_citations
    _verify_citations(timeout_s=10.0)
except Exception as _verify_err:
    print(f"[cli] citation verify_at_startup failed: {_verify_err}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="BioSwarm CLI runner")
    parser.add_argument(
        "--mode", required=True, choices=["wet_lab", "dry_lab"],
    )
    parser.add_argument("--input", required=True, help="Paper title/DOI/URL")
    parser.add_argument(
        "--enable-iteration", action="store_true",
        help="Run the closed-loop iteration phase (wet_lab only)",
    )
    parser.add_argument(
        "--trace-field", default=None,
        help="After completion, render this field's lineage tree (e.g. 'step_1.template_amount_ng')",
    )
    parser.add_argument(
        "--trace-all-fields", action="store_true",
        help="After completion, render every field's lineage tree",
    )
    parser.add_argument(
        "--demo-paper", default=None,
        help="Load demo cache 'rt-qpcr' from workspace/demo_cache/; skips Research+Methodology",
    )
    args = parser.parse_args()

    # P0.3 — reject empty / trivially-short input when not using a demo cache.
    if args.demo_paper is None:
        if len(args.input.strip()) < 8:
            print(
                f"[cli] error: --input must be a non-trivial paper title/DOI/URL"
                f" (got: {args.input!r})",
                file=sys.stderr,
            )
            sys.exit(2)

    task_id = str(uuid.uuid4())[:8]
    print(f"[cli] task_id={task_id}  mode={args.mode}")
    print(f"[cli] input: {args.input}")
    print()

    def cli_callback(event):
        if isinstance(event, dict):
            phase = event.get("phase", "?")
            etype = event.get("type", "")

            # P1.6 — iteration events get a payload-rich format instead of the
            # generic "starting / success" lines that would be meaningless.
            if phase == "iteration":
                if etype == "phase_start":
                    idx = event.get("iteration_index", "?")
                    print(f"[cli] iteration {idx}: starting  (oracle reading + replanner)")
                elif etype == "phase_end":
                    idx = event.get("iteration_index", "?")
                    cq = event.get("cq")
                    regime = event.get("regime", "?")
                    action = event.get("action", "?")
                    cq_str = f"cq={cq}" if cq is not None else "cq=none"
                    print(f"[cli] iteration {idx}: {event.get('status', '?')} — {cq_str} regime={regime} action={action}")
                else:
                    print(f"[cli] {event}")
                return

            if etype == "phase_start":
                print(f"[cli] {phase}: starting")
            elif etype == "phase_end":
                status = event.get("status", "?")
                msg = event.get("message", "")
                print(f"[cli] {phase}: {status}" + (f" — {msg}" if msg else ""))
            else:
                print(f"[cli] {event}")
        else:
            print(f"[cli] {event}")

    if args.demo_paper:
        from pathlib import Path
        import shutil as _sh
        demo_slug = _demo_slug(args.demo_paper)
        demo_src = Path(f"workspace/demo_cache/{demo_slug}_protocol.json")
        if not demo_src.exists():
            print(f"[cli] demo cache not found: {demo_src}", file=sys.stderr)
            sys.exit(1)
        proto_path = Path(f"workspace/extracted_protocols/protocol_{task_id}.json")
        _sh.copy(demo_src, proto_path)
        print(f"[cli] demo-paper loaded: {demo_slug}")

        from agents.supervisor import run_pipeline_from_demo
        result = run_pipeline_from_demo(
            user_input=args.input, mode=args.mode, task_id=task_id,
            protocol_path=str(proto_path),
            enable_iteration=args.enable_iteration,
            status_callback=cli_callback,
        )
    else:
        result = run_pipeline(
            user_input=args.input, mode=args.mode, task_id=task_id,
            status_callback=cli_callback,
            enable_iteration=args.enable_iteration,
        )

    print()
    print(f"[cli] pipeline finished — status: {result['status']}")
    if result.get("report_file"):
        print(f"[cli] report: {result['report_file']}")
    if result["status"] == "error":
        errors = result.get("state", {}).get("errors", [])
        if errors:
            print(f"[cli] errors:")
            for e in errors:
                print(f"  - {e}")

    exit_code = 0 if result["status"] == "success" else 1
    print(f"[cli] exit_code={exit_code}")

    if (args.trace_field or args.trace_all_fields) and result.get("status") == "success":
        from tools.lineage_renderer import (
            render_lineage_tree, render_aggregate_summary,
        )
        from tools.file_tool import load_json
        from schemas.lineage_schema import FieldLineage
        from schemas.state_schema import IterationsState

        proto_path = result["state"]["extraction"]["protocol_file"]
        if proto_path:
            proto = load_json(proto_path)
            fields: dict[str, FieldLineage] = {}
            for step in proto.get("sequential_steps", []):
                for field_name, fl_json in (step.get("field_lineage") or {}).items():
                    key = f"step_{step['step_number']}.{field_name}"
                    fields[key] = FieldLineage.model_validate(fl_json)

            iters = IterationsState.model_validate(
                result["state"].get("iterations", {})
            )
            print()
            print(render_aggregate_summary(
                task_id=task_id, all_field_lineages=fields,
                iterations_state=iters,
            ))
            print()
            targets = (
                list(fields.keys()) if args.trace_all_fields else [args.trace_field]
            )
            # Build a quick lookup of step_number -> step dict for P0.4.
            steps_by_number: dict[int, dict] = {
                step["step_number"]: step
                for step in proto.get("sequential_steps", [])
            }

            for t in targets:
                if t in fields:
                    print(f"── {t} ──")
                    print(render_lineage_tree(fields[t]))
                    print()
                    continue

                # P0.4 — three-state field diagnosis.
                parts = t.split(".", 1)
                if (
                    len(parts) == 2
                    and parts[0].startswith("step_")
                    and parts[0][len("step_"):].isdigit()
                ):
                    step_num = int(parts[0][len("step_"):])
                    field_name = parts[1]
                    if step_num not in steps_by_number:
                        print(
                            f"[cli] field not in protocol: {t}"
                            f" (step {step_num} does not exist in this protocol)"
                        )
                    elif field_name not in steps_by_number[step_num]:
                        print(
                            f"[cli] field not in protocol: {t}"
                            f" (step {step_num} exists but has no '{field_name}' attribute)"
                        )
                    else:
                        print(
                            f"[cli] field has no lineage record: {t}"
                            f" (field present, no FieldLineage attached"
                            f" — likely a demo-cache field or pre-lineage protocol)"
                        )
                else:
                    # Unparseable key format — fall back to generic message.
                    print(f"[cli] field not found: {t}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
