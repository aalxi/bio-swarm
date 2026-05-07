# BioSwarm Smoke Test — 2026-05-04

**Reviewer:** acting as a senior researcher with high standards for an automated paper→protocol pipeline.
**Constraint:** single-tenant `workspace/state.json` → tests run sequentially.
**Window:** "highly recent (last 6 months)" interpreted as Nov 2025 – May 2026, with allowance for late-2024 high-impact releases that remain the canonical recent reference (AlphaFold 3, ESM-3) since the field has not been displaced.

## Test matrix

| # | Mode | Paper / Protocol | Why this paper |
|---|------|-----------------|----------------|
| 1 | wet_lab | Smart-seq3 single-cell RNA-seq library preparation | Discrete pipetting steps, well-indexed in PMC/protocols.io |
| 2 | wet_lab | NEBNext Ultra II DNA Library Prep for Illumina | Canonical, exhaustively documented, exercises labware/reagent extraction |
| 3 | dry_lab | Deep learning prediction of selenoprotein / 21st-amino-acid (Sec) insertion sites — recent academic work | Niche, small-group repos — surfaces real failure modes (rough README, missing entry points, undeclared deps). AlphaFold 3 / ESM-3 deliberately avoided since their polished code would mask pipeline weaknesses. |
| 4 | dry_lab | Ribosome profiling pause-site / stalling prediction (deep learning model, recent) | Same rationale — small-group computational biology code is where dry-lab pipelines actually break. |

Each test below is graded on:
- **Did each phase succeed?** (research / extraction / enrichment / coding / synthesis)
- **Was the artifact scientifically credible?** (extracted JSON, generated code, simulation result, report)
- **Failure-mode quality**: when it failed, did the system fail loudly and informatively, or silently and misleadingly?

---

## Test 1 — Wet lab — Smart-seq3 (Hagemann-Jensen et al.)

**Task ID:** `ea08c24d` · **Pipeline status:** `success` · **Tokens:** 124,342 (Synth 57.9k + Enricher 48.6k + Methodology 10k + Coder 5.1k + Researcher 2.7k)

### Phase results
| Phase | Status | Notes |
|---|---|---|
| research | success | 3 queries, 15 results, 15 unique sources |
| extraction | success | 12 sequential steps extracted, schema-valid |
| enrichment | success | 18 gaps identified, 6 filled (3 notes-mining @0.84-0.98 conf, 3 Tavily PMC/protocols.io @0.86-0.98), 0 conflicts, 12 still null |
| coding | success | Opentrons 9.0.0 simulated cleanly, 9 liquid-handling calls, 5 SKIPPED steps |
| synthesis | success | Report rendered |

### Critical assessment — issues a senior reviewer would flag

**1. "Success" is generous — most of the protocol is comments, not actions.** Of 12 steps, only 4 actually emit liquid-handling calls (steps 4, 7, 9, plus implicit aspirate/dispense inside `transfer`/`distribute`). Steps 1, 6, 11, 12 are pure `protocol.comment()`. The silent-no-op detector cleared the run because total liquid calls > 0, but the **per-step** ratio is 4/12 — a more honest metric.

**2. The FACS step was modelled as a pipetting transfer.** Step 1 is FACS sorting cells into a 96-well plate. That's a flow-cytometry sorter operation, not an OT-2 transfer — there is no source well. The Methodology agent should have categorized it as `setup`/`prep` (no such schema action exists) or flagged it as out-of-scope. Instead it became `action: "transfer"` with both source and destination set to `"96-well plate"` — meaningless.

**3. Wrong labware abstraction for the magnetic stand.** Generated code: `mag_plate = protocol.load_labware("nest_96_wellplate_200ul_flat", "4", "magnetic stand placeholder")`. Opentrons OT-2 has a real `magnetic_module` (and Flex has `magneticBlockV1`) — the Coder fell back to a flat plate placeholder rather than `protocol.load_module("magnetic module gen2", "4")`. A real bead-cleanup protocol *requires* the magnetic module abstraction; this script would mechanically execute but wouldn't actually engage a magnet.

