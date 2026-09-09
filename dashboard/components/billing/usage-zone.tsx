"use client";

import type { TenantUsage, UsageMeter } from "@/lib/api";
import { formatDate } from "@/lib/format";

/**
 * The meters, worst first, with the consequence of filling each one named
 * (teardown Z3, Z6).
 *
 * Its own component rather than the shared `UsageMeters`, which the admin
 * console also renders: an operator wants six meters in a fixed order to
 * compare tenants at a glance, and an owner wants the one that is about to
 * bind, with what happens when it does. Same numbers from the same endpoint,
 * two different questions.
 *
 * Scope and unit are stated on the page rather than assumed. Both meters that
 * appear elsewhere in the product (voice on the admin console, voice again as a
 * platform total on System Health) come from the same computation, and the only
 * thing that made them look like different numbers was nothing here saying
 * whose usage this is or that the minutes round up (finding F7).
 *
 * Every sentence below was read off the code that enforces the limit, not
 * guessed, because the value of saying anything here is that it is right:
 *
 * - messages: `is_hard_quota_exceeded` in `workers/pipeline.py`. The rep stops
 *   answering and every inbound turn gets `QUOTA_EXCEEDED_REPLY` instead.
 *   Inbound and outbound both count towards the meter.
 * - voice: `agent/voice_allowance.py`. Voice *replies* stop; the reply still
 *   goes out as text, and inbound voice notes are still transcribed because
 *   that happens before the gate. The customer is told once per period.
 * - seats: `api/team.py` refuses the invitation. Pending invites hold seats.
 * - knowledge: `check_room_for` in `api/knowledge_limits.py` refuses the next
 *   write. Everything already ingested keeps answering.
 */

type Cadence = "monthly" | "total";

interface Row {
  key: string;
  label: string;
  meter: UsageMeter;
  unit?: string;
  cadence: Cadence;
  /** Used at 80-99%. Future tense, because it has not happened yet. */
  whenFull: string;
  /** Used at 100%. What is happening to the business right now. */
  nowFull: string;
  /** How the meter counts, where that is not obvious. */
  note?: string;
}

const KNOWLEDGE_WHEN_FULL =
  "the next thing you add is refused until you delete something. Everything already there keeps answering.";
const KNOWLEDGE_NOW_FULL =
  "Adding anything new is refused until you delete something. Everything already there keeps answering.";

function rows(usage: TenantUsage): Row[] {
  return [
    {
      key: "messages",
      label: "Messages",
      meter: usage.messages,
      cadence: "monthly",
      whenFull:
        "your rep stops answering. Every customer gets one line saying you are at your limit and that someone will be in touch, and their message waits in your inbox.",
      nowFull:
        "Your rep has stopped answering. Every customer gets one line saying you are at your limit and that someone will be in touch, and their messages are waiting in your inbox.",
      note: "Counts what customers send and what your rep replies.",
    },
    {
      key: "voice",
      label: "Voice minutes",
      meter: usage.voiceMinutes,
      unit: "min",
      cadence: "monthly",
      whenFull:
        "your rep keeps working and answers in writing instead. Customers can still send voice notes and it still understands them; it just stops replying in voice, and tells them so once.",
      nowFull:
        "Voice replies are paused. Your rep is still answering by text, and it still understands the voice notes customers send.",
      // The exact figure, spelled out (finding F7). The minutes round up, so 89
      // metered seconds reads as "2 min of 5" here while an operator looking at
      // the same tenant sees 89. Both are right and neither said so, which is
      // how one number became three. The seconds come from the same
      // computation, not a second sum.
      note: `Counts voice in both directions, rounded up to the next minute: ${voicePrecision(usage)}.`,
    },
    {
      key: "seats",
      label: "Team seats",
      meter: usage.seats,
      cadence: "total",
      whenFull:
        "you cannot invite anyone else until you remove a member or cancel a pending invitation.",
      nowFull:
        "You cannot invite anyone else until you remove a member or cancel a pending invitation.",
      note: "A pending invitation holds a seat.",
    },
    {
      key: "knowledge_sources",
      label: "Knowledge sources",
      meter: usage.knowledgeSources,
      cadence: "total",
      whenFull: KNOWLEDGE_WHEN_FULL,
      nowFull: KNOWLEDGE_NOW_FULL,
    },
    {
      key: "knowledge_chars",
      label: "Knowledge text",
      meter: usage.knowledgeChars,
      unit: "characters",
      cadence: "total",
      whenFull: KNOWLEDGE_WHEN_FULL,
      nowFull: KNOWLEDGE_NOW_FULL,
    },
    {
      key: "knowledge_upload",
      label: "Uploaded files",
      meter: usage.knowledgeUploadMb,
      unit: "MB",
      cadence: "total",
      whenFull: KNOWLEDGE_WHEN_FULL,
      nowFull: KNOWLEDGE_NOW_FULL,
    },
  ];
}

