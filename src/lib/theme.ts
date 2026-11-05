export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";
let volatilePreference: ThemePreference | undefined;

export function themePreference(): ThemePreference {
  if (volatilePreference !== undefined) return volatilePreference;
  try {
    const saved = localStorage.getItem("spectral-theme");
    if (saved === "light" || saved === "dark" || saved === "system")
      return saved;
  } catch {
    /* Use the in-memory preference when storage is unavailable. */
  }
  return volatilePreference ?? "system";
}

export function resolveTheme(preference: ThemePreference): Theme {
  return preference === "system"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light"
    : preference;
}

export function initialTheme(): Theme {
  return resolveTheme(themePreference());
}

export function chooseTheme(preference: ThemePreference) {
  volatilePreference = preference;
  try {
    localStorage.setItem("spectral-theme", preference);
  } catch {
    /* The visit-local preference still applies. */
  }
  applyTheme(resolveTheme(preference));
  window.dispatchEvent(new Event("spectral-theme-change"));
}

export function clearVolatileTheme() {
  volatilePreference = undefined;
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#101c20" : "#f5f7f8");
}
