# BioSwarm

A multi-agent system that takes a published biology paper and turns it into something you can actually run, either physically (a validated Opentrons script simulated in a cloud sandbox) or computationally (find the repo, spin up its exact environment, try to reproduce the results, return a Reproducibility Score). Built on GPT-5.4 mini, Tavily, Daytona, FastAPI, and a vanilla HTML/JS frontend.

## The problem

Biology has a reproducibility crisis. A 2016 Nature survey found over 70% of researchers couldn't reproduce others' experiments and over half couldn't reproduce their own, and the US spends roughly $28 billion a year on preclinical research that can't be replicated. LLM agents built to help often make this worse by fabricating real-looking citations and passing blobs of paper text around that lose signal at every hop. Here's how we tried to fix that from the architecture up.

## What we did about it

Every value the system produces carries its full origin as a typed FieldLineage chain, so an incubation temperature means exactly where it came from in the paper, what filled it in if the paper didn't state it, what an instrument measured during execution, and what any later revision changed it to and why. The chain renders as a tree.

The LLM can't fabricate citations. Every citation has to resolve to a registered entry whose quoted text is verified against the live source page at startup, and if the LLM keeps trying to cite a fake source the rationale text gets thrown out and replaced with a deterministic fallback rather than preserved with a hallucinated "per Schrader 2012" buried in it.

The system is allowed to refuse to act. When a measurement is ambiguous in a way automation can't responsibly resolve, it exits cleanly and tells the user the next move is manual diagnosis, not another automated guess.

No agent passes raw text to another agent. Every handoff is a typed Pydantic object or a filename pointing into the shared workspace, so context flows as paths and models, never as blobs.

## Closed-loop iteration

You can optionally let the system iterate: after the script is generated and simulated, a (currently mocked) instrument reads the result and the system decides whether the protocol is good, needs an adjustment, or should be handed back because the issue isn't something automation should fix. Three cycles max. Every revision is preserved in the lineage chain so the final value is traceable to the instrument reading that motivated each step.

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
