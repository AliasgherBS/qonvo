"""Staging E2E part 2: activation, billing lifecycle, sessions, remaining races."""
import json, subprocess, threading, time

S = "http://localhost:8010"
OWNER = open("/tmp/s_owner").read().strip()


def req(method, ep, body=None, tok=None, out="/tmp/e3.json"):
    args = ["curl", "-s", "-o", out, "-w", "%{http_code}", "--max-time", "60", "-X", method, S + ep,
            "-H", "Authorization: Bearer " + (tok or OWNER)]
    if body is not None:
        f = "/tmp/e3b_%s.json" % threading.current_thread().name
        open(f, "w").write(json.dumps(body))
        args += ["-H", "Content-Type: application/json", "--data", "@" + f]
    code = subprocess.run(args, capture_output=True, text=True).stdout
    try:
        data = json.load(open(out))
    except Exception:
        data = open(out, errors="replace").read()[:160]
    return code, data


def show(label, r):
    print("  %-40s -> %s %s" % (label, r[0], str(r[1])[:110]))


def race(label, method, ep, bodies):
    res = [None] * len(bodies)

    def go(i):
        res[i] = req(method, ep, bodies[i], out="/tmp/e3r_%d.json" % i)[0]
    ts = [threading.Thread(target=go, args=(i,), name=str(i)) for i in range(len(bodies))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print("  %-40s -> %s" % (label, " | ".join(str(x) for x in res)))


print("=== ACTIVATION ===")
show("GET  /api/activation", req("GET", "/api/activation"))
show("PUT  rep_active=false", req("PUT", "/api/activation", {"rep_active": False}))
show("GET  after pause", req("GET", "/api/activation"))
show("PUT  rep_active=true", req("PUT", "/api/activation", {"rep_active": True}))
race("RACE two activation toggles", "PUT", "/api/activation",
     [{"rep_active": False}, {"rep_active": True}])
show("GET  after race", req("GET", "/api/activation"))
req("PUT", "/api/activation", {"rep_active": True})

print("=== BILLING LIFECYCLE (manual provider on staging) ===")
show("GET  /api/billing", req("GET", "/api/billing"))
show("GET  /api/billing/plans", req("GET", "/api/billing/plans"))
show("POST change-plan -> growth", req("POST", "/api/billing/change-plan", {"plan_key": "growth"}))
show("GET  usage after change", req("GET", "/api/billing/usage"))
show("POST change-plan -> bogus", req("POST", "/api/billing/change-plan", {"plan_key": "unicorn"}))
show("POST cancel", req("POST", "/api/billing/cancel"))
show("GET  billing after cancel", req("GET", "/api/billing"))
show("POST resume", req("POST", "/api/billing/resume"))
show("POST resume again (idempotent?)", req("POST", "/api/billing/resume"))
race("RACE two cancels", "POST", "/api/billing/cancel", [None, None])
show("GET  billing after race", req("GET", "/api/billing"))
show("POST resume (restore)", req("POST", "/api/billing/resume"))
show("POST checkout", req("POST", "/api/billing/checkout", {"plan_key": "scale"}))

print("=== SESSIONS ===")
show("GET  /api/sessions", req("GET", "/api/sessions"))
show("POST create session", req("POST", "/api/sessions", {"session_name": "qa-e2e-sess"}))
time.sleep(2)
show("GET  status", req("GET", "/api/sessions/qa-e2e-sess/status"))
show("GET  qr", req("GET", "/api/sessions/qa-e2e-sess/qr"))
show("POST duplicate session name", req("POST", "/api/sessions", {"session_name": "qa-e2e-sess"}))

print("=== KNOWLEDGE CAP RACE (create at the boundary) ===")
c, d = req("GET", "/api/billing/usage")
if isinstance(d, dict):
    src = d.get("knowledge_sources", {})
    print("  sources now: %s of %s" % (src.get("used"), src.get("allowed")))
race("RACE two knowledge creates", "POST", "/api/knowledge/sources",
     [{"type": "manual", "title": "qa-race-k1", "content": "a"},
      {"type": "manual", "title": "qa-race-k2", "content": "b"}])
