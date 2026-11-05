import { Moon, Sun } from "lucide-react";
import { useThemePreference } from "../hooks/useThemePreference";

export function ThemeToggle() {
  const { theme, chooseTheme } = useThemePreference();
  function toggle() {
    chooseTheme(theme === "light" ? "dark" : "light");
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
