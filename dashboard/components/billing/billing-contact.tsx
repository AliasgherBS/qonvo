"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { config, describeError, type TenantConfig } from "@/lib/api";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Where the business's invoices go, and how it reaches us about them
 * (teardown Z7).
 *
 * Both directions, because they are two different questions that arrive
 * together on this page and neither had an answer. Billing notices went to
 * whoever happened to sign up, which in a business of any size is a founder or
 * an office manager rather than the person who pays invoices; and a page about
 * money named no way to ask a question about money.
 *
 * Deliberately no tax id, company registration or invoice address. The
 * merchant of record is the seller named on the invoice and issues it under
 * its own registration, so which of those fields apply is its answer and not
 * ours. Collecting a number we never print on anything would look like a
 * feature and behave like a dead field, which is worse than the gap.
 */
export function BillingContact() {
  const token = useAuthToken();
  const { toast } = useToast();
  const { data, loading } = useApi(() => config.get({ token }), [token]);

  /** The full config, so the save can PUT one field of a known-good object. */
  const [form, setForm] = useState<TenantConfig | null>(null);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) {
      setForm(data);
      setValue(data.billingEmail);
    }
  }, [data]);

  // Compared trimmed, because trailing whitespace is what a paste leaves
  // behind and it is not a change worth offering to save.
  const dirty = !!form && value.trim() !== form.billingEmail;

  async function save() {
    if (!form) return;
    const next = { ...form, billingEmail: value.trim() };
    setSaving(true);
    try {
      // Only this field: the API applies exclude_unset, so nothing else on the
      // config is touched by a save from the Billing page.
      const saved = await config.update(next, { token }, ["billing_email"]);
      setForm(saved);
      setValue(saved.billingEmail);
      toast({
        title: saved.billingEmail ? "Billing address saved" : "Back to your login address",
        variant: "success",
      });
    } catch (err) {
      // The API refuses an address that is not one with a 400 rather than
      // storing it, so this is the real message and worth showing verbatim: a
      // billing address that silently never delivers is worse than none.
      toast({ title: "Could not save", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Billing contact</CardTitle>
          <CardDescription>
            Where invoices and payment notices go, and how to reach us about them.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading || !form ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor="billing-email">Send invoices to</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id="billing-email"
                type="email"
                autoComplete="email"
                className="max-w-sm flex-1"
                placeholder="accounts@yourbusiness.com"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-describedby="billing-email-help"
              />
              {/* Only once there is something to save, matching the settings
                  pages: a permanently enabled Save on a pre-filled field
                  invites a click that does nothing. */}
              {dirty ? (
                <Button onClick={save} disabled={saving}>
                  {saving ? "Saving" : "Save"}
                </Button>
              ) : null}
            </div>
            <p id="billing-email-help" className="text-xs text-muted-foreground">
              {form.billingEmail
                ? "Leave it empty to go back to the address you sign in with."
                : "Empty, so invoices go to the address you sign in with. Set an accounts address here if that is not the right person."}
            </p>
          </div>
        )}

        {/* Us, not them. A page about money with no way to ask about money is
            how a billing question becomes a chargeback. */}
        <p className="border-t border-border pt-4 text-xs text-muted-foreground">
          Billing questions, or a problem with a payment?{" "}
          <a href={CONTACT.billingHref} className="font-semibold text-primary-strong hover:underline">
            {CONTACT.billing}
          </a>
        </p>
      </CardContent>
    </Card>
  );
}
