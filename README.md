# BioSwarm

Multi-agent system that bridges published biology research and physical or computational execution. Built on GPT-5.4 mini, Tavily, Daytona sandboxes, FastAPI, and a vanilla HTML/JS frontend.

## What it does

Wet Lab Mode: paste a biology paper or protocol description. BioSwarm extracts the methodology, enriches missing critical fields from open-access sources, converts the result into a validated Opentrons Python script, and simulates it in a cloud sandbox.

Dry Lab Mode: paste a computational biology paper. BioSwarm finds its code repository, spins up the exact environment in a Daytona sandbox, runs the entry point, and returns a Reproducibility Score (PASS, PARTIAL, FAIL).

Closed-Loop Iteration (wet lab, opt-in): after simulation, a mocked qPCR instrument reads the result. A replanner decides whether to converge, revise the template amount, or exit with diagnose_required when the regime cannot be resolved by template adjustment alone. Every value in the system, whether from a paper span, a Tavily enrichment, an instrument reading, or a replanner revision, carries a typed FieldLineage chain that traces its full origin.

## What's different

Every value carries its history. A `template_amount_ng = 25.0` is not just a number, it's a chain: where it was first extracted from the paper, what PIE enriched it from, what the qPCR oracle measured, what the replanner revised it to and why. The chain links by parent pointer and renders as a tree. The type is `FieldLineage` in `schemas/lineage_schema.py`.

The LLM cannot invent citations. Every citation in a lineage record is a registry key, not a URL. Every key must resolve to a seed entry in `tools/citation_registry.py` whose `quoted_text` is verified at startup against the live source page. A Pydantic validator rejects unregistered keys at write time. When the replanner LLM cites a fake key twice in a row, the rationale text gets replaced entirely with a deterministic fallback string. No preserved prose that might contain hallucinated inline references like "per Schrader 2012".

The replanner can refuse to act. When ambiguous Cq sits at mid-range template (5 to 50 ng), the rule emits diagnose_required with no new value and exits the loop. Template adjustment alone cannot resolve that regime, so the system says so instead of guessing. The user gets a clear signal that this needs a dilution series, not another iteration.

No raw text between agents. Every handoff is either a Pydantic model or a filename pointing into workspace/. The Researcher saves raw scrape output to disk; the Methodology agent reads files and emits typed protocols; the Enricher mutates the protocol in place; the Iteration phase appends typed records onto lineage chains. Context never gets passed as a blob, only as a path or a model.

## Architecture

Eight agents coordinate through a shared file-based workspace. No raw text passes between agents, only structured JSON and filenames.

| Agent | Role | Tools |
|---|---|---|
| Supervisor (PI) | Orchestrates pipeline, owns state.json | Python only, no LLM |
| Researcher | Web search and scraping | Tavily |
| Methodology | Extracts structured protocols from raw research | GPT-5.4 mini, Pydantic |
| Enricher (PIE) | Fills null critical fields, wet lab only | Tavily, GPT-5.4 mini |
| Coder | Generates and validates executable code | Daytona sandboxes |
| Results Reader | Interprets instrument output into typed lineage records | deterministic Python |
| Replanner | Picks revision action by rule, narrates rationale | GPT-5.4 mini, citation registry |
| Synthesizer | Writes the final markdown report | GPT-5.4 mini |

Wet lab pipeline:

```
Research      Tavily search and scrape          -> workspace/raw_research/
   v
Methodology   LLM extracts protocol JSON         -> writes FieldLineage(paper_span)
              Pydantic validates                    per typed field
   v
Enricher      Notes mining + targeted Tavily     -> writes FieldLineage(enricher_fill)
              on open-access domains only           per filled gap
   v
Coder         opentrons_simulate in Daytona      -> .py script + simulator output
              retries on parse/import errors        rejects silent no-ops
   v
Iteration     opt-in, max 3 cycles:
              simulate_qpcr_well                 -> raw CSV + QPCRReading
              Results Reader                     -> FieldLineage(oracle_reading)
              Replanner (rule + LLM rationale)   -> FieldLineage(replanner_revision)
              exits on converged | diagnose_required
   v
Synthesizer   Markdown report                    -> includes Field Lineage Summary
                                                    when iterations ran
```

