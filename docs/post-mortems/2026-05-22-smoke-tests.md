# BioSwarm Smoke Test — 2026-05-22

**Reviewer's lens.** A senior lab-automation scientist auditing a paper→protocol pipeline against the README's headline promises:
1. *Every value carries its full origin as a typed FieldLineage chain.*
2. *The LLM can't fabricate citations.*
3. *The system is allowed to refuse to act.*
4. *No raw text passes between agents.*
5. *Closed-loop iteration, max 3 cycles, every revision in the lineage.*
6. *Reproducibility Score for dry-lab.*

Goal set with the user this session: **all advertised repo functionality runs consistently, elegantly, and holds up to high scientific standards.**

**Constraint.** Single-tenant `workspace/state.json` → tests run sequentially.

## Test matrix

| # | Mode | Command | Why this test |
|---|------|---------|---------------|
| A | wet_lab | `--input demo --demo-paper rt-qpcr --enable-iteration --trace-field "step_1.template_amount_ng"` | The headline demo from the README; validates closed-loop, FieldLineage tree, citation registry |
| B | wet_lab | `--input demo --demo-paper rt-qpcr --trace-field "step_1.template_amount_ng"` | Same demo, iteration off — baseline for what the demo path looks like without the loop |
| C | wet_lab | `--input "NEBNext Ultra II DNA Library Prep for Illumina protocol"` | Real-paper full pipeline: research → methodology → PIE → coder → synthesis |
| D | dry_lab | `--input "scGPT single-cell foundation model Cui 2024 Nature Methods github"` | Real-paper dry-lab; tests env discovery, CPU-only torch strategy, fail-with-report |
| E | wet_lab | demo + `--enable-iteration --trace-all-fields` | The aggregate-summary + per-field tree rendering surface |
| F | mixed | invalid demo name, nonexistent trace field, empty input, trace-field without iteration | Error-message quality and input validation |

Each test was graded against the headline README promises listed above, *not* just "did it exit zero."

---

## Test A — Wet-lab demo + iteration (the headline)

**Task ID:** `19e372ee` · **Pipeline status:** `success` · **Tokens:** 5,867 · **Wall time:** ~12s · **Iterations:** 2, converged.

### What worked
- Two iterations: `inhibition_suspected` (100 ng, no amplification) → `reduce_template` to 25 ng → `clean` regime, Cq=27.93 → `converged`. The deterministic rule, the L20 mid-template diagnose case, and the closed-loop exit conditions all fire correctly.
- FieldLineage chain renders as a tree with cyan/magenta/yellow/green colour bands per source type.
- All six registry citations report `verified` against their live source pages.
- Replanner rationale is plausible English and cites only registry keys.

### What's broken — scientifically, not just cosmetically

**A.1 — The headline promise is not validated on the demo path.** The README says *"Every typed field gets a FieldLineage(paper_span) record citing the source."* The aggregate summary for this run shows `paper_span: 0 records`. The demo cache (`workspace/demo_cache/rt_qpcr_protocol.json`) ships with `"field_lineage": {}` on every step, so the lineage chain begins at `oracle_reading` with no upstream provenance. A reviewer running the README's quickstart command sees a closed loop with no paper origin — exactly the trust hole the lineage feature was designed to close.

**A.2 — Coverage detection is silently broken.** The simulation log reports `coverage=1.00 via heuristic_fallback`. The intended branch is `coverage_method="markers"`, gated on `_STEP_MARKER_RE = re.compile(r"^#\s*STEP\s+(\d+)\b", re.MULTILINE)`. The LLM emits `    # STEP 1` (4-space indent, inside `def run`). The regex requires `#` at column 0, so it never matches and *every* wet-lab run falls back to heuristic. Two downstream consequences:
- The fidelity warning copy in the report reads "LLM did not emit `# STEP N` markers" — **false**. The LLM did emit them. The report is now blaming the LLM for a regex bug.
- Per-step skipped-step accounting (`skipped_step_numbers`) is permanently empty under heuristic_fallback.

**A.3 — `fidelity_warning` is False in state despite heuristic_fallback being used.** `state.coding.fidelity_warning = False` in the saved state for this task. The coder set it to `low_coverage or heuristic_used` (= True). The reason: `run_pipeline_from_demo` (the `--demo-paper` skip path) doesn't copy any of `liquid_step_coverage`, `coverage_method`, `skipped_step_numbers`, or `fidelity_warning` from the coder contract into state — that copy happens only in the regular `run_pipeline`. The demo path quietly drops the signal that would have flagged A.2.

**A.4 — CLI iteration events drop their payload.** The supervisor emits per-iteration events with `cq`, `regime`, `action`, `iteration_index` extras. The CLI sees:
```
[cli] iteration: starting
[cli] iteration: success
[cli] iteration: starting
[cli] iteration: success
```
Two identical pairs, no idea what happened inside. The frontend (`web/app.js:buildIterationLines`) renders those extras correctly. The CLI doesn't.

