"use client";

import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import {
  config,
  describeError,
  type ConfigField,
  type LlmProvider,
  type TenantConfig,
  OTHER_REPLY_LANGUAGE,
  REPLY_LANGUAGE_PRESETS,
} from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/**
 * The tenant config used to be one 385-line form rendering six unrelated
 * concerns on a single scroll, so choosing a bot's tone sat beside choosing an
 * LLM model. It is now a shared hook plus independent sections, composed by
 * whichever page owns that concern.
 *
 * Every section still reads and writes the same TenantConfig object and the
 * same API payload keys, so no backend change was needed and nothing that
 * depends on those field names breaks.
 */

/** Label for the free-text escape hatch. Never stored; see the select below. */
const OTHER_PERSONA = "Other (write your own)";

const PERSONA_OPTIONS = [
  "Friendly & warm",
  "Professional",
  "Playful & witty",
  "Formal",
  "Direct & concise",
];
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

// Value is the ISO code the backend stores ("en"); label is what the owner
// sees. Previously the option value was the display name, so picking "English"
// persisted "english", an invalid language code.
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
const DEFAULT_BUSINESS_HOURS = DAY_LABELS.map((_, day) => ({
  day,
  open: "09:00",
  close: "17:00",
  closed: false,
}));

function withCurrent(options: string[], current: string): string[] {
  if (!current || options.includes(current)) return options;
  return [current, ...options];
}

const SELECT_CLASSES =
  "h-10 w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

export type SectionProps = {
  form: TenantConfig;
  setForm: (next: TenantConfig) => void;
};

/**
 * Loads the config, holds the draft, and saves it. Every page that renders any
 * config section uses this, so each page owns exactly one save button and the
 * user never wonders which fields a given Save applies to.
 */
