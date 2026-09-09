"use client";

import { AlertTriangle, CalendarDays, FileSpreadsheet, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { UsageLine } from "@/components/integrations/usage-line";
import { config as configApi, type Integration, type IntegrationProvider, integrations } from "@/lib/api";
import { integrationUsage, type IntegrationUsage } from "@/lib/api/connections";
import { timeIn } from "@/lib/timezones";
import { useApi, useAuthToken } from "@/lib/use-api";
import { openSheetPicker } from "@/lib/google-picker";

/** A text link, for the two actions that must not compete with the primary. */
const QUIET_LINK_CLASSES =
  "text-sm font-medium text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50";

const SELECT_CLASSES =
  "h-10 w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

interface ProviderMeta {
  title: string;
  description: string;
  icon: typeof CalendarDays;
}

const META: Record<IntegrationProvider, ProviderMeta> = {
  google_calendar: {
    title: "Google Calendar",
    description: "Let the AI book appointments straight onto your calendar.",
    icon: CalendarDays,
  },
  google_sheets: {
    title: "Google Sheets",
    description: "Log leads, orders, and requests into a spreadsheet.",
    icon: FileSpreadsheet,
  },
};

/** Messages for the ?integration_error= codes the OAuth callback redirects with. */
const ERROR_COPY: Record<string, string> = {
  access_denied: "You cancelled the Google sign-in. Nothing was changed.",
  state_expired: "That sign-in link expired. Please click Connect again.",
  missing_code: "Google didn't send back an authorization code. Try again.",
  exchange_failed: "Google rejected the sign-in. Please try again.",
  no_refresh_token: "Google didn't grant offline access. Please try connecting again.",
  partial_consent:
    "Some required permissions were left unchecked. Click Connect and accept all of them.",
  store_failed: "We couldn't save the connection. Please try again.",
};

export default function IntegrationsPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => integrations.list({ token }), [token]);
  // Only for the clock shown on the calendar card. A failure here leaves the
  // line reading "UTC", which is a cosmetic wrong rather than a broken page,
  // so it deliberately does not gate rendering.
  const { data: tenantConfig } = useApi(() => configApi.get({ token }), [token]);
  // "Last booking 2 hours ago" (teardown N3). Deliberately not gating render:
  // a card without its usage line is still a usable card, and a failure here
  // must not hide the connect button.
  const { data: usage } = useApi(() => integrationUsage.map({ token }), [token]);
  const { toast } = useToast();
  const handledRedirect = useRef(false);

  // The OAuth callback lands back here with ?connected= or ?integration_error=.
  useEffect(() => {
    if (handledRedirect.current) return;
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const failed = params.get("integration_error");
    if (!connected && !failed) return;

    handledRedirect.current = true;
    if (connected) {
      toast({
        title: `${META[connected as IntegrationProvider]?.title ?? "Google"} connected`,
        variant: "success",
      });
    } else if (failed) {
      toast({
        title: "Couldn't connect Google",
        description: ERROR_COPY[failed] ?? failed,
        variant: "error",
      });
    }
    window.history.replaceState({}, "", window.location.pathname);
    refetch();
  }, [toast, refetch]);

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Integrations</h1>
        <p className="text-sm text-muted-foreground">
          Connect your Google account so your AI rep can take real actions: book appointments and
          record leads. Sign in once; there&apos;s nothing to copy or paste.
        </p>
      </div>

      {loading ? (
        <IntegrationsSkeleton />
      ) : error && !data ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <div className="space-y-6">
          {data.map((integration) => (
            <IntegrationCard
              key={integration.provider}
              integration={integration}
              token={token}
              timezone={tenantConfig?.timezone}
              usage={usage?.[integration.provider]}
              onChanged={refetch}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function IntegrationCard({
  integration,
  token,
  timezone,
  usage,
  onChanged,
}: {
  integration: Integration;
  token: string | undefined;
  /** The tenant's clock, shown on the calendar card. Undefined while loading. */
  timezone: string | undefined;
  /** Bookings made / rows written. Undefined while loading, or never connected. */
  usage: IntegrationUsage | undefined;
  onChanged: () => void;
}) {
  const meta = META[integration.provider];
  const Icon = meta.icon;
  const { toast } = useToast();

  const [busy, setBusy] = useState<string | null>(null);
  const isCalendar = integration.provider === "google_calendar";
  const config = integration.config ?? {};
  const needsReconnect =
    integration.status === "reauth_required" || integration.status === "scope_upgrade_required";
  const hasGrant = integration.status === "ok" || needsReconnect;

  const run = useCallback(
    async (label: string, fn: () => Promise<unknown>, successTitle?: string) => {
      setBusy(label);
      try {
        await fn();
        if (successTitle) toast({ title: successTitle, variant: "success" });
        onChanged();
      } catch (err) {
        toast({ title: "Something went wrong", description: errMessage(err), variant: "error" });
      } finally {
        setBusy(null);
      }
    },
    [onChanged, toast],
  );

  async function connect() {
    setBusy("connect");
    try {
      const url = await integrations.oauthStart(integration.provider, { token });
      // Full navigation, not fetch: the consent screen must be top-level.
      window.location.assign(url);
    } catch (err) {
      toast({ title: "Couldn't start sign-in", description: errMessage(err), variant: "error" });
      setBusy(null);
    }
  }

  async function chooseSheet() {
    setBusy("choose");
    try {
      const picker = await integrations.pickerConfig({ token });
      const spreadsheetId = await openSheetPicker(picker);
      if (!spreadsheetId) return; // owner closed the chooser
      const target = await integrations.selectSheet(spreadsheetId, undefined, { token });
      toast({ title: `Using “${target.title}”`, variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't pick that sheet", description: errMessage(err), variant: "error" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/15 text-primary-strong">
              <Icon className="h-5 w-5" />
            </span>
            <div>
              <CardTitle>{meta.title}</CardTitle>
              <CardDescription>{meta.description}</CardDescription>
            </div>
          </div>
          {integration.connected ? (
            <Badge tone="success">Connected</Badge>
          ) : needsReconnect ? (
            <Badge tone="warning">Reconnect needed</Badge>
          ) : hasGrant ? (
            <Badge tone="warning">Almost there</Badge>
          ) : (
            <Badge tone="default">Not connected</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {needsReconnect ? (
          <div className="flex items-start gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-semibold">
                {integration.status === "reauth_required"
                  ? "Google access was revoked"
                  : "New permissions needed"}
              </p>
              <p className="mt-0.5 text-muted-foreground">
                {integration.status === "reauth_required"
                  ? "Your AI rep has stopped using this until you reconnect."
                  : "Qonvo needs a couple of extra permissions to keep this working."}
              </p>
            </div>
          </div>
        ) : null}

        {!hasGrant ? (
          <div className="rounded-2xl border border-border bg-surface-muted px-4 py-4 text-sm">
            <p className="text-muted-foreground">
              {isCalendar
                ? "Sign in with Google and Qonvo creates a “Qonvo Bookings” calendar in your account. Bookings show up alongside your other calendars."
                : "Sign in with Google, then choose which spreadsheet to use, or let Qonvo make one for you."}
            </p>
          </div>
        ) : null}

        {integration.accountEmail ? (
          <p className="text-sm text-muted-foreground">
            Signed in as <span className="font-medium text-foreground">{integration.accountEmail}</span>
          </p>
        ) : null}

        {/* Whether the rep has actually used this, not just whether the token
            works (teardown N3). */}
        {hasGrant ? <UsageLine usage={usage} /> : null}

        {hasGrant && isCalendar ? (
          <div className="space-y-4">
            {config.calendar_id ? (
              <div className="rounded-2xl border border-border bg-surface-muted px-4 py-3 text-sm">
                Booking into{" "}
                <span className="font-semibold">{config.calendar_summary ?? "Qonvo Bookings"}</span>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Open Google Calendar and you&apos;ll see it in your calendar list.
                </p>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-muted px-4 py-3 text-sm">
                <span className="text-muted-foreground">
                  The bookings calendar hasn&apos;t been created yet.
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  onClick={() =>
                    run(
                      "provision",
                      () => integrations.provisionCalendar({ token }),
                      "Bookings calendar created",
                    )
                  }
                >
                  {busy === "provision" ? "Creating…" : "Create it"}
                </Button>
              </div>
            )}

            {/* Shown, not set. This used to be a select, and it was the only
                place the timezone could be changed at all -- so a tenant with
                no Google account could not reach the setting that governed
                their opening hours (teardown N1/V2). The tenant's own clock
                now governs both, and leaving an editable control here that no
                longer decides anything would be worse than the original bug:
                the owner would change it, see "Timezone updated", and nothing
                would happen. */}
            <p className="text-sm text-muted-foreground">
              Bookings use your business time zone,{" "}
              <strong className="font-bold text-foreground">
                {(timezone ?? "UTC").replace(/_/g, " ")}
              </strong>
              {timeIn(timezone ?? "UTC") ? `, where it is ${timeIn(timezone ?? "UTC")}` : null}.{" "}
              <Link
                href="/business"
                className="font-semibold text-primary-strong underline-offset-2 hover:underline"
              >
                Change it on Business
              </Link>
              .
            </p>
          </div>
        ) : null}

        {hasGrant && !isCalendar ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-muted px-4 py-3 text-sm">
              {config.spreadsheet_title || config.spreadsheet_id ? (
                <span>
                  Using{" "}
                  <span className="font-semibold">
                    {config.spreadsheet_title ?? config.spreadsheet_id}
                  </span>
                </span>
              ) : (
                <span className="text-muted-foreground">No spreadsheet chosen yet.</span>
              )}
              <div className="ml-auto flex items-center gap-2">
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={chooseSheet}>
                  {busy === "choose" ? "Opening…" : config.spreadsheet_id ? "Change sheet" : "Choose a sheet"}
                </Button>
                {!config.spreadsheet_id ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy !== null}
                    onClick={() =>
                      run(
                        "create",
                        () => integrations.createSheet("Qonvo Leads", { token }),
                        "Spreadsheet created",
                      )
                    }
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    {busy === "create" ? "Creating…" : "Make one for me"}
                  </Button>
                ) : null}
              </div>
            </div>

            {config.spreadsheet_id ? (
              <div className="max-w-xs space-y-1.5">
                <Label htmlFor="sheet-tab">Tab</Label>
                <select
                  id="sheet-tab"
                  className={SELECT_CLASSES}
                  value={config.sheet_range ?? ""}
                  disabled={busy !== null}
                  onChange={(e) =>
                    run(
                      "tab",
                      () =>
                        integrations.update(
                          integration.provider,
                          { config: { sheet_range: e.target.value } },
                          { token },
                        ),
                      "Tab updated",
                    )
                  }
                >
                  {parseTabs(config.available_tabs).map((tab) => (
                    <option key={tab} value={tab}>
                      {tab}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  Rows are appended to the bottom of this tab.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          {hasGrant ? (
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={integration.enabled}
                onCheckedChange={(enabled) =>
                  run("enabled", () =>
                    integrations.update(integration.provider, { enabled }, { token }),
                  )
                }
                label="Enabled"
              />
              <span className="text-muted-foreground">Enabled</span>
            </label>
          ) : (
            <span />
          )}
          {/* Emphasis follows the health of the connection (teardown N2).
              Reconnect used to be the loudest thing on a card whose badge said
              Connected -- a recovery action shouting at somebody with nothing
              to recover. On a working connection the loud button is "Test
              connection", which is what an owner actually came to do, and
              Reconnect is a quiet link beside Disconnect. It only turns loud
              when the connection itself reports a problem. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {hasGrant ? (
              <>
                <Button
                  variant={needsReconnect ? "outline" : "primary"}
                  size="sm"
                  disabled={busy !== null}
                  onClick={async () => {
                    setBusy("test");
                    try {
                      const result = await integrations.test(integration.provider, { token });
                      toast({
                        title: result.ok ? "Connection works" : "Connection failed",
                        description: result.message,
                        variant: result.ok ? "success" : "error",
                      });
                    } catch (err) {
                      toast({ title: "Test failed", description: errMessage(err), variant: "error" });
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  {busy === "test" ? "Testing…" : "Test connection"}
                </Button>
                {needsReconnect ? (
                  <Button size="sm" disabled={busy !== null} onClick={connect}>
                    {busy === "connect" ? "Redirecting…" : "Reconnect Google"}
                  </Button>
                ) : null}
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() =>
                    run(
                      "disconnect",
                      () => integrations.disconnect(integration.provider, { token }),
                      `${meta.title} disconnected`,
                    )
                  }
                  className={QUIET_LINK_CLASSES}
                >
                  Disconnect
                </button>
                {needsReconnect ? null : (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={connect}
                    className={QUIET_LINK_CLASSES}
                  >
                    {busy === "connect" ? "Redirecting…" : "Reconnect"}
                  </button>
                )}
              </>
            ) : (
              <Button size="sm" disabled={busy !== null} onClick={connect}>
                {busy === "connect" ? "Redirecting…" : "Connect Google"}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/** `available_tabs` round-trips through a JSON config column, so it may be a
 *  real array or its stringified form depending on the response path. */
function parseTabs(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[];
  if (typeof value === "string" && value.trim().startsWith("[")) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed as string[];
    } catch {
      // fall through
    }
  }
  return typeof value === "string" && value ? [value] : [];
}

function errMessage(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "Something went wrong.";
}

function IntegrationsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1].map((i) => (
        <Card key={i}>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
