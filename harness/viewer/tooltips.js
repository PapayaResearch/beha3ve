const tooltip = document.createElement("div");
tooltip.id = "viewer-tooltip";
tooltip.className = "viewer-tooltip";
tooltip.role = "note";
tooltip.hidden = true;
document.body.append(tooltip);
let tooltipTarget;

function hideTooltip() {
  if (tooltipTarget) {
    tooltipTarget.removeAttribute("aria-describedby");
    tooltipTarget.setAttribute("aria-expanded", "false");
  }
  tooltipTarget = null;
  tooltip.hidden = true;
}

function showTooltip(target) {
  hideTooltip();
  const key = target.dataset.help;
  tooltip.textContent = key.startsWith("outcome:")
    ? (viewerCopy.outcomes[key.slice(8)]?.detail || viewerCopy.tooltips.unknownOutcome)
    : viewerCopy.tooltips[key];
  tooltipTarget = target;
  target.setAttribute("aria-describedby", tooltip.id);
  target.setAttribute("aria-expanded", "true");
  tooltip.hidden = false;
  const bounds = target.getBoundingClientRect();
  const width = tooltip.offsetWidth;
  const height = tooltip.offsetHeight;
  tooltip.style.left = `${Math.max(12, Math.min(bounds.left, window.innerWidth - width - 12))}px`;
  tooltip.style.top = `${Math.max(12, bounds.bottom + height + 20 < window.innerHeight ? bounds.bottom + 8 : bounds.top - height - 8)}px`;
}

function attachHelpButtons() {
  document.querySelectorAll("[data-tooltip]").forEach((target) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "help-button";
    button.dataset.help = target.dataset.tooltip;
    const label = target.textContent;
    button.setAttribute("aria-label", `Help: ${label.trim()}`);
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", tooltip.id);
    button.textContent = "?";
    target.append(button);
    target.removeAttribute("tabindex");
    delete target.dataset.tooltip;
  });
}

document.addEventListener("DOMContentLoaded", attachHelpButtons);
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-help]");
  if (target) {
    event.preventDefault();
    event.stopPropagation();
    if (target === tooltipTarget) hideTooltip();
    else showTooltip(target);
  } else if (!tooltip.contains(event.target)) {
    hideTooltip();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideTooltip();
});
document.addEventListener("scroll", (event) => {
  if (!tooltip.contains(event.target)) hideTooltip();
}, true);
window.addEventListener("resize", hideTooltip);