const TONE: Record<string, { bar: string; text: string }> = {
  ok: { bar: "bg-primary", text: "text-muted-foreground" },
  near: { bar: "bg-warning", text: "text-warning" },
  over: { bar: "bg-danger", text: "text-danger" },
};

/** The stored figure behind a rounded-up minute count, for this business. */
function voicePrecision(usage: TenantUsage): string {
  const { used, allowed } = usage.voiceSeconds;
  return `${used.toLocaleString()} of ${allowed.toLocaleString()} seconds used by this business`;
}

function amount(n: number, unit?: string) {
  return unit ? `${n.toLocaleString()} ${unit}` : n.toLocaleString();
}

function MeterRow({ row }: { row: Row }) {
  const { meter } = row;
  const tone = TONE[meter.state] ?? TONE.ok;
  const pct = Math.round(meter.ratio * 100);
  const empty = meter.used === 0;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold">
          {row.label}
          <span className="ml-2 text-xs font-medium text-muted-foreground">
            {row.cadence === "monthly" ? "this month" : "in total"}
          </span>
        </span>
        <span className={`text-sm tabular-nums ${tone.text}`}>
          {amount(meter.used, row.unit)} of {amount(meter.allowed, row.unit)}
        </span>
      </div>

      <div
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-border"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={row.label}
      >
        {/* A zero meter used to render as a flat grey track, which reads as a
            disabled control rather than as an untouched allowance. The start
            cap says the meter is alive and at the beginning. */}
        {empty ? (
          <div className="h-full w-1 rounded-full bg-muted-foreground/30" />
        ) : (
          <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${pct}%` }} />
        )}
      </div>

      {empty ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Nothing used yet.{row.note ? ` ${row.note}` : ""}
        </p>
      ) : meter.state === "over" ? (
        <p className="mt-1.5 text-xs font-semibold text-danger">Full. {row.nowFull}</p>
      ) : meter.state === "near" ? (
        <p className="mt-1.5 text-xs font-semibold text-warning">
          Nearly full. When it runs out, {row.whenFull}
        </p>
      ) : row.note ? (
        <p className="mt-1.5 text-xs text-muted-foreground">{row.note}</p>
      ) : null}
    </div>
  );
}

const SEVERITY: Record<string, number> = { over: 0, near: 1, ok: 2 };

export function UsageZone({
  usage,
  /** The billing anniversary, which is not the usage reset date. Naming both
      in one sentence is the fix: two dates a paragraph apart read as a bug. */
  renewsOn,
}: {
  usage: TenantUsage;
  renewsOn: string | null;
}) {
  // Worst first. The meter that is about to bind is the only one the owner
  // needs, and a fixed order buries it behind five that are fine.
  const ordered = [...rows(usage)].sort(
    (a, b) => SEVERITY[a.meter.state] - SEVERITY[b.meter.state] || b.meter.ratio - a.meter.ratio,
  );
  const worst = ordered[0];
  const pressured = worst && worst.meter.state !== "ok";

  return (
    <div className="space-y-5">
      {ordered.map((row) => (
        <MeterRow key={row.key} row={row} />
      ))}

      <div className="space-y-1 border-t border-border pt-4 text-xs text-muted-foreground">
        {/* Z3: the two dates are different things, said in one sentence so
            neither looks like a mistake in the other. */}
        <p>
          Messages and voice minutes reset on {formatDate(usage.periodEnd)}, and on the 1st of every
          month after that. Seats and knowledge are running totals, so they do not reset.
        </p>
        {/* F7: the scope, said once and out loud. The same voice figure appears
            on the admin console per tenant and again on System Health as a
            platform-wide total, and an owner comparing notes with support had
            nothing on the page telling them which of those they were reading. */}
        <p>Every figure here is your business only, for the period named above.</p>
        {renewsOn ? (
          <p>
            Your plan renews separately, on {formatDate(renewsOn)}. That is the date your card is
            charged; it is not the date your usage resets.
          </p>
        ) : null}
      </div>

      {pressured ? (
        <p className="text-xs">
          <a
            href="#plans"
            className="font-semibold text-primary-strong underline-offset-2 hover:underline"
          >
            Compare plans
          </a>{" "}
          to see what a larger one allows.
        </p>
      ) : null}
    </div>
  );
}
