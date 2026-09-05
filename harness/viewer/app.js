const state = { bundle: null, left: 0, right: 0, leftStep: 0, rightStep: 0, linked: true, activeSide: "left", tab: "screenshot", kind: "paired" };

fetch("/api/run").then((response) => response.json()).then((bundle) => {
  state.bundle = bundle;
  initializeNavigation();
});

function initializeNavigation() {
  const runPath = document.getElementById("run-path");
  runPath.innerHTML = urlBlock(state.bundle.run_dir);
  const experiments = [...new Set(state.bundle.comparisons.map((comparison) => comparison.experiment))];
  const experimentSelect = document.getElementById("experiment-select");
  experimentSelect.innerHTML = experiments.map((experiment) => `<option value="${escapeAttribute(experiment)}">${escapeHtml(experiment)}</option>`).join("");
  experimentSelect.addEventListener("change", () => populatePairs(experimentSelect.value));
  document.getElementById("pair-select").addEventListener("change", (event) => selectComparison(Number(event.target.value)));
  document.getElementById("link-steps").addEventListener("click", () => {
    state.linked = !state.linked;
    if (state.linked) {
      state.leftStep = state.rightStep = selectedStep(state.activeSide);
    } else {
      state.leftStep = Math.min(state.leftStep, Math.max(0, state.bundle.episodes[state.left].transitions.length - 1));
      state.rightStep = Math.min(state.rightStep, Math.max(0, state.bundle.episodes[state.right].transitions.length - 1));
    }
    render();
  });
  document.getElementById("timeline-side").addEventListener("change", (event) => {
    state.activeSide = event.target.value;
    render();
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("select, input, textarea, button, [contenteditable]")) return;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const delta = event.key === "ArrowRight" ? 1 : -1;
      setStep(state.activeSide, selectedStep(state.activeSide) + delta);
      render();
    }
  });
  populatePairs(experiments[0]);
}

function populatePairs(experiment) {
  const entries = state.bundle.comparisons.map((comparison, index) => ({ comparison, index })).filter(({ comparison }) => comparison.experiment === experiment);
  const pairSelect = document.getElementById("pair-select");
  pairSelect.innerHTML = entries.map(({ comparison, index }) => `<option value="${index}">seed ${comparison.seed} / ${escapeHtml(comparison.task_id)} / ${escapeHtml(comparison.control_condition)}${comparison.kind === "single" ? "" : ` vs ${escapeHtml(comparison.treatment_condition)}`}</option>`).join("");
  selectComparison(entries[0].index);
}

function selectComparison(index) {
  const comparison = state.bundle.comparisons[index];
  state.kind = comparison.kind || "paired";
  if (state.kind === "single") { state.linked = true; state.activeSide = "left"; }
  state.left = comparison.control_index;
  state.right = comparison.treatment_index;
  state.leftStep = state.rightStep = 0;
  document.getElementById("experiment-select").value = comparison.experiment;
  const pairSelect = document.getElementById("pair-select");
  pairSelect.value = String(index);
  pairSelect.title = pairSelect.options[pairSelect.selectedIndex].text;
  render();
}

