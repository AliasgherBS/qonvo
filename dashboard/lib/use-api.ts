"use client";

import { signOut, useSession } from "next-auth/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** A 401 means the access token expired or was revoked — bounce to /login. */
function handleUnauthorized(err: unknown) {
  if (err instanceof ApiError && err.status === 401) {
    void signOut({ callbackUrl: "/login" });
  }
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
        handleUnauthorized(err);
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

/** Same as useApi, but re-runs on an interval — used for the QR/inbox/notification polls. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const runRef = useRef<() => void>(() => {});

  useEffect(() => {
    let active = true;

    const run = () => {
      fetcherRef
        .current()
        .then((data) => {
          if (active) setState({ data, loading: false, error: null });
        })
        .catch((err: unknown) => {
          handleUnauthorized(err);
          if (active) {
            setState((prev) => ({
              data: prev.data,
              loading: false,
              error: err instanceof Error ? err.message : "Something went wrong.",
            }));
          }
        });
    };

    runRef.current = run;
    run();
    const id = window.setInterval(run, intervalMs);

    return () => {
      active = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const refetch = useCallback(() => runRef.current(), []);

  return { ...state, refetch };
}

/** Convenience accessor for the bearer token every authed api.ts call needs. */
export function useAuthToken(): string | undefined {
  const { data: session } = useSession();
  return session?.accessToken;
}
