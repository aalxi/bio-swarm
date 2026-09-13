# BioSwarm

**AI agents for scientific reproducibility.**

---

## 📄 Executive Summary

Read the one-pager for a high-level overview of the system design and capabilities:

![One-Pager Preview](Alexei_Manuel_Agentic_Lab_Automation_One-Pager.pdf)

[📋 Full One-Pager (PDF)](Alexei_Manuel_Agentic_Lab_Automation_One-Pager.pdf) — System architecture, reproducibility guarantees, and closed-loop iteration.

---

## The Problem

Biology has a reproducibility crisis. A 2016 Nature survey found **over 70% of researchers couldn't reproduce others' experiments** and over half couldn't reproduce their own. The US spends roughly $28B/year on irreproducible research.

The roadblock isn't just lab technique: every "materials and methods" section is an archaeologist's puzzle. Values are scattered, units are implicit, protocols are verbal, and the glue between paper-as-published and protocol-as-runnable is human interpretation—which fails, often silently.

## What We Built

A multi-agent system that takes a published biology paper and turns it into something you can actually run, either:
- **Physically**: A validated Opentrons script simulated in a cloud sandbox
- **Computationally**: Executable dry-lab analysis code

Every value the system produces carries its full origin as a typed **FieldLineage** chain, so an incubation temperature means exactly where it came from in the paper, what filled it in if the paper didn't say, and whether a human or the system guessed.

### Core Guarantees

✅ **No fabricated citations.** Every citation resolves to a registered entry whose quoted text is verified against the live source page at startup.

✅ **Refuses unsafe automation.** When a measurement is ambiguous, the system exits cleanly and asks for human input—not an automated guess.

✅ **Full lineage tracing.** No raw text passes between agents. Every handoff is a typed Pydantic object with origin metadata.

✅ **Closed-loop iteration.** After code generation and simulation, a (currently mocked) instrument reads results and the system decides whether to refine or require manual diagnosis.

## Architecture

Eight agents coordinate through a shared file-based workspace:

| Agent | Role | Tools |
|---|---|---|
| **Supervisor (PI)** | Orchestrates pipeline, owns state.json | Python only, no LLM |
| **Researcher** | Web search and scraping | Tavily |
| **Methodology** | Extracts structured protocols from raw research | GPT-4o mini, Pydantic |
| **Enricher (PIE)** | Fills null critical fields, wet lab only | Tavily, GPT-4o mini |
| **Coder** | Generates and validates executable code | Daytona sandboxes |
| **Results Reader** | Interprets instrument output into lineage records | Deterministic Python |
| **Replanner** | Picks revision action by rule, narrates rationale | GPT-4o mini, citation registry |
| **Synthesizer** | Writes the final markdown report | GPT-4o mini |

### Wet Lab Pipeline

```
Research      Tavily search and scrape          → workspace/raw_research/
   ↓
Methodology   LLM extracts protocol JSON         → FieldLineage(paper_span)
              Pydantic validates                   per typed field
   ↓
Enricher      Notes mining + targeted Tavily     → FieldLineage(enricher_fill)
              on open-access domains only         per filled gap
   ↓
Coder         opentrons_simulate in Daytona      → .py script + simulator output
              retries on parse/import errors      rejects silent no-ops
   ↓
Iteration     opt-in, max 3 cycles:
              simulate_qpcr_well                 → raw CSV + QPCRReading
              Results Reader                     → FieldLineage(oracle_reading)
              Replanner (rule + LLM rationale)   → FieldLineage(replanner_revision)
              exits on converged | diagnose_required
   ↓
Synthesizer   Markdown report                    → Field Lineage Summary
                                                   (when iterations ran)
```

**Dry lab pipeline:** Research → Methodology → Coder → Synthesizer (no Enricher, no Iteration).

## Project Structure

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

**Python 3.11 or newer.**

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill the keys in `.env`:
- `OPENAI_API_KEY`
- `TAVILY_API_KEY`
- `DAYTONA_API_KEY`
- `DAYTONA_API_URL`
- `DAYTONA_TARGET`

## Run

**Web UI:**

```bash
python server.py
# open http://127.0.0.1:8000
```

**CLI on a real paper:**

```bash
python run_cli.py --mode wet_lab --input "<paper title or DOI>"
```

**Closed-loop demo** (from committed cache, skips Research and Methodology):

```bash
python run_cli.py --mode wet_lab --input demo --demo-paper rt-qpcr \
    --enable-iteration --trace-field "step_1.template_amount_ng"
```

The demo prints the lineage tree for the demo field after the pipeline finishes.

## How It Works

1. **Research.** Tavily searches and scrapes the paper. Raw results go to `workspace/raw_research/`.

2. **Extraction.** The Methodology agent parses raw text into a Pydantic-validated protocol. Every typed field gets a `FieldLineage(paper_span)` record citing the source.

3. **Enrichment** (wet lab only). The Enricher mines protocol notes for unstated-but-known values, then runs targeted Tavily searches pinned to open-access domains (PMC, bioRxiv, protocols.io). Each filled field gets a `FieldLineage(enricher_fill)` record.

4. **Coding.** The Coder generates an Opentrons script, simulates it in a Daytona sandbox, and retries on parse or import errors. A clean simulation with zero liquid-handling calls is treated as failure.

5. **Iteration** (wet lab, opt-in). A mocked qPCR instrument reads the protocol's `template_amount_ng` field. The Results Reader interprets the reading into a `FieldLineage(oracle_reading)` record. The Replanner decides whether to refine or exit.

6. **Synthesis.** The Synthesizer reads every workspace artifact and produces the final markdown report, including a Field Lineage Summary section when iterations ran.

## Implementation Notes

- **Sandbox cleanup.** All Daytona sandbox usage is wrapped in try/finally. No leaked billable sandboxes.
- **Single state owner.** Only the Supervisor writes to `state.json`. Worker agents return structured contract dicts and the Supervisor updates state.
- **Token tracking.** Every LLM call is logged through `tools/token_tracker.py`. Per-agent prompt and completion totals print at the end of each run.
- **Replayable workspace.** After a run completes, every intermediate artifact stays on disk (raw research bundles, extracted protocol JSON, enrichment audit log, generated script, simulator stdout, iteration records, lineage snapshots).

## License

See [LICENSE](LICENSE).
