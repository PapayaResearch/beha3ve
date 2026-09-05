const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
let themePreference = localStorage.getItem("viewer-theme") || "system";

function applyTheme() {
  document.documentElement.dataset.theme = themePreference === "system"
    ? (systemTheme.matches ? "dark" : "light")
    : themePreference;
}

applyTheme();
systemTheme.addEventListener("change", applyTheme);
document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("theme-select");
  select.value = themePreference;
  select.addEventListener("change", () => {
    themePreference = select.value;
    localStorage.setItem("viewer-theme", themePreference);
    applyTheme();
  });
});
