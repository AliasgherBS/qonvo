"use client";

import { CalendarDays, Copy, FileSpreadsheet } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { type Integration, type IntegrationProvider, integrations } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

interface ProviderMeta {
  title: string;
  description: string;
  icon: typeof CalendarDays;
  targetKey: string;
  targetLabel: string;
  targetPlaceholder: string;
  secondKey: string;
  secondLabel: string;
  secondPlaceholder: string;
  shareNoun: string;
}

const META: Record<IntegrationProvider, ProviderMeta> = {
  google_calendar: {
    title: "Google Calendar",
    description: "Let the AI book appointments straight onto a calendar.",
    icon: CalendarDays,
    targetKey: "calendar_id",
    targetLabel: "Calendar ID",
    targetPlaceholder: "abc123@group.calendar.google.com",
    secondKey: "timezone",
    secondLabel: "Timezone (IANA)",
    secondPlaceholder: "Asia/Karachi",
    shareNoun: "calendar",
  },
  google_sheets: {
    title: "Google Sheets",
    description: "Log leads, orders, and requests into a spreadsheet.",
    icon: FileSpreadsheet,
    targetKey: "spreadsheet_id",
    targetLabel: "Spreadsheet ID",
    targetPlaceholder: "1AbCdEf... (from the sheet URL)",
    secondKey: "sheet_range",
    secondLabel: "Tab / range",
    secondPlaceholder: "Sheet1",
    shareNoun: "spreadsheet",
  },
};

export default function IntegrationsPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => integrations.list({ token }), [token]);

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Integrations</h1>
        <p className="text-sm text-muted-foreground">
          Connect a Google account so your AI rep can take real actions — book appointments and record
          leads. No code: you just share your calendar or sheet with a service-account email.
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
  onChanged,
}: {
  integration: Integration;
  token: string | undefined;
  onChanged: () => void;
}) {
  const meta = META[integration.provider];
  const Icon = meta.icon;
  const { toast } = useToast();

  const [target, setTarget] = useState(integration.config[meta.targetKey] ?? "");
  const [second, setSecond] = useState(integration.config[meta.secondKey] ?? "");
  const [saJson, setSaJson] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const connected = integration.enabled && integration.hasCredentials && Boolean(integration.config[meta.targetKey]);

  async function save() {
    setSaving(true);
    try {
      const config: Record<string, string> = { [meta.targetKey]: target.trim() };
      if (second.trim()) config[meta.secondKey] = second.trim();
      await integrations.update(
        integration.provider,
        { config, serviceAccountJson: saJson.trim() || undefined, enabled: true },
        { token },
      );
      setSaJson("");
      toast({ title: `${meta.title} saved`, variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't save", description: errMessage(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTesting(true);
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
      setTesting(false);
    }
  }

  async function toggleEnabled(enabled: boolean) {
    try {
      await integrations.update(integration.provider, { enabled }, { token });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't update", description: errMessage(err), variant: "error" });
    }
  }

  async function disconnect() {
    try {
      await integrations.disconnect(integration.provider, { token });
      toast({ title: `${meta.title} disconnected`, variant: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "Couldn't disconnect", description: errMessage(err), variant: "error" });
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
          {connected ? (
            <Badge tone="success">Connected</Badge>
          ) : integration.hasCredentials ? (
            <Badge tone="warning">Needs setup</Badge>
          ) : (
            <Badge tone="default">Not connected</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {integration.serviceAccountEmail ? (
          <div className="rounded-2xl border border-border bg-surface-muted px-4 py-3 text-sm">
            <p className="font-semibold">Share your {meta.shareNoun} with this email</p>
            <p className="mt-0.5 text-muted-foreground">
              Give it edit access, then Save and Test below.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 truncate rounded-lg bg-background px-2 py-1 text-xs">
                {integration.serviceAccountEmail}
              </code>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(integration.serviceAccountEmail ?? "");
                  toast({ title: "Copied", variant: "success" });
                }}
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${integration.provider}-target`}>{meta.targetLabel}</Label>
            <Input
              id={`${integration.provider}-target`}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={meta.targetPlaceholder}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${integration.provider}-second`}>{meta.secondLabel}</Label>
            <Input
              id={`${integration.provider}-second`}
              value={second}
              onChange={(e) => setSecond(e.target.value)}
              placeholder={meta.secondPlaceholder}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${integration.provider}-sa`}>
            Service-account key (JSON){integration.hasTenantKey ? " — already set, paste to replace" : ""}
          </Label>
          <Textarea
            id={`${integration.provider}-sa`}
            value={saJson}
            onChange={(e) => setSaJson(e.target.value)}
            placeholder={
              integration.hasCredentials
                ? "Leave blank to keep the current key"
                : '{ "type": "service_account", ... }'
            }
            rows={4}
            className="font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground">
            Stored encrypted. Leave blank to use the platform&apos;s shared service account.
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={integration.enabled} onCheckedChange={toggleEnabled} label="Enabled" />
            <span className="text-muted-foreground">Enabled</span>
          </label>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={disconnect}>
              Disconnect
            </Button>
            <Button variant="outline" size="sm" onClick={runTest} disabled={testing}>
              {testing ? "Testing…" : "Test connection"}
            </Button>
            <Button size="sm" onClick={save} disabled={saving || !target.trim()}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
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
