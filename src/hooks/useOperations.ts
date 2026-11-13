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
  taskOffset: number,
  eventOffset: number,
) {
  const scope = `${day ?? ""}:${runId ?? ""}`;
  const [data, setData] = useState<{
    scope?: string;
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
    setError("");
    async function refresh() {
      try {
        const [run, tasks, events] = await Promise.all([
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
          setData({ scope, run, tasks, events });
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
  }, [day, runId, taskOffset, eventOffset, attempt, scope]);
  return {
    ...(data.scope === scope ? data : {}),
    error,
    retry: () => setAttempt((v) => v + 1),
  };
}
