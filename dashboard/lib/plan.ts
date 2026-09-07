/**
 * Trial terms, in one place.
 *
 * These numbers are decided by the backend: `TRIAL_DAYS` in
 * `backend/app/services/auth.py` sets the clock, and the trial plan's
 * `monthly_message_quota` in `backend/app/billing/plans.py` sets the allowance.
 * This file mirrors them for copy, because a Next.js component cannot import
 * from Python.
 *
 * A mirror drifts unless something checks it, so something does:
 * `backend/tests/test_trial_terms.py` reads this file and fails if either value
 * stops matching its source. That is the whole reason the values live here as
 * named exports with a fixed shape rather than being typed into each component.
 *
 * The rule that follows: **no component writes "14" or "300" as a literal.**
 * Import from here. Before this existed the trial was spelled out in seven
 * places, and changing the clock would have left six of them lying to customers
 * with nothing failing.
 */

/** Days a self-serve trial runs. Mirrors `auth.TRIAL_DAYS`. */
export const TRIAL_DAYS = 14;

/** Customer messages included in the trial. Mirrors `plans.PLANS["trial"]`. */
export const TRIAL_MESSAGE_QUOTA = 300;

/** "14 days" */
export const trialLength = `${TRIAL_DAYS} days`;

/** "14-day" */
export const trialLengthAdjective = `${TRIAL_DAYS}-day`;

/**
 * The full terms, one sentence. The trial ends on whichever limit is hit first,
 * so quoting only the clock overstates it for a busy tenant.
 */
export const trialTerms = `${TRIAL_DAYS} days or ${TRIAL_MESSAGE_QUOTA} customer messages, whichever comes first`;

/** Headline form: "14 days free. No card required." */
export const trialHeadline = `${TRIAL_DAYS} days free. No card required.`;
