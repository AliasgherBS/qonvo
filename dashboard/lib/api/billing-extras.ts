/**
 * Billing endpoints added after `lib/api.ts` became the file every stream
 * collides in. Same conventions, same `apiFetch`; new endpoint groups live
 * here by the instruction at the top of that file.
 */

import { apiFetch, type CallOpts } from "@/lib/api";

/**
 * The card the next renewal is charged to.
 *
 * `state` is decided by the backend on purpose: the sixty-day warning window
 * is a policy, and comparing the expiry to `Date.now()` here would be a second
 * place it lived.
 */
export interface CardOnFile {
  brand: string;
  last4: string;
  expMonth: number;
  expYear: number;
  /** "apple_pay" / "google_pay" when the card sits behind a wallet. */
  wallet: string | null;
  state: "ok" | "expiring" | "expired";
}

interface CardOnFileDto {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  wallet: string | null;
  state: "ok" | "expiring" | "expired";
}

export const paymentMethod = {
  /**
   * Null for a tenant with no gateway, no subscription or no saved card. All
   * three mean the same thing to the page: show nothing, guess nothing. A card
   * the customer does not recognise is worse than no card at all.
   */
  get: (opts: CallOpts = {}) =>
    apiFetch<{ card: CardOnFileDto | null }>("/api/billing/card", opts).then(
      ({ card }): CardOnFile | null =>
        card
          ? {
              brand: card.brand,
              last4: card.last4,
              expMonth: card.exp_month,
              expYear: card.exp_year,
              wallet: card.wallet,
              state: card.state,
            }
          : null,
    ),
};