**4. Bioanalyzer step is a category error.** Step 12 loads an `opentrons_96_wellplate_200ul_pcr_full_skirt` as a "Bioanalyzer HS DNA chip plate placeholder". The Bioanalyzer is a separate Agilent instrument; emitting any deck slot for it is wrong. Should be excluded from the protocol entirely.

**5. The `if p20.has_tip: pass else: pick_up_tip()` pattern in step 4.** Defensive code that's nonsensical inside a generated single-pass protocol where state is known. Suggests the LLM is fighting an imagined error rather than writing clean code.

**6. PIE provenance `field_sources: null` for notes-derived fills.** Audit trail is correct (`source_note` + `rationale` are populated in `enrichment_*.json`) but the **per-step** `field_sources` map collapses notes-derived fills to `null`, which a downstream reader will misread as "no citation." Should be a sentinel like `"notes_mining"` or the literal note text.

**7. Smart-seq3 is fundamentally a multi-cell parallel workflow** (96 cells per plate). The generated protocol does single-well operations everywhere (e.g. `sample_plate.wells()[0]`, `pcr_strip.wells()[0]`). Even with all gaps filled, this script would only process well A1 — silently dropping 95 cells. The schema lacks any concept of "applies to all wells" / "per-well loop", and neither Methodology nor Coder surfaced that gap.

**8. Tokens: Synthesizer is the single biggest LLM consumer at 57.9k prompt tokens.** It re-reads the entire protocol JSON + script + state to build a Markdown report. Reasonable for a hackathon but it's the obvious optimization target if scaling up.

### Verdict
**Pipeline-level: success. Scientific-utility: D+.** A bench scientist would treat the output as a starting scaffold but not a runnable protocol. The system told the truth in its `confidence notes` section (lots of nulls, lots of placeholders), which is good — but the `simulation_passed: true` line at the top of the report is the headline most users will read, and it's misleadingly cheerful.

### Errors / non-fatal warnings logged
- None at the pipeline level. The 12 `still_null` entries are documented gaps, not errors.

---
## Test 2 — Wet lab — NEBNext Ultra II DNA Library Prep (NEB E7645)

**Task ID:** `d44d8348` · **Pipeline status:** `error` · **Tokens:** 80,796 (Enricher 51.3k + Coder 16k + Methodology 10.4k + Researcher 3.1k; Synthesizer skipped)

### Phase results
| Phase | Status | Notes |
|---|---|---|
| research | success | 3 queries, 15 results |
| extraction | success | Schema-valid; **0 notes-mining gaps available** (Methodology produced minimal `notes` strings vs. Smart-seq3) |
| enrichment | success | 12 gaps identified, 2 filled (both Tavily, no notes-mining), 10 still null |
| coding | **error after 4 attempts** | Four distinct error classes — the self-correction loop is not converging |
| synthesis | **skipped** | Supervisor halted on coding error — no report generated for the user |

### Coder retry trajectory — four attempts, four different bug classes

