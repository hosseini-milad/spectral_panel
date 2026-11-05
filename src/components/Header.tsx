import { ChevronLeft, Menu, Orbit } from "lucide-react";

export function Header({
  title,
  menuOpen,
  onMenu,
}: {
  title: string;
  menuOpen: boolean;
  onMenu: () => void;
}) {
  return (
    <header className="header">
      <div className="header-location">
        <button
          className="icon-button menu-toggle"
          onClick={onMenu}
          aria-label="باز کردن منو"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          aria-controls="mobile-navigation"
        >
          <Menu size={23} />
        </button>
        <Orbit size={19} className="breadcrumb-icon" />
        <span className="breadcrumb-root">فضای کار</span>
        <ChevronLeft size={15} className="breadcrumb-chevron" />
        <span className="breadcrumb-current">{title}</span>
      </div>
      <div className="header-meta">
        <span className="version-badge">
          <span />
          نسخهٔ اولیه
        </span>
        <span className="header-divider" />
        <span className="project-name" dir="ltr">
          spectral_project
        </span>
      </div>
    </header>
  );
}
