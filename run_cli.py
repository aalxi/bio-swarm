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

from agents.supervisor import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="BioSwarm CLI runner")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["wet_lab", "dry_lab"],
        help="Pipeline mode: wet_lab or dry_lab",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Paper title, DOI, URL, or abstract",
    )
    args = parser.parse_args()

    task_id = str(uuid.uuid4())[:8]
    print(f"[cli] task_id={task_id}  mode={args.mode}")
    print(f"[cli] input: {args.input}")
    print()

    result = run_pipeline(
        user_input=args.input,
        mode=args.mode,
        task_id=task_id,
        status_callback=lambda msg: print(f"[cli] {msg}"),
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

    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
