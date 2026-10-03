#!/usr/bin/env python3
"""Drive whole conversations through the ingress, without WhatsApp.

The point of this file is that nobody has to pick up a phone.

Every behaviour worth testing in this product -- language matching, debounce,
grounding, refusals, handoff, the skills -- happens between the webhook arriving
and the reply being written. WhatsApp's only job is delivery. So we post the
same signed payload WAHA would post, and read what the pipeline does with it.

STAGING ONLY, and it refuses to run anywhere else: it creates tenants, writes
knowledge and sends real model requests.

    python3 scripts/conversation-lab/lab.py --list
    python3 scripts/conversation-lab/lab.py --tenant salon --script language
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("QONVO_LAB_API", "http://127.0.0.1:8010")
PG = os.environ.get("QONVO_LAB_PG", "qonvo-staging-postgres-1")
OWNER = os.environ.get("QONVO_LAB_OWNER", "owner@dev.dev")
PASSWORD = os.environ.get("QONVO_LAB_PASSWORD", "dev-password-123")

if "qonvo.org" in API and "dev" not in API:
    sys.exit("refusing to run against production: this creates tenants and sends model requests")


# --- plumbing ------------------------------------------------------------- #

def sql(query: str) -> str:
    out = subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "qonvo", "-d", "qonvo", "-tAc", query],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout.strip()


def api(method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            try:
                return r.status, json.load(r)
            except Exception:
                return r.status, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, None


def login(email=OWNER, password=PASSWORD) -> str:
    status, body = api("POST", "/api/auth/login", {"email": email, "password": password})
    if status != 200:
        raise RuntimeError(f"login failed ({status})")
    return body["access_token"]


# --- the ingress ---------------------------------------------------------- #

def inbound(session: str, secret: str, text: str, chat: str, *, name="Lab Customer") -> tuple[int, str]:
    """Post exactly what WAHA posts, signed exactly how WAHA signs it."""
    payload = {
        "event": "message",
        "session": session,
        "payload": {
            "id": "lab_" + uuid.uuid4().hex[:16],
            "timestamp": int(time.time()),
            "from": chat,
            "fromMe": False,
            "body": text,
            "type": "chat",
            "_data": {"notifyName": name},
        },
    }
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    req = urllib.request.Request(
        API + "/webhooks/waha", data=raw, method="POST",
        headers={"content-type": "application/json", "X-Webhook-Hmac": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read()[:160].decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:160].decode("utf8", "replace")


def wait_for_reply(tenant_id: str, chat: str, after: str, *, timeout=90) -> str | None:
    """The reply as the database recorded it, which is what the customer got."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = sql(
            "select m.body from messages m join conversations c on c.id=m.conversation_id "
            f"where c.tenant_id='{tenant_id}' and c.chat_id='{chat}' "
            f"and m.direction='outbound' and m.created_at > '{after}' "
            "order by m.created_at desc limit 1;"
        )
        if got:
            return got
        time.sleep(2)
    return None


def now_utc() -> str:
    return sql("select now() at time zone 'utc';")


# --- the businesses ------------------------------------------------------- #
#
# Four archetypes rather than one, because everything we have proved so far was
# proved on a beauty salon whose own instructions forbid quoting a price and
# forbid looking at a diary. A rule that holds for Depilex and nowhere else is
# not a rule the product has.

