"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { describeError } from "@/lib/api";
import { profile } from "@/lib/api/account";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * The one thing about you that you can change (teardown V5, V7).
 *
 * The card said "How you appear to your team" and let you set nothing: it
 * showed an email and a role, both read-only, and neither of which is how you
 * appear to anyone. The display name behind that phrase, the string in the
 * avatar menu, in the Team list and on every invitation you send, was captured
 * once at signup and could never be changed from here or from anywhere else. A
 * Google signup took it from the Google profile, so a typo was permanent.
 *
 * The read-only values are rendered as text with a label rather than as
 * bordered, filled boxes the same size and shape as an input (teardown V7).
 * The eye read a form and then found nothing to type in, which is worse than a
 * plain fact, because it wastes the reader's attention before disappointing
 * them.
 *
 * The name comes from the API rather than from the Auth.js session, because the
 * session's copy is baked into a JWT at sign-in: after a save this card is
 * right immediately and the avatar initial catches up when the token next
 * refreshes. Reading the session here would show the old name straight back at
 * somebody who had just changed it.
 */
export function ProfileCard() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => profile.get({ token }), [token]);
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setName(data.fullName);
  }, [data]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await profile.setName(name, { token });
      toast({
        title: "Name saved",
        // Said plainly rather than left as a surprise: the avatar menu reads
        // the session, which is a JWT minted at sign-in.
        description: "The avatar menu and your team list catch up next time you sign in.",
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Could not save your name", description: describeError(err), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  const dirty = !!data && name.trim() !== data.fullName;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            Your name is what your team and your invitations show.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        ) : error || !data ? (
          <div className="text-sm text-muted-foreground">
            {error ?? "Could not load your profile."}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="full-name">Your name</Label>
              <Input
                id="full-name"
                value={name}
                autoComplete="name"
                maxLength={120}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
              />
            </div>

            <Button type="submit" disabled={saving || !dirty || !name.trim()}>
              {saving ? "Saving" : "Save name"}
            </Button>

            <dl className="space-y-4 border-t border-border pt-5">
              <div>
                <dt className="text-xs font-semibold text-muted-foreground">Email</dt>
                <dd className="text-sm font-semibold">{data.email}</dd>
                <p className="mt-1 text-xs text-muted-foreground">
                  Your email is how you sign in and cannot be changed here.{" "}
                  <a
                    href={CONTACT.supportHref}
                    className="font-semibold text-primary-strong underline-offset-2 hover:underline"
                  >
                    Email {CONTACT.support}
                  </a>{" "}
                  to have it moved.
                </p>
              </div>

              {data.role ? (
                <div>
                  <dt className="text-xs font-semibold text-muted-foreground">Role</dt>
                  <dd className="text-sm font-semibold capitalize">
                    {data.role.replace(/_/g, " ")}
                  </dd>
                </div>
              ) : null}
            </dl>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
