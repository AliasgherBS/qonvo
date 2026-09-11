"""Staging E2E: drive the inbound pipeline through a signed WAHA webhook and test the gates."""
import hashlib, hmac, json, subprocess, time, uuid

S = "http://localhost:8010"
OWNER = open("/tmp/s_owner").read().strip()


def sql(q):
    r = subprocess.run(["docker", "exec", "qonvo-staging-postgres-1", "psql", "-U", "qonvo",
                        "-d", "qonvo", "-tAc", q], capture_output=True, text=True)
    return r.stdout.strip()


def api(method, ep, body=None, tok=None):
    args = ["curl", "-s", "-o", "/tmp/p.json", "-w", "%{http_code}", "-X", method, S + ep,
            "-H", "Authorization: Bearer " + (tok or OWNER)]
    if body is not None:
        open("/tmp/pb.json", "w").write(json.dumps(body))
        args += ["-H", "Content-Type: application/json", "--data", "@/tmp/pb.json"]
    code = subprocess.run(args, capture_output=True, text=True).stdout
    try:
        return code, json.load(open("/tmp/p.json"))
    except Exception:
        return code, open("/tmp/p.json", errors="replace").read()[:150]


row = sql("select session_name || '|' || hmac_secret from whatsapp_sessions "
          "where session_name like 'e2e-smoke%' limit 1;")
if "|" not in row:
    row = sql("select session_name || '|' || hmac_secret from whatsapp_sessions limit 1;")
SESSION, SECRET = row.split("|", 1)
print("session:", SESSION)


def inbound(text, chat="923001234567@c.us"):
    payload = {
        "event": "message",
        "session": SESSION,
        "payload": {
            "id": "qa_" + uuid.uuid4().hex[:16],
            "timestamp": int(time.time()),
            "from": chat,
            "fromMe": False,
            "body": text,
            "type": "chat",
            "_data": {"notifyName": "QA Probe"},
        },
    }
    raw = json.dumps(payload).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
    open("/tmp/wh.json", "wb").write(raw)
    r = subprocess.run(["curl", "-s", "-o", "/tmp/whr.json", "-w", "%{http_code}",
                        "-X", "POST", S + "/webhooks/waha",
                        "-H", "Content-Type: application/json",
                        "-H", "X-Webhook-Hmac: " + sig, "--data", "@/tmp/wh.json"],
                       capture_output=True, text=True)
    return r.stdout, open("/tmp/whr.json", errors="replace").read()[:110]


print("=== webhook signature enforcement ===")
raw = json.dumps({"event": "message", "session": SESSION, "payload": {}}).encode()
open("/tmp/wh2.json", "wb").write(raw)
for label, hdr in [("no signature", []), ("wrong signature", ["-H", "X-Webhook-Hmac: deadbeef"])]:
    r = subprocess.run(["curl", "-s", "-o", "/tmp/x.json", "-w", "%{http_code}", "-X", "POST",
                        S + "/webhooks/waha", "-H", "Content-Type: application/json"] + hdr +
                       ["--data", "@/tmp/wh2.json"], capture_output=True, text=True)
    print("  %-18s -> %s %s" % (label, r.stdout, open("/tmp/x.json", errors="replace").read()[:70]))

print("=== GATE: rep paused ===")
print("  set rep_active=false ->", api("PUT", "/api/activation", {"rep_active": False})[0])
before = sql("select count(*) from messages;")
print("  inbound ->", inbound("QA gate probe while paused"))
time.sleep(9)
after = sql("select count(*) from messages;")
out = sql("select count(*) from messages where direction='outbound' "
          "and created_at > now() - interval '30 seconds';")
print("  messages %s -> %s | outbound in last 30s: %s" % (before, after, out))

print("=== GATE: rate limit (25 messages in one burst) ===")
print("  set rep_active=true ->", api("PUT", "/api/activation", {"rep_active": True})[0])
codes = {}
for i in range(25):
    c, _ = inbound("flood %d" % i, chat="923009999999@c.us")
    codes[c] = codes.get(c, 0) + 1
print("  webhook responses:", codes)
time.sleep(6)
drops = sql("select coalesce(sum(1),0) from messages where chat_id like '923009999999%';")
print("  stored inbound from the flood chat:", drops)

print("=== restore ===")
print("  rep_active=true ->", api("PUT", "/api/activation", {"rep_active": True})[0])