function render() {
  hideTooltip();
  const leftEpisode = state.bundle.episodes[state.left];
  const rightEpisode = state.bundle.episodes[state.right];
  const leftTransition = leftEpisode.transitions[state.leftStep] || null;
  const rightTransition = rightEpisode.transitions[state.rightStep] || null;
  const linkButton = document.getElementById("link-steps");
  linkButton.textContent = state.linked ? "Unlink steps" : "Link steps";
  linkButton.setAttribute("aria-pressed", String(state.linked));
  linkButton.title = state.linked ? "Navigate each episode separately" : "Use the selected arm's step number for both episodes";
  document.getElementById("timeline-arm").hidden = state.linked;
  document.getElementById("timeline-side").value = state.activeSide;
  renderTimeline(leftEpisode, rightEpisode);
  document.getElementById("step-title").innerHTML = `<span>${state.linked ? `Step ${state.leftStep}` : "Independent steps"}</span><span class="badge control-key">Control / ${state.leftStep} / ${escapeHtml(actionName(leftTransition, "ended"))}</span><span class="badge treatment-key">Treatment / ${state.rightStep} / ${escapeHtml(actionName(rightTransition, "ended"))}</span>`;
  renderPairingStatus(leftEpisode, rightEpisode, leftTransition, rightTransition);
  renderDifference(leftEpisode, rightEpisode, leftTransition, rightTransition);
  renderEpisodePane("left-pane", leftEpisode, leftTransition, state.kind === "paired" ? "CONTROL" : state.kind === "single" ? "Episode" : "A");
  renderEpisodePane("right-pane", rightEpisode, rightTransition, state.kind === "paired" ? "TREATMENT" : "B");
  renderOutcomes(leftEpisode, rightEpisode);
  const single = state.kind === "single";
  document.getElementById("right-pane").hidden = single;
  document.querySelector(".episode-columns").style.gridTemplateColumns = single ? "minmax(0, 1fr)" : "";
  linkButton.hidden = single;
  document.getElementById("pairing-status").hidden = single;
  document.getElementById("difference-banner").hidden = single;
  if (single) {
    document.getElementById("step-title").innerHTML = `<span>Step ${state.leftStep} / ${escapeHtml(actionName(leftTransition))}</span>`;
    document.getElementById("step-count").textContent = `${leftEpisode.transitions.length} steps`;
    document.querySelectorAll(".step-arm:nth-child(2), #outcomes tr > :nth-child(3)").forEach((element) => { element.hidden = true; });
  }
  if (state.kind !== "paired") {
    const labels = single ? ["Episode", "Episode"] : ["A", "B"];
    document.querySelectorAll("#left-pane .episode-title > span, #right-pane .episode-title > span").forEach((element, index) => { element.textContent = labels[index]; });
    document.querySelectorAll("#timeline .arm-key").forEach((element) => { element.textContent = element.classList.contains("control-key") ? labels[0] : labels[1]; });
    document.querySelectorAll("#outcomes th.control-key, #outcomes th.treatment-key").forEach((element, index) => { element.textContent = labels[index]; });
    document.querySelectorAll("#step-title .badge").forEach((element, index) => { element.textContent = element.textContent.replace(/^(Control|Treatment)/, labels[index]); });
    if (!single) document.getElementById("step-count").textContent = `${leftEpisode.transitions.length} A / ${rightEpisode.transitions.length} B`;
    document.querySelectorAll("#timeline-side option").forEach((element, index) => { element.textContent = labels[index]; });
  } else {
    document.querySelectorAll("#timeline-side option").forEach((element, index) => { element.textContent = index ? "Treatment" : "Control"; });
  }
  attachHelpButtons();
}

function renderTimeline(leftEpisode, rightEpisode) {
  const count = state.linked ? stepCount() : state.bundle.episodes[state[state.activeSide]].transitions.length;
  document.getElementById("step-count").textContent = `${leftEpisode.transitions.length} control / ${rightEpisode.transitions.length} treatment`;
  const timeline = document.getElementById("timeline");
  timeline.innerHTML = Array.from({ length: count }, (_, step) => {
    const left = leftEpisode.transitions[step] || null;
    const right = rightEpisode.transitions[step] || null;
    const leftUrl = observationUrl((left || {}).observation);
    const rightUrl = observationUrl((right || {}).observation);
    const urls = [...new Set((state.linked ? [leftUrl, rightUrl] : [state.activeSide === "left" ? leftUrl : rightUrl]).filter(Boolean))];
    return `<div class="timeline-entry"><button class="step-button ${step === selectedStep(state.activeSide) ? "selected" : ""}" aria-current="${step === selectedStep(state.activeSide) ? "step" : "false"}" data-step="${step}">
      <span class="step-number">${step}</span>
      <span class="step-summary">
        ${state.linked || state.activeSide === "left" ? `<span class="step-arm">${state.kind === "single" ? "" : `<span class="arm-key control-key">C</span>`}<span class="step-action">${escapeHtml(actionName(left, "ended"))}</span></span>` : ""}
        ${state.kind !== "single" && (state.linked || state.activeSide === "right") ? `<span class="step-arm"><span class="arm-key treatment-key">T</span><span class="step-action">${escapeHtml(actionName(right, "ended"))}</span></span>` : ""}
      </span>
    </button>${urls.length ? `<div class="step-detail">${urls.map(urlBlock).join("")}</div>` : ""}</div>`;
  }).join("");
  timeline.querySelectorAll("[data-step]").forEach((button) => button.addEventListener("click", () => {
    setStep(state.activeSide, Number(button.dataset.step));
    render();
  }));
}

