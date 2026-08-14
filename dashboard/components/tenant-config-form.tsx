"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import type { LlmProvider, TenantConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

const PERSONA_OPTIONS = ["Friendly & warm", "Professional", "Playful & witty", "Formal", "Direct & concise"];
const TONE_OPTIONS = [
  "Warm",
  "Professional",
  "Concise",
  "Friendly",
  "Casual",
  "Formal",
  "Enthusiastic",
  "Direct",
  "Empathetic",
];

/** Tone is stored as a comma-joined string ("warm, concise, professional"). */
function parseTones(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function toggleTone(current: string, option: string): string {
  const tones = parseTones(current);
  const idx = tones.findIndex((t) => t.toLowerCase() === option.toLowerCase());
  if (idx >= 0) tones.splice(idx, 1);
  else tones.push(option);
  return tones.join(", ");
}
// Value is the ISO code the backend stores ("en"); label is what the owner sees.
// (Previously the option value was the display name, so picking "English"
// persisted "english" — an invalid language code.)
const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
  { value: "en", label: "English" },
  { value: "ur", label: "Urdu" },
  { value: "ar", label: "Arabic" },
  { value: "hi", label: "Hindi" },
];
const LLM_PROVIDER_OPTIONS: { value: LlmProvider; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "groq", label: "Groq" },
  { value: "gemini", label: "Gemini" },
];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const DEFAULT_BUSINESS_HOURS = DAY_LABELS.map((_, day) => ({ day, open: "09:00", close: "17:00", closed: false }));

function withCurrent(options: string[], current: string): string[] {
  if (!current || options.includes(current)) return options;
  return [current, ...options];
}

const SELECT_CLASSES =
  "h-10 w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

