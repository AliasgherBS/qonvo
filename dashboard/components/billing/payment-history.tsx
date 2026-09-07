"use client";

import { ExternalLink, Loader2, Receipt, Settings } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { describeError, payments, type PaymentRow } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Payment history, and the way into the provider's own billing portal.
 *
 * The split is deliberate. History is read from the provider and shown here,
 * because a customer asking "what have I paid" should get an answer without
 * leaving. Cancelling, changing a card and downloading an invoice all happen in
 * the provider's portal, because the merchant of record owns the subscription
 * and issues the tax document: a cancel button of our own would give two
 * systems an opinion about the same subscription, and ours would be the one
 * that was wrong after a dunning retry.
 */

const STATUS_TONE: Record<string, string> = {
  refunded: "text-warning",
  pending: "text-muted-foreground",
};

function money(cents: number, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(cents / 100);
}

export function PaymentHistory() {
  const token = useAuthToken();
  const { toast } = useToast();
  const { data, loading } = useApi(() => payments.list({ token }), [token]);
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
            ? "You are on the free trial, so there is no subscription to change."
            : "Try again in a moment, or reply to any Qonvo email and we will sort it.",
        variant: reason === "no_subscription" ? "success" : "error",
      });
    } catch (err) {
      toast({ title: "Could not open this", description: describeError(err), variant: "error" });
    } finally {
      setOpening(false);
    }
  }

  const rows: PaymentRow[] = data ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Payments</CardTitle>
            <CardDescription>
              What you have been charged, and where to change your plan or card.
            </CardDescription>
          </div>
          <Button variant="outline" onClick={openPortal} disabled={opening}>
            {opening ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Settings className="mr-2 h-4 w-4" />
            )}
            Manage plan
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Receipt className="h-5 w-5" />}
            title="No payments yet"
            description="You are on the free trial. Anything you are charged shows up here with its invoice number."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[440px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3 font-semibold">Date</th>
                  <th className="py-2 pr-3 font-semibold">For</th>
                  <th className="py-2 pr-3 font-semibold">Amount</th>
                  <th className="py-2 pr-3 font-semibold">Invoice</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.date}-${row.invoiceNumber ?? row.amountCents}`}
                    className="border-b border-border last:border-0"
                  >
                    <td className="py-2.5 pr-3 tabular-nums">
                      {new Date(row.date).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="py-2.5 pr-3">{row.description ?? "Subscription"}</td>
                    <td className="py-2.5 pr-3 tabular-nums">
                      {money(row.amountCents, row.currency)}
                      {/* Shown only when it is not the ordinary case, so the
                          column stays scannable and a refund stands out. */}
                      {row.status !== "paid" ? (
                        <span
                          className={`ml-2 text-xs font-semibold ${
                            STATUS_TONE[row.status] ?? "text-muted-foreground"
                          }`}
                        >
                          {row.status}
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2.5 pr-3">
                      {row.invoiceUrl ? (
                        <a
                          href={row.invoiceUrl}
                          target="_blank"
                          rel="noopener"
                          className="inline-flex items-center gap-1 font-semibold text-primary-strong underline-offset-2 hover:underline"
                        >
                          {row.invoiceNumber ?? "Invoice"}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        /* No link until the provider has generated the
                            document. A link to a PDF that does not exist is
                            worse than a reference the customer can quote. */
                        <span className="tabular-nums text-muted-foreground">
                          {row.invoiceNumber ?? "-"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="mt-4 border-t border-border pt-4 text-xs text-muted-foreground">
          Cancel any time from <strong>Manage plan</strong>. Your rep keeps answering until the end
          of the period you have paid for, and payments already made are not refunded except where
          the law requires it.
        </p>
      </CardContent>
    </Card>
  );
}