TENANTS = {
    "salon": {
        "description": "a hair and beauty salon",
        "name": "Lab Salon",
        "instructions": (
            "Answer only from this salon's own knowledge. If something is not in it, say "
            "so plainly and offer to pass the customer to the team.\n\n"
            "Never quote a price. Prices vary by branch. Say the branch will confirm.\n\n"
            "A booking on WhatsApp is a request, not a confirmed slot: take the service, "
            "the date and the name, then say someone will call to confirm."
        ),
        "knowledge": (
            "Lab Salon opens 9am to 7pm Monday to Saturday, closed Sunday. "
            "Services: haircut, hair colour, blow dry, facial, manicure, pedicure, "
            "threading, waxing. Appointments are recommended but walk-ins are taken "
            "when a stylist is free. Cancellations need four hours notice. "
            "We are on Main Boulevard, Gulberg."
        ),
    },
    "dental": {
        "description": "a dental practice",
        "name": "Lab Dental",
        "instructions": (
            "Answer only from this practice's own knowledge.\n\n"
            "Never give clinical advice, never diagnose, and never suggest a treatment "
            "plan. If a customer describes pain, swelling, bleeding or an injury, say it "
            "needs a dentist to look and offer the next appointment, then hand over.\n\n"
            "You may state the consultation fee, which is published. Do not quote any "
            "other price."
        ),
        "knowledge": (
            "Lab Dental is open 10am to 6pm Monday to Friday and 10am to 2pm on Saturday. "
            "The consultation fee is 2,000 rupees. Treatments offered: scaling and "
            "polishing, fillings, root canal, crowns, braces, teeth whitening, extraction. "
            "Emergency slots are held each morning. We do not treat children under five."
        ),
    },
    "clinic": {
        "description": "a multi-department medical clinic",
        "name": "Lab Clinic",
        "instructions": (
            "Answer only from this clinic's own knowledge.\n\n"
            "Never give medical advice and never interpret a symptom. Anything about "
            "symptoms, medication or test results goes to a human immediately.\n\n"
            "You may give opening hours, departments and how to book."
        ),
        "knowledge": (
            "Lab Clinic is open 8am to 10pm every day including Sunday. Departments: "
            "general medicine, paediatrics, dermatology, physiotherapy, laboratory. "
            "Walk-in registration closes thirty minutes before closing. Lab reports are "
            "ready the next working day and are collected in person."
        ),
    },
    "info": {
        "description": "a brand and web design studio",
        "name": "Lab Studio",
        "instructions": (
            "Answer only from this studio's own knowledge. This number is for information "
            "only: there is no booking, no diary and no payment taken here. If someone "
            "wants to buy or book, explain what we do and give them the way to get in "
            "touch."
        ),
        "knowledge": (
            "Lab Studio is a design studio. We do brand identity, packaging and web "
            "design. A typical identity project runs six to eight weeks. We work with "
            "clients across Pakistan and the Gulf. New enquiries go to hello@labstudio.test "
            "and we reply within two working days. We do not do printing or photography."
        ),
    },
}


# --- the scripts ---------------------------------------------------------- #
#
# Each is a list of (label, message, check) where check(reply) -> None or a
# complaint. Checks are deliberately about shape rather than wording: asserting
# exact prose would fail the first time the prompt improved.

URDU_MARKERS = (
    " hai", " hain", " aap ", " kar ", " ke ", " ki ", " ka ", " mein ", " dein",
    " karein", " batain", " gaya", " gayi", " nahi", " kya ", " hum ",
)
URDU_SCRIPT = range(0x0600, 0x06FF)


def looks_roman_urdu(text: str) -> bool:
    """Count occurrences, not distinct markers.

    "Ji, Lab Clinic roz 8am se 10pm tak khuli rehti hai ... band ho jati hai"
    is unmistakably Roman Urdu and scored 1 under the old rule, because " hai"
    is a single marker however many times it appears.
    """
    low = f" {text.lower()} "
    return sum(low.count(m) for m in URDU_MARKERS) >= 2


def looks_urdu_script(text: str) -> bool:
    return any(ord(c) in URDU_SCRIPT for c in text)


def must_be_english(reply: str) -> str | None:
    if looks_urdu_script(reply):
        return "replied in Urdu script to an English thread"
    if looks_roman_urdu(reply):
        return "replied in Roman Urdu to an English thread"
    return None


def must_be_roman_urdu(reply: str) -> str | None:
    if looks_urdu_script(reply):
        return "replied in Urdu script to a Roman Urdu thread"
    if not looks_roman_urdu(reply):
        return "replied in English to a Roman Urdu thread"
    return None


def must_be_urdu_script(reply: str) -> str | None:
    if not looks_urdu_script(reply):
        return "replied in Latin script to an Urdu-script thread"
    return None


def must_not_narrate(reply: str) -> str | None:
    """The rep speaks as the business, never about its own instructions."""
    low = reply.lower()
    for tell in (
        "roman urdu mein", "i will reply in", "my instructions", "i am instructed",
        "as an ai", "i cannot see", "i have been told", "system prompt",
        "i'll answer in", "mein hi bata",
    ):
        if tell in low:
            return f"narrated its own instructions: {tell!r}"
    return None


def chain(*checks):
    def run(reply: str) -> str | None:
        for c in checks:
            bad = c(reply)
            if bad:
                return bad
        return None
    return run


