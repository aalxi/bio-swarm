// app.js — BioSwarm frontend.
// Vanilla JS, no build step. Streams phase events from /events/{task_id}
// over SSE and renders one terminal panel per agent.

(function () {
  "use strict";

  // ── State ─────────────────────────────────────────────────────────────────
  let mode = "wet_lab";
  let activeTaskId = null;

  const PHASE_LABEL = {
    research:   "RESEARCHER AGENT",
    extraction: "METHODOLOGY AGENT",
    enrichment: "PIE AGENT",
    coding:     "CODER AGENT",
    iteration:  "ITERATION AGENT",
    synthesis:  "SYNTHESIZER AGENT",
    unknown:    "PIPELINE",
  };

  const NEXT_AGENT = {
    research:   "METHODOLOGY AGENT",
    extraction: null,    // depends on mode — handled inline
    enrichment: "CODER AGENT",
    coding:     "ITERATION AGENT",
    iteration:  "SYNTHESIZER AGENT",
  };

  // ── Mode toggle ───────────────────────────────────────────────────────────
  const toggle = document.querySelector(".toggle");
  toggle.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    mode = btn.dataset.mode;
    toggle.dataset.mode = mode;
    toggle.querySelectorAll("button").forEach((b) => {
      const on = b === btn;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  });

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderPanel(phase, state, lines) {
    // state: 'running' | 'success' | 'error'
    const wrap = document.createElement("div");
    wrap.className = `terminal-panel ${state}`;
    wrap.dataset.phase = phase;
    wrap.innerHTML = panelHTML(phase, state, lines);
    return wrap;
  }

  function panelHTML(phase, state, lines) {
    const label = PHASE_LABEL[phase] || phase.toUpperCase();
    const rows = lines
      .map(([cls, txt]) => `<div class="terminal-line ${cls}">${esc(txt)}</div>`)
      .join("");
    const cursor = state === "running" ? '<span class="terminal-cursor"></span>' : "";
    return (
      `<div class="terminal-header">${esc(label)}</div>` +
      rows +
      cursor
    );
  }

  function updatePanel(phaseEl, phase, state, lines) {
    if (!phaseEl) return;
    phaseEl.className = `terminal-panel ${state}`;
    phaseEl.innerHTML = panelHTML(phase, state, lines);
  }

  function appendHandoff(parent, nFiles, toAgent) {
    const div = document.createElement("div");
    div.className = "handoff-msg";
    div.innerHTML = `Passing ${nFiles} file(s) &nbsp;&middot;&nbsp; ${esc(toAgent)}`;
    parent.appendChild(div);
  }

  // ── Per-phase line builders ───────────────────────────────────────────────
  // Each takes the phase_end event dict and returns an array of [cssClass, text] pairs.

  function basenames(files) {
    return (files || []).map((f) => f.split("/").pop());
  }

  function buildResearchLines(ev) {
    const ts = ev.ts;
    const n = (ev.files || []).length;
    return [
      ["dim",     `> [${ts}]  task: ${activeTaskId}  |  mode: ${mode}`],
      ["",        `> [${ts}]  web search queries executed via Tavily`],
      ["",        `> [${ts}]  ${ev.message || "Research complete"}`],
      ["success", `> [${ts}]  ${n} file(s) saved to workspace/raw_research/`],
      ["dim",     `> [${ts}]  retries: ${ev.retry_count || 0}`],
      ["success", `> [${ts}]  status: SUCCESS`],
    ];
  }

  function buildExtractionLines(ev) {
    const ts = ev.ts;
    const protocolFile = (ev.files || [])[0] || "N/A";
    const lines = [
      ["",        `> [${ts}]  calling GPT-5.4 mini for structured extraction...`],
      ["",        `> [${ts}]  validating output against Pydantic schema...`],
    ];
    if ((ev.retry_count || 0) > 0) {
      lines.push(["warn", `> [${ts}]  schema validation retry: ${ev.retry_count} attempt(s)`]);
    }
    lines.push(["success", `> [${ts}]  schema validation: PASSED`]);
    lines.push(["success", `> [${ts}]  protocol saved to ${protocolFile}`]);
    lines.push(["success", `> [${ts}]  status: SUCCESS`]);
    return lines;
  }

  function buildEnrichmentLines(ev) {
    const ts = ev.ts;
    const filled = ev.gaps_filled || 0;
    const identified = ev.gaps_identified || 0;
    const queries = ev.tavily_queries_executed || 0;
    const conflicts = (ev.conflicts || []).length;
    const lines = [
      ["dim",     `> [${ts}]  reading protocol_${activeTaskId}.json from methodology agent`],
      ["",        `> [${ts}]  gap analysis: ${identified} critical null fields found`],
      ["",        `> [${ts}]  executing ${queries} targeted Tavily searches...`],
    ];
    if (conflicts > 0) {
      lines.push(["warn", `> [${ts}]  ${conflicts} conflicting value(s) found — not applied`]);
    }
    lines.push(["success", `> [${ts}]  ${filled}/${identified} fields enriched (confidence ≥ 0.7)`]);
    lines.push(["success", `> [${ts}]  enriched protocol saved → protocol_${activeTaskId}.json`]);
    lines.push(["dim",     `> [${ts}]  audit log → enrichment_${activeTaskId}.json`]);
    lines.push(["success", `> [${ts}]  status: SUCCESS`]);
    return lines;
  }

  function buildCodingLines(ev) {
    const ts = ev.ts;
    const scriptFile = (ev.files || [])[0] || "N/A";
    const retry = ev.retry_count || 0;
    if (mode === "wet_lab") {
      const lines = [
        ["dim",     `> [${ts}]  protocol_${activeTaskId}.json loaded and validated`],
        ["",        `> [${ts}]  GPT-5.4 mini script generation complete`],
        ["",        `> [${ts}]  Daytona sandbox created, installing opentrons...`],
        ["",        `> [${ts}]  uploading protocol.py, running opentrons_simulate...`],
      ];
      lines.push(retry > 0
        ? ["warn", `> [${ts}]  simulation fix applied: ${retry} retry attempt(s)`]
        : ["dim",  `> [${ts}]  opentrons_simulate passed on first attempt`]);
      lines.push(["success", `> [${ts}]  simulation: PASSED`]);
      lines.push(["success", `> [${ts}]  script saved to ${scriptFile}`]);
      lines.push(["dim",     `> [${ts}]  sandbox cleaned up`]);
      lines.push(["success", `> [${ts}]  status: SUCCESS`]);
      return lines;
    } else {
      const lines = [
        ["dim",     `> [${ts}]  protocol_${activeTaskId}.json loaded and validated`],
        ["",        `> [${ts}]  GitHub repo cloned into sandbox`],
        ["",        `> [${ts}]  dependencies installed`],
        ["",        `> [${ts}]  entry point executed`],
      ];
      lines.push(retry > 0
        ? ["warn", `> [${ts}]  execution required ${retry} retry attempt(s)`]
        : ["dim",  `> [${ts}]  entry point passed on first attempt`]);
      lines.push(["success", `> [${ts}]  execution: PASSED`]);
      lines.push(["success", `> [${ts}]  artifacts saved to ${scriptFile}`]);
      lines.push(["dim",     `> [${ts}]  sandbox cleaned up`]);
      lines.push(["success", `> [${ts}]  status: SUCCESS`]);
      return lines;
    }
  }

  function buildSynthesisLines(ev) {
    const ts = ev.ts;
    const reportFile = (ev.files || [])[0] || "N/A";
    return [
      ["dim",     `> [${ts}]  loading state.json, protocol JSON, code artifacts`],
      ["",        `> [${ts}]  calling GPT-5.4 mini to generate final Markdown report...`],
      ["success", `> [${ts}]  report written to ${reportFile}`],
      ["success", `> [${ts}]  status: SUCCESS`],
    ];
  }

  function buildErrorLines(ev) {
    const ts = ev.ts;
    const detail = (ev.error_detail || "").slice(0, 1500);
    const retry = ev.retry_count || 0;
    const lines = [
      ["error", `> [${ts}]  ERROR: ${ev.message || "Unknown error"}`],
    ];
    if (retry > 0) {
      lines.push(["warn", `> [${ts}]  attempted ${retry} retry/retries`]);
    }
    if (detail) {
      lines.push(["error", `> [${ts}]  ${detail}`]);
    }
    lines.push(["error", `> [${ts}]  status: FAILED`]);
    return lines;
  }

  function buildRunningLines(phase) {
    const ts = new Date().toTimeString().slice(0, 8);
    const intros = {
      research:   [["", `> [${ts}]  planning Tavily web search queries via GPT-5.4 mini...`]],
      extraction: [["", `> [${ts}]  chunking research content and calling extractor...`]],
      enrichment: [["", `> [${ts}]  running gap analysis on extracted protocol...`]],
      coding:     [["", `> [${ts}]  generating code and spinning up Daytona sandbox...`]],
      iteration:  [["", `> [${ts}]  oracle reading results and evaluating convergence...`]],
      synthesis:  [["", `> [${ts}]  reading workspace artifacts and state.json...`]],
    };
    return [
      ["dim", `> [${ts}]  initializing ${phase} agent...`],
      ...(intros[phase] || []),
    ];
  }

  const PHASE_BUILDER = {
    research:   buildResearchLines,
    extraction: buildExtractionLines,
    enrichment: buildEnrichmentLines,
    coding:     buildCodingLines,
    iteration:  buildIterationLines,
    synthesis:  buildSynthesisLines,
  };

  // ── Iteration phase support ──────────────────────────────────────────────
  function buildIterationLines(ev) {
    const ts = ev.ts;
    const cq = ev.cq != null ? `cq=${ev.cq}` : "cq=none";
    return [
      ["dim",     `> [${ts}]  iter ${ev.iteration_index}: oracle evaluated convergence quality`],
      ["",        `> [${ts}]  action=${ev.action || "unknown"}  ${cq}  regime=${ev.regime || "unknown"}`],
      ["success", `> [${ts}]  status: SUCCESS`],
    ];
  }

  // Track iteration outcomes for the lineage summary.
  let currentIterationsState = { iterations_completed: 0 };

  function trackIterationEvent(event) {
    if (event.phase !== "iteration") return;
    if (event.type === "phase_end") {
      currentIterationsState.iterations_completed = event.iteration_index;
      if (event.action === "converged") currentIterationsState.converged = true;
      if (event.action === "diagnose_required") currentIterationsState.diagnosis_required = true;
      if (event.action === "cap_reached") currentIterationsState.cap_reached = true;
    }
  }

  // ── Field Lineage rendering ──────────────────────────────────────────────
  const SOURCE_TYPE_COLORS = {
    paper_span:          "paper-span",
    enricher_fill:       "enricher-fill",
    oracle_reading:      "oracle-reading",
    replanner_revision:  "replanner-revision",
  };

  function elCreate(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function renderAggregate(taskId, fields, registry, iters) {
    const target = document.getElementById("lineage-aggregate");
    if (!target) return;
    target.innerHTML = "";
    const counts = { paper_span: 0, enricher_fill: 0, oracle_reading: 0, replanner_revision: 0 };
    for (const head of Object.values(fields)) {
      let cur = head;
      while (cur) { counts[cur.source_type] = (counts[cur.source_type] || 0) + 1; cur = cur.parent; }
    }
    const summary = elCreate("div", "lineage-summary");
    summary.appendChild(elCreate("div", "lineage-summary-row", `Task: ${taskId}`));
    summary.appendChild(elCreate("div", "lineage-summary-row",
      `Fields with lineage: ${Object.keys(fields).length}`));
    summary.appendChild(elCreate("div", "lineage-summary-row",
      `paper_span:${counts.paper_span} · enricher_fill:${counts.enricher_fill} · oracle_reading:${counts.oracle_reading} · replanner_revision:${counts.replanner_revision}`));
    // P0.5 — mirror the five-state logic from tools/lineage_renderer.py.
    let outcome;
    if (!iters || !iters.enabled) {
      outcome = "DISABLED";
    } else if (iters.converged) {
      outcome = "CONVERGED";
    } else if (iters.diagnosis_required) {
      outcome = "DIAGNOSE_REQUIRED";
    } else if (iters.cap_reached) {
      outcome = "CAP_REACHED";
    } else if (!iters.iterations_completed) {
      outcome = "NOT_REACHED";
    } else {
      outcome = "PENDING";
    }
    summary.appendChild(elCreate("div", "lineage-summary-row",
      `Iteration outcome: ${outcome} in ${(iters && iters.iterations_completed) || 0} iterations`));
    target.appendChild(summary);
  }

  function renderCitationChip(key, registry) {
    const chip = elCreate("span", "citation-chip");
    chip.textContent = key;
    const entry = registry && registry[key];
    if (entry) {
      chip.title = [
        entry.full_text || "",
        entry.quoted_text ? `"${entry.quoted_text}"` : "",
        entry.url || "",
      ].filter(Boolean).join("\n");
      if (entry.url) {
        chip.style.cursor = "pointer";
        chip.addEventListener("click", () => window.open(entry.url, "_blank"));
      }
      const status = entry.verification_status || "unchecked";
      chip.classList.add(`vstatus-${status}`);
    }
    return chip;
  }

  function renderRecord(fl, registry) {
    const wrap = elCreate("div", `lineage-record ${SOURCE_TYPE_COLORS[fl.source_type] || ""}`);
    const header = elCreate("div", "lineage-record-header");
    header.appendChild(elCreate("span", "source-type", fl.source_type));
    if (fl.iteration_index != null) {
      header.appendChild(elCreate("span", "iter-badge", `iter ${fl.iteration_index}`));
    }
    wrap.appendChild(header);
    wrap.appendChild(elCreate("div", "lineage-field", `value = ${JSON.stringify(fl.value)}`));
    const detail = fl[fl.source_type];
    if (detail) {
      for (const [k, v] of Object.entries(detail)) {
        if (v != null && k !== "rationale") {
          wrap.appendChild(elCreate("div", "lineage-field", `${k} = ${v}`));
        }
      }
      if (detail.rationale) {
        wrap.appendChild(elCreate("div", "lineage-rationale", detail.rationale));
      }
    }
    if (fl.citations && fl.citations.length) {
      const c = elCreate("div", "citation-row");
      c.appendChild(elCreate("span", "citation-label", "cites:"));
      for (const k of fl.citations) c.appendChild(renderCitationChip(k, registry));
      wrap.appendChild(c);
    }
    return wrap;
  }

  function renderChain(head, registry) {
    const container = elCreate("div", "lineage-chain");
    const chain = [];
    let cur = head;
    while (cur) { chain.push(cur); cur = cur.parent; }
    chain.reverse();
    for (const fl of chain) container.appendChild(renderRecord(fl, registry));
    return container;
  }

  async function fetchAndRenderLineage(taskId, iters) {
    try {
      const r = await fetch(`/lineage/${taskId}`);
      if (!r.ok) return;
      const { fields, registry } = await r.json();
      renderAggregate(taskId, fields, registry, iters);
      const target = document.getElementById("lineage-content");
      if (!target) return;
      target.innerHTML = "";
      for (const [path, head] of Object.entries(fields)) {
        const block = elCreate("details", "lineage-field-block");
        const sum = elCreate("summary", "", path);
        block.appendChild(sum);
        block.appendChild(renderChain(head, registry));
        target.appendChild(block);
      }
    } catch (e) {
      console.error("lineage fetch failed", e);
    }
  }

  // ── Pipeline run ──────────────────────────────────────────────────────────
  const form = document.getElementById("input-form");
  const inputEl = document.getElementById("input");
  const runBtn = document.getElementById("run-btn");
  const iterEl = document.getElementById("enable-iteration");
  const demoBtn = document.getElementById("demo-btn");
  const pipelineEl = document.getElementById("pipeline");
  const resultEl = document.getElementById("result");

  function setRunControlsDisabled(disabled) {
    runBtn.disabled = disabled;
    if (demoBtn) demoBtn.disabled = disabled;
  }

  async function startRun(payload) {
    setRunControlsDisabled(true);
    runBtn.textContent = "Running...";
    pipelineEl.innerHTML = "";
    resultEl.hidden = true;
    // P0.5 — seed enabled from the payload so renderAggregate can distinguish
    // "disabled" from "not yet reached."
    currentIterationsState = {
      iterations_completed: 0,
      enabled: !!payload.enable_iteration,
    };

    let res;
    try {
      res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      showFatalError(`Network error contacting /run: ${err.message}`);
      return null;
    }
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      showFatalError(`Server returned ${res.status}: ${txt}`);
      return null;
    }
    return (await res.json()).task_id;
  }

  // Demo button: skips Research+Methodology and runs the closed loop on the
  // committed RT-qPCR cache. Forces mode to wet_lab.
  demoBtn.addEventListener("click", async () => {
    mode = "wet_lab";
    toggle.dataset.mode = "wet_lab";
    toggle.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.mode === "wet_lab";
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    inputEl.value = "demo";
    iterEl.checked = true;
    const task_id = await startRun({
      input: "demo", mode: "wet_lab",
      enable_iteration: true, demo_paper: "rt-qpcr",
    });
    if (task_id) wireEventStream(task_id);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = inputEl.value.trim();
    if (!input) return;
    const task_id = await startRun({
      input, mode, enable_iteration: !!(iterEl && iterEl.checked),
    });
    if (!task_id) return;
    wireEventStream(task_id);
  });

  function wireEventStream(task_id) {
    activeTaskId = task_id;

    const panels = {};  // phase -> element
    let lastPhase = null;

    const es = new EventSource(`/events/${task_id}`);

    es.addEventListener("phase_start", (ev) => {
      const data = JSON.parse(ev.data);
      const phase = data.phase;
      trackIterationEvent(data);
      const panel = renderPanel(phase, "running", buildRunningLines(phase));
      panels[phase] = panel;
      pipelineEl.appendChild(panel);
      lastPhase = phase;
    });

    es.addEventListener("phase_end", (ev) => {
      const data = JSON.parse(ev.data);
      const phase = data.phase;
      trackIterationEvent(data);
      const ok = data.status === "success";
      const builder = PHASE_BUILDER[phase];
      const lines = ok && builder ? builder(data) : buildErrorLines(data);
      updatePanel(panels[phase], phase, ok ? "success" : "error", lines);

      if (ok) {
        let nextAgent = NEXT_AGENT[phase];
        if (phase === "extraction") {
          nextAgent = mode === "wet_lab" ? "PIE AGENT" : "CODER AGENT";
        }
        if (nextAgent) {
          appendHandoff(pipelineEl, (data.files || []).length, nextAgent);
        }
      }
    });

    es.addEventListener("done", async (ev) => {
      es.close();
      setRunControlsDisabled(false);
      runBtn.textContent = "Run BioSwarm";
      const { result } = JSON.parse(ev.data);
      if (result.status === "success") {
        await showResult(task_id, result);
        fetchAndRenderLineage(task_id, currentIterationsState);
      } else {
        showFinalError(result);
      }
    });

    es.addEventListener("error", () => {
      // EventSource auto-reconnects; only act if the connection is fully closed.
      if (es.readyState === EventSource.CLOSED) {
        setRunControlsDisabled(false);
        runBtn.textContent = "Run BioSwarm";
      }
    });
  }

  // ── Result display ────────────────────────────────────────────────────────

  async function showResult(taskId, result) {
    resultEl.hidden = false;

    // State viewer
    if (result.state) {
      document.getElementById("state-json").textContent =
        JSON.stringify(result.state, null, 2);
    }

    // Report (server-rendered HTML)
    try {
      const r = await fetch(`/report/${taskId}`);
      if (r.ok) {
        const { html } = await r.json();
        const reportEl = document.getElementById("report");
        reportEl.innerHTML = html;
        if (window.hljs) {
          reportEl.querySelectorAll("pre code").forEach((el) => {
            window.hljs.highlightElement(el);
          });
        }
      }
    } catch (err) {
      document.getElementById("report").textContent =
        `Failed to load report: ${err.message}`;
    }

    // Download links
    const dlScript = document.getElementById("download-script");
    const dlReport = document.getElementById("download-report");
    if (mode === "wet_lab") {
      dlScript.href = `/download/${taskId}?kind=script`;
      dlScript.hidden = false;
    } else {
      dlScript.hidden = true;
    }
    dlReport.href = `/download/${taskId}?kind=report`;
    dlReport.hidden = false;

    resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showFinalError(result) {
    resultEl.hidden = false;
    document.getElementById("report").innerHTML =
      `<h2>Pipeline failed</h2>` +
      `<pre>${esc(result.error_detail || JSON.stringify(result, null, 2))}</pre>`;
    if (result.state) {
      document.getElementById("state-json").textContent =
        JSON.stringify(result.state, null, 2);
    }
    document.getElementById("download-script").hidden = true;
    document.getElementById("download-report").hidden = true;
  }

  function showFatalError(message) {
    setRunControlsDisabled(false);
    runBtn.textContent = "Run BioSwarm";
    pipelineEl.innerHTML = "";
    const panel = renderPanel("unknown", "error", [
      ["error", `> ${message}`],
    ]);
    pipelineEl.appendChild(panel);
  }
})();
