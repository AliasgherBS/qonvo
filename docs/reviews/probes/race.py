"""Race the same probe that found the seat-cap bug against every other write path."""
import json, subprocess, threading, time

A = "https://api.qonvo.org"
TOK = open("/tmp/qtok").read().strip()
H = "Authorization: Bearer " + TOK


def call(method, ep, body=None, out=None):
    args = ["curl", "-s", "-o", out or "/dev/null", "-w", "%{http_code}", "--max-time", "40",
            "-X", method, A + ep, "-H", H]
    if body is not None:
        f = "/tmp/rb_%s.json" % threading.current_thread().name
        open(f, "w").write(json.dumps(body))
        args += ["-H", "Content-Type: application/json", "--data", "@" + f]
    return subprocess.run(args, capture_output=True, text=True).stdout


def race(label, method, ep, bodies):
    res = [None] * len(bodies)

    def go(i):
        res[i] = call(method, ep, bodies[i], out="/tmp/race_%d.json" % i)

    ts = [threading.Thread(target=go, args=(i,), name=str(i)) for i in range(len(bodies))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("  %-46s -> %s" % (label, " | ".join(res)))
    return res


def get(ep):
    r = subprocess.run(["curl", "-s", A + ep, "-H", H], capture_output=True, text=True)
    return json.loads(r.stdout)


print("=== 1. CONFIG: two simultaneous writes with different values ===")
before = get("/api/config")["tone"]
print("  tone before:", repr(before))
race("PUT /api/config x2 (tone A vs tone B)", "PUT", "/api/config",
     [{"tone": "RACE-AAA"}, {"tone": "RACE-BBB"}])
time.sleep(1)
print("  tone after :", repr(get("/api/config")["tone"]))

print("=== 2. ACTIVATION: two simultaneous toggles ===")
st = get("/api/billing")
print("  probing activation endpoint shape")
r = subprocess.run(["curl", "-s", "-o", "/tmp/act.json", "-w", "%{http_code}",
                    A + "/api/activation", "-H", H], capture_output=True, text=True)
print("  GET /api/activation ->", r.stdout, open("/tmp/act.json").read()[:120])

print("=== 3. DOUBLE DELETE of the same knowledge source ===")
c = call("POST", "/api/knowledge/sources",
         {"type": "manual", "title": "QA race delete", "content": "temp"}, out="/tmp/ks.json")
sid = json.load(open("/tmp/ks.json")).get("id")
print("  created ->", c, sid)
if sid:
    race("DELETE same source x2", "DELETE", "/api/knowledge/sources/" + sid, [None, None])

print("=== 4. NOTIFICATIONS: double mark-read ===")
ns = get("/api/notifications")
rows = ns if isinstance(ns, list) else ns.get("items", ns)
if rows:
    nid = rows[0]["id"]
    race("POST notifications/{id}/read x2", "POST",
         "/api/notifications/%s/read" % nid, [None, None])
    after = get("/api/notifications")
    rows2 = after if isinstance(after, list) else after.get("items", after)
    unread = sum(1 for r in rows2 if not r.get("read_at"))
    print("  unread after explicit mark-read:", unread, "of", len(rows2))