#: Every turn carries the no-narration check, because that leak showed up in a
#: language reply and would show up anywhere else just as easily.
def norm(text: str) -> str:
    """Fold the punctuation a model actually types.

    The replies use typographic apostrophes and dashes. Four correct refusals
    failed on "We don’t ..." because the check looked for "don't".
    """
    return (
        text.lower()
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
    )


SCRIPTS = {
    "language-english": [
        ("plain English", "what are your opening hours?", chain(must_be_english, must_not_narrate)),
        ("English follow-up", "and are you open on Sunday?", chain(must_be_english, must_not_narrate)),
        # The message that broke it on production: proper nouns and digits, no
        # language markers at all. Detection returns "Latin script, unknown
        # language", and the thread must not drift.
        ("proper nouns and digits", "Lahore, Signature, haircut, name Ali, 03132941504",
         chain(must_be_english, must_not_narrate)),
        ("still English after", "thanks, what else do you offer?",
         chain(must_be_english, must_not_narrate)),
    ],
    "language-roman-urdu": [
        ("Roman Urdu", "aap kab khulte hain?", chain(must_be_roman_urdu, must_not_narrate)),
        ("Roman Urdu again", "kya main aaj aa sakta hun?", chain(must_be_roman_urdu, must_not_narrate)),
        ("ambiguous mid-thread", "Lahore, 03132941504", must_not_narrate),
        ("Roman Urdu after", "theek hai, aur kya services hain?",
         chain(must_be_roman_urdu, must_not_narrate)),
    ],
    "language-urdu-script": [
        ("Urdu script", "آپ کے اوقات کیا ہیں؟", chain(must_be_urdu_script, must_not_narrate)),
        ("Urdu script again", "کیا اتوار کو کھلے ہیں؟", chain(must_be_urdu_script, must_not_narrate)),
    ],
    "grounding": [
        ("in its knowledge", "what are your opening hours?",
         lambda r: None if any(x in r.lower() for x in ("9", "10", "8", "am", "pm", "open"))
         else "did not answer from its own knowledge"),
        # Declining is not enough. "We don't have that detail to hand, the team
        # will confirm" treats a question about tyres as a gap in the knowledge
        # base rather than as a question about a different business, and offers
        # to come back about it. Saying what you ARE is the thing being checked.
        ("not in its knowledge", "do you sell car tyres?",
         lambda r: None if any(x in norm(r) for x in
                               ("don't sell", "do not sell", "we are a", "we're a",
                                "we only", "not something we", "we don't do",
                                "we do not do", "salon", "dental", "clinic", "design"))
         else "declined without saying what the business actually is"),
        ("invented detail", "how much is a haircut exactly, in rupees?", must_not_narrate),
        # The salon answered an English question in Urdu script. Whatever else
        # a refusal does, it must not change the alphabet.
        ("English question stays Latin", "do you sell car tyres?", must_be_english),
    ],
    "handover": [
        ("a complaint", "my treatment last week went wrong and I want a refund",
         lambda r: None if any(x in norm(r) for x in
                               ("team", "someone", "colleague", "representative", "human",
                                "get back", "call", "pass", "dentist", "doctor", "manager",
                                "appointment"))
         else "did not offer a person for a complaint"),
    ],
}


# --- setting a business up ------------------------------------------------ #

