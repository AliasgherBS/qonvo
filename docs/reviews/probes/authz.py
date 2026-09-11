"""Staff-role authorization matrix on staging. Every call is a staff token."""
import json, subprocess

S = "http://localhost:8010"
STAFF = open("/tmp/s_staff").read().strip()
OWNER = open("/tmp/s_owner").read().strip()


def call(tok, method, ep, body=None):
    args = ["curl", "-s", "-o", "/tmp/az.json", "-w", "%{http_code}", "--max-time", "30",
            "-X", method, S + ep, "-H", "Authorization: Bearer " + tok]
    if body is not None:
        open("/tmp/azb.json", "w").write(json.dumps(body))
        args += ["-H", "Content-Type: application/json", "--data", "@/tmp/azb.json"]
    code = subprocess.run(args, capture_output=True, text=True).stdout
    return code, open("/tmp/az.json", errors="replace").read()[:70].replace("\n", " ")


# (label, method, endpoint, body, should staff be allowed?)
CASES = [
    ("read inbox",              "GET",  "/api/conversations", None, True),
    ("read knowledge",          "GET",  "/api/knowledge/sources", None, True),
    ("read config",             "GET",  "/api/config", None, True),
    ("read analytics",          "GET",  "/api/analytics/summary", None, True),
    ("read billing",            "GET",  "/api/billing", None, False),
    ("read invoices",           "GET",  "/api/billing/payments", None, False),
    ("read team",               "GET",  "/api/team", None, True),
    ("--- writes ---",          None,   None, None, None),
    ("WRITE config (persona)",  "PUT",  "/api/config", {"persona": "STAFF-PROBE"}, False),
    ("WRITE payment details",   "PUT",  "/api/config", {"payment_details": "STAFF-PROBE-IBAN"}, False),
    ("add knowledge",           "POST", "/api/knowledge/sources",
     {"type": "manual", "title": "staff probe", "content": "x"}, True),
    ("invite a teammate",       "POST", "/api/team/invitations",
     {"email": "staff-probe@example.com", "role": "staff"}, False),
    ("export all tenant data",  "GET",  "/api/account/export", None, False),
    ("toggle the rep off",      "POST", "/api/activation", {"active": False}, False),
    ("cancel the subscription", "POST", "/api/billing/cancel", None, False),
    ("change plan",             "POST", "/api/billing/change-plan", {"plan_key": "scale"}, False),
    ("open billing portal",     "POST", "/api/billing/portal", None, False),
    ("create a WhatsApp session", "POST", "/api/sessions", {"session_name": "staff-probe"}, False),
    ("disconnect Google",       "DELETE", "/api/integrations/google_calendar", None, False),
    ("admin route",             "GET",  "/api/admin/tenants", None, False),
]

print("  %-28s %-6s %-8s %s" % ("action", "code", "verdict", "detail"))
print("  " + "-" * 78)
bad = []
for label, method, ep, body, allowed in CASES:
    if method is None:
        print("  %s" % label)
        continue
    code, detail = call(STAFF, method, ep, body)
    ok = code.startswith("2")
    if allowed is True:
        verdict = "ok" if ok else "BLOCKED?"
    else:
        verdict = "LEAK" if ok else "ok"
        if ok:
            bad.append(label)
    print("  %-28s %-6s %-8s %s" % (label[:28], code, verdict, detail))

print()
print("  staff can do %d things it should not:" % len(bad))
for b in bad:
    print("    -", b)