export function TenantConfigForm({
  config,
  onSave,
}: {
  config: TenantConfig;
  onSave: (next: TenantConfig) => Promise<void>;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState<TenantConfig>(config);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm(config);
  }, [config]);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(form);
      toast({ title: "Settings saved", variant: "success" });
    } catch {
      toast({ title: "Couldn't save settings", description: "The config API isn't connected yet.", variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  const businessHours = form.businessHours.length ? form.businessHours : DEFAULT_BUSINESS_HOURS;

  function updateDay(day: number, patch: Partial<TenantConfig["businessHours"][number]>) {
    const next = businessHours.map((row) => (row.day === day ? { ...row, ...patch } : row));
    setForm({ ...form, businessHours: next });
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Business</CardTitle>
            <CardDescription>What your business is called and how your AI rep shows up.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="business-name">Business name</Label>
            <Input
              id="business-name"
              value={form.businessName}
              onChange={(e) => setForm({ ...form, businessName: e.target.value })}
              placeholder="Your business name"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="persona">Persona</Label>
              <select
                id="persona"
                className={SELECT_CLASSES}
                value={form.persona}
                onChange={(e) => setForm({ ...form, persona: e.target.value })}
              >
                {withCurrent(PERSONA_OPTIONS, form.persona).map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tone">Tone</Label>
              <div id="tone" className="flex flex-wrap gap-2 pt-1">
                {TONE_OPTIONS.map((option) => {
                  const selected = parseTones(form.tone).some(
                    (t) => t.toLowerCase() === option.toLowerCase(),
                  );
                  return (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setForm({ ...form, tone: toggleTone(form.tone, option) })}
                      className={cn(
                        "rounded-full border px-3 py-1.5 text-sm font-semibold transition-colors",
                        selected
                          ? "border-primary bg-primary/15 text-primary-strong"
                          : "border-border-strong text-foreground hover:bg-surface-muted",
                      )}
                    >
                      {option}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground">Pick any that fit — they combine.</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="primary-language">Primary language</Label>
            <select
              id="primary-language"
              className={SELECT_CLASSES}
              value={form.primaryLanguage}
              onChange={(e) => setForm({ ...form, primaryLanguage: e.target.value })}
            >
              {!LANGUAGE_OPTIONS.some((o) => o.value === form.primaryLanguage) && form.primaryLanguage ? (
                <option value={form.primaryLanguage}>{form.primaryLanguage}</option>
              ) : null}
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="custom-instructions">Custom instructions</Label>
            <Textarea
              id="custom-instructions"
              rows={4}
              value={form.customInstructions}
              onChange={(e) => setForm({ ...form, customInstructions: e.target.value })}
              placeholder="Anything else your AI rep should always keep in mind."
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle>Business hours</CardTitle>
              <CardDescription>Outside open hours, customers get your custom auto-reply.</CardDescription>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={form.businessHoursEnabled}
                onCheckedChange={(on) => setForm({ ...form, businessHoursEnabled: on })}
                label="Enforce business hours"
              />
              <span className="text-muted-foreground">{form.businessHoursEnabled ? "On" : "Off"}</span>
            </label>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {!form.businessHoursEnabled ? (
            <p className="rounded-xl bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
              Off — your AI rep replies around the clock. Turn on to set open hours below.
            </p>
          ) : null}
          {businessHours.map((row) => (
            <div key={row.day} className="flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2">
              <span className="w-12 text-sm font-semibold">{DAY_LABELS[row.day]}</span>
              <Switch
                checked={!row.closed}
                onCheckedChange={(open) => updateDay(row.day, { closed: !open })}
                label={`${DAY_LABELS[row.day]} open`}
              />
              <span className="text-xs text-muted-foreground">{row.closed ? "Closed" : "Open"}</span>
              <div className="ml-auto flex items-center gap-2">
                <Input
                  type="time"
                  value={row.open}
                  disabled={row.closed}
                  onChange={(e) => updateDay(row.day, { open: e.target.value })}
                  className="w-32"
                />
                <span className="text-sm text-muted-foreground">to</span>
                <Input
                  type="time"
                  value={row.close}
                  disabled={row.closed}
                  onChange={(e) => updateDay(row.day, { close: e.target.value })}
                  className="w-32"
                />
              </div>
            </div>
          ))}
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
            <Label htmlFor="owner-alert-number">Owner alert number (WhatsApp)</Label>
            <Input
              id="owner-alert-number"
              value={form.ownerAlertNumber}
              onChange={(e) => setForm({ ...form, ownerAlertNumber: e.target.value })}
              placeholder="+92 3XX XXXXXXX"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Payments</CardTitle>
            <CardDescription>
              Your own receiving account details. The AI shares these verbatim when a customer wants to
              pay — never card data, just how to send you money.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            <Label htmlFor="payment-details">Payment / account details</Label>
            <Textarea
              id="payment-details"
              rows={4}
              value={form.paymentDetails}
              onChange={(e) => setForm({ ...form, paymentDetails: e.target.value })}
              placeholder={"Bank: HBL\nTitle: Glow Salon\nAccount / IBAN: PK..\nJazzCash/Easypaisa: 03XX-XXXXXXX"}
            />
            <p className="text-xs text-muted-foreground">
              Leave blank to keep the payment option off — the bot only offers it when this is set.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Voice</CardTitle>
            <CardDescription>
              Whether your AI rep replies with a voice note. Requires a voice (STT/TTS) provider key
              in your plan — otherwise it always replies in text.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            <Label htmlFor="voice-reply-mode">Voice replies</Label>
            <select
              id="voice-reply-mode"
              className={SELECT_CLASSES}
              value={form.voiceReplyMode}
              onChange={(e) =>
                setForm({ ...form, voiceReplyMode: e.target.value as TenantConfig["voiceReplyMode"] })
              }
            >
              <option value="match">Match the customer (voice in → voice out)</option>
              <option value="always">Always reply with voice</option>
              <option value="never">Text only</option>
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>AI provider</CardTitle>
            <CardDescription>Which LLM powers your AI representative.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="llm-provider">Provider</Label>
            <select
              id="llm-provider"
              className={SELECT_CLASSES}
              value={form.llmProvider}
              onChange={(e) => setForm({ ...form, llmProvider: e.target.value as LlmProvider | "" })}
            >
              {form.llmProvider === "" ? <option value="">Use platform default</option> : null}
              {LLM_PROVIDER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="llm-model">Model</Label>
            <Input
              id="llm-model"
              value={form.llmModel}
              onChange={(e) => setForm({ ...form, llmModel: e.target.value })}
              placeholder="e.g. gpt-4o-mini"
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}
