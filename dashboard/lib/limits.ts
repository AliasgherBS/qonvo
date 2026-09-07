/**
 * Field caps, mirrored from `backend/app/core/limits.py`.
 *
 * The API rejects an oversized value rather than truncating it, so the counter
 * beside a field has to know the same number the validator uses. A component
 * cannot import from Python, so this mirrors it.
 *
 * A mirror drifts unless something checks it, so `backend/tests/test_input_caps.py`
 * reads this file and fails when a value stops matching its source. Same
 * arrangement as `lib/plan.ts`, and for the same reason: the drift is otherwise
 * invisible, and it shows up as a save that fails with a number the UI said was
 * fine.
 */

/** Sits in the system prompt on every reply, so this one is billed forever. */
export const MAX_CUSTOM_INSTRUCTIONS = 2000;

/** The free-text escape hatch behind the persona presets. */
export const MAX_PERSONA = 500;

/** Sent verbatim to customers over WhatsApp. */
export const MAX_PAYMENT_DETAILS = 1000;

/** One pasted knowledge entry, roughly twenty pages. */
export const MAX_TEXT_ENTRY_CHARS = 50000;

/** One uploaded file. Also the bound on what a single request holds in memory. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