export function TenantConfigPage({
  title,
  description,
  fields,
  children,
}: {
  title: string;
  description: string;
  /**
   * The wire fields this page owns. Only these are sent, so a page cannot fail
   * validation on a field it does not show, and two pages cannot clobber each
   * other. The API applies exclude_unset, so anything omitted is left alone.
   */
  fields: ConfigField[];
  children: (props: SectionProps) => ReactNode;
}) {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => config.get({ token }), [token]);
  const { toast } = useToast();
  const [form, setForm] = useState<TenantConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  async function handleSave() {
    if (!form) return;
    setSaving(true);
    try {
      await config.update(form, { token }, fields);
      toast({ title: "Saved", variant: "success" });
    } catch (err) {
      toast({
        title: "Could not save",
        description: describeError(err),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>

      {loading ? (
        <ConfigSkeleton />
      ) : error && !form ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : form ? (
        <>
          {children({ form, setForm })}
          <div className="flex items-center gap-3">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving" : "Save changes"}
            </Button>
          </div>
        </>
      ) : null}
    </div>
  );
}

/**
 * Every section on one page, with an injectable save.
 *
 * This is for the admin console, which edits another tenant's config through a
 * different endpoint and genuinely wants the whole thing on one screen: an
 * operator looking at someone else's workspace is doing support, not the
 * task-shaped work the owner-facing pages are organised around.
 */
export function AllConfigSections({
  config: initial,
  onSave,
}: {
  config: TenantConfig;
  onSave: (next: TenantConfig) => Promise<void>;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState<TenantConfig>(initial);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm(initial);
  }, [initial]);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(form);
      toast({ title: "Saved", variant: "success" });
    } catch (err) {
      toast({
        title: "Could not save",
        description: describeError(err),
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  const props = { form, setForm };

  return (
    <div className="space-y-6">
      <BusinessNameSection {...props} />
      <PersonaSection {...props} />
      <HoursSection {...props} />
      <VoiceSection {...props} />
      <EscalationSection {...props} />
      <PaymentsSection {...props} />
      <ModelSection {...props} />
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function ConfigSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1].map((i) => (
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

/* ---------------------------------------------------------------- Behavior */

export function PersonaSection({ form, setForm }: SectionProps) {
  // A saved persona that is not one of the presets was written as free text, so
  // the form opens in that mode rather than silently offering to overwrite it.
  const [personaIsCustom, setPersonaIsCustom] = useState(
    () => !!form.persona && !PERSONA_OPTIONS.includes(form.persona),
  );

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Persona and tone</CardTitle>
          <CardDescription>How your AI rep sounds to a customer.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="persona">Persona</Label>
            <select
              id="persona"
              className={SELECT_CLASSES}
              // "Other" is a UI state, not a stored value: choosing it clears the
              // field so the textarea starts empty and whatever is typed is what
              // gets saved. The column has always been free text; only the write
              // path was locked to five presets, which is why every real
              // personality had to be smuggled into Custom instructions.
              value={personaIsCustom ? OTHER_PERSONA : form.persona}
              onChange={(e) => {
                const chosen = e.target.value;
                if (chosen === OTHER_PERSONA) {
                  setPersonaIsCustom(true);
                  setForm({ ...form, persona: "" });
                } else {
                  setPersonaIsCustom(false);
                  setForm({ ...form, persona: chosen });
                }
              }}
            >
              {withCurrent(PERSONA_OPTIONS, personaIsCustom ? "" : form.persona).map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
              <option value={OTHER_PERSONA}>{OTHER_PERSONA}</option>
            </select>
            {personaIsCustom ? (
              <Textarea
                id="persona-custom"
                rows={3}
                placeholder="Describe how your rep should come across. E.g. Warm but brisk, never pushy, always offers the nearest branch."
                value={form.persona}
                onChange={(e) => setForm({ ...form, persona: e.target.value })}
              />
            ) : null}
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
            <p className="text-xs text-muted-foreground">Pick any that fit. They combine.</p>
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
            {!LANGUAGE_OPTIONS.some((o) => o.value === form.primaryLanguage) &&
            form.primaryLanguage ? (
              <option value={form.primaryLanguage}>{form.primaryLanguage}</option>
            ) : null}
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Used when it cannot tell what the customer wrote in. Otherwise it matches them.
          </p>
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
  );
}

export function HoursSection({ form, setForm }: SectionProps) {
  const businessHours = form.businessHours.length ? form.businessHours : DEFAULT_BUSINESS_HOURS;

  function updateDay(day: number, patch: Partial<TenantConfig["businessHours"][number]>) {
    setForm({
      ...form,
      businessHours: businessHours.map((row) => (row.day === day ? { ...row, ...patch } : row)),
    });
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Business hours</CardTitle>
            <CardDescription>Outside open hours, customers get your auto-reply.</CardDescription>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={form.businessHoursEnabled}
              onCheckedChange={(on) => setForm({ ...form, businessHoursEnabled: on })}
              label="Enforce business hours"
            />
            <span className="text-muted-foreground">
              {form.businessHoursEnabled ? "On" : "Off"}
            </span>
          </label>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {!form.businessHoursEnabled ? (
          <p className="rounded-xl bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
            Off. Your AI rep replies around the clock. Turn on to set open hours below.
          </p>
        ) : null}
        {businessHours.map((row) => (
          <div
            key={row.day}
            className="flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2"
          >
            <span className="w-12 text-sm font-semibold">{DAY_LABELS[row.day]}</span>
            <Switch
              checked={!row.closed}
              onCheckedChange={(open) => updateDay(row.day, { closed: !open })}
              label={`${DAY_LABELS[row.day]} open`}
            />
            <span className="text-xs text-muted-foreground">
              {row.closed ? "Closed" : "Open"}
            </span>
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
  );
}

/**
 * Voice lives with behaviour, not with the engine settings: it decides whether
 * a customer hears a voice back, which is a thing the rep does, not a piece of
 * infrastructure the owner should have to reason about.
 */
export function VoiceSection({ form, setForm }: SectionProps) {
  // A saved language that is not one of the two presets was typed, so the form
  // opens in that mode rather than silently offering to replace it.
  const [languageIsCustom, setLanguageIsCustom] = useState(
    () => !!form.replyLanguageMode && !["match", "en"].includes(form.replyLanguageMode),
  );

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Voice replies</CardTitle>
          <CardDescription>
            Whether your AI rep answers with a voice note. Needs a voice provider key in your plan,
            otherwise it always replies in text.
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
              setForm({
                ...form,
                voiceReplyMode: e.target.value as TenantConfig["voiceReplyMode"],
              })
            }
          >
            <option value="match">Match the customer. Voice in, voice out.</option>
            <option value="always">Always reply with voice</option>
            <option value="never">Text only</option>
          </select>
        </div>

        <div className="mt-5 space-y-1.5">
          <Label htmlFor="reply-language-mode">Reply language</Label>
          <select
            id="reply-language-mode"
            className={SELECT_CLASSES}
            // "Other" is a UI state, not a stored value: choosing it clears the
            // field so the text input starts empty and what gets typed is what
            // gets saved.
            value={languageIsCustom ? OTHER_REPLY_LANGUAGE : form.replyLanguageMode}
            onChange={(e) => {
              const chosen = e.target.value;
              if (chosen === OTHER_REPLY_LANGUAGE) {
                setLanguageIsCustom(true);
                setForm({ ...form, replyLanguageMode: "" });
              } else {
                setLanguageIsCustom(false);
                setForm({ ...form, replyLanguageMode: chosen });
              }
            }}
          >
            {REPLY_LANGUAGE_PRESETS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            <option value={OTHER_REPLY_LANGUAGE}>Other (type a language)</option>
          </select>
          {languageIsCustom ? (
            <>
              <Input
                id="reply-language-custom"
                placeholder="Roman Urdu"
                value={form.replyLanguageMode}
                onChange={(e) => setForm({ ...form, replyLanguageMode: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Any language your AI model can write. Name the script if it matters: Urdu and
                Roman Urdu are the same language written two ways, and asking for Urdu will get
                you Urdu script.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Matching the customer matches their script too, so Roman Urdu gets Roman Urdu back.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ Skills */

export function EscalationSection({ form, setForm }: SectionProps) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Handover</CardTitle>
          <CardDescription>Where we reach you when a customer needs a person.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="owner-alert-number">Your WhatsApp number for alerts</Label>
          <Input
            id="owner-alert-number"
            value={form.ownerAlertNumber}
            onChange={(e) => setForm({ ...form, ownerAlertNumber: e.target.value })}
            placeholder="+92 3XX XXXXXXX"
          />
        </div>
        <label className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-2.5">
          <span className="text-sm">
            <span className="font-semibold">Alert me on handover</span>
            <span className="block text-xs text-muted-foreground">
              Sends a WhatsApp and email alert when the bot hands a chat to a person. The in-app
              notification is always kept.
            </span>
          </span>
          <Switch
            checked={form.notifyOnHandoff}
            onCheckedChange={(on) => setForm({ ...form, notifyOnHandoff: on })}
            label="Alert me on handover"
          />
        </label>
      </CardContent>
    </Card>
  );
}

export function PaymentsSection({ form, setForm }: SectionProps) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Payment details</CardTitle>
          <CardDescription>
            Your own receiving account. The AI shares this verbatim when a customer asks how to pay.
            Never card data, just how to send you money.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-1.5">
          <Label htmlFor="payment-details">Account details</Label>
          <Textarea
            id="payment-details"
            rows={4}
            value={form.paymentDetails}
            onChange={(e) => setForm({ ...form, paymentDetails: e.target.value })}
            placeholder={
              "Bank: HBL\nTitle: Glow Salon\nAccount / IBAN: PK..\nJazzCash/Easypaisa: 03XX-XXXXXXX"
            }
          />
          <p className="text-xs text-muted-foreground">
            Leave blank to keep the payment option off. The bot only offers it when this is set.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

/* --------------------------------------------------------------- Workspace */

export function BusinessNameSection({ form, setForm }: SectionProps) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Business</CardTitle>
          <CardDescription>What your business is called.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-1.5">
          <Label htmlFor="business-name">Business name</Label>
          <Input
            id="business-name"
            value={form.businessName}
            onChange={(e) => setForm({ ...form, businessName: e.target.value })}
            placeholder="Your business name"
          />
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Engine settings. **Admin console only.**
 *
 * This was on the owner's Business page behind a disclosure. It is not any
 * more: picking a model is not a decision a business owner is equipped to make,
 * and a wrong answer costs quality or money with no signal that anything is
 * wrong. The platform default is the supported configuration.
 *
 * It survives here because an operator pinning one tenant to a specific model
 * during an incident is a real need, and because the per-tenant override in
 * `resolve_llm` already exists and works. Rendered only by
 * `AllConfigSections`, which only the admin tenant page uses.
 */
export function ModelSection({ form, setForm }: SectionProps) {
  return (
    <Card>
      <CardContent className="pt-5">
        <details className="group">
          <summary className="cursor-pointer list-none text-sm font-semibold">
            <span className="group-open:hidden">Show advanced settings</span>
            <span className="hidden group-open:inline">Hide advanced settings</span>
          </summary>

          <p className="mt-3 text-xs text-muted-foreground">
            Which model powers this tenant. Leave on the platform default unless you are pinning
            this workspace deliberately, for example during a provider incident.
          </p>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="llm-provider">Provider</Label>
              <select
                id="llm-provider"
                className={SELECT_CLASSES}
                value={form.llmProvider}
                onChange={(e) =>
                  setForm({ ...form, llmProvider: e.target.value as LlmProvider | "" })
                }
              >
                {form.llmProvider === "" ? (
                  <option value="">Use platform default</option>
                ) : null}
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
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