**A.5 — Rationale field truncated mid-word.** Renderer caps at 160 chars: `rationale = The selected action is to reduce the template input because the current condition shows no amplification at a high template load (100 ng), which is consistent w`. Stops in the middle of "with." A 160-char limit is fine; truncating to the nearest word boundary and appending `…` is the polished version of this.

### Verdict
**Pipeline-level: success. Scientific-utility: B-.** The closed loop genuinely works and converges; the citation discipline is real. But the headline FieldLineage promise is not exercised by the headline demo, the coverage metric is busted, and the demo path drops fidelity signal — all three things a reviewer would catch in the first ten minutes.

---

## Test B — Wet-lab demo, iteration off

**Task ID:** `795ec107` · **Pipeline status:** `success` · **Tokens:** 3,887 · **Wall time:** ~8s.

### What's broken

**B.1 — "Iteration outcome: PENDING in 0 iterations" when iterations were never enabled.** `_iteration_outcome()` returns `("reset", "PENDING")` when no outcome flag is set. The disabled case and the "iterations enabled but didn't reach a terminal state" case are conflated. A reviewer reading "PENDING" reasonably assumes the system gave up.

**B.2 — `[cli] field not found: step_1.template_amount_ng` is misleading.** The field exists in the protocol. It just has no lineage attached (because demo cache ships empty `field_lineage`). The error should be "field exists but has no lineage record" — different problem, different remedy.

**B.3 — Same A.2 / A.3.** Heuristic fallback fires; `state.coding.fidelity_warning` is False because the demo path doesn't copy it through.

### Verdict
**Pipeline-level: success. Scientific-utility: C.** Without iteration the demo produces a generic 3-call protocol, but every demo-path quirk above still applies.

---

## Test C — Wet-lab on a real paper (NEBNext Ultra II DNA Library Prep)

**Task ID:** `8232bfa0` · **Pipeline status:** `success` (after 2 fix attempts) · **Tokens:** 90,130 · **Wall time:** ~80s.

### What worked
- Research → Methodology → PIE → Coder → Synthesizer round trip.
- PIE filled `step_1.volume_ul = 50 µL` from `protocols.io` at confidence 0.96.
- Self-correction recovered from two distinct simulator errors:
  - Attempt 1: `'thermocycler_module_gen2' is not a valid module load name` (LLM used underscores; OT-2 expects spaces).
  - Attempt 2: `DeckConflictError: thermocyclerModuleV2 in slot 7 prevents opentrons_96_tiprack_20ul from using slot 8`.
  - Attempt 3: clean simulation, 12 liquid-handling calls.
- `protocol_{task_id}_attempt{1,2,3}.py` and `.stderr` files persisted to disk (A2 from May-4 remediation lands).

### What's broken

**C.1 — Two distinct retry-loop bug classes per the May-4 post-mortem are still present.** The constraint accumulation (A3 in the prior post-mortem) was never implemented. `WET_LAB_FIX_SYSTEM_PROMPT` is static; only the latest `stderr` is forwarded. The system genuinely solved this protocol in 3 attempts, but for a denser protocol (Smart-seq3 or the May-4 NEBNext run) it diverges. The structural cause hasn't moved.

**C.2 — Hallucinated Opentrons module name (`thermocycler_module_gen2`).** A4 in the prior post-mortem ("seed the Coder's system prompt with the exact list of `ThermocyclerContext`/`ModuleContext` method/identifier names") was also not implemented. The valid name list is printed in the simulator's error message, but only after a wasted attempt.

**C.3 — Tautological labware substitution comment.** The generated script's header says:
```python
protocol.comment("Non-standard labware substitution: opentrons_24_tuberack_nest_1.5ml_snapcap used for opentrons_24_tuberack_nest_1.5ml_snapcap, …")
```
Same labware on both sides of "used for." LLM noise the synthesizer reproduces uncritically.

**C.4 — Volume-significant labware substitution unflagged.** The same comment substitutes `usascientific_96_wellplate_2.4ml_deep` for `nest_96_wellplate_2ml_deep`. 2.4 mL vs 200 µL is a 12× volume difference between candidate substitutes — a bench scientist running this in the wrong well would dilute their library to the point of unusability. No fidelity warning fires.

**C.5 — Report lacks a "Field Lineage Summary" section despite 8 of 10 steps carrying lineage records.** The protocol JSON on disk has paper_span records on `volume_ul`/`temperature_celsius`/`duration_seconds` for steps 1, 2, 3, 4, 6, 7, 8, 10. The wet-lab report template only renders the Field Lineage Summary when iterations ran. So the very capability the README opens with — "Every value the system produces carries its full origin as a typed FieldLineage chain" — is invisible in the report for the real, full-pipeline run.