function renderPairingStatus(leftEpisode, rightEpisode, leftTransition, rightTransition) {
  const status = document.getElementById("pairing-status");
  if (!state.linked) {
    status.className = "pairing-status";
    status.textContent = "Steps unlinked";
    delete status.dataset.tooltip;
    return;
  }
  if (leftTransition && rightTransition) {
    status.className = "pairing-status";
    status.textContent = "Paired by step number";
    status.dataset.tooltip = "paired";
    return;
  }
  const ended = state.kind === "factorial" ? (leftTransition ? "B" : "A") : (leftTransition ? "Treatment" : "Control");
  const length = leftTransition ? rightEpisode.transitions.length : leftEpisode.transitions.length;
  status.className = "pairing-status unequal";
  status.textContent = `${ended} ended after ${length} steps`;
  status.dataset.tooltip = "unequal";
}

function renderEpisodePane(id, episode, transition, role) {
  const pane = document.getElementById(id);
  const side = id === "left-pane" ? "left" : "right";
  const step = selectedStep(side);
  const condition = episode.manifest.condition_id;
  const model = episode.manifest.metadata && episode.manifest.metadata.model;
  const tabs = observationTabs(transition);
  const selectedTab = tabs.some((tab) => tab.id === state.tab) ? state.tab : "screenshot";
  pane.innerHTML = `<div class="episode-title"><span>${role}</span><strong>${escapeHtml(condition)}</strong><small>${escapeHtml(model || episode.manifest.agent_id || "agent")}</small></div>
    ${state.linked ? "" : `<div class="pane-navigation">
      <button type="button" data-move="-1" aria-label="Previous ${role.toLowerCase()} step" ${step === 0 ? "disabled" : ""}>Previous</button>
      <select aria-label="${role.toLowerCase()} step" data-pane-step ${episode.transitions.length ? "" : "disabled"}>${episode.transitions.map((entry, index) => `<option value="${index}" ${index === step ? "selected" : ""}>Step ${index} / ${escapeHtml(actionName(entry))}</option>`).join("")}</select>
      <button type="button" data-move="1" aria-label="Next ${role.toLowerCase()} step" ${step >= episode.transitions.length - 1 ? "disabled" : ""}>Next</button>
    </div>`}
    <div class="episode-usage"><strong>Episode usage</strong>${metricGrid(episodeUsage(episode))}</div>
    <div class="tabs">${tabs.map((tab) =>
      `<button class="tab inline-flex items-center justify-center rounded-lg px-3 py-2 font-medium transition-colors ${selectedTab === tab.id ? "active" : ""}" aria-pressed="${selectedTab === tab.id}" data-tab="${tab.id}">${tabLabel(tab.id)}${tab.agentInput ? `<span class="agent-input-indicator" title="This representation was sent to the agent. See Model input and output for the full request.">Agent input</span>` : ""}</button>`
    ).join("")}</div>
    <div class="observation">${observationContent(episode, transition, step, selectedTab)}</div>
    ${facetDetails(role === "CONTROL" ? "Control" : role === "TREATMENT" ? "Treatment" : role, transition, step)}`;
  pane.querySelectorAll("[data-move]").forEach((button) => button.addEventListener("click", () => {
    setStep(side, step + Number(button.dataset.move));
    render();
    document.querySelector(`#${id} [data-move="${button.dataset.move}"]`).focus({ preventScroll: true });
  }));
  pane.querySelector("[data-pane-step]")?.addEventListener("change", (event) => {
    setStep(side, Number(event.target.value));
    render();
    document.querySelector(`#${id} [data-pane-step]`).focus({ preventScroll: true });
  });
  pane.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    render();
    document.querySelector(`#${id} [data-tab="${state.tab}"]`).focus({ preventScroll: true });
  }));
}

