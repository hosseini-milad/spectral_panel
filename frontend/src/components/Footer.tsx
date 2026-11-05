import { ArrowUpLeft } from "lucide-react";

export function Footer() {
  return (
    <footer className="footer">
      <span>
        اسپکترال <span className="footer-dot">·</span> مدیریت و مشاهدهٔ چارچوب
        علمی
      </span>
      <div>
        <span className="footer-version">نسخهٔ ۰.۱.۰</span>
        <a href="/swagger/" target="_blank" rel="noreferrer">
          راهنمای API
          <ArrowUpLeft size={14} />
        </a>
      </div>
    </footer>
  );
}