| Attempt | Error | Class |
|---|---|---|
| 1 | `UnexpectedTipRemovalError: Cannot perform mix without a tip attached` | Forgot `pick_up_tip()` before `.mix()` |
| 2 | `TypeError: float() argument ... not 'NoneType'` | Passed a `None` volume to a transfer (didn't guard against null `volume_ul`) |
| 3 | `AttributeError: 'ThermocyclerContext' object has no attribute 'wait_for_block_temperature'` | **Hallucinated API method**. Real method: `set_block_temperature` |
| 4 | `RuntimeError: Cannot move to labware loaded in Thermocycler when lid is not fully open` | Forgot `thermocycler.open_lid()` before pipetting into a Thermocycler-mounted plate |

These are **not regressions of the same bug** — each fix introduces a new bug class. The retry loop appears to be regenerating sections of the script in isolation without re-validating the whole script's invariants (tip state, lid state, null guards, API surface).

### Critical assessment — what this surfaces

**1. Self-correction loop is shallow.** Coder is getting the next-attempt prompt with only the most recent stderr, so it patches the obvious symptom and breaks something else. There's no growing list of constraints — every attempt starts from a fresh interpretation of the same JSON.

**2. Failed scripts are not persisted.** `workspace/generated_code/` contains nothing for `task_id=d44d8348` — the four attempts each lived only in the sandbox, then were thrown away. A post-mortem cannot inspect *which* script failed *which* way without scraping the log. **The system loses the very evidence needed to debug it.**

**3. Synthesis is skipped on coding error.** When coding fails, the user gets nothing — no report, no extracted protocol summary, no "here's what we got and where it broke." Synthesizer should still run on partial state and emit a "Failed at: coding" report.

**4. Methodology output asymmetry is structural.** For Smart-seq3, Methodology produced rich step-level `notes` (3 of 6 PIE fills came from notes-mining). For NEBNext (better-documented), Methodology produced sparse notes (0 notes-mining fills available). PIE's effectiveness is bottlenecked on how chatty Methodology happens to be — non-deterministic.

**5. Hallucinated `wait_for_block_temperature` is a known LLM failure mode.** Real method: `set_block_temperature`. **Mitigation:** seed the Coder's system prompt with the exact list of `ThermocyclerContext` / `MagneticModuleContext` / `TemperatureModuleContext` methods.

**6. CLI exit code masking.** Background-task wrapper reported exit 0 even though `[cli] pipeline finished — status: error`. Worth checking whether `run_cli.py` actually exits 1 or whether something upstream swallows it. Either way, the printed `status: error` is the source of truth.

### Errors logged
- Final coding error: `RuntimeError [line 76]: Cannot move to labware loaded in Thermocycler when lid is not fully open.`
- Earlier attempts: `UnexpectedTipRemovalError`, `TypeError: float() ... NoneType`, `AttributeError: 'ThermocyclerContext' object has no attribute 'wait_for_block_temperature'`.
- Pipeline `state.errors[0]` contains the full final traceback.

### Verdict
**Pipeline-level: hard fail.** This is the more useful test: the system has to deal with adversity. Every error was a small fix away from working — but the retry loop's lack of constraint accumulation and the loss of intermediate scripts means a single bad LLM mood ends the run.

---
## Test 3 — Dry lab — selenoprotein/Sec insertion ML (deep-Sep, PMC12013277)

**Task ID:** `fd7a8827` · **Pipeline status:** `error` · **Tokens:** 10,655 (Methodology 8k + Researcher 2.7k; Coder/Synthesizer skipped)

### Phase results
| Phase | Status | Notes |
|---|---|---|
| research | success | 3 queries, 15 sources. Real paper found: deep-Sep (PMC12013277, 2025) |
| extraction | success | Schema-valid `ReproducibilityTarget`, but `github_url=null` |
| coding | **error (fast fail)** | "No github_url in reproducibility target" — no sandbox even spun up |
| synthesis | **skipped** | |

### What actually happened — the github resolver double-failed

The pipeline has **two** fallback mechanisms for finding a GitHub URL when extraction returns null. Both were defeated:

**Researcher fallback (`agents/researcher.py:189-191`)**: triggers an extra `{user_input} site:github.com` query *only if* zero results contain `github.com`. But the initial 15 sources included `https://github.com/Peldom/papers_for_protein_design_using_DL` — a generic catalog repo — so the check passed and the fallback **never ran**. **Bug: presence of *any* github.com URL satisfies this guard, even URLs that are obviously catalogs.**

**Methodology fallback (`agents/methodology.py:193-225`, `_find_missing_github_url`)**: extracts capitalized words from the paper title and searches `{pkg} github repository`. The paper's title is `"deep-Sep: a deep learning-based method..."` — but:
1. The token-extraction regex requires `w[0].isupper() or w.isupper()` → `"deep-Sep"` starts with lowercase `d`, **so it doesn't qualify as a candidate**.
2. The remaining capitalized tokens are `"Sep:"` → stripped to `"Sep"`. The match guard `pkg.lower() in url.lower()` would over-match any URL containing `"sep"` (separated, sequence, etc.), so even if it ran, it'd likely false-positive.
3. On exception → **silent pass** (`pass  # Silent fail, return None below`). User never sees that the resolver was attempted, let alone why it failed.

So a paper that **is publicly indexed** (PMC, 2025), with **a github repo that almost certainly exists** (`fafa1971/deep-Sep` or similar — most deep-* PMC papers have repos), failed because the resolver heuristics are too brittle for hyphenated lowercase package names.

### Critical assessment

**1. The "any github.com URL means we're good" check is wrong.** A catalog repo (`papers_for_protein_design_using_DL`) is not the paper's repo. The Researcher should require the github URL to **also appear in the same source as the paper or its DOI**, or run the targeted fallback regardless and merge results.

**2. Title-token heuristic doesn't handle modern naming conventions.** `deep-Sep`, `scGPT`, `geneformer`, `nf-core/foo`, `AlphaFold` — many tool names start with lowercase or contain hyphens. The current filter only catches `[A-Z][A-Za-z]+` patterns. Should be: split on whitespace, strip punctuation, keep tokens >= 3 chars that aren't English stopwords, and use them as-is (case-insensitive).

**3. No "Tavily site:github.com" fallback in Methodology.** Methodology has the full paper title (a much stronger search anchor than the user's input) but doesn't do its own pinned-domain search. Cheapest improvement: when `github_url=null` after extraction, run one `"<paper_title>" site:github.com` query before declaring failure.

**4. No use of bioRxiv "Code availability" sections or PMC's structured "Data availability" links.** PMC papers almost always have a "Code availability" subsection. Researcher could parse that explicitly when the source URL is `pmc.ncbi.nlm.nih.gov`.

**5. Failing fast at coding without a partial report is harsh.** The Synthesizer should still emit a report explaining what was found (PMC paper, abstract, expected outputs) and what was missing (github_url). The user is left with `state.json` and a one-line error.

**6. The token cost is *good* news for once.** Failing fast at 10k tokens (vs. 80k+ for the wet-lab failure) is the right behavior — the system avoided spending money on a clearly broken pipeline. Credit where due.

### Errors logged
- `[coding] No github_url in reproducibility target: github_url is null or missing`
- Methodology `extraction_notes[0]`: `"No GitHub repository URL was present in the provided source material."` — accurate but does not mention that the resolver tried/skipped.

### Verdict
**Pipeline-level: hard fail, fast.** The resolver heuristics need to grow up to handle real paper-title patterns. This is **the most fixable failure** in the test set.

---
## Test 4 — Dry lab — Riboformer (Nat Commun 2024, lingxusb/Riboformer)

**Task ID:** `51aaf8bc` · **Pipeline status:** `error` · **Tokens:** 9,744 (Methodology 7.4k + Researcher 2.3k; Synthesis skipped)

### Phase results
| Phase | Status | Notes |
|---|---|---|
| research | success | Real paper (Nat Commun 2024) + repo (lingxusb/Riboformer) found |
| extraction | success | `github_url` populated, `main_script` populated as a notebook path |
| coding | **error** | Notebook execution failed: `ModuleNotFoundError: No module named 'numpy'` |
| synthesis | **skipped** | Despite a complete `dry_lab_51aaf8bc_run.json` artifact existing |

### What actually happened

Coder cloned `https://github.com/lingxusb/Riboformer` cleanly, found the requested entry point notebook, converted it via `nbconvert`, and tried to execute the first cell — which immediately failed on `import numpy`. Then ran the diagnostics layer which tried to "download" each `expected_outputs` entry as if it were a remote file path, all 7 of which failed because they're paper figure captions ("Fig 2b", "Fig 2c", etc.).

### Root causes (multiple, layered)

**1. No requirements file → no install at all.** `requirements_install.stdout = "NO_REQUIREMENTS_FILE"`, `success=true`. The CPU-only torch / pip install path is **gated on the existence of `requirements.txt`/`environment.yml`**. When neither exists, the Coder declares install successful and proceeds to run code in an empty venv. **Numpy isn't installed because nothing told the venv to install anything.**

**2. No fallback "import scan" to populate a minimum env.** A trivial improvement: `grep -rE "^(import|from) " *.py *.ipynb` in the cloned repo, build the set of top-level imports, install the well-known scientific-python ones (`numpy scipy pandas matplotlib scikit-learn torch tensorflow jupyter nbconvert`). This would have made Test 4 reach the *next* failure (missing data files), which is more informative.

**3. Data files on Google Drive, never downloaded.** Methodology extracted `data_download_urls: ["Google Drive"]` — a string label, not a URL. The schema accepts this because it's `List[str]`, but it's semantically null. Coder never attempted to download anything. Then the notebook tries to read `../Datasets/GSE139036 disome/Disome_SIS.txt` (literal path with a space — already a smell) which doesn't exist.

**4. `expected_outputs` is consumed as file paths but is described in free text.** From `protocol_51aaf8bc.json`:
```json
"expected_outputs": ["Fig 2b", "Fig 2c", "Fig 2e",
                     "Model prediction and source data for GSE77617", ...]
```
Coder's diagnostics path: `[coder] Downloading expected output: /home/daytona/repo/Fig 2b` → fail. Repeated 7 times. **Schema says these are paper deliverables; Coder treats them as repo paths.** Either rename the field, or have Coder **only** treat entries that match a file-path regex as downloadable and ignore the rest.

**5. Notebook entry point with `discovered: false`.** Methodology pre-supplied `main_script`, so the `find -maxdepth 4` discovery was bypassed. That's fine, but the diagnostic tag `discovered: false` is misleading — it sounds like a failure when it actually means "Methodology hinted, didn't need discovery." Rename to `via_methodology_hint: true` for clarity.

**6. Synthesis skipped despite a complete `dry_lab_*_run.json` artifact.** This is the biggest waste: the system collected real signal (10 data files found in repo, `random_seeds_set=false`, README captured, full stderr) — exactly what a Reproducibility Score report is supposed to consume — and then threw it away because the supervisor halted on coding error. **The dry-lab path *especially* needs synthesis-on-failure** because failed reproductions are *the point* of a Reproducibility Score.

### Critical assessment

**1. The Coder for dry-lab needs a "make a best-effort env" mode.** Real research repos often have no requirements file at all (a third of academic ML repos by my read). The current behavior — install nothing, then run, then fail on `numpy` — is the worst of all worlds.

**2. Honest bright spot: the diagnostics layer.** `dry_lab_51aaf8bc_run.json` correctly identifies that the repo has no fixed seeds, doesn't require GPU, has a README, lists the 10 data files actually present in the repo, and surfaces the data-loading code refs. **This is exactly what the rubric wants.** It's wasted because synthesis never runs.

**3. `download_errors` should be filtered upstream.** Trying to download a file literally called `"Fig 2b"` is silly. If Coder must consume `expected_outputs`, classify each entry: starts-with-/ → file path, matches `Fig|Table|Figure|Supplementary` → paper deliverable (skip), all-caps GSE-prefix → GEO accession (could be fetched separately).

**4. Cost is appropriately small (9.7k tokens).** Like Test 3, failing fast at the first hard error is the right call cost-wise — but only if the user gets *any* report at all. Right now they get error JSON.

### Errors logged
- `[coding] Main script exited with non-zero status: ... CellExecutionError ... ModuleNotFoundError: No module named 'numpy'` (~6kB traceback in `state.errors[0]`)
- 7 download failures for non-file entries in `expected_outputs` (logged as warnings, not in `state.errors`)

### Verdict
**Pipeline-level: hard fail.** But the diagnostics that *did* run are good and would produce a useful FAIL-grade Reproducibility Score report — if synthesis weren't gated on coding success.

---
# Cross-cutting analysis & remediation plan

## Two failure categories — and they need separate workstreams

The four tests exposed two structurally different failure modes. Conflating them in one fix-list misallocates effort.

### Category A: Honest failures (Tests 2, 3, 4)
Pipeline errored, user got nothing useful. The system **knows** it failed, the issue is graceful-degradation hygiene: persist intermediate state, render a "failed at: X" report, accumulate constraints across retries. **Fixing these unblocks dry-lab as a feature** (failed reproduction → FAIL-grade score is *the point*).

### Category B: Silent successes (Test 1) — the more dangerous class
Pipeline reports `success`, output is scientifically wrong (FACS modeled as a transfer, magnetic stand as a flat plate, no per-well loop, Bioanalyzer as a placeholder, 4-of-12 steps actually do anything). **No alarm fires.** A bench scientist who trusts the headline `simulation_passed: true` ships a broken protocol.

If we fix only Category A, the system gets *more* dangerous — more "successes" of Test 1's caliber, with no triggering signal that something is wrong. Category B fixes are about adding correctness signals beyond `simulation_passed`.

---

## Prioritized remediation — Category A (graceful degradation)

### A1. Synthesis-on-failure — **highest leverage, lowest cost**
**Root cause:** `agents/supervisor.py` halts before synthesis whenever any blocking phase errors. So Tests 2/3/4 — all of which had real signal collected (extracted JSON, enrichment audit, `dry_lab_*_run.json`, full stderr) — produced no report.
**Fix:** In `run_pipeline`, on any phase error, still call `synthesizer_agent(task_id)` (it already reads `state.json` to find artifacts). Add a "Failed at: {phase}" header section to both report templates. For dry-lab, this directly produces the FAIL-grade Reproducibility Score that the rubric describes.
**Tests changed:** 2, 3, 4 all gain a real report instead of a one-line error.

### A2. Persist every Coder attempt to disk
**Root cause:** `agents/coder.py` uploads each attempt to the sandbox, simulates, and on failure throws the script away. After Test 2's 4 attempts, `workspace/generated_code/` contained nothing for `task_id=d44d8348`.
**Fix:** Before `upload_file(...)`, also write to `workspace/generated_code/protocol_{task_id}_attempt{n}.py`. Also write the corresponding stderr to `_attempt{n}.stderr`. On final failure, the user (and the system itself) has the four broken scripts and four error traces.
**Tests changed:** 2 (debuggable post-mortem); enables every other Coder fix below.

### A3. Coder retry loop must accumulate constraints
**Root cause:** Test 2 produced four distinct error classes in four attempts (missing `pick_up_tip`, null `volume_ul`, hallucinated `wait_for_block_temperature`, missing `open_lid`). Each retry started from a fresh interpretation of the JSON with only the most recent stderr. No memory.
**Fix:** Maintain a `learned_constraints: list[str]` across retries. After each failure, the LLM is asked to produce *both* a fixed script *and* a one-line constraint to append (e.g., `"Always call .open_lid() before any pipette move into Thermocycler-loaded labware"`). The next attempt's system prompt prepends all accumulated constraints. This is essentially episodic memory for the retry loop.
**Tests changed:** 2 likely passes within 4 attempts; future similar protocols converge faster.

### A4. Opentrons API cheatsheet in Coder system prompt
**Root cause:** Hallucinated `wait_for_block_temperature` (Test 2 attempt 3). The real method is `set_block_temperature`.
**Fix:** Generate (once, offline) a JSON list of valid methods on `ProtocolContext`, `InstrumentContext`, `ThermocyclerContext`, `MagneticModuleContext`, `TemperatureModuleContext`, `Labware`. Inject as a "ALLOWED API" block in the Coder's system prompt. Defensive layer beyond A3.
**Tests changed:** 2 (this specific class of bug eliminated).

### A5. Smarter `requirements` file discovery for dry-lab
**Root cause:** Test 4 — `requirements_install.stdout = "NO_REQUIREMENTS_FILE"`. But Riboformer ships `env.yml` at the repo root (verified via GitHub API). The Coder only looks for the canonical names `requirements.txt` / `environment.yml`.
**Fix:** Glob for `requirements*.txt`, `environment*.yml`, `env*.yml`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`. For pyproject/setup.py, fall back to `uv pip install -e .`. For env.yml/environment.yml, use `conda env create` if conda is available, else parse `dependencies:` and translate to `pip install`.
**Tests changed:** 4 (numpy actually installed, run reaches the next failure mode — missing data — which is the *correct* failure to report).

### A6. Best-effort env synthesis when no env file exists
**Root cause:** Same Test 4 path, secondary fallback. Even with A5, some repos genuinely have nothing.
**Fix:** Run `python3 -c "import ast,sys; ..."` in the sandbox over all `.py` and `.ipynb` files; collect top-level imports; install the well-known scientific stack (`numpy scipy pandas matplotlib scikit-learn torch tensorflow jupyter nbconvert biopython`) for any import that maps to a known package. Mark in the report: "env was synthesized — reproducibility score should be discounted accordingly."
**Tests changed:** 4 (and any future no-env-file repo).

### A7. CLI exit code masking — verify and fix
**Root cause:** Background-task wrapper reported `exit code 0` for Test 2 even though `run_cli.py` ends with `sys.exit(0 if result['status'] == 'success' else 1)` and the printed status was `error`. Either I'm misreading the wrapper or there's an actual bug.
**Fix:** Add a final `print(f"[cli] exit_code={1 if status=='error' else 0}")` and verify against the wrapper's report. Cheap, makes error vs. success unambiguous to any caller.
**Tests changed:** Tooling consistency only.

---

## Prioritized remediation — Category B (silent-success detection)

### B1. Per-step liquid-handling-call ratio check (not just total > 0)
**Root cause:** Test 1 cleared the silent-no-op detector with 9 liquid calls across 12 steps, but only 4 of 12 steps emitted any liquid handling — the rest were `protocol.comment()`. The current regex (`\.transfer|distribute|consolidate|aspirate|dispense|mix|blow_out|pick_up_tip|drop_tip`) is checked once across the whole script.
**Fix:** Parse the generated script with `ast`; for each step (delimited by `# Step N` comments or a structured emission convention), count liquid-handling calls. If `liquid_steps / total_steps < 0.5` and any step has `volume_ul` populated in the source JSON, mark `simulation_passed: true, fidelity_warning: true` with a list of skipped steps. Surface in the report headline, not buried in confidence notes.
**Tests changed:** 1 (no longer reports a clean "success"; produces a fidelity-warning header that matches reality).

### B2. Methodology must classify out-of-scope steps explicitly
**Root cause:** Test 1's step 1 was FACS sorting — categorized as `action: "transfer"` because the schema has no `out_of_scope` action.
**Fix:** Add `Literal[..., "out_of_scope_setup", "out_of_scope_qc", "off_deck_instrument"]` to `ProtocolStep.action`. Update Methodology's system prompt to use these for FACS/Bioanalyzer/manual-prep steps. Coder emits `protocol.comment()` only (no fake transfers) and the fidelity check (B1) excludes these from the denominator.
**Tests changed:** 1 (FACS, Bioanalyzer, magnetic-stand-only steps no longer pollute the protocol).

### B3. Module-aware labware loading
**Root cause:** Test 1's magnetic stand became a `nest_96_wellplate_200ul_flat`. Bioanalyzer became another well plate.
**Fix:** Coder system prompt: explicit "if `labware_setup` mentions magnetic / temperature / thermocycler / heater-shaker stand, you MUST use `protocol.load_module(...)` followed by `module.load_labware(...)`. NEVER substitute a flat plate." Plus a cheatsheet of valid module strings (`"magnetic module gen2"`, `"thermocycler module v2"`, etc.).
**Tests changed:** 1 (real magnetic module loaded; bead cleanup actually engages the magnet); generally raises Coder labware quality.

### B4. Per-well loop / parallel sample concept in the schema
**Root cause:** Test 1's Smart-seq3 protocol does single-well operations across the board (`sample_plate.wells()[0]`) — it would silently process only well A1 of a 96-well plate. Schema has no concept of "applies to all samples."
**Fix:** Add `applies_to_wells: Literal["A1_only","row","column","plate","custom"] = "plate"` to `ProtocolStep` (default `"plate"` because most steps are parallel). Coder emits `for well in plate.wells():` loops accordingly. Methodology populates from context.
**Tests changed:** 1 (96-cell parallelism is no longer silently dropped).

### B5. PIE provenance: distinguish notes-derived from missing
**Root cause:** Test 1's `field_sources: null` for notes-mining fills is correct-but-ambiguous (looks like "no citation").
**Fix:** Sentinel string `"<notes_mining: step.notes>"` in `field_sources` for notes-derived fills. Synthesizer renders it as `"derived from extraction notes"` in the report.
**Tests changed:** 1 (audit trail no longer misleading).

### B6. Fidelity-warning headline in the wet-lab report template
**Root cause:** Test 1's report headline says `simulation_passed: true` with no qualifier; the fidelity issues are buried in the "Confidence notes" section that comes after the script.
**Fix:** Synthesizer template: if B1's `fidelity_warning` is true OR `still_null > liquid_steps`, the simulation-result section reads `Pass (with caveats)` and lists them above the fold. The bench scientist sees the warning before they read the script.
**Tests changed:** 1 (and any future "passing-but-thin" wet-lab run).

---

## Implementation order (suggested)

1. **A1** (synthesis-on-failure) — 1-2 hour change to `supervisor.py` + report templates. Unblocks 3/4 failing tests immediately.
2. **A2** (persist Coder attempts) — 30-min change to `coder.py`. Required to debug A3 properly.
3. **A5 + A6** (env discovery + best-effort) — 2-3 hour change to `coder.py` dry-lab path. Test 4 starts producing partial reproductions.
4. **B1 + B6** (fidelity check + headline) — 2-3 hour change. Test 1's misleading "success" headline goes away. **Do this before A3/A4** because otherwise the wet-lab fixes will be measured against a broken success criterion.
5. **B2 + B3 + B4** (schema/labware/loop fixes) — 1-day change. Substantively improves wet-lab scientific quality.
6. **A3 + A4** (constraint-accumulating retry + API cheatsheet) — 1-day change to `coder.py`. Test 2-class bugs converge.
7. **A7 + B5** (cleanup) — 1-hour each.

## What I would *not* do
- **Don't add more agents.** The five-agent split is right. The fixes above are all to existing agents.
- **Don't increase `WET_LAB_MAX_SIM_ATTEMPTS` beyond 4.** Test 2 shows the loop diverges; more attempts of a divergent loop is just more tokens. A3 fixes the cause.
- **Don't widen PIE's `MAX_QUERIES`.** Test 1's 12 still-null fields were *not* PIE's fault — they were genuine gaps in the source material. Spending more Tavily queries wouldn't fill them.
- **Don't switch to a more expensive model for any agent.** Test 2's API hallucination is a prompt/grounding issue, not a capability issue. Model-size escalation hides the real fix.

## Token-cost note
Across the four tests: **225,537 tokens** total. ~52% in synthesis (Test 1 alone) + enricher. The synthesis-on-failure fix (A1) will *increase* total tokens (3 more synth runs). Worth it — but watch enricher token cost: 48-51k per wet-lab run is high relative to its 2-6 fills. Future optimization: PIE could batch step-level note-mining into one LLM call rather than per-field iteration.
