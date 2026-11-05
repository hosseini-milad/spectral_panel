import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { applyTheme, initialTheme, type Theme } from "../lib/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    applyTheme(next);
    try {
      localStorage.setItem("spectral-theme", next);
    } catch {
      /* Keep the in-memory choice. */
    }
  }
  return (
    <button
      className="theme-toggle icon-button"
      onClick={toggle}
      aria-label="تم تیره"
      aria-pressed={theme === "dark"}
      title={theme === "dark" ? "تغییر به تم روشن" : "تغییر به تم تیره"}
    >
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      <span className="theme-label">{theme === "dark" ? "روشن" : "تیره"}</span>
    </button>
  );
}
