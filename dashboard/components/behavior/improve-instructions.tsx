"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CharCounter } from "@/components/settings/char-counter";
import { useToast } from "@/components/ui/toast";
import type { SectionProps } from "@/components/settings/tenant-config";
import {
  describeReviewError,
  reviewInstructions,
  type InstructionChange,
  type InstructionReview,
} from "@/lib/api/behavior";
import { MAX_CUSTOM_INSTRUCTIONS } from "@/lib/limits";
import { useAuthToken } from "@/lib/use-api";

/**
 * Improve with AI, for the custom instructions field.
 *
 * Why this exists: the instructions are the most powerful input in the whole
 * product, roughly 1,800 characters against a handful of hardcoded sentences,
 * and nothing bounds or reconciles them. Three live defects came out of that
 * one field, and none of them looked like a defect on this page. A language
 * line overrode the Reply language setting on every turn. "You cannot see any
 * diary" switched off a connected Google Calendar and both booking skills
 * while the Skills page went on advertising them. A single sentence committed
 * the business to a callback within a few hours.
 *
 * Three rules shape the component.
 *
 * **It never overwrites silently.** The suggestion is shown beside the
 * original, with Accept and Discard. Accepting only fills the textarea, so the
 * page becomes dirty and the ordinary Save bar appears. Nothing is stored
 * until the owner saves, and the original is on screen the whole time.
 *
 * **It says what it changed.** An opaque rewrite is not reviewable, and
 * reviewability is the entire reason for not auto-saving. The reviewer returns
 * a line per edit and they are rendered as a list beside the two versions.
 *
 * **It is honest when it fails.** Every failure leaves the field untouched and
 * says which failure it was, because the owner's next move differs: out of
 * quota is their provider's billing page, a rejected key is Settings, slow is
 * try again. A partial generation is never shown as a suggestion at all: the
 * API refuses it before it gets here.
 */