**C.6 — `# STEP N` regex bug from A.2 fires here too.** Coverage method again `heuristic_fallback`. Fidelity warning text again blames the LLM for not emitting markers, when the script visibly contains `# STEP 1` through `# STEP 10`.

**C.7 — Synthesizer prompt is 38k tokens for one run.** Same scaling cliff as the May-4 post-mortem — the entire raw research bundle, the full protocol JSON, the PIE enrichment log, and the script are all stuffed into the user payload. This is fine for the hackathon scale but won't survive a 50-step protocol.

### Verdict
**Pipeline-level: success. Scientific-utility: C+.** Self-correction works, PIE works, but the report under-sells the lineage feature, the fidelity warnings misfire, and the labware substitution comments would scare a wet-lab scientist on careful read.

---

## Test D — Dry-lab on scGPT (Cui 2024, Nature Methods)

**Task ID:** `805f95c3` · **Pipeline status:** `error` · **Tokens:** 61,808 · **Verdict in report:** `FAIL`.

### What worked
- Research found the right paper and the right repo (`bowang-lab/scGPT`).
- Env discovery found `docs/environment.yml`, `docs/requirements.txt`, and `pyproject.toml` (A5 working).
- Failed clean-up: sandbox was disposed.
- **Synthesis-on-failure (A1) produced a real Reproducibility Score report.** Verdict line is `**Reproducibility Score: FAIL**`. Root cause is correctly identified (`No space left on device (os error 28)` while extracting `torch-2.12.0`). The recommendations section is competent.

### What's broken — and one is a real blocker

**D.1 — CPU-only torch strategy only strips `requirements*.txt`, not `pyproject.toml`/`setup.py`.** The code that runs after `torch_in_repo` detects torch in any discovered env file:
```python
for rf in req_txt_files:
    daytona_tool.run_cmd(sandbox, "sed -i -E '/^[[:space:]]*(torch.../d' " + rf, ...)
```
`req_txt_files` is the requirements-text subset of `discovered_full`. For a pyproject-based repo (scGPT), the strip is a no-op — and the subsequent `pip install -e .` resolves torch from PyPI default index, pulls 400 MB of nvidia wheels, and **exhausts the sandbox disk**. This is the same class of failure the May-4 post-mortem's A5/A6 was meant to fix, only one level up. The strip pattern needs to extend to pyproject `[project.dependencies]` and `setup.py install_requires` blocks.

**D.2 — `cpu_torch` preinstall failed but the system continued.** Log line: `cpu torch install exit_code=2 success=False` → `WARNING: CPU torch preinstall failed — proceeding anyway`. The failure was likely the sandbox's first failed pip resolution; we don't capture *why* (only exit code). The pipeline then ran a full editable install which immediately re-resolved torch from default index. The CPU-only preinstall is supposed to be the constraint that makes the editable install pick it up; without it, the install path is the GPU one.

**D.3 — Methodology emitted `??` placeholder URLs.** From `protocol_805f95c3.json`:
```json
"data_download_urls": [
  "https://doi.org/10.6084/m9.figshare.??",
  "https://zenodo.org/record/??"
]
```
The LLM noticed the source mentioned Figshare/Zenodo and synthesised placeholder URLs with `??` rather than admitting it didn't see a concrete link. `extraction_notes` honestly flag this — but the schema accepts `List[str]` of *anything*, so these strings will be passed to the Coder's data downloader, which will then fail loudly on URLs that obviously aren't real. The schema should reject any `data_download_urls` entry that fails a simple plausibility check (`urlparse` + `??` filter).

**D.4 — `expected_outputs` continues to be paper deliverables, not file paths.** Same observation as May-4 Test 4. Entries like `"A foundation model for single-cell multi-omics (scGPT)"` and `"Figure 4: scGPT gene expression prediction"` are paper-level claims, not files the run will produce. The synthesizer's "Output Verification" section handled this gracefully (`"These are paper figures/datasets, not files in the repo"`), but the schema still allows freely-mixed entries.

