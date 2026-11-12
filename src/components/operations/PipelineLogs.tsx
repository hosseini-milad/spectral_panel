import { useEffect, useRef } from "react";
import { Terminal, Circle } from "lucide-react";
import { type PipelineLog, pipelineLogTime } from "../../data/operations";
import { number } from "../../data/days";

const levelLabels = {
  info: "اطلاع",
  success: "موفق",
  error: "خطا",
  warning: "توجه",
};
export function PipelineLogs({
  logs,
  busy,
}: {
  logs: PipelineLog[];
  busy: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useEffect(() => {
    if (!logs.length) follow.current = true;
    if (box.current && follow.current)
      box.current.scrollTop = box.current.scrollHeight;
  }, [logs]);
  return (
    <section className="op-card op-logs" aria-labelledby="pipeline-logs-title">
      <div className="op-section-heading">
        <div>
          <Terminal size={18} />
          <h2 id="pipeline-logs-title">رویدادهای پردازش</h2>
          <span className="op-count">{number(logs.length)}</span>
        </div>
        <span className={`op-log-state${busy ? " active" : ""}`}>
          <Circle size={6} fill="currentColor" />
          {busy ? "در حال دریافت از سرور" : "ثبت سرور"}
        </span>
      </div>
      <div
        className="op-log-output"
        ref={box}
        role="log"
        aria-live="polite"
        aria-label="رویدادهای پردازش سرور"
        tabIndex={0}
        onScroll={() => {
          if (box.current)
            follow.current =
              box.current.scrollHeight -
                box.current.clientHeight -
                box.current.scrollTop <
              40;
        }}
      >
        {logs.length ? (
          logs.map((log) => (
            <div key={log.id} className={`op-log-line ${log.level}`}>
              <time dateTime={log.time}>{pipelineLogTime(log.time)}</time>
              <span className="op-log-level">{levelLabels[log.level]}</span>
              <p>
                {log.message
                  .split(/(mock-[A-Za-z0-9-]+|\d{4}-\d{2}-\d{2})/g)
                  .map((part, index) =>
                    /^(mock-|\d{4}-\d{2}-\d{2}$)/.test(part) ? (
                      <bdi key={index} dir="ltr">
                        {part}
                      </bdi>
                    ) : (
                      part
                    ),
                  )}
              </p>
            </div>
          ))
        ) : (
          <div className="op-log-empty">
            <Terminal size={25} />
            <strong>هنوز اجرایی شروع نشده است</strong>
            <p>
              با انتخاب روز و اجرای مرحله، وضعیت و رویدادها اینجا نمایش داده
              می‌شوند.
            </p>
          </div>
        )}
      </div>
      <div className="op-log-note">
        زمان‌ها به وقت تهران‌اند. رویدادهای امنِ ثبت‌شده در سرور نمایش داده
        می‌شوند؛ جزئیات فنی در لاگ داخلی worker باقی می‌مانند.
      </div>
    </section>
  );
}