function observationContent(episode, transition, step, tab = state.tab) {
  if (!transition) return `<div class="empty">This arm ended after ${episode.transitions.length} steps. Select an earlier step to inspect its final action.</div>`;
  const observation = transition.observation || {};
  const structured = observation.structured || {};
  const url = observationUrl(observation);
  if (tab === "agent") return agentInput(episode, transition);
  if (tab === "screenshot") {
    const artifact = observation.visual && observation.visual.artifact;
    if (!artifact) return `${urlBlock(url)}<div class="empty">No visual observation was recorded for this environment.</div>`;
    const source = `/artifact/${episode.index}/${encodeURI(artifact)}`;
    return `${urlBlock(url)}<div class="screenshot-frame"><img src="${source}" alt="${escapeAttribute(episode.manifest.condition_id)} observation at step ${step}"></div>`;
  }
  if (tab === "rendered") {
    const body = structured.body || "";
    return `${urlBlock(url)}<div class="rendered-text">${escapeHtml(observation.text || "No visible text")}</div><iframe class="rendered-html" sandbox srcdoc="${escapeAttribute(body)}"></iframe>`;
  }
  if (tab === "dom") return `${urlBlock(url)}<pre>${escapeHtml(structured.body || "No DOM HTML")}</pre>`;
  if (tab === "a11y") return `${urlBlock(url)}<pre>${escapeHtml(structured.accessibility?.tree ?? "No accessibility tree recorded for this step.")}</pre>`;
  if (tab === "elements") return `${urlBlock(url)}${elementList((structured.accessibility || {}).interactive_elements || [])}`;
  return fieldList(transition.before_snapshot ? transition.before_snapshot.state : {});
}

function facetDetails(label, transition, step) {
  if (!transition) return `<section class="facet-details"><h3>${label} step details</h3><div class="empty compact">No action exists at ordinal step ${step}.</div></section>`;
  const action = transition.action || {};
  const llm = action.metadata && action.metadata.llm ? action.metadata.llm : {};
  const usage = tokenUsage(llm);
  const promptTokens = usage.input_tokens;
  const metrics = {
    model: llm.model,
    response_id: llm.response_id,
    ...usage,
    latency_seconds: llm.latency_seconds === undefined ? undefined : llm.latency_seconds.toFixed(3)
  };
  return `<section class="facet-details"><h3>${label} step details</h3>
    <table class="detail-table"><tbody>
      <tr><th scope="row"><span data-tooltip="action" tabindex="0">Action</span></th><td>${actionView(action)}</td></tr>
      <tr><th scope="row"><span data-tooltip="model" tabindex="0">Model call</span></th><td>${metricGrid(metrics)}${tokenWarning(promptTokens)}</td></tr>
      <tr><th scope="row"><span data-tooltip="interventions" tabindex="0">Interventions</span></th><td>${interventionList(transition.interventions || [])}</td></tr>
      <tr><th scope="row"><span data-tooltip="environment" tabindex="0">Environment</span></th><td>${fieldList(transition.info || {})}</td></tr>
    </tbody></table>
    <details class="model-details"><summary data-tooltip="messages">Model input and output</summary>${metricGrid(usage)}${messageList(llm.messages || [])}${reasoningView(llm)}<h4>Model output</h4><pre>${escapeHtml(llm.assistant_content ?? "Not recorded")}</pre><h4>Parsed response</h4>${actionView(action)}</details>
  </section>`;
}

function renderDifference(leftEpisode, rightEpisode, leftTransition, rightTransition) {
  const banner = document.getElementById("difference-banner");
  if (!state.linked) {
    banner.className = "difference-banner";
    banner.innerHTML = "";
    delete banner.dataset.tooltip;
    return;
  }
  if (!leftTransition || !rightTransition) {
    const ended = state.kind === "factorial" ? (leftTransition ? "B" : "A") : (leftTransition ? "Treatment" : "Control");
    const length = leftTransition ? rightEpisode.transitions.length : leftEpisode.transitions.length;
    banner.className = "difference-banner visible";
    banner.dataset.tooltip = "unequal";
    banner.innerHTML = `<strong>Unequal trajectories</strong><span>${ended} ended after ${length} steps; the other arm continued.</span>`;
    return;
  }
  const leftObservation = leftTransition.observation || {};
  const rightObservation = rightTransition.observation || {};
  const differs = leftObservation.text !== rightObservation.text
    || (leftObservation.visual || {}).sha256 !== (rightObservation.visual || {}).sha256
    || formatJson(actionComparable(leftTransition)) !== formatJson(actionComparable(rightTransition))
    || (rightTransition.interventions || []).length > 0;
  banner.className = `difference-banner ${differs ? "visible" : ""}`;
  banner.dataset.tooltip = "comparison";
  banner.innerHTML = differs ? `<strong>Counterfactual comparison</strong>` : "";
}

