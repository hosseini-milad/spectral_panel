import { useEffect, useRef, useState } from "react";
import type { ProcessingDay } from "../data/days";
import {
  initialPipelineState,
  mockPipelineResults,
  operationSteps,
  type PipelineLog,
  type PipelineSettings,
  type Scenario,
} from "../data/operations";

interface ActiveSimulation {
  id: string;
  timer: ReturnType<typeof setTimeout> | null;
}
const makeLog = (
  level: PipelineLog["level"],
  message: string,
): PipelineLog => ({
  id: crypto.randomUUID(),
  time: new Date().toISOString(),
  level,
  message,
});

export function useMockPipeline(day: ProcessingDay | undefined) {
  const [state, setState] = useState(initialPipelineState);
  const active = useRef<ActiveSimulation | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (active.current?.timer) clearTimeout(active.current.timer);
      active.current = null;
    };
  }, []);

  function run(
    mode: "all" | number,
    settings: PipelineSettings,
    scenario: Scenario,
  ) {
    if (!day || active.current || !mounted.current) return;
    const first = state.steps.findIndex((step) => step.status !== "succeeded");
    if (first < 0 || (typeof mode === "number" && mode !== first)) return;
    const queue =
      typeof mode === "number"
        ? [mode]
        : operationSteps.map((_, index) => index).slice(first);
    const snapshotSettings = { ...(state.settings ?? settings) };
    const results = mockPipelineResults(day, snapshotSettings);
    const simulation: ActiveSimulation = {
      id: `mock-${day.date.replaceAll("-", "")}-${crypto.randomUUID().slice(0, 8)}`,
      timer: null,
    };
    active.current = simulation;
    setState((previous) => ({
      ...previous,
      runId: simulation.id,
      runDay: day.date,
      settings: snapshotSettings,
      status: "running",
      steps: previous.steps.map((step, index) =>
        queue.includes(index)
          ? {
              ...step,
              status: "queued",
              progress: 0,
              error: null,
              result: null,
              runId: `${simulation.id}-${index + 1}`,
              startedAt: null,
              finishedAt: null,
            }
          : step,
      ),
      logs: [
        ...previous.logs,
        makeLog(
          "info",
          `${typeof mode === "number" ? "اجرای یک مرحله" : "اجرای مراحل باقی‌مانده"} برای روز ${day.date} آغاز شد. شناسه: ${simulation.id}`,
        ),
      ],
    }));

    function begin(position: number) {
      if (active.current !== simulation || !mounted.current) return;
      const index = queue[position];
      const label = operationSteps[index].shortLabel;
      setState((previous) => ({
        ...previous,
        steps: previous.steps.map((step, current) =>
          current === index
            ? {
                ...step,
                status: "running",
                startedAt: new Date().toISOString(),
              }
            : step,
        ),
        logs: [
          ...previous.logs,
          makeLog(
            "info",
            `شروع ${label} · روز ${day!.date} · پیشرفت کاملاً نمایشی است.`,
          ),
        ],
      }));
      let tick = 0;
      function advance() {
        if (active.current !== simulation || !mounted.current) return;
        tick += 1;
        if (scenario === "sampling-error" && index === 1 && tick === 3) {
          active.current = null;
          const error =
            "خطای تزریقی ماک: ورودی نمونه‌برداری در دسترس نیست. برای آزمایش تلاش مجدد، سناریو را به «اجرای موفق» تغییر دهید.";
          setState((previous) => ({
            ...previous,
            status: "failed",
            steps: previous.steps.map((step, current) =>
              current === index
                ? {
                    ...step,
                    status: "failed",
                    progress: tick * 20,
                    finishedAt: new Date().toISOString(),
                    error,
                  }
                : step.status === "queued"
                  ? { ...step, status: "pending", progress: 0, runId: null }
                  : step,
            ),
            logs: [
              ...previous.logs,
              makeLog("error", error),
              makeLog(
                "warning",
                "ادامهٔ مراحل متوقف شد؛ هیچ مرحلهٔ بعدی اجرا نشد.",
              ),
            ],
          }));
          return;
        }
        if (tick === 5) {
          const last = position === queue.length - 1;
          if (last) active.current = null;
          setState((previous) => ({
            ...previous,
            status: last ? "finished" : "running",
            steps: previous.steps.map((step, current) =>
              current === index
                ? {
                    ...step,
                    status: "succeeded",
                    progress: 100,
                    result: results[index],
                    finishedAt: new Date().toISOString(),
                  }
                : step,
            ),
            logs: [
              ...previous.logs,
              makeLog(
                "success",
                `${label} تکمیل شد · خروجی نمونه: ${results[index].output} ${operationSteps[index].output}`,
              ),
              ...(last
                ? [
                    makeLog(
                      "success",
                      "اجرای درخواستی پایان یافت. هیچ داده یا وضعیت واقعی تغییر نکرد.",
                    ),
                  ]
                : []),
            ],
          }));
          if (!last) begin(position + 1);
          return;
        }
        setState((previous) => ({
          ...previous,
          steps: previous.steps.map((step, current) =>
            current === index ? { ...step, progress: tick * 20 } : step,
          ),
        }));
        simulation.timer = setTimeout(advance, 400);
      }
      simulation.timer = setTimeout(advance, 400);
    }
    begin(0);
  }

  function stop() {
    if (!active.current) return;
    if (active.current.timer) clearTimeout(active.current.timer);
    active.current = null;
    setState((previous) => ({
      ...previous,
      status: "interrupted",
      steps: previous.steps.map((step) =>
        step.status === "running"
          ? {
              ...step,
              status: "interrupted",
              finishedAt: new Date().toISOString(),
            }
          : step.status === "queued"
            ? { ...step, status: "pending", progress: 0, runId: null }
            : step,
      ),
      logs: [
        ...previous.logs,
        makeLog(
          "warning",
          "شبیه‌سازی با درخواست کاربر متوقف شد. مرحلهٔ نیمه‌تمام در تلاش بعد از ابتدا نمایش داده می‌شود.",
        ),
      ],
    }));
  }
  function reset() {
    if (!active.current) setState(initialPipelineState());
  }
  return { state, run, stop, reset, busy: state.status === "running" };
}