def ensure_tenant(key: str) -> tuple[str, str, str, str]:
    """Return (tenant_id, session_name, secret, chat_id), creating what is missing."""
    spec = TENANTS[key]
    name = spec["name"]
    tid = sql(f"select id from tenants where name='{name}' limit 1;")
    token = login()

    if not tid:
        # Sign a new owner up, which is also the only path that builds a tenant
        # the way a real one is built.
        # owner_name, not full_name; and example.com rather than .test, which
        # EmailStr refuses as a reserved TLD.
        email = f"lab-{key}@example.com"
        status, body = api("POST", "/api/auth/signup", {
            "business_name": name, "owner_name": "Lab Owner",
            "email": email, "password": "Lab-Tenant-2026-Xy",
        })
        if status not in (200, 201):
            raise RuntimeError(f"could not create {name}: {status} {json.dumps(body)[:200]}")
        tid = sql(f"select id from tenants where name='{name}' limit 1;")

    # Idempotent, not create-only. A half-finished earlier run leaves the tenant
    # behind unverified, and the next run then cannot connect a number -- which
    # reads as a product refusal rather than as a setup gap.
    owner_email = f"lab-{key}@example.com"
    sql(f"update tenants set status='active' where id='{tid}';")
    sql(f"update users set email_verified=true where email='{owner_email}';")

    try:
        token = login(owner_email, "Lab-Tenant-2026-Xy")
    except RuntimeError:
        pass

    # Instructions and knowledge, set through the API so validation applies.
    version = (api("GET", "/api/config", token=token)[1] or {}).get("version", 1)
    api("PUT", "/api/config", {
        "business_name": name,
        "business_description": spec["description"],
        "custom_instructions": spec["instructions"],
        "primary_language": "en",
        "version": version,
    }, token=token)

    # A new tenant starts with the rep paused, which is correct for a real
    # signup and silent for a test: the ingress stores the message and logs
    # "rep is switched off", so the lab waits ninety seconds for a reply that
    # was never going to come.
    api("PUT", "/api/activation", {"rep_active": True}, token=token)

    have = sql(
        f"select count(*) from knowledge_sources where tenant_id='{tid}' and status='ready';"
    )
    if have == "0":
        api("POST", "/api/knowledge/sources", {
            "type": "manual", "title": f"{name} facts", "content": spec["knowledge"],
        }, token=token)
        for _ in range(40):
            if sql(f"select count(*) from knowledge_sources where tenant_id='{tid}' "
                   "and status='ready';") != "0":
                break
            time.sleep(3)

    # A session row is all the ingress needs; WAHA is only asked to deliver.
    row = sql(
        f"select session_name || '|' || hmac_secret from whatsapp_sessions "
        f"where tenant_id='{tid}' limit 1;"
    )
    if "|" not in row:
        status, body = api("POST", "/api/sessions", {"name": f"lab-{key}"}, token=token)
        if status not in (200, 201):
            raise RuntimeError(f"could not create a session for {name}: {status} {body}")
        row = sql(
            f"select session_name || '|' || hmac_secret from whatsapp_sessions "
            f"where tenant_id='{tid}' limit 1;"
        )
    session, secret = row.split("|", 1)
    return tid, session, secret, f"lab{abs(hash(key)) % 10**11}@c.us"


# --- running a script ----------------------------------------------------- #

def run_script(tenant_key: str, script_key: str, *, verbose=True) -> list[dict]:
    tid, session, secret, chat = ensure_tenant(tenant_key)
    results = []
    for label, message, check in SCRIPTS[script_key]:
        mark = now_utc()
        status, _ = inbound(session, secret, message, chat)
        if status != 200:
            results.append({"label": label, "sent": message, "ok": False,
                            "why": f"ingress refused the webhook ({status})", "reply": ""})
            continue
        reply = wait_for_reply(tid, chat, mark)
        if reply is None:
            results.append({"label": label, "sent": message, "ok": False,
                            "why": "no reply within 90s", "reply": ""})
            continue
        why = check(reply)
        results.append({"label": label, "sent": message, "ok": why is None,
                        "why": why or "", "reply": reply})
        if verbose:
            flag = "PASS" if why is None else "FAIL"
            print(f"    {flag}  {label}")
            print(f"          sent  {message[:68]}")
            print(f"          got   {reply[:100].replace(chr(10), ' ')}")
            if why:
                print(f"          why   {why}")
        # A real customer does not type the next message in the same instant,
        # and the debounce window is five seconds.
        time.sleep(7)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="all", help=f"{'|'.join(TENANTS)}|all")
    ap.add_argument("--script", default="all", help=f"{'|'.join(SCRIPTS)}|all")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("tenants:", ", ".join(TENANTS))
        print("scripts:", ", ".join(SCRIPTS))
        return 0

    tenants = list(TENANTS) if args.tenant == "all" else [args.tenant]
    scripts = list(SCRIPTS) if args.script == "all" else [args.script]

    every = []
    for t in tenants:
        print(f"\n=== {TENANTS[t]['name']} ===")
        for s in scripts:
            print(f"  -- {s} --")
            for r in run_script(t, s):
                r["tenant"], r["script"] = t, s
                every.append(r)

    failed = [r for r in every if not r["ok"]]
    print(f"\n=== {len(every) - len(failed)} passed, {len(failed)} failed ===")
    for r in failed:
        print(f"  {r['tenant']}/{r['script']}: {r['label']} -- {r['why']}")
        print(f"      got: {r['reply'][:140]}")
    with open("/tmp/conversation-lab.json", "w") as f:
        json.dump(every, f, indent=2)
    print("\nfull transcript: /tmp/conversation-lab.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
