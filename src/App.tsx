import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { navigation } from "./config/navigation";
import { WorkspacePage } from "./pages/WorkspacePage";
import { DaysPage } from "./pages/DaysPage";
import { VisualizationsPage } from "./pages/VisualizationsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { OperationsPage } from "./pages/OperationsPage";
import { ModelsPage } from "./pages/ModelsPage";

export function App() {
  const { pathname } = useLocation();
  const page = navigation.find((item) => item.path === pathname);
  const [menuOpen, setMenuOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [pathname]);
  useEffect(() => {
    document.title = `${page?.label ?? "صفحه پیدا نشد"} | اسپکترال`;
  }, [page]);
  useEffect(() => {
    const dialog = drawer.current;
    if (menuOpen) dialog?.showModal();
    else if (dialog?.open) dialog.close();
    const previousOverflow = document.body.style.overflow;
    if (menuOpen) document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [menuOpen]);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1001px)");
    const closeOnDesktop = () => {
      if (media.matches) setMenuOpen(false);
    };
    media.addEventListener("change", closeOnDesktop);
    return () => media.removeEventListener("change", closeOnDesktop);
  }, []);

  return (
    <div className="app-shell">
      <a
        href="#main-content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        رفتن به محتوای اصلی
      </a>
      <aside className="sidebar desktop-sidebar">
        <Sidebar onNavigate={() => setMenuOpen(false)} />
      </aside>
      <dialog
        id="mobile-navigation"
        ref={drawer}
        className="mobile-drawer"
        aria-label="منوی اصلی"
        onCancel={() => setMenuOpen(false)}
        onClose={() => setMenuOpen(false)}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = drawer.current?.querySelectorAll<HTMLElement>(
            "a[href], button:not([disabled])",
          );
          if (!controls?.length) return;
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onClick={(event) => {
          if (event.target === drawer.current) setMenuOpen(false);
        }}
      >
        <div className="sidebar">
          <Sidebar onNavigate={() => setMenuOpen(false)} />
        </div>
      </dialog>
      <div className="content-shell">
        <Header
          title={page?.label ?? "صفحه پیدا نشد"}
          menuOpen={menuOpen}
          onMenu={() => setMenuOpen(true)}
        />
        {pathname === "/models" ? (
          <ModelsPage />
        ) : pathname === "/operations" ? (
          <OperationsPage />
        ) : pathname === "/" ? (
          <OverviewPage />
        ) : pathname === "/visualizations" ? (
          <VisualizationsPage />
        ) : pathname === "/days" ? (
          <DaysPage />
        ) : page ? (
          <WorkspacePage page={page} />
        ) : (
          <main id="main-content" className="main-content" tabIndex={-1}>
            <h1>صفحه پیدا نشد</h1>
            <Link to="/">بازگشت به نمای کلی</Link>
          </main>
        )}
        <Footer />
      </div>
    </div>
  );
}
