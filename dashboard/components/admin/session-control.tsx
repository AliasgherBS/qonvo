"use client";

import { MoreHorizontal, RotateCw, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { adminFleet, describeError, type FleetAction, type FleetSession } from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * The controls for one WhatsApp session (finding A1).
 *
 * Every Fleet row used to render Restart, Start, Stop and Logout in a line, at
 * identical size and weight, with no grouping and no confirmation.
 *
 * **Logout ends the WhatsApp pairing.** The customer has to find their phone,
 * open WhatsApp, go to Linked devices and scan a fresh QR code before their rep
 * answers anybody again. It is an outage the operator cannot fix from their
 * side, sitting one pixel from Restart, which is the harmless thing an operator
 * actually wants. Tenant deletion, two screens away, correctly demands the
 * business name typed in full.
 *
 * Three changes, in order of how much they matter:
 *
 * 1. **Restart is the only prominent control**, because it is the answer to
 *    almost every "their rep has gone quiet". Stop and Logout live behind a
 *    menu.
 * 2. **Logout confirms by name.** Typed in full, the same bar tenant deletion
 *    sets, because the consequence is comparable and lands on somebody who did
 *    not press the button.
 * 3. **Only the actions that make sense for the state are offered.** Start on a
 *    working session is noise, and noise is what made four equal buttons
 *    scannable-past in the first place.
 */

/** Statuses that mean the session is up, or on its way up. */
const LIVE_STATES = ["WORKING", "STARTING", "SCAN_QR_CODE", "OPENING"];

function isRunning(session: FleetSession): boolean {
  // Prefer WAHA's live answer: the stored row is what we last heard, and a
  // session that died since is exactly the case an operator is here to fix.
  const state = (session.liveStatus ?? session.status ?? "").toUpperCase();
  return LIVE_STATES.includes(state);
}

export function SessionControl({
  session,
  onChanged,
}: {
  session: FleetSession;
  onChanged: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState<FleetAction | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocumentClick(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocumentClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocumentClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const running = isRunning(session);
  const label = session.tenantName ?? session.label ?? session.name;

  async function run(action: FleetAction) {
    setBusy(action);
    setMenuOpen(false);
    try {
      const res = await adminFleet.action(session.name, action, { token });
      toast({
        title: `${action[0].toUpperCase()}${action.slice(1)} sent`,
        description: res.live_status ? `Live status: ${res.live_status}` : undefined,
        variant: "success",
      });
      onChanged();
    } catch (err) {
      toast({ title: "Action failed", description: describeError(err), variant: "error" });
    } finally {
      setBusy(null);
      setConfirmLogout(false);
    }
  }

  return (
    <div className="flex items-center justify-end gap-1.5">
      {/* The one control an operator reaches for, and the only one that looks
          like a control. */}
      {running ? (
        <Button variant="primary" size="sm" disabled={busy !== null} onClick={() => run("restart")}>
          <RotateCw className="h-3.5 w-3.5" />
          {busy === "restart" ? "Restarting…" : "Restart"}
        </Button>
      ) : (
        <Button variant="primary" size="sm" disabled={busy !== null} onClick={() => run("start")}>
          <Play className="h-3.5 w-3.5" />
          {busy === "start" ? "Starting…" : "Start"}
        </Button>
      )}

      <div className="relative" ref={menuRef}>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`More actions for ${label}`}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          disabled={busy !== null}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>

        {menuOpen ? (
          <div
            role="menu"
            className="absolute right-0 z-30 mt-1 w-56 overflow-hidden rounded-xl border border-border bg-background p-1 text-left shadow-lg"
          >
            {/* Restart is already the prominent control when the session is up,
                so it only appears here for a session that is down, where Start
                is the prominent one and a restart is the second thing to try. */}
            {!running ? (
              <MenuItem onClick={() => run("restart")}>Restart</MenuItem>
            ) : (
              <MenuItem onClick={() => run("stop")}>
                Stop
                <MenuHint>Goes offline until started again. The pairing survives.</MenuHint>
              </MenuItem>
            )}

            <div className="my-1 border-t border-border" />

            <MenuItem destructive onClick={() => setConfirmLogout(true)}>
              Log out
              <MenuHint>
                Unlinks the phone. {label} has to scan a new QR code before their rep answers
                anybody.
              </MenuHint>
            </MenuItem>
          </div>
        ) : null}
      </div>

      <LogoutDialog
        open={confirmLogout}
        tenantName={label}
        sessionName={session.name}
        busy={busy === "logout"}
        onClose={() => setConfirmLogout(false)}
        onConfirm={() => run("logout")}
      />
    </div>
  );
}

function MenuItem({
  children,
  onClick,
  destructive,
}: {
  children: React.ReactNode;
  onClick: () => void;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`w-full rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted ${
        destructive ? "text-danger" : ""
      }`}
    >
      {children}
    </button>
  );
}

function MenuHint({ children }: { children: React.ReactNode }) {
  return <span className="mt-0.5 block font-normal text-muted-foreground">{children}</span>;
}

/**
 * Confirmation by name, not by "are you sure".
 *
 * A yes/no dialog on a destructive action is a speed bump, and an operator
 * working through a list clicks past it. Typing the business name makes the
 * operator name the customer they are about to take offline, which is the only
 * check that catches the actual mistake: doing it to the wrong row.
 */
function LogoutDialog({
  open,
  tenantName,
  sessionName,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  tenantName: string;
  sessionName: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Log out this number?"
      description={`This unlinks the phone from "${tenantName}". Their rep stops answering immediately, and it stays down until the owner scans a fresh QR code from WhatsApp on their phone. You cannot undo it from here.`}
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
          Session <span className="font-mono font-semibold">{sessionName}</span>. If the rep has
          simply gone quiet, Restart is what you want instead.
        </div>
        <div className="space-y-1.5">
          <label htmlFor="logout-confirm" className="text-xs font-semibold">
            Type <span className="font-bold text-foreground">{tenantName}</span> to confirm
          </label>
          <Input
            id="logout-confirm"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={tenantName}
            autoComplete="off"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" disabled={busy || typed !== tenantName} onClick={onConfirm}>
            {busy ? "Logging out…" : "Log out and unlink"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