export function ImproveInstructionsSection({ form, setForm }: SectionProps) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [review, setReview] = useState<InstructionReview | null>(null);
  /**
   * The exact text the suggestion was built from.
   *
   * Kept so that editing the textarea afterwards can be detected. Accepting
   * replaces the whole field, so accepting a stale suggestion would silently
   * throw away whatever the owner typed in the meantime, which is the failure
   * mode this component exists to avoid.
   */
  const [reviewedFrom, setReviewedFrom] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = form.customInstructions ?? "";
  const empty = current.trim().length === 0;
  const stale = review !== null && current.trim() !== reviewedFrom.trim();

  async function handleReview() {
    setLoading(true);
    setError(null);
    setReview(null);
    try {
      const result = await reviewInstructions(current, { token });
      setReview(result);
      setReviewedFrom(current);
    } catch (err) {
      // The field is deliberately not touched here. A failed review has to
      // leave the owner exactly where they were.
      setError(describeReviewError(err));
    } finally {
      setLoading(false);
    }
  }

  function handleAccept() {
    if (!review || stale) return;
    setForm({ ...form, customInstructions: review.improved });
    setReview(null);
    toast({
      title: "Suggestion applied",
      description: "Nothing is saved yet. Press Save changes to keep it.",
      variant: "success",
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Improve your instructions with AI</CardTitle>
          <CardDescription>
            Checks the custom instructions above against your own settings and
            connected tools, then suggests a tidier version for you to accept or
            discard.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-xl bg-surface-muted p-3.5 text-xs text-muted-foreground">
          <p className="font-semibold text-foreground">What it looks for</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            <li>
              Rules that fight your settings. A line about which language to
              reply in overrides your Reply language setting on every message.
            </li>
            <li>
              Rules that switch off a connected tool. Telling your rep it cannot
              see a calendar disables booking and availability while Google
              Calendar is connected.
            </li>
            <li>
              Promises made for you. &ldquo;A representative will call within a
              few hours&rdquo; is a commitment your rep cannot keep and your
              business is held to.
            </li>
            <li>
              Vague rules, duplicates and filler, which you pay for on every
              single reply.
            </li>
          </ul>
          <p className="mt-2">
            It never invents a price, a service or a policy you did not write.
            Each review is one call to your own AI provider, so it uses your
            credit, and it only ever runs when you press the button.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            onClick={handleReview}
            disabled={loading || empty}
          >
            {loading ? "Reviewing" : "Improve with AI"}
          </Button>
          {empty ? (
            <p className="text-xs text-muted-foreground">
              Write a few rules above first, then press this.
            </p>
          ) : null}
          {loading ? (
            <p role="status" className="text-xs text-muted-foreground">
              Reading your instructions. This takes a few seconds.
            </p>
          ) : null}
        </div>

        {error ? (
          <div
            role="alert"
            className="rounded-xl border border-danger/40 bg-danger/10 p-3.5 text-sm text-foreground"
          >
            <p className="font-semibold">The review did not finish</p>
            <p className="mt-1 text-muted-foreground">{error}</p>
          </div>
        ) : null}

        {review && review.unchanged ? (
          <div className="rounded-xl border border-border-strong bg-surface p-3.5 text-sm">
            <p className="font-semibold">Nothing to change</p>
            <p className="mt-1 text-muted-foreground">
              Your instructions do not contradict your settings or your
              connected tools, and there was nothing worth tightening. Left
              exactly as you wrote them.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => setReview(null)}
            >
              Close
            </Button>
          </div>
        ) : null}

        {review && !review.unchanged ? (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <VersionPane title="Your instructions" body={current} muted />
              <VersionPane title="Suggested" body={review.improved} />
            </div>

            <div>
              <p className="text-sm font-bold">What changed, and why</p>
              {review.changes.length ? (
                <ul className="mt-2 space-y-2">
                  {review.changes.map((change, i) => (
                    <li key={i} className="flex gap-2.5 text-sm">
                      <ChangeBadge kind={change.kind} />
                      <span className="text-muted-foreground">
                        {change.summary}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">
                  The suggestion came back with no explanation of its edits.
                  Read both versions before accepting it.
                </p>
              )}
            </div>

            <CharCounter
              value={review.improved}
              max={review.limit || MAX_CUSTOM_INSTRUCTIONS}
            />

            {stale ? (
              <p
                role="alert"
                className="rounded-xl border border-warning/40 bg-warning/10 p-3.5 text-sm"
              >
                You have edited your instructions since this suggestion was
                made, so accepting it would discard those edits. Run the review
                again.
              </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" onClick={handleAccept} disabled={stale}>
                Use this version
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setReview(null)}
              >
                Discard
              </Button>
              <p className="text-xs text-muted-foreground">
                Accepting fills the box above. Nothing is saved until you press
                Save changes.
              </p>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * One version of the text, scrollable rather than clipped.
 *
 * Both are shown in full because the owner is comparing them line by line;
 * a collapsed pane would make the accept an act of faith.
 */
function VersionPane({
  title,
  body,
  muted = false,
}: {
  title: string;
  body: string;
  muted?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <div
        className={
          muted
            ? "max-h-72 overflow-auto rounded-xl border border-border bg-surface-muted p-3.5 text-sm whitespace-pre-wrap"
            : "max-h-72 overflow-auto rounded-xl border border-primary/40 bg-surface p-3.5 text-sm whitespace-pre-wrap"
        }
      >
        {body}
      </div>
    </div>
  );
}

const CHANGE_LABELS: Record<
  InstructionChange["kind"],
  { label: string; tone: "default" | "success" | "warning" | "info" }
> = {
  removed: { label: "Removed", tone: "warning" },
  tightened: { label: "Tightened", tone: "info" },
  merged: { label: "Merged", tone: "info" },
  kept: { label: "Kept", tone: "success" },
  changed: { label: "Changed", tone: "default" },
};

function ChangeBadge({ kind }: { kind: InstructionChange["kind"] }) {
  const { label, tone } = CHANGE_LABELS[kind] ?? CHANGE_LABELS.changed;
  return (
    <Badge tone={tone} className="shrink-0">
      {label}
    </Badge>
  );
}