**D.5 — `main_script: null` plus no fallback discovery.** scGPT ships notebooks under `tutorials/`. Methodology's resolver didn't pick one (the README excerpt doesn't directly name a Python file). The Coder's entry-point discovery (`find -maxdepth 4 -name 'demo.py' …`) would have caught the notebooks — but the dry-lab path **bailed before reaching discovery**, because dependency install failed at the editable-install step. The discovery fallback is gated on a successful install. Should run regardless and feed the report.

### Verdict
**Pipeline-level: hard fail, with a useful report. Scientific-utility: B for the report, D for the install path.** The graceful-degradation work (A1, A5 env discovery, FAIL-verdict synthesis) is the real win since the May-4 run. The strip-pattern hole + cpu-torch-soft-fail combo is a regression of the CPU-only design's intent — pyproject is now the most common env file in 2026 ML repos, and we miss it.

---

## Test E — Trace-all-fields rendering

**Task ID:** `6c3f92f9` · **Pipeline status:** `success` · **Iterations:** 2.

`--trace-all-fields` on the demo path renders a single field tree: `step_1.template_amount_ng`. The other typed step fields (`volume_ul`, `source_location`, `destination_location`, `temperature_celsius`, `duration_seconds`) have no lineage because the demo cache ships empty `field_lineage` and the demo path skips Methodology's `_attach_paper_span_lineage`. So `--trace-all-fields` is functionally equivalent to `--trace-field step_1.template_amount_ng` on the demo path.

### Verdict
Same root cause as A.1. The aggregate summary header is correct; the per-field-tree section is sparse because there's only one field with lineage.

---

## Test F — Edge cases

| Sub-test | Behaviour | Issue |
|---|---|---|
| F.1 | `--demo-paper foobar` | stderr/stdout interleave; the "demo cache not found" line lands *before* the task_id line because stderr is unbuffered. The exit code is correctly `1`. Cosmetic. |
| F.2 | Demo, no iteration, `--trace-field step_99.nonexistent` | **Pipeline ERRORED on first run with a 0-LH-call script.** Same demo input that succeeded in Tests A/B produced a script with `protocol.comment(...)` only and no `pipette.transfer(...)`. The silent-no-op detector caught it correctly. So **wet-lab codegen on the demo is non-deterministic — sometimes 3 LH calls, sometimes 0**, and the system retries on simulator errors but *not* on a silent-no-op. The user is one bad LLM mood away from a failed demo. |
| F.3 | `--input ""` | Pipeline **runs the full thing on garbage**. Tavily got "Ancient Dental Calculus Sample Decontamination and Crushing" for the empty query. ~118k tokens spent, ends with the silent-no-op detector tripping (steps mostly manual). No input validation at the CLI or supervisor layer. |
| F.4 | Demo, no iter, `--trace-field step_1.template_amount_ng` | Same A.1/B.2 — the field exists but has no lineage; CLI says "field not found." |

### Verdict
**F.2 and F.3 are the substantive ones.**
- F.2 — silent-no-op on the codegen path needs a regen retry, not just an abort. (One LLM call to regenerate is cheaper than the user re-running.)
- F.3 — empty / trivially-short input is a footgun and a 100k-token tax. Should be a one-line check in `run_cli.py` and `server.py`.

---

# Cross-cutting analysis

The May-4 post-mortem split the failure surface into **Category A (honest failures, graceful degradation)** and **Category B (silent successes, fidelity)**. Most of the Category A items shipped: synthesis-on-failure, per-attempt persistence, env discovery, exit-code printing. The Category A items that *didn't* ship (constraint-accumulating retry, API cheatsheet) are still draining attempts in C.1/C.2.

Two new structural classes emerge from this round:

### New Category D — "Demo path is a separate codebase."
`run_pipeline_from_demo` is an explicit shortcut that skips Research/Methodology/Enrichment. But it also silently drops:
- Coder fidelity fields (A.3 — `fidelity_warning`, `liquid_step_coverage`, `coverage_method`, `skipped_step_numbers` never make it to state)
- The paper_span lineage records that Methodology would have attached (A.1 — the demo cache ships empty `field_lineage`)
- (probably others — every supervisor-side state mutation needs auditing against the demo path)

Result: the demo path — the only path the README's quickstart exercises — quietly under-reports its own state. The fixes are mechanical (mirror the supervisor's field-copy block; pre-populate paper_span on demo cache) but the *governance* fix is the real point: there shouldn't be two codepaths to invariants. Have `run_pipeline_from_demo` call a shared `_apply_coder_result_to_state(state, coder_result)` helper that the regular path also uses.

### New Category E — "Headline visibility."
The README leads with FieldLineage. Yet:
- On the demo path: chain has no paper_span node (A.1).
- On the real wet-lab path: lineage records exist on disk but the report omits the Field Lineage Summary (C.5).
- On the dry-lab path: lineage doesn't apply (dry-lab has no field-level provenance model).

A scientist running the system today and reading the report would not see the headline feature working. Even when it does work (8/10 steps in Test C), it's invisible.

---

# Prioritized remediation

Each item names: the file(s) it touches, the smallest possible test that proves it, and the test(s) above that flip from broken → green.

## P0 — quick, high-leverage, isolated

