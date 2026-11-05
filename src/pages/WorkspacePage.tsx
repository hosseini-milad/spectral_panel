import { ArrowDownRight, PanelsTopLeft, Sparkles } from "lucide-react";
import type { NavigationItem } from "../config/navigation";
import { navigation } from "../config/navigation";

export function WorkspacePage({ page }: { page: NavigationItem }) {
  return (
    <main id="main-content" className="main-content" tabIndex={-1}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">پنل مدیریت / {page.label}</p>
          <h1>{page.label}</h1>
          <p className="page-description">{page.description}</p>
        </div>
        <span className="section-number" aria-hidden="true">
          /{" "}
          {String(
            navigation.findIndex((item) => item.path === page.path) + 1,
          ).padStart(2, "0")}
        </span>
      </div>
      <section className="workspace-card" aria-labelledby="workspace-title">
        <div className="card-topline">
          <span>
            <PanelsTopLeft size={15} />
            فضای کار شما
          </span>
          <span className="card-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </div>
        <div className="workspace-placeholder">
          <div className="placeholder-art" aria-hidden="true">
            <div className="art-orbit orbit-one" />
            <div className="art-orbit orbit-two" />
            <span className="art-point point-one" />
            <span className="art-point point-two" />
            <span className="art-point point-three" />
            <div className="art-center">
              <page.icon size={35} strokeWidth={1.3} />
            </div>
            <span className="art-spark">
              <Sparkles size={16} />
            </span>
          </div>
          <span className="phase-label">گام اول · ساختار پنل</span>
          <h2 id="workspace-title">
            {page.path === "/"
              ? "همه‌چیز از یک نمای روشن شروع می‌شود."
              : `فضای ${page.label}`}
          </h2>
          <p>
            ساختار اولیه آماده است. امکانات این بخش در مرحله‌های بعد،
            <br className="desktop-break" /> با اتصال به داده‌ها و اجراهای پروژه
            تکمیل می‌شود.
          </p>
          <div className="placeholder-hint">
            <ArrowDownRight size={16} />
            <span>بخش‌های مختلف را از منوی کناری مرور کنید.</span>
          </div>
        </div>
        <div className="card-bottomline">
          <span className="outline-dot" />
          داده و اجرای زنده در این نسخه نمایش داده نمی‌شود.
        </div>
      </section>
    </main>
  );
}
