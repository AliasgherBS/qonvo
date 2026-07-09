"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Minimal fetch-on-mount hook — deliberately no cache/dedupe library. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetcherRef
      .current()
      .then((data) => {
        if (active) setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            data: null,
            loading: false,
            error: err instanceof Error ? err.message : "Something went wrong.",
          });
        }
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey]);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  return { ...state, refetch };
}

/** Same as useApi, but re-runs on an interval — used for the QR onboarding poll. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let active = true;

    const run = () => {
      fetcherRef
        .current()
        .then((data) => {
          if (active) setState({ data, loading: false, error: null });
        })
        .catch((err: unknown) => {
          if (active) {
            setState((prev) => ({
              data: prev.data,
              loading: false,
              error: err instanceof Error ? err.message : "Something went wrong.",
            }));
          }
        });
    };

    run();
    const id = window.setInterval(run, intervalMs);

    return () => {
      active = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