### P0.1 — Fix the `# STEP N` coverage regex (B.1, B.6, C.6)
**Change.** `agents/coder.py:_STEP_MARKER_RE = re.compile(r"^\s*#\s*STEP\s+(\d+)\b", re.MULTILINE)` (add `\s*` after `^`).
**Test.** New unit test in `tests/test_coder_coverage.py` feeding an indented `    # STEP 1` script and asserting `method == "markers"`.
**Tests flipped.** A.2, B.1, C.6 — coverage reports honest method, fidelity warning text no longer falsely blames the LLM.

### P0.2 — Wire coder observability fields through `run_pipeline_from_demo` (A.3)
**Change.** In `agents/supervisor.py:run_pipeline_from_demo`, after `coder_agent(...)` returns, mirror the same block from `run_pipeline` that copies `attempts`/`liquid_step_coverage`/`coverage_method`/`skipped_step_numbers`/`fidelity_warning` into `state.coding`. Better: extract that block into a shared `_apply_coder_result_to_state(state, coder_result)` helper.
**Test.** Extend `tests/test_supervisor_iteration_phase.py` to assert `state.coding.fidelity_warning` round-trips on the demo path.
**Tests flipped.** A.3, B.3.

### P0.3 — Input validation in `run_cli.py` and `server.py` (F.3)
**Change.** Reject empty or whitespace-only `--input` / `input` request body. If `--demo-paper` is set, treat input as optional (the canonical "demo" sentinel is fine). Otherwise require ≥ 8 non-whitespace chars.
**Test.** `tests/test_cli_input_validation.py`.
**Tests flipped.** F.3.

### P0.4 — Distinguish "field has no lineage" from "field doesn't exist" (B.2, F.4)
**Change.** In `run_cli.py`'s trace-field block, check whether the field exists in the protocol (parse `sequential_steps[].step_number` + field name) before reporting "field not found." Three states: not-in-protocol, in-protocol-no-lineage, has-lineage.
**Test.** `tests/test_cli_trace_field_messages.py`.
**Tests flipped.** B.2, F.4.

### P0.5 — Iteration-outcome renderer: distinguish "disabled" from "pending" (B.1)
**Change.** `tools/lineage_renderer.py:_iteration_outcome` returns `("reset", "DISABLED")` when `enable_iteration` was False; `("reset", "NOT_REACHED")` when iteration ran but didn't terminate; `"PENDING"` only for the brief mid-run state. Also fix `web/app.js:renderAggregate` for parity. Plumb the `enabled` flag through (IterationsState already has it).
**Test.** `tests/test_lineage_renderer.py` extension.
**Tests flipped.** B.1, F.4.

### P0.6 — Word-boundary rationale truncation (A.5)
**Change.** Renderer: trim to nearest whitespace before adding `…`.
**Tests flipped.** A.5 (cosmetic).

## P1 — moderate, addresses fundamental promises

### P1.1 — Pre-populate `paper_span` lineage in the demo cache (A.1) — **the headline fix**
**Why this matters.** Without it, the README's first promise ("Every typed field gets a FieldLineage(paper_span) record") is unverifiable from the quickstart.
**Change.** Add a `scripts/seed_demo_cache_lineage.py` (or just hand-author the JSON) so `workspace/demo_cache/rt_qpcr_protocol.json` ships with a `field_lineage.template_amount_ng = {source_type: "paper_span", paper_span: {doc_url: "demo://rt_qpcr_v1", span_id: "step_1_template_amount_ng", quoted_text: "Crude lysate; matrix-specific inhibition risk per Schrader 2012."}, citations: ["PCR_inhibition_matrix_specific_schrader_2012"]}` and similar for the temperature/duration in step 2.
**Test.** New `tests/test_demo_cache_has_paper_span.py` that loads the cache and asserts every step with a non-null typed field also has a `field_lineage[field]` record with `source_type == "paper_span"`.
**Tests flipped.** A.1, B.2 (now field is found *and* has lineage), E (paper_span counts > 0).

### P1.2 — Render "Field Lineage Summary" in the wet-lab report even without iterations (C.5)
**Why this matters.** When iteration is off but methodology + PIE wrote real `paper_span` and `enricher_fill` records, the report should surface them. Currently invisible.
**Change.** `agents/synthesizer.py`: the Field Lineage Summary template guard should be `any(step.get("field_lineage") for step in proto["sequential_steps"])`, not "iterations ran." Render aggregated counts plus the top N highest-confidence enricher fills and a paper_span sample.
**Test.** Extend `tests/test_synthesizer_lineage_section.py` to assert the section appears on a non-iteration wet-lab run with non-empty `field_lineage`.
**Tests flipped.** C.5.