Dry lab pipeline: Research -> Methodology -> Coder -> Synthesizer (no Enricher, no Iteration).

## Project structure

```
bio-swarm/
├── server.py              FastAPI entry, serves web/ and streams agent events over SSE
├── run_cli.py             Headless CLI, supports --demo-paper and --enable-iteration
├── main.py                Legacy Streamlit UI, kept as fallback
├── web/                   Vanilla HTML/CSS/JS frontend
├── agents/                8 agent modules
├── schemas/
│   ├── opentrons_schema.py
│   ├── dry_lab_schema.py
│   ├── state_schema.py
│   └── lineage_schema.py  FieldLineage and four detail models, with validators
├── tools/
│   ├── tavily_tool.py
│   ├── daytona_tool.py
│   ├── file_tool.py
│   ├── token_tracker.py
│   ├── citation_registry.py   Registry-keyed citations, three-state startup verification
│   ├── mock_qpcr.py           Continuous Cq(template) model with inhibition regime
│   └── lineage_renderer.py    Terminal renderer for FieldLineage chains
├── scripts/               One-off migrations
├── tests/                 pytest suite (~90 tests; network tests gated by -m network)
└── workspace/             Shared agent memory, auto-created
    ├── demo_cache/        Committed pre-extracted demo protocols
    ├── raw_research/
    ├── extracted_protocols/
    ├── generated_code/
    ├── iterations/        Per-iteration raw instrument records
    ├── lineage/           Field lineage snapshots
    └── final_reports/
```

## Setup

Python 3.11 or newer.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill the keys in `.env`: OPENAI_API_KEY, TAVILY_API_KEY, DAYTONA_API_KEY, DAYTONA_API_URL, DAYTONA_TARGET.

## Run

Web UI:

```bash
python server.py
# open http://127.0.0.1:8000
```

CLI on a real paper:

```bash
python run_cli.py --mode wet_lab --input "<paper title or DOI>"
```

Closed-loop demo from the committed cache (skips Research and Methodology):

```bash
python run_cli.py --mode wet_lab --input demo --demo-paper rt-qpcr \
    --enable-iteration --trace-field "step_1.template_amount_ng"
```

The demo prints the lineage tree for the demo field after the pipeline finishes.

## How it works

1. Research. Tavily searches and scrapes the paper. Raw results go to workspace/raw_research/.
2. Extraction. The Methodology agent parses raw text into a Pydantic-validated protocol. Every typed field gets a FieldLineage(paper_span) record citing the source.
3. Enrichment, wet lab only. The Enricher mines protocol notes for unstated-but-known values, then runs targeted Tavily searches pinned to open-access domains (PMC, biorxiv, protocols.io). Each fill writes a FieldLineage(enricher_fill) record.
4. Coding. The Coder generates an Opentrons script, simulates it in a Daytona sandbox, and retries on parse or import errors. A clean simulation with zero liquid-handling calls is treated as failure (fabricated success).
5. Iteration, wet lab, opt-in. A mocked qPCR instrument reads the protocol's template_amount_ng field. The Results Reader interprets the reading into a FieldLineage(oracle_reading) record. The Replanner picks one of converged, reduce_template, increase_template, or diagnose_required by deterministic rule, and the LLM narrates the rationale constrained to registry-keyed citations. Loop exits on converged or diagnose_required, max 3 iterations.
6. Synthesis. The Synthesizer reads every workspace artifact and produces the final markdown report, including a Field Lineage Summary section when iterations ran.

## Implementation notes

Sandbox cleanup. All Daytona sandbox usage is wrapped in try/finally. No leaked billable sandboxes.

Single state owner. Only the Supervisor writes to state.json. Worker agents return structured contract dicts and the Supervisor updates state.

Token tracking. Every LLM call is logged through `tools/token_tracker.py`. Per-agent prompt and completion totals print at the end of each run.

Workspace is replayable. After a run completes, every intermediate artifact stays on disk (raw research bundles, extracted protocol JSON, enrichment audit log, generated script, simulator stdout, per-iteration raw CSVs, lineage snapshots, final report). You can rerun the Synthesizer alone or inspect any phase by hand.

## License

See [LICENSE](LICENSE).
