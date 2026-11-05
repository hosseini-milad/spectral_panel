import { useEffect, useState } from "react";
import {
  applyTheme,
  chooseTheme,
  clearVolatileTheme,
  resolveTheme,
  themePreference,
} from "../lib/theme";

function snapshot() {
  const preference = themePreference();
  return { preference, theme: resolveTheme(preference) };
}
export function useThemePreference() {
  const [state, setState] = useState(snapshot);
  useEffect(() => {
    const update = () => {
      const next = snapshot();
      applyTheme(next.theme);
      setState(next);
    };
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const systemChange = () => {
      if (themePreference() === "system") update();
    };
    const storageChange = (event: StorageEvent) => {
      if (event.key === "spectral-theme" || event.key === null) {
        clearVolatileTheme();
        update();
      }
    };
    window.addEventListener("spectral-theme-change", update);
    window.addEventListener("storage", storageChange);
    media.addEventListener("change", systemChange);
    update();
    return () => {
      window.removeEventListener("spectral-theme-change", update);
      window.removeEventListener("storage", storageChange);
      media.removeEventListener("change", systemChange);
    };
  }, []);
  return { ...state, chooseTheme };
}
