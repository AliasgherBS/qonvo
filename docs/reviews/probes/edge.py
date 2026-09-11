import json, subprocess

A = "https://api.qonvo.org"
TOK = open("/tmp/qtok").read().strip()


def post(body, label, ep="/api/knowledge/sources"):
    f = "/tmp/pl.json"
    open(f, "w").write(json.dumps(body))
    r = subprocess.run(
        ["curl", "-s", "-o", "/tmp/e.json", "-w", "%{http_code}", "--max-time", "90",
         "-X", "POST", A + ep, "-H", "Authorization: Bearer " + TOK,
         "-H", "Content-Type: application/json", "--data", "@" + f],
        capture_output=True, text=True)
    out = open("/tmp/e.json", errors="replace").read()[:120].replace("\n", " ")
    print("  %-44s -> %s  %s" % (label, r.stdout, out))
    return r.stdout


print("=== UNICODE / INJECTION-SHAPED ===")
post({"type": "manual", "title": "QA emoji \U0001F1F5\U0001F1F0",
      "content": "rate \U0001F642 salam سلام 日本語 ok"},
     "emoji + RTL + CJK")
post({"type": "manual", "title": "QA nul",
      "content": "before" + chr(0) + "after"}, "NUL byte in content")
post({"type": "manual", "title": "QA xss",
      "content": "<script>alert(1)</script><img src=x onerror=alert(1)>"},
     "script tag in content")
post({"type": "manual", "title": "QA sqlish",
      "content": "'; DROP TABLE knowledge_sources; --"}, "sql-shaped content")
post({"type": "manual", "title": "", "content": "x"}, "empty title")
post({"type": "manual", "content": "no title key"}, "missing title key")
post({"type": "bogus", "title": "QA bad type", "content": "x"}, "invalid source type")

print("=== PAYLOAD SIZE ===")
post({"type": "manual", "title": "QA big", "content": "x" * 60000}, "60k chars (cap 50k)")
post({"type": "manual", "title": "QA huge", "content": "x" * 8000000}, "8 MB body")