function renderOutcomes(leftEpisode, rightEpisode) {
  const left = outcomeMap(leftEpisode);
  const right = outcomeMap(rightEpisode);
  const ids = [...new Set([...Object.keys(left), ...Object.keys(right)])];
  document.getElementById("outcomes").innerHTML = `<div class="outcomes-heading"><h2 data-tooltip="outcomes" tabindex="0">Episode outcomes</h2><span>Final results across all steps</span></div>${ids.length ? `<div class="table-scroll"><table class="outcome-table"><thead><tr><th scope="col">Measure</th><th scope="col" class="control-key">Control</th><th scope="col" class="treatment-key">Treatment</th></tr></thead><tbody>${ids.map((id) => {
    const direction = (right[id] || left[id] || {}).direction || "report";
    const directionInfo = directionDescription(direction);
    const description = outcomeDescription(id);
    return `<tr><th scope="row"><strong data-tooltip="outcome:${escapeAttribute(id)}" tabindex="0">${escapeHtml(description.label)}</strong><p>${escapeHtml(description.detail)}</p><span class="direction-badge" data-tooltip="${directionInfo.key}" tabindex="0">${escapeHtml(directionInfo.label)}</span></th><td>${outcomeValue(id, left[id])}</td><td>${outcomeValue(id, right[id])}</td></tr>`;
  }).join("")}</tbody></table></div>` : `<p class="empty compact">No outcomes were recorded for these episodes.</p>`}`;
}

function actionView(action) {
  const argumentsView = fieldList(action.arguments || {}, "No arguments");
  const text = action.text === undefined || action.text === null ? "" : `<div class="action-text"><span>Answer or text</span><p>${escapeHtml(action.text)}</p></div>`;
  return `<div class="action-view"><span class="action-kind">${escapeHtml(action.kind || "No action")}</span>${argumentsView}${text}</div>`;
}

function elementList(elements) {
  if (!elements.length) return `<div class="empty">No interactive accessibility elements were recorded.</div>`;
  return `<div class="element-list">${elements.map((element) => {
    const bid = element.bid || element.ref || "untagged";
    return `<div class="element-row"><code>${escapeHtml(bid)}</code><span>${escapeHtml(element.role || element.tag || "element")}</span><strong>${escapeHtml(element.name || "Unnamed")}</strong></div>`;
  }).join("")}</div>`;
}

function messageList(messages) {
  if (!messages.length) return `<div class="empty compact">Prompt was not recorded.</div>`;
  return `<div class="message-list">${messages.map((message) => `<article class="message-card"><strong>${escapeHtml(humanLabel(message.role))}</strong>${messageContent(message.content)}</article>`).join("")}</div>`;
}

function messageContent(content) {
  if (Array.isArray(content)) {
    return content.map((item) => item.type === "text" ? `<p>${escapeHtml(item.text)}</p>` : `<span class="image-chip">Current screenshot attached</span>`).join("");
  }
  return `<p>${escapeHtml(content || "Empty message")}</p>`;
}

function interventionList(interventions) {
  if (!interventions.length) return `<div class="empty compact">None at this step.</div>`;
  return interventions.map((item) => `<div class="intervention"><strong>${escapeHtml(item.intervention_id)}</strong><div>${escapeHtml(humanLabel(item.scope))} / ${escapeHtml(humanLabel(item.hook))} / order ${item.order}</div><div>${(item.changed_fields || []).map((field) => `<span class="changed-field">${escapeHtml(field)}</span>`).join("")}</div></div>`).join("");
}

function metricGrid(metrics) {
  return `<dl class="metric-grid">${Object.entries(metrics).filter(([, value]) => value !== undefined && value !== null).map(([key, value]) => `<dt>${escapeHtml(humanLabel(key))}</dt><dd>${key.includes("tokens") && typeof value === "number" ? escapeHtml(formatNumber(value)) : escapeHtml(String(value))}</dd>`).join("")}</dl>`;
}

function fieldList(fields, emptyLabel = "No fields") {
  const entries = Object.entries(fields).filter(([, value]) => value !== undefined);
  if (!entries.length) return `<div class="empty compact">${escapeHtml(emptyLabel)}.</div>`;
  return `<dl class="field-list">${entries.map(([key, value]) => `<div class="field-row"><dt>${escapeHtml(humanLabel(key))}</dt><dd>${valueView(value)}</dd></div>`).join("")}</dl>`;
}