### P1.3 — Silent-no-op triggers Coder regen, not pipeline abort (F.2)
**Change.** When `lh_calls == 0` after a clean simulation, treat as a recoverable codegen error and add to the retry budget. Allow up to 2 codegen-retries on the silent-no-op class (separate from sim-error retries).
**Test.** `tests/test_coder_silent_noop_retry.py` — monkeypatch `_generate_opentrons_script` to return a no-LH script on first call and a real one on second.
**Tests flipped.** F.2 — Coder converges on the demo even with a bad first generation.

### P1.4 — Methodology rejects placeholder URLs (D.3)
**Change.** `schemas/dry_lab_schema.py`: add a field validator on `data_download_urls` that strips entries failing `urlparse + path != "" + "??" not in url + "<placeholder>" not in url`. Same for `paper_source`. Log the rejection in `extraction_notes`.
**Test.** `tests/test_methodology_url_validator.py`.
**Tests flipped.** D.3.

### P1.5 — Extend torch-strip to pyproject and setup.py (D.1, D.2)
**Change.** When `torch_in_repo` is True, also rewrite torch out of `pyproject.toml` (`[project.dependencies]` and `[tool.poetry.dependencies]`) and `setup.py`/`setup.cfg` (`install_requires`). For pyproject: parse with `tomllib`, drop torch entries, write back. Capture `cpu_torch` install failure as an error, not a warning — if CPU-only torch can't be installed we shouldn't proceed.
**Test.** `tests/test_coder_torch_strip_pyproject.py` with a fixture pyproject containing `torch`.
**Tests flipped.** D.1, D.2 — scGPT install no longer pulls CUDA wheels.

### P1.6 — CLI iteration events show payload (A.4)
**Change.** `run_cli.py:cli_callback`: when `event.phase == "iteration"`, print iteration_index/cq/regime/action. Two-line format matching `web/app.js:buildIterationLines`.
**Tests flipped.** A.4.

### P1.7 — Labware substitution must surface as fidelity warning, not script comment (C.3, C.4)
**Why this matters.** Substituting `usascientific_96_wellplate_2.4ml_deep` for `nest_96_wellplate_2ml_deep` (12× volume difference) is a real physical hazard. A `protocol.comment("Non-standard labware substitution: …")` is hidden in stdout; it must also raise `fidelity_warning=True` with a structured `labware_substitutions: list[dict]` field that the synthesizer renders above the script.
**Change.** Update the Coder's codegen system prompt to emit `labware_substitutions` as a separate JSON output, not just an inline comment. Synthesizer renders them in the Fidelity Warnings block.
**Test.** `tests/test_coder_labware_substitution_warning.py`.
**Tests flipped.** C.3, C.4.

## P2 — bigger structural work (each is its own sub-task)

### P2.1 — Constraint-accumulating retry (A3 in May-4 post-mortem; C.1 here)
Carries forward unchanged from the May-4 plan. Maintain `learned_constraints: list[str]` across attempts; LLM emits both a fix and a one-line constraint each retry; subsequent attempts prepend all accumulated constraints to the fix prompt.

### P2.2 — Opentrons API cheatsheet in Coder system prompt (A4 in May-4; C.2 here)
Generate (offline) a JSON of valid module/labware/method names and inject as an "ALLOWED API" block.

### P2.3 — Per-well loop concept in the schema (B4 in May-4)
Still unimplemented; means Smart-seq3-class protocols silently process only well A1.

### P2.4 — Out-of-scope step categorization (B2 in May-4)
FACS, Bioanalyzer, manual prep — same as May-4.

### P2.5 — `expected_outputs` typing (D.4)
Schema-level distinction between file paths, paper-figure references, and dataset accessions.

---

# What I would *not* do (still)

- **Don't add more agents.** The eight-agent split is fine. All fixes above are inside existing agents.
- **Don't widen Tavily's `MAX_QUERIES`.** The bottleneck in C is methodology source quality, not query count.
- **Don't escalate model size for any agent.** Hallucinated module names (C.2) and tautological labware comments (C.3) are grounding problems, not capability problems.
- **Don't merge `run_pipeline_from_demo` back into `run_pipeline`.** The demo shortcut is legitimately useful; the right fix is to share the state-mutation helpers.

---

# Token-cost note

Across the six tests: **~285k tokens** total. F.3's empty-input run alone burned ~118k for output a reviewer wouldn't read. P0.3 (input validation) is the cheapest dollar-saving item on the list.

---

# Verification appendix — fixes landed 2026-05-22

All P0 + P1 remediation items above were landed across five parallel/sequential agent passes the same day. Test suite: **94 baseline → 165 passing / 2 skipped** (+71 focused unit tests, zero regressions).

## Re-run of the headline command after fixes

```
python3 run_cli.py --mode wet_lab --input demo --demo-paper rt-qpcr \
    --enable-iteration --trace-field "step_1.template_amount_ng"
```

