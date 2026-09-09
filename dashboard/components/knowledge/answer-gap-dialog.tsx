"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { describeError, type KnowledgeGap } from "@/lib/api";
import { knowledgeExtras } from "@/lib/api/knowledge-extras";
import { useAuthToken } from "@/lib/use-api";

/**
 * Answering a gap (teardown K1).
 *
 * The product already knew what it had failed to answer and showed it in a
 * clean table, and then stopped: there was nothing to do about a gap from the
 * page that reported it. This is the missing half of the loop -- the answer
 * becomes a knowledge entry, and the gap stops being reported.
 */

/** `knowledge_sources.name` is varchar(255). A long question becomes the entry's
    title and would be refused by the database, so it is trimmed for the title
    while the full text still goes into the content below. */
const TITLE_MAX = 200;

function titleFor(question: string): string {
  const clean = question.trim().replace(/\s+/g, " ");
  return clean.length > TITLE_MAX ? `${clean.slice(0, TITLE_MAX - 1)}…` : clean;
}

/**
 * The stored entry carries the question as well as the answer.
 *
 * Retrieval matches the customer's wording against the chunk, and the customer
 * is going to ask this in roughly the words that already missed. An answer
 * stored on its own is measurably harder to find than the pair.
 */
function contentFor(question: string, answer: string): string {
  return `Question: ${question.trim()}\nAnswer: ${answer.trim()}`;
}

export function AnswerGapDialog({
  gap,
  onClose,
  onAnswered,
}: {
  gap: KnowledgeGap | null;
  onClose: () => void;
  onAnswered: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [answer, setAnswer] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (gap) setAnswer("");
  }, [gap]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!gap || !answer.trim()) return;
    setSaving(true);
    try {
      await knowledgeExtras.answerGap(
        {
          gapId: gap.id,
          title: titleFor(gap.question),
          content: contentFor(gap.question, answer),
        },
        { token },
      );
      toast({
        title: "Answer added",
        description: "Your rep can answer this now. The gap will drop off the list.",
        variant: "success",
      });
      onAnswered();
    } catch (err) {
      toast({ title: "Couldn't save the answer", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={gap !== null}
      onClose={onClose}
      title="Answer this question"
      description="Saved as a knowledge entry, so the next customer who asks gets your answer."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="gap-question">The question</Label>
          {/* Read-only rather than an editable title field: the wording is what
              customers actually typed, and editing it is how an answer stops
              matching the question it was written for. */}
          <p
            id="gap-question"
            className="rounded-xl border border-border bg-surface-muted px-3 py-2 text-sm font-semibold"
          >
            {gap?.question}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="gap-answer">Your answer</Label>
          <Textarea
            id="gap-answer"
            rows={6}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Answer it the way you would on the phone. Include the details a customer needs to act: prices, times, what to bring."
            required
            autoFocus
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving || !answer.trim()}>
            {saving ? "Saving…" : "Save answer"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
