import { useEffect, useState } from "react";
import { apiPath, getJSON, type Page } from "../api/days";
import {
  getRun,
  getTasks,
  type Run,
  type RunEvent,
  type Task,
} from "../api/operations";
export function useOperations(
  day: string | null,
  runId: string | null,
  queueOffset: number,
  taskOffset: number,
  eventOffset: number,
) {
  const [data, setData] = useState<{
    queue?: Page<Run>;
    run?: Run;
    tasks?: Page<Task>;
    events?: Page<RunEvent>;
  }>({});
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    setData({});
    setError("");
    async function refresh() {
      try {
        const [queue, run, tasks, events] = await Promise.all([
          getJSON<Page<Run>>(
            apiPath("operations/runs/", {
              day: day ?? undefined,
              limit: 5,
              offset: queueOffset,
            }),
            controller.signal,
          ),
          runId ? getRun(runId, controller.signal) : Promise.resolve(undefined),
          runId
            ? getTasks(runId, taskOffset, controller.signal)
            : Promise.resolve(undefined),
          runId
            ? getJSON<Page<RunEvent>>(
                apiPath(`operations/runs/${runId}/events/`, {
                  limit: 20,
                  offset: eventOffset,
                }),
                controller.signal,
              )
            : Promise.resolve(undefined),
        ]);
        if (active) {
          setData({ queue, run, tasks, events });
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) timer = setTimeout(refresh, 10000);
      }
    }
    void refresh();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [day, runId, queueOffset, taskOffset, eventOffset, attempt]);
  return { ...data, error, retry: () => setAttempt((v) => v + 1) };
}