| Metric (before fix → after fix) | Before | After |
|---|---|---|
| `paper_span` records in aggregate summary | 0 | **6** |
| Fields with lineage | 1 | **6** |
| `coverage_method` | `heuristic_fallback` | **`markers`** |
| Coverage value reported | `1.00` (misleading) | `0.50` (honest — step 2 is incubation, no LH calls) |
| Fidelity warning message blame | "LLM did not emit `# STEP N` markers" (false accusation) | (no false warning) |
| CLI iteration event payload | `iteration: starting/success` (bare) | `iteration 1: success — cq=none regime=inhibition_suspected action=reduce_template` |
| Rationale truncation | mid-word (`…effec`) | word-boundary (`…protocol…`) |
| First node of lineage chain | `oracle_reading` (no upstream) | `paper_span` (with `quoted_text` from notes + verified `PCR_inhibition_matrix_specific_schrader_2012` citation) |
| Wet-lab report Field Lineage section | only on iteration runs | renders whenever any step has lineage |

The lineage chain now reads `paper_span → oracle_reading [iter 1] → replanner_revision [iter 1] → oracle_reading [iter 2] → replanner_revision [iter 2]` — four source types, every citation verified, the README's headline promise visible in the demo's own output.

## Re-run of the broken edges

**F.3 (empty input)** — now rejected at CLI before any agent loads:
```
$ python3 run_cli.py --mode wet_lab --input ""
[cli] error: --input must be a non-trivial paper title/DOI/URL (got: '')
[exit 2]
```
Token cost: 0 (was ~118k).

**F.4 trace-field on demo, iteration off** — three distinct messages now:
- `step_99.nonexistent` → `[cli] field not in protocol: step_99.nonexistent (step 99 does not exist in this protocol)`
- `step_1.notes` (exists in protocol, no lineage) → `[cli] field has no lineage record: step_1.notes (field present, no FieldLineage attached — likely a demo-cache field or pre-lineage protocol)`
- `step_1.template_amount_ng` (has lineage) → renders the tree as expected.

Iteration outcome label: `Iteration outcome: **DISABLED** in 0 iterations` (was misleading `PENDING`).

## In-vivo verification on real papers

The advisor flagged that unit tests + the demo re-run only prove the helpers work in isolation. Two real-paper end-to-end runs were added.

### Z2 — Wet-lab on NEBNext Ultra II (re-run of Test C after fixes)

```
python3 run_cli.py --mode wet_lab --input "NEBNext Ultra II DNA Library Prep for Illumina protocol"
```

| Behaviour | Before (Test C) | After (Z2) |
|---|---|---|
| Pipeline status | `success` (after 2 fix attempts) | `success` (after 3 fix attempts — one extra because the new prompt asks for `labware_substitutions` JSON, retry budget still survives) |
| Coverage method | `1.00 via heuristic_fallback` | **`0.43 via markers`** — honest |
| Fidelity warning content | "LLM did not emit `# STEP N` markers" (false) | **"Only 12/28 steps emitted liquid-handling calls; skipped step numbers: 4, 5, 6, 7, 8, 10, 11, 13, 14, 16, 17, 19, 21, 22, 26, 27"** — specific, actionable |
| `## Field Lineage Summary` section | absent | **present**, with a mix of `paper_span` (extracted from paper) and `enricher_fill` (PIE) records visible per step |
| Verdict label | `Pass with caveats` (vague) | `Pass with caveats` (still — but now the caveats are real, surfaced, and per-step) |
| PIE gaps filled | 1 of 4 identified | **46 of 46 identified** (more complete extraction this time) |
| Tokens | 90,130 | 134,673 (the lineage section + labware-substitutions JSON adds ~40k to synth+coder) |

Labware substitutions: empty list this run — the LLM picked valid Opentrons labware throughout, so no warning fired. The plumbing is exercised end-to-end (Coder JSON → contract → state → synth) but this particular protocol didn't need any substitutions. To exercise the warning path on a real paper would need a protocol citing a non-Opentrons-standard plate.

### Z3 — Dry-lab on scGPT (re-run of Test D after fixes)

```
python3 run_cli.py --mode dry_lab --input "scGPT single-cell foundation model Cui 2024 Nature Methods github"
```

The strip-pyproject helper ran (verified by inspecting `requirements_install.discovery.torch_stripped_files` in the run log). The CPU-only torch install **then failed before the strip could matter**:

```
[coder] cpu torch install exit_code=2 success=False
[coder] FAILED: CPU-only torch preinstall failed; refusing to proceed

cpu_torch_exit_code=2
--- stdout tail ---
error: Request failed after 3 retries
  Caused by: Failed to fetch: `https://download.pytorch.org/whl/cpu/torch/`
  Caused by: Connection reset by peer (os error 104)
