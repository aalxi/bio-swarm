# BioSwarm

Multi-agent AI system that bridges published biology research and physical/computational execution. Built with GPT-5.4, Tavily, Daytona sandboxes, and Streamlit.

## What It Does

**Wet Lab Mode** — Paste a biology paper or protocol description. BioSwarm extracts the methodology, converts it into a validated Opentrons Python script, simulates it in a cloud sandbox, and returns the ready-to-run protocol file.

**Dry Lab Mode** — Paste a computational biology paper. BioSwarm finds its linked code repository, spins up the exact environment in a Daytona sandbox, attempts to reproduce the paper's results, and returns a Reproducibility Score (PASS / PARTIAL / FAIL).

## Architecture

Five specialized agents coordinate through a shared file-based workspace — no raw text passes between agents, only structured JSON and filenames:

| Agent | Role | Tools |
|---|---|---|
| **Supervisor** (PI) | Orchestrates pipeline, owns state | `state.json` |
| **Researcher** | Web search & scraping | Tavily |
| **Methodology** | Extracts structured protocols from raw research | GPT-5.4 + Pydantic |
| **Coder** | Generates & validates executable code | Daytona sandboxes |
| **Synthesizer** | Writes final human-readable report | GPT-5.4 |

```
User Input → Supervisor → Researcher → Methodology → Coder → Synthesizer → Report
                  ↑                                      |
                  └──── retry on error (max 3) ──────────┘
```

## Project Structure

```
bio-swarm/
├── main.py                 # Streamlit entry point
├── agents/
│   ├── supervisor.py       # PI Agent — routes tasks, owns state.json
│   ├── researcher.py       # Tavily Agent — web search & scraping
│   ├── methodology.py      # Extractor Agent — raw text → JSON schema
│   ├── coder.py            # Daytona Agent — JSON → executable code
│   └── synthesizer.py      # Reporter Agent — produces final output
├── schemas/
│   ├── opentrons_schema.py # Pydantic model for wet lab protocols
│   ├── dry_lab_schema.py   # Pydantic model for reproducibility targets
│   └── state_schema.py     # Pydantic model for shared workspace state
├── tools/
│   ├── tavily_tool.py      # search_web(), extract_url()
│   ├── daytona_tool.py     # create_sandbox(), run_code(), run_cmd(), cleanup()
│   └── file_tool.py        # save/load JSON and text
├── workflows/
│   ├── wet_lab_workflow.md  # Step-by-step agent routing for wet lab
│   └── dry_lab_workflow.md  # Step-by-step agent routing for dry lab
└── workspace/              # Shared agent memory (auto-created at runtime)
```

## Setup

**Requirements**: Python 3.11+

1. Clone the repo:
   ```bash
   git clone https://github.com/aalxi/bio-swarm.git
   cd bio-swarm
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.example .env
   ```
   Fill in your API keys in `.env`:
   - `OPENAI_API_KEY` — OpenAI API key
   - `TAVILY_API_KEY` — Tavily search API key
   - `DAYTONA_API_KEY` — Daytona sandbox API key
   - `DAYTONA_API_URL` — Daytona API endpoint (default: `https://app.daytona.io/api`)
   - `DAYTONA_TARGET` — Daytona target region (default: `us`)

4. Run the app:
   ```bash
   streamlit run main.py
   ```

## How It Works

1. **Research** — The Researcher agent uses Tavily to search for and scrape the paper's content, saving raw results to `workspace/raw_research/`.

2. **Extraction** — The Methodology agent reads raw research and extracts a structured protocol validated against Pydantic schemas, saved to `workspace/extracted_protocols/`.

3. **Code Generation & Validation** — The Coder agent generates executable code from the extracted protocol, then validates it in a Daytona cloud sandbox (e.g., running `opentrons_simulate` for wet lab protocols). Failed attempts trigger automatic self-correction up to 3 retries.

4. **Synthesis** — The Synthesizer agent reads all workspace artifacts and produces a final Markdown report with citations, saved to `workspace/final_reports/`.

## Key Design Decisions

- **File-based communication**: Agents never pass large text blobs through function arguments. Every artifact is saved to `workspace/` and referenced by filename — this prevents context window bloat and makes the pipeline debuggable.
- **Single state owner**: Only the Supervisor writes to `state.json`, preventing race conditions.
- **Mandatory sandbox cleanup**: All Daytona sandbox usage is wrapped in `try/finally` to prevent leaked billable sandboxes.
- **No hallucinated values**: If a scientific value isn't in the source material, it's set to `null` with an extraction note — agents never guess.

## License

See [LICENSE](LICENSE) for details.
