import { BookOpen, Orbit, X, ArrowUpLeft } from "lucide-react";
import { NavLink } from "react-router-dom";
import { navigation, navigationGroups } from "../config/navigation";

export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  return (
    <>
      <div className="sidebar-brand">
        <span className="brand-mark">
          <Orbit size={27} strokeWidth={1.5} />
        </span>
        <div>
          <span className="brand-title">
            اسپکترال<span className="brand-dot">.</span>
          </span>
          <span className="brand-caption">فضای مدیریت تحلیل</span>
        </div>
        <button
          className="icon-button close-menu"
          onClick={onNavigate}
          aria-label="بستن منو"
        >
          <X size={21} />
        </button>
      </div>
      <nav aria-label="منوی اصلی" className="navigation">
        {navigationGroups.map((group) => (
          <div className="nav-group" key={group.id}>
            <p className="nav-group-title">{group.label}</p>
            {navigation
              .filter((item) => item.group === group.id)
              .map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.path === "/"}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `nav-item${isActive ? " active" : ""}`
                  }
                >
                  <item.icon size={19} strokeWidth={1.7} />
                  <span>{item.label}</span>
                  <span className="active-indicator" />
                </NavLink>
              ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <a
          className="docs-link"
          href="/swagger/"
          target="_blank"
          rel="noreferrer"
        >
          <BookOpen size={19} />
          <span>مستندات API</span>
          <ArrowUpLeft size={16} />
        </a>
        <div className="sidebar-version">
          <span>چارچوب تحلیل طیفی</span>
          <span dir="ltr">v0.1</span>
        </div>
      </div>
    </>
  );
}
