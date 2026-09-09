"use client";

import { AlertTriangle, CreditCard, Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { describeError, payments } from "@/lib/api";
import { paymentMethod } from "@/lib/api/billing-extras";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Which card is being charged, and whether it is about to lapse (teardown Z4).
 *
 * There used to be an "Update card" button and nothing saying what card it
 * would update. An expiring card is the largest preventable cause of
 * involuntary churn in a subscription product, and the only thing that
 * prevents it is telling the owner the expiry before the renewal fails.
 *
 * Read from the provider each time rather than stored: they own the card, and
 * a copy of an expiry date is a copy that is wrong the day it is replaced.
 *
 * Entering or replacing card details still happens in the provider's hosted
 * portal, and must: that is what keeps card numbers off our servers.
 */

const WALLET_LABELS: Record<string, string> = {
  apple_pay: "Apple Pay",
  google_pay: "Google Pay",
  link: "Link",
};

/** "Visa", "Mastercard". Polar reports the brand lower case. */
function brandLabel(brand: string) {
  return brand.charAt(0).toUpperCase() + brand.slice(1);
}

/**
 * "09/2028", as printed on the card.
 *
 * Deliberately not `formatDate`: a card expiry is a month, not a day, and the
 * card stays valid to the *end* of that month. Rendering it as "1 Oct 2028"
 * would be a date the customer cannot find on their card and would be a day
 * they could not use it.
 */
function expiry(month: number, year: number) {
  return `${String(month).padStart(2, "0")}/${year}`;
}

export function CardOnFile() {
  const token = useAuthToken();
  const { toast } = useToast();
  const { data: card, loading } = useApi(() => paymentMethod.get({ token }), [token]);
  const [opening, setOpening] = useState(false);

  async function openPortal() {
    setOpening(true);
    try {
      const { url, reason } = await payments.portal({ token });
      if (url) {
        window.open(url, "_blank", "noopener");
        return;
      }
      toast({
        title: reason === "no_subscription" ? "Nothing to manage yet" : "Could not open this",
        description:
          reason === "no_subscription"
            ? "You are on the free trial, so there is no card on file yet."
            : "Try again in a moment, or reply to any Qonvo email and we will sort it.",
        variant: reason === "no_subscription" ? "success" : "error",
      });
    } catch (err) {
      toast({
        title: "Could not open this",
        description: describeError(err),
        variant: "error",
      });
    } finally {
      setOpening(false);
    }
  }

  const expired = card?.state === "expired";
  const expiring = card?.state === "expiring";

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>How you pay</CardTitle>
          <CardDescription>
            Card details are held by our payment provider, never by us. Updating one opens their
            secure page.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {loading ? (
            <Skeleton className="h-6 w-48" />
          ) : card ? (
            <p className="flex items-center gap-2 text-sm">
              <CreditCard className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="font-semibold">
                {card.wallet ? (WALLET_LABELS[card.wallet] ?? brandLabel(card.wallet)) : null}
                {card.wallet ? " · " : null}
                {brandLabel(card.brand)} ending {card.last4}
              </span>
              <span className={expired || expiring ? "text-warning" : "text-muted-foreground"}>
                {expired ? "expired" : "expires"} {expiry(card.expMonth, card.expYear)}
              </span>
            </p>
          ) : (
            /* No card rather than a placeholder. This is a trial tenant, a
               tenant paying some other way, or a provider that did not answer,
               and inventing a card for any of them would be worse than
               silence. */
            <p className="text-sm text-muted-foreground">
              No card on file yet. One is saved when you first pay.
            </p>
          )}

          <Button variant="outline" onClick={openPortal} disabled={opening}>
            {opening ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <CreditCard className="mr-2 h-4 w-4" />
            )}
            {card ? "Update card" : "Payment settings"}
          </Button>
        </div>

        {/* The whole point of the feature. A renewal on a lapsed card fails
            quietly, the rep stops replying, and the owner finds out from a
            customer. */}
        {expired || expiring ? (
          <p className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 p-3 text-xs">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              {expired
                ? "This card has expired, so your next renewal will fail and your rep will stop replying. Update it now to avoid that."
                : `This card expires in ${expiry(card!.expMonth, card!.expYear)}. If it lapses before your next renewal the payment fails and your rep stops replying, so it is worth updating before then.`}
            </span>
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
