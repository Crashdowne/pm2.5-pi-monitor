import { useEffect, useRef, useState } from "react";

interface State<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

// Fetch on mount and whenever deps change; optionally re-poll on an interval.
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number): State<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    const run = () => {
      fnRef
        .current()
        .then((d) => alive && setState({ data: d, error: null, loading: false }))
        .catch((e) => alive && setState((s) => ({ data: s.data, error: String(e), loading: false })));
    };
    setState((s) => ({ ...s, loading: true }));
    run();
    if (pollMs) {
      const id = setInterval(run, pollMs);
      return () => { alive = false; clearInterval(id); };
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
