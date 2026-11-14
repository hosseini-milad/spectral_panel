import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowUpLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ListTodo,
} from "lucide-react";
import { ExecutionQueue } from "../components/operations/ExecutionQueue";
import { apiPath, type InventoryDay, type Page } from "../api/days";
import { useApi } from "../hooks/useApi";
import { dateLabel } from "../data/days";
import { isISODate } from "../lib/dayNavigation";
import "./jobs.css";

export function JobsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [daysOffset, setDaysOffset] = useState(0);
  const days = useApi<Page<InventoryDay>>(
    apiPath("days/", { limit: 10, offset: daysOffset }),
  );
  const requested = params.get("day");
  const day = requested && isISODate(requested) ? requested : null;
  const parsed = Number(params.get("offset") ?? 0);
  const offset =
    Number.isInteger(parsed) && parsed >= 0 && parsed <= 1000000 ? parsed : 0;
  const currentLink = new URLSearchParams();
  if (day) currentLink.set("day", day);
  if (params.get("run")) currentLink.set("run", params.get("run")!);
  return (
    <main id="main-content" className="main-content jq-page" tabIndex={-1}>
      <header className="jq-page-heading">
        <div>
          <span className="jq-eyebrow">
            <ListTodo size={14} />
            مرکز پیگیری پردازش
          </span>
          <h1>صف اجراها</h1>
          <p>
            اجرای فعال و نوبت‌های بعدی پردازش؛ مستقل از روزی که مشاهده می‌کنید.
          </p>
        </div>
        <div className="jq-actions">
          <Link
            to={"/operations" + (currentLink.size ? "?" + currentLink : "")}
          >
            عملیات و پردازش
            <ArrowUpLeft size={15} />
          </Link>
        </div>
      </header>
      {requested && !day && (
        <p className="jq-notice warning" role="alert">
          تاریخ فیلتر معتبر نیست؛ روز را از فهرست انتخاب کنید.
        </p>
      )}
      <ExecutionQueue
        day={day}
        selectedId={params.get("run")}
        offset={offset}
        onPageChange={(value) =>
          setParams((previous) => {
            const q = new URLSearchParams(previous);
            if (value) q.set("offset", String(value));
            else q.delete("offset");
            return q;
          })
        }
        onSelect={(run) =>
          navigate(
            `/operations?${new URLSearchParams({ day: run.day, run: run.id })}`,
          )
        }
        filters={
          <>
            <label className="jq-day-filter">
              <CalendarDays size={15} />
              روز داده
              <select
                aria-label="فیلتر روز اجرا"
                value={day ?? ""}
                onChange={(e) =>
                  setParams(e.target.value ? { day: e.target.value } : {})
                }
              >
                <option value="">همهٔ روزها</option>
                {day && !days.data?.results.some((d) => d.day === day) && (
                  <option value={day}>{dateLabel(day)}</option>
                )}
                {days.data?.results.map((d) => (
                  <option key={d.day} value={d.day}>
                    {dateLabel(d.day)}
                  </option>
                ))}
              </select>
            </label>
            {days.data && days.data.count > 10 && (
              <div className="jq-day-pages">
                <button
                  aria-label="روزهای جدیدتر فیلتر صف"
                  disabled={!daysOffset || days.loading}
                  onClick={() => setDaysOffset(Math.max(0, daysOffset - 10))}
                >
                  <ChevronRight size={14} />
                </button>
                <button
                  aria-label="روزهای قدیمی‌تر فیلتر صف"
                  disabled={daysOffset + 10 >= days.data.count || days.loading}
                  onClick={() => setDaysOffset(daysOffset + 10)}
                >
                  <ChevronLeft size={14} />
                </button>
              </div>
            )}
            <span className="jq-filter-note">
              اجرای فعالِ روزهای دیگر همواره نمایش داده می‌شود.
            </span>
            {days.error && (
              <button className="jq-text-button" onClick={days.retry}>
                دریافت دوبارهٔ روزها
              </button>
            )}
          </>
        }
      />
    </main>
  );
}
