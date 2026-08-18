"use client";

import { signOut, useSession } from "next-auth/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, describeError } from "@/lib/api";

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * A 401 means the access token expired or was revoked - bounce to /login.
 *
 * Guard on the *presence of a token*: during the brief window before the
 * session hydrates, `useAuthToken()` is undefined and requests go out
 * token-less, which the backend rightly 401s. Signing out on that would nuke a
 * perfectly good session and loop the user back to /login. Only a 401 on a
 * request that *did* carry a token is a real expiry.
 */
function handleUnauthorized(err: unknown, token: string | undefined) {
  if (token && err instanceof ApiError && err.status === 401) {
    void signOut({ callbackUrl: "/login" });
  }
}

/** Minimal fetch-on-mount hook - deliberately no cache/dedupe library. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [reloadKey, setReloadKey] = useState(0);
  // Snapshotted per effect run so the 401 guard reflects the token the request
  // actually carried, not whatever the current token happens to be by the time
  // the request rejects (which would race).
  const token = useAuthToken();

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetcherRef
      .current()
      .then((data) => {
        if (active) setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        handleUnauthorized(err, token);
        if (active) {
          setState({
            data: null,
            loading: false,
            error: describeError(err),
          });
        }
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey, token]);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  return { ...state, refetch };
}

/** Same as useApi, but re-runs on an interval - used for the QR/inbox/notification polls. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const runRef = useRef<() => void>(() => {});
  // See useApi - snapshot the request-time token for the 401 guard.
  const token = useAuthToken();

  useEffect(() => {
    let active = true;

    const run = () => {
      fetcherRef
        .current()
        .then((data) => {
          if (active) setState({ data, loading: false, error: null });
        })
        .catch((err: unknown) => {
          handleUnauthorized(err, token);
          if (active) {
            setState((prev) => ({
              data: prev.data,
              loading: false,
              error: describeError(err),
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
  }, [...deps, token]);

  const refetch = useCallback(() => runRef.current(), []);

  return { ...state, refetch };
}

/** Convenience accessor for the bearer token every authed api.ts call needs. */
export function useAuthToken(): string | undefined {
  const { data: session } = useSession();
  return session?.accessToken;
}
