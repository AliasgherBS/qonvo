"""Staging E2E: signup, email verification, and what an unverified tenant may do."""
import json, subprocess, time, re, secrets

S = "http://localhost:8010"
EMAIL = "qa-e2e-%s@example.com" % secrets.token_hex(3)
PW = "QaStaging!2026"


def req(method, ep, body=None, tok=None, out="/tmp/e2.json"):
    args = ["curl", "-s", "-o", out, "-w", "%{http_code}", "--max-time", "40", "-X", method, S + ep]
    if tok:
        args += ["-H", "Authorization: Bearer " + tok]
    if body is not None:
        open("/tmp/e2b.json", "w").write(json.dumps(body))
        args += ["-H", "Content-Type: application/json", "--data", "@/tmp/e2b.json"]
    code = subprocess.run(args, capture_output=True, text=True).stdout
    try:
        data = json.load(open(out))
    except Exception:
        data = open(out, errors="replace").read()[:200]
    return code, data


def logs(pattern, mins="2m"):
    r = subprocess.run(["docker", "compose", "-p", "qonvo-staging", "logs", "--since", mins, "api"],
                       capture_output=True, text=True)
    return re.findall(pattern, r.stdout)


print("=== 1. SIGNUP ===")
c, d = req("POST", "/api/auth/signup",
           {"business_name": "QA E2E Salon", "owner_name": "QA Runner",
            "email": EMAIL, "password": PW})
print("  signup ->", c, str(d)[:150])
tok = d.get("access_token") if isinstance(d, dict) else None

print("=== 2. WEAK PASSWORD AT SIGNUP ===")
c2, d2 = req("POST", "/api/auth/signup",
             {"business_name": "QA Weak", "owner_name": "QA", "email": "qa-weak@example.com",
              "password": "password"})
print("  weak signup ->", c2, str(d2)[:150])

print("=== 3. DUPLICATE EMAIL ===")
c3, d3 = req("POST", "/api/auth/signup",
             {"business_name": "QA Dup", "owner_name": "QA", "email": EMAIL, "password": PW})
print("  duplicate ->", c3, str(d3)[:150])

print("=== 4. VERIFICATION EMAIL ===")
time.sleep(3)
links = logs(r"verify[a-z-]*\?token=([A-Za-z0-9._-]+)")
print("  verify tokens found in log:", len(links))

print("=== 5. WHAT CAN AN UNVERIFIED OWNER DO? ===")
if tok:
    for label, m, ep, b in [
        ("GET /api/me", "GET", "/api/me", None),
        ("GET /api/config", "GET", "/api/config", None),
        ("GET /api/onboarding", "GET", "/api/onboarding", None),
        ("POST knowledge", "POST", "/api/knowledge/sources",
         {"type": "manual", "title": "unverified probe", "content": "x"}),
        ("POST /api/sessions (link a number)", "POST", "/api/sessions",
         {"session_name": "qa-e2e-unverified"}),
        ("PUT /api/activation (go live)", "PUT", "/api/activation", {"active": True}),
    ]:
        cc, dd = req(m, ep, b, tok=tok)
        print("  %-36s -> %s %s" % (label, cc, str(dd)[:90]))

if links:
    print("=== 6. CONSUME THE VERIFICATION LINK ===")
    t = links[-1]
    c6, d6 = req("POST", "/api/auth/verify-email", {"token": t})
    print("  verify ->", c6, str(d6)[:120])
    c7, d7 = req("POST", "/api/auth/verify-email", {"token": t})
    print("  reuse  ->", c7, str(d7)[:120])
    if tok:
        c8, d8 = req("GET", "/api/me", tok=tok)
        print("  /api/me email_verified:", d8.get("email_verified") if isinstance(d8, dict) else d8)

print("EMAIL=" + EMAIL)
open("/tmp/qa_e2e_email", "w").write(EMAIL)
if tok:
    open("/tmp/qa_e2e_tok", "w").write(tok)