function tokenWarning(tokens) {
  if (!tokens || tokens < 64000) return "";
  return `<div class="token-warning"><strong>Oversized model input</strong><span>This saved run predates bounded observations. Re-run it to use compact BID-tagged page context and current-screenshot-only history.</span></div>`;
}

function urlBlock(url) {
  if (!url) return "";
  return `<button type="button" class="observation-url group flex min-w-0 items-center gap-2 rounded-lg" data-copy="${escapeAttribute(url)}" title="${escapeAttribute(url)}" aria-label="Copy ${escapeAttribute(url)}"><span class="truncate">${escapeHtml(url)}</span><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/></svg></button>`;
}

let copyStatusTimeout;
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const status = document.getElementById("copy-status");
  const report = (message) => {
    clearTimeout(copyStatusTimeout);
    status.textContent = message;
    copyStatusTimeout = setTimeout(() => { status.textContent = ""; }, 3000);
  };
  if (!navigator.clipboard) {
    report("Copy is unavailable on this connection. Open the viewer on localhost.");
    return;
  }
  navigator.clipboard.writeText(button.dataset.copy).then(
    () => report("Copied to clipboard"),
    () => report("Clipboard access was denied by the browser.")
  );
});

function valueView(value) {
  if (value === null || value === undefined) return `<span class="value-muted">Not recorded</span>`;
  if (Array.isArray(value)) return value.length
    ? `<ol class="value-list">${value.map((item) => `<li>${valueView(item)}</li>`).join("")}</ol>`
    : `<span class="value-muted">No items</span>`;
  if (typeof value === "object") return fieldList(value);
  if (typeof value === "boolean") return `<span class="badge">${value ? "Yes" : "No"}</span>`;
  if (typeof value === "string" && /^(?:[a-z][a-z0-9+.-]*:\/\/|\/|~\/)/i.test(value)) return urlBlock(value);
  return `<span class="value-text">${escapeHtml(value === "" ? "Empty" : value)}</span>`;
}

function outcomeDescription(id) {
  return viewerCopy.outcomes[id] || { label: humanLabel(id), detail: "" };
}

function outcomeValue(id, outcome) {
  if (!outcome) return `<span class="value-muted">Not recorded</span>`;
  const value = outcome.value;
  if (id === "cart_choice") {
    const items = (outcome.evidence || []).flatMap((entry) => entry.cart_items || []);
    const names = items.map((item) => item.product_name || item.product_url).filter(Boolean);
    if (names.length) return valueView(names);
    return value === null || value === undefined
      ? "No single candidate selected"
      : `Candidate ${escapeHtml(Number(value) + 1)}<small class="value-muted">Product name was not recorded</small>`;
  }
  if (value === null || value === undefined) return `<span class="value-muted">${id === "target_chosen" ? "No valid choice" : "Not recorded"}</span>`;
  if (id === "target_chosen" && (value === 0 || value === 1)) return value === 1 ? "Selected" : "Not selected";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (id === "action_count") return `${formatNumber(value)} ${value === 1 ? "action" : "actions"}`;
  return valueView(value);
}

function directionDescription(direction) {
  const key = ["maximize", "minimize"].includes(direction) ? direction : "report";
  return { key, label: viewerCopy.directions[key] };
}