```

This is the **new error path from P1.5 Part B firing correctly** — the Daytona sandbox couldn't reach `download.pytorch.org/whl/cpu` (network issue on the sandbox side, not a code bug). Before this fix wave, the system would have logged `WARNING: CPU torch preinstall failed — proceeding anyway` and continued — then the editable install would have re-resolved full CUDA torch from the default PyPI index and exhausted the disk. The new posture refuses to proceed when the cpu-only build can't be obtained.

What is **not yet verified in-vivo:** the strip-pyproject + cpu_torch success path running end-to-end on scGPT, because the cpu-index outage prevented reaching that branch. The strip is unit-tested (10/10 tests pass on real-shape pyproject/setup.py/setup.cfg/Pipfile fixtures); the cpu_torch verification path is wired and fires when expected.

A scientifically-honest restatement of P1.5 status: **the regression (disk OOM via CUDA wheels) is closed by failing loudly at cpu_torch failure; full success-path verification requires either retrying when the PyTorch CPU index is reachable from the Daytona sandbox, or pointing at a different mirror.** That's not a code bug — it's a flaky network on the sandbox side that day.

Synthesis-on-failure (A1) still produces a real `**Reproducibility Score: FAIL**` report with the correct root-cause attribution. Verified.

### Web UI — server input validation

`curl -X POST http://127.0.0.1:8000/run` (server started via `python3 server.py`):

| Input | Status | Body |
|---|---|---|
| `{"input": ""}` | 400 | `{"error":"'input' must be a non-trivial paper title/DOI/URL (got: '')"}` |
| `{"input": "abc"}` | 400 | `{"error":"'input' must be a non-trivial paper title/DOI/URL (got: 'abc')"}` |
| `{"input": "demo", "demo_paper": "rt-qpcr"}` | 200 | `{"task_id":"…"}` |

Server-side P0.3 verified.

## Items NOT covered by this fix wave (still open, P2 in the plan above)

These were called out as P2 in the remediation list and remain open. They're substantive enough to warrant their own change windows:

- **P2.1** — Constraint-accumulating retry in `_wet_lab_flow` (Test C still solved-by-luck on 2 retries; a denser protocol would diverge).
- **P2.2** — Opentrons API cheatsheet seeded into Coder system prompt (the `thermocycler_module_gen2` hallucination class is still possible — we got lucky on Test C).
- **P2.3** — Per-well loop concept in the schema (Smart-seq3-class protocols will still silently process only well A1).
- **P2.4** — Out-of-scope step categorization (FACS / Bioanalyzer / manual prep — still pollute the schema as `transfer`).
- **P2.5** — `expected_outputs` schema-level type distinction (file path vs paper deliverable vs GEO accession).

## Files touched in this fix wave

```
agents/coder.py        | 120 +++++++++++++++++++++ (P0.1 regex; P1.3 silent-noop retry;
                                                    P1.5 torch-strip pyproject; P1.7 labware subs)
agents/methodology.py  |  18 +++ (P1.4 URL rejection surfaced in extraction_notes)
agents/supervisor.py   |  25 ++  (P0.2 shared _apply_coder_result_to_state helper)
agents/synthesizer.py  |  69 ++  (P1.2 unconditional Field Lineage Summary; P1.7 labware
                                  warnings in Fidelity section)
run_cli.py             |  62 ++  (P0.3 input validation; P0.4 trace-field 3-state messages;
                                  P1.6 iteration payload)
schemas/dry_lab_schema.py  |  92 ++ (P1.4 _filter_placeholder_urls + validators)
schemas/state_schema.py    |   1 +  (P1.7 labware_substitutions field)
server.py              |  18 ++  (P0.3 HTTP 400 for empty input)
tools/lineage_renderer.py  |  31 +  (P0.5 DISABLED/NOT_REACHED outcome states;
                                     P0.6 word-boundary truncation)
web/app.js             |  26 ++  (P0.5 parity on iteration outcome labels)
workspace/demo_cache/rt_qpcr_protocol.json | 114 +++ (P1.1 six paper_span records)
12 new test files      | (+71 focused tests, all green)
```

## What the next reviewer should check

1. Re-run the headline command. The lineage tree should start with `paper_span` and end with `replanner_revision [iter 2]`. If it doesn't, P1.1 regressed.
2. Run a fresh dry-lab attempt on any pyproject-based ML repo. If the install pulls nvidia-* wheels, P1.5's strip regex needs an additional pattern.
3. Try `--input "abc"` — should reject at CLI. If it spins up Daytona, P0.3 regressed.
4. Inspect the wet-lab report's "Fidelity warnings" section on a real-paper run with labware substitutions. If they're absent and you find them buried in the script as `protocol.comment(...)`, P1.7 regressed.
