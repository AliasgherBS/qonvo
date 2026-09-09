/**
 * Improve with AI, for the custom instructions field.
 *
 * A domain module rather than more of `lib/api.ts`, which is past a thousand
 * lines and is the file every concurrent change collides in.
 *
 * The one thing worth knowing about this client: it deliberately does not use
 * `describeError` for a failure. The shared helper flattens anything 500 or
 * above into "Server error", and every honest failure here is a 5xx that has
 * something specific and actionable to say: your provider is out of quota,
 * your key was rejected, it was too slow. Turning those into "Server error"
 * would blame us for the owner's provider and hide the fix.
 */

import { apiFetch, ApiError, describeError, type CallOpts } from "@/lib/api";

/** What the reviewer says it did. `kind` is normalised by the API. */
export interface InstructionChange {
  kind: "removed" | "tightened" | "merged" | "kept" | "changed";
  summary: string;
}

export interface InstructionReview {
  /** The suggested replacement. Never applied by anything but an explicit accept. */
  improved: string;
  changes: InstructionChange[];
  characters: number;
  /** The field cap the API validated against, so the counter cannot drift. */
  limit: number;
  /** True when the reviewer found nothing to repair. Not an error. */
  unchanged: boolean;
}

interface InstructionReviewDto {
  improved: string;
  changes: { kind: string; summary: string }[];
  characters: number;
  limit: number;
  unchanged: boolean;
}

const KINDS: InstructionChange["kind"][] = [
  "removed",
  "tightened",
  "merged",
  "kept",
  "changed",
];

function mapChange(dto: { kind: string; summary: string }): InstructionChange {
  const kind = KINDS.find((k) => k === dto.kind) ?? "changed";
  return { kind, summary: dto.summary };
}

/**
 * Review the instructions currently in the textarea.
 *
 * The text is sent rather than read from the saved config, because the owner
 * may be halfway through an edit and a suggestion built from the saved version
 * would not match what is on their screen.
 *
 * One call per press. Never called on a timer, on mount, or on blur: it spends
 * the tenant's own provider credit.
 */
export async function reviewInstructions(
  instructions: string,
  opts: CallOpts = {},
): Promise<InstructionReview> {
  const dto = await apiFetch<InstructionReviewDto>(
    "/api/behavior/instructions/review",
    {
      method: "POST",
      body: { instructions },
      token: opts.token,
      signal: opts.signal,
    },
  );
  return {
    improved: dto.improved,
    changes: (dto.changes ?? []).map(mapChange),
    characters: dto.characters,
    limit: dto.limit,
    unchanged: dto.unchanged,
  };
}

/**
 * The sentence to show the owner when a review fails.
 *
 * Prefers the API's own `detail.message`, which names the actual failure and
 * always ends with the owner's instructions being untouched, because that is
 * the fact they need first.
 */
export function describeReviewError(err: unknown): string {
  if (err instanceof ApiError && err.detail?.message) return err.detail.message;
  return describeError(
    err,
    "The review could not be completed. Your instructions are untouched.",
  );
}
