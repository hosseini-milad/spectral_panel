import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { mockDays, mockSnapshotDate, number, utcDate } from "../../data/days";

import { apiPath, type Page, type InventoryDay } from "../../api/days";
import { useApi } from "../../hooks/useApi";

function persianParts(date: Date) {
  const parts = new Intl.DateTimeFormat("en-US-u-ca-persian", {
    timeZone: "UTC",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(date);
  return Object.fromEntries(
    parts.map((part) => [part.type, Number(part.value)]),
  );
}
function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}
function monthStart(date: Date) {
  return addDays(date, 1 - persianParts(date).day);
}
function iso(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function PersianCalendar({
  selectedDate,
  onSelect,
  live = false,
  latestDate,
}: {
  selectedDate: string;
  onSelect: (date: string) => void;
  live?: boolean;
  latestDate?: string;
}) {
  const [month, setMonth] = useState(() => monthStart(utcDate(selectedDate)));
  useEffect(() => {
    setMonth(monthStart(utcDate(selectedDate)));
  }, [selectedDate]);
  const start = monthStart(month);
  let next = addDays(start, 29);
  while (persianParts(next).month === persianParts(start).month)
    next = addDays(next, 1);
  const length = Math.round((next.getTime() - start.getTime()) / 86400000);
  const offset = (start.getUTCDay() + 1) % 7;
  const title = new Intl.DateTimeFormat("fa-IR", {
    timeZone: "UTC",
    month: "long",
    year: "numeric",
  }).format(start);
  const dates = useApi<Page<InventoryDay>>(
    live
      ? apiPath("days/", {
          date_from: iso(start),
          date_to: iso(addDays(next, -1)),
          limit: 100,
        })
      : null,
  );
  const hasData = new Set(
    live
      ? (dates.data?.results.map((day) => day.day) ?? [])
      : mockDays.map((day) => day.date),
  );

  return (
    <section className="days-card calendar-card" aria-label="تقویم انتخاب روز">
      <div className="calendar-heading">
        <h2>انتخاب از تقویم</h2>
        <span>شمسی</span>
      </div>
      <div className="calendar-month">
        <button
          type="button"
          className="icon-button"
          aria-label="ماه قبل"
          onClick={() => setMonth(monthStart(addDays(start, -1)))}
        >
          <ChevronRight size={17} />
        </button>
        <strong aria-live="polite">{title}</strong>
        <button
          type="button"
          className="icon-button"
          aria-label="ماه بعد"
          onClick={() => setMonth(next)}
        >
          <ChevronLeft size={17} />
        </button>
      </div>
      <div className="calendar-grid calendar-weekdays" aria-hidden="true">
        {["ش", "ی", "د", "س", "چ", "پ", "ج"].map((day, index) => (
          <span key={index}>{day}</span>
        ))}
      </div>
      <div className="calendar-grid" role="group" aria-label={title}>
        {Array.from({ length: offset }, (_, index) => (
          <span key={`empty-${index}`} />
        ))}
        {Array.from({ length }, (_, index) => {
          const date = iso(addDays(start, index));
          return (
            <button
              type="button"
              key={date}
              className={`calendar-day${selectedDate === date ? " selected" : ""}${hasData.has(date) ? " has-data" : ""}`}
              aria-pressed={selectedDate === date}
              aria-label={new Intl.DateTimeFormat("fa-IR", {
                timeZone: "UTC",
                dateStyle: "full",
              }).format(utcDate(date))}
              onClick={() => onSelect(date)}
            >
              {number(index + 1)}
              {hasData.has(date) && <i aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <div className="calendar-legend">
        <span>
          <i />
          {live ? "دارای اطلاعات ثبت‌شده" : "دارای دادهٔ ماک"}
        </span>
        <button
          type="button"
          onClick={() => {
            const target = live ? latestDate : mockSnapshotDate;
            if (target) {
              setMonth(monthStart(utcDate(target)));
              onSelect(target);
            }
          }}
        >
          {live ? "آخرین روز موجود" : "آخرین روز نمونه"}
        </button>
      </div>
      <p className="calendar-caption">
        {live
          ? dates.loading
            ? "در حال دریافت روزهای این ماه…"
            : dates.error
              ? "دریافت روزهای تقویم ممکن نشد؛ از فهرست روزها استفاده کنید."
              : "نقطه‌ها روزهای ثبت‌شدهٔ همین ماه در سرور را نشان می‌دهند."
          : "نقطه‌های تقویم، روزهای موجود در نمونه را نشان می‌دهند؛ برای سایر روزها داده‌ای ثبت نشده است."}
      </p>
    </section>
  );
}
