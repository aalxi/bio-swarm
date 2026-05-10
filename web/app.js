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
    synthesis:  "SYNTHESIZER AGENT",
    unknown:    "PIPELINE",
  };

  const NEXT_AGENT = {
    research:   "METHODOLOGY AGENT",
    extraction: null,    // depends on mode — handled inline
    enrichment: "CODER AGENT",
    coding:     "SYNTHESIZER AGENT",
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
    synthesis:  buildSynthesisLines,
  };

  // ── Pipeline run ──────────────────────────────────────────────────────────
  const form = document.getElementById("input-form");
  const inputEl = document.getElementById("input");
  const runBtn = document.getElementById("run-btn");
  const pipelineEl = document.getElementById("pipeline");
  const resultEl = document.getElementById("result");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = inputEl.value.trim();
    if (!input) return;

    runBtn.disabled = true;
    runBtn.textContent = "Running...";
    pipelineEl.innerHTML = "";
    resultEl.hidden = true;

    let res;
    try {
      res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input, mode }),
      });
    } catch (err) {
      showFatalError(`Network error contacting /run: ${err.message}`);
      return;
    }
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      showFatalError(`Server returned ${res.status}: ${txt}`);
      return;
    }
    const { task_id } = await res.json();
    activeTaskId = task_id;

    const panels = {};  // phase -> element
    let lastPhase = null;

    const es = new EventSource(`/events/${task_id}`);

    es.addEventListener("phase_start", (ev) => {
      const data = JSON.parse(ev.data);
      const phase = data.phase;
      const panel = renderPanel(phase, "running", buildRunningLines(phase));
      panels[phase] = panel;
      pipelineEl.appendChild(panel);
      lastPhase = phase;
    });

    es.addEventListener("phase_end", (ev) => {
      const data = JSON.parse(ev.data);
      const phase = data.phase;
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
      runBtn.disabled = false;
      runBtn.textContent = "Run BioSwarm";
      const { result } = JSON.parse(ev.data);
      if (result.status === "success") {
        await showResult(task_id, result);
      } else {
        showFinalError(result);
      }
    });

    es.addEventListener("error", () => {
      // EventSource auto-reconnects; only act if the connection is fully closed.
      if (es.readyState === EventSource.CLOSED) {
        runBtn.disabled = false;
        runBtn.textContent = "Run BioSwarm";
      }
    });
  });

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
    runBtn.disabled = false;
    runBtn.textContent = "Run BioSwarm";
    pipelineEl.innerHTML = "";
    const panel = renderPanel("unknown", "error", [
      ["error", `> ${message}`],
    ]);
    pipelineEl.appendChild(panel);
  }
})();