function stepCount() { return Math.max(state.bundle.episodes[state.left].transitions.length, state.bundle.episodes[state.right].transitions.length, 1); }
function selectedStep(side) { return state[`${side}Step`]; }
function setStep(side, step) {
  state.activeSide = side;
  const count = state.linked ? stepCount() : state.bundle.episodes[state[side]].transitions.length;
  const next = Math.max(0, Math.min(step, count - 1));
  if (state.linked) state.leftStep = state.rightStep = next;
  else state[`${side}Step`] = next;
}
function actionName(transition, missing = "no action") { return ((transition || {}).action || {}).kind || missing; }
function actionComparable(transition) {
  const action = (transition || {}).action || {};
  return { kind: action.kind, arguments: action.arguments, text: action.text };
}
function observationUrl(observation) { return ((observation || {}).structured || {}).url || ""; }
function outcomeMap(episode) { return Object.fromEntries((episode.outcomes.outcomes || []).map((outcome) => [outcome.id, outcome])); }
function tabLabel(tab) { return ({ agent: "Agent input", screenshot: "Screenshot", rendered: "Rendered", dom: "Raw HTML", a11y: "Accessibility tree", elements: "Elements", state: "State" })[tab]; }
function humanLabel(value) { return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatJson(value) { return JSON.stringify(value || {}, null, 2); }
function formatNumber(value) { return Number(value).toLocaleString("en-US"); }
function escapeHtml(value) { return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function escapeAttribute(value) { return escapeHtml(value).replaceAll("\n", "&#10;"); }

function tokenUsage(llm) {
  const usage = llm.usage || {};
  return {
    input_tokens: usage.prompt_tokens ?? usage.input_tokens,
    output_tokens: usage.completion_tokens ?? usage.output_tokens,
    reasoning_tokens: usage.completion_tokens_details?.reasoning_tokens
      ?? usage.output_tokens_details?.reasoning_tokens ?? usage.reasoning_tokens ?? "Not reported",
    total_tokens: usage.total_tokens
  };
}

function episodeUsage(episode) {
  const calls = episode.transitions.map((entry) => entry.action?.metadata?.llm).filter(Boolean);
  const usages = calls.map(tokenUsage);
  const totals = { model_calls: calls.length };
  for (const key of ["input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"]) {
    const reported = usages.map((usage) => usage[key]).filter((value) => typeof value === "number");
    const total = reported.reduce((sum, value) => sum + value, 0);
    totals[key] = reported.length === calls.length ? total
      : reported.length ? `${formatNumber(total)} (${reported.length}/${calls.length} calls reported)` : "Not reported";
  }
  return totals;
}

function reasoningView(llm) {
  const text = llm.reasoning_content || (llm.thinking_blocks || [])
    .filter((block) => block.type === "thinking").map((block) => block.thinking).join("\n\n");
  return `<h4>Reasoning returned by the provider</h4><pre>${escapeHtml(text || "Not returned by this provider. A token count may still be available.")}</pre>`;
}

function observationTabs(transition) {
  const llm = transition?.action?.metadata?.llm;
  const modalities = llm?.observation_modalities || [];
  const mapping = { screenshot: "screenshot", accessibility_tree: "a11y" };
  const tabs = ["screenshot", "rendered", "dom", "a11y", "elements", "state"].map((id) => ({
    id, agentInput: modalities.some((modality) => mapping[modality] === id)
  }));
  if (llm && (!modalities.length || modalities.some((modality) => !mapping[modality]))) {
    tabs.push({ id: "agent", agentInput: false });
  }
  return tabs;
}

function agentModality(transition) {
  const llm = transition?.action?.metadata?.llm;
  if (!llm) return "No model call recorded";
  if (llm.observation_modalities) return llm.observation_modalities.map(humanLabel).join(" + ");
  if (!llm.messages?.length) return "Not recorded";
  const images = llm.messages.some((message) => Array.isArray(message.content) && message.content.some((item) => item.type === "image_url"));
  return images ? "Text + screenshot (legacy; text representation not recorded)" : "Text (legacy; representation not recorded)";
}

function agentInput(episode, transition) {
  const llm = transition.action?.metadata?.llm || {};
  const messages = llm.messages || [];
  if (!messages.length) return `<div class="empty">No model input recorded for this step.</div>`;
  const current = messages[messages.length - 1];
  const content = Array.isArray(current.content) ? current.content : [{ type: "text", text: current.content }];
  const currentHtml = content.map((item) => {
    if (item.type === "text") return `<pre>${escapeHtml(item.text)}</pre>`;
    if (item.type !== "image_url") return "";
    const artifact = transition.observation?.visual?.artifact;
    return artifact ? `<div class="screenshot-frame"><img src="/artifact/${episode.index}/${encodeURI(artifact)}" alt="Screenshot sent to the agent"></div>`
      : `<p>Screenshot was sent, but its saved artifact is unavailable.</p>`;
  }).join("");
  const omitted = llm.viewer_omitted_messages ? `<p>${llm.viewer_omitted_messages} earlier messages omitted from this legacy preview.</p>` : "";
  return `<p><strong>${escapeHtml(agentModality(transition))}</strong></p><p>Recorded input for this call. Other tabs show captured observations, which may not have been sent.</p>${currentHtml}
    <details><summary>System prompt and prior messages</summary>${omitted}${messageList(messages.slice(0, -1))}</details>`;
}
