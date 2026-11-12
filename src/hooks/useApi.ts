import { useEffect, useState } from "react";
import { ApiError, getJSON } from "../api/days";

export function useApi<T>(url: string | null) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    url: string | null;
    data?: T;
    error?: ApiError;
    loading: boolean;
  }>({ url: null, loading: false });
  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    setState({ url, loading: true });
    getJSON<T>(url, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ url, data, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({ url, error, loading: false });
      });
    return () => controller.abort();
  }, [url, attempt]);
  const current: typeof state =
    state.url === url ? state : { url, loading: Boolean(url) };
  return { ...current, retry: () => setAttempt((value) => value + 1) };
}
export function useDebounced<T>(value: T, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}
