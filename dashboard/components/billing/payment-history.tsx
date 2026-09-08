"use client";

import { Download, Loader2, Receipt } from "lucide-react";
import { useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { describeError, payments, type PaymentRow } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Payment history: what has been charged, with the invoice for each line.
 *
 * History is read from the provider and shown here, because a customer asking
 * "what have I paid" should get an answer without leaving. Card details live
 * one card above, in `CardOnFile`, which also owns the way into the provider's
 * hosted portal: the card and the button that changes it belong together, and
 * splitting them is what produced an "Update card" button with no card beside
 * it (teardown Z4).
 *
 * The invoice document itself stays the provider's. They are the merchant of
 * record and the seller named on it, so this fetches theirs rather than
 * rendering one.
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
  const [fetchingInvoice, setFetchingInvoice] = useState<string | null>(null);

  async function openInvoice(orderId: string) {
    setFetchingInvoice(orderId);
    try {
      const { url } = await payments.invoice(orderId, { token });
      // A new tab rather than a same-tab navigation: the link is a signed S3
      // URL that expires, so a back button would land on a dead page.
      window.open(url, "_blank", "noopener");
    } catch (err) {
      toast({
        title: "Invoice not ready",
        description: describeError(err),
        variant: "error",
      });
    } finally {
      setFetchingInvoice(null);
    }
  }

  const rows: PaymentRow[] = data ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Payments</CardTitle>
          <CardDescription>
            What you have been charged. Click an invoice to download it.
          </CardDescription>
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
                      {/* One date helper for the whole product (teardown K4):
                          the browser's locale used to render this month-first
                          for a Pakistan-first product. */}
                      {formatDate(row.date)}
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
                      {row.orderId ? (
                        <button
                          onClick={() => openInvoice(row.orderId!)}
                          disabled={fetchingInvoice === row.orderId}
                          className="inline-flex items-center gap-1 font-semibold text-primary-strong underline-offset-2 hover:underline disabled:opacity-60"
                        >
                          {fetchingInvoice === row.orderId ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3" />
                          )}
                          {row.invoiceNumber ?? "Invoice"}
                        </button>
                      ) : (
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
          Change or cancel your plan above. Your rep keeps answering until the end of the period you
          have paid for, and payments already made are not refunded except where the law requires
          it.
        </p>
      </CardContent>
    </Card>
  );
}
