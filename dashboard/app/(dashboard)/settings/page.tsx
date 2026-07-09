"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { settings, type TenantConfig } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const LANGUAGES = ["English", "Urdu", "Arabic", "Hindi"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function SettingsPage() {
  const { data, loading, error, refetch } = useApi(() => settings.get());
  const [form, setForm] = useState<TenantConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  async function handleSave() {
    if (!form) return;
    setSaving(true);
    try {
      await settings.update(form);
      setSavedAt(Date.now());
    } catch {
      // Backend not wired yet in Phase 0 — the form still reflects local edits.
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Persona, languages, hours, and escalation — how your AI rep shows up for customers.
        </p>
      </div>

      {loading ? (
        <SettingsSkeleton />
      ) : error && !form ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            Can&apos;t reach the backend yet — settings will load once the API is connected.
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : form ? (
        <>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Persona</CardTitle>
                <CardDescription>How your AI rep introduces and carries itself.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="persona">Persona description</Label>
                <Textarea
                  id="persona"
                  rows={3}
                  value={form.persona}
                  onChange={(e) => setForm({ ...form, persona: e.target.value })}
                  placeholder="Friendly, sharp, and quick to help — sounds like a great front-desk teammate."
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tone">Tone</Label>
                <Input
                  id="tone"
                  value={form.tone}
                  onChange={(e) => setForm({ ...form, tone: e.target.value })}
                  placeholder="Warm, confident, concise"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Languages</CardTitle>
                <CardDescription>Customers get replies in whichever of these they write in.</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-3">
                {LANGUAGES.map((language) => {
                  const checked = form.languages.includes(language);
                  return (
                    <label
                      key={language}
                      className="flex items-center gap-2 rounded-full border border-border-strong px-3 py-1.5 text-sm"
                    >
                      <Switch
                        checked={checked}
                        onCheckedChange={(next) =>
                          setForm({
                            ...form,
                            languages: next
                              ? [...form.languages, language]
                              : form.languages.filter((l) => l !== language),
                          })
                        }
                        label={language}
                      />
                      {language}
                    </label>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Business hours</CardTitle>
                <CardDescription>Outside these hours, customers get your custom auto-reply.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="timezone">Timezone</Label>
                <Input
                  id="timezone"
                  value={form.businessHours.timezone}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      businessHours: { ...form.businessHours, timezone: e.target.value },
                    })
                  }
                  placeholder="Asia/Karachi"
                />
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                {DAYS.map((day) => (
                  <span key={day} className="rounded-full bg-surface-muted px-2.5 py-1">
                    {day}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Per-day windows editor lands once the settings API is connected — timezone above already saves.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Escalation</CardTitle>
                <CardDescription>Where we alert you when a customer needs a human, now.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="escalation-number">Owner alert number (WhatsApp)</Label>
                <Input
                  id="escalation-number"
                  value={form.escalationNumber}
                  onChange={(e) => setForm({ ...form, escalationNumber: e.target.value })}
                  placeholder="+92 3XX XXXXXXX"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="auto-resume">Auto-resume bot after (hours)</Label>
                <Input
                  id="auto-resume"
                  type="number"
                  min={1}
                  value={form.autoResumeHours}
                  onChange={(e) => setForm({ ...form, autoResumeHours: Number(e.target.value) })}
                  className="max-w-[8rem]"
                />
              </div>
            </CardContent>
          </Card>

          <div className="flex items-center gap-3">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
            {savedAt ? <span className="text-sm text-muted-foreground">Saved.</span> : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
