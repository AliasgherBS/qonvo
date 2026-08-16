# Qonvo — Testing Matrix & Plan

_A single place to see: every objective feature, whether it's covered by an
**automated** test or needs a **manual** check, and a step-by-step plan to verify
the whole product works. Pair this with [`FEATURES.md`](FEATURES.md) (what the
product does) — this file is **how we prove it works.**_

---

## 1. How to run the tests

```bash
# Unit tests — no external services. This is the everyday gate. (~2s)
cd backend && uv run pytest -q && uv run ruff check
#   → 219 passed, 7 skipped

# Integration tests (marked @pytest.mark.postgres) — need a live, MIGRATED Postgres.
#   Run from the host with the two test DSNs pointed at the exposed DB (port 5433):
QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:<pass>@localhost:5433/qonvo \
QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:<pass>@localhost:5433/qonvo \
  uv run pytest -m postgres -q
#   36/41 pass. The 5 that fail are all in test_knowledge_api.py — they call
#   get_redis() directly (default host `redis:6379`, unresolvable from the host)
#   and expect the async ingest worker to flip a source to `ready`. That's an
#   environment limitation, not a code defect (see §4), and they aren't in the
#   docker image, so `docker compose exec` can't run them either.

# Frontend typecheck + build
cd dashboard && npx tsc --noEmit && npm run build

# One end-to-end smoke of the live API (see script in §5).
```

**Current status:** ✅ 219 unit tests pass · ✅ ruff clean · ✅ dashboard builds ·
✅ 36/41 integration tests pass (team/admin/auth/takeover/RLS) · ⚠️ 5 knowledge
integration tests are host-environment-broken, not defects (§4).

---

## 2. Automated test coverage (what pytest already guards)

| Test file | # | Kind | Covers |
|---|---|---|---|
| `test_security.py` | 11 | unit | JWT mint/verify, HMAC, argon2, Fernet |
| `test_providers.py` | 14 | unit | LLM/embedding adapter, retries, usage parsing |
| `test_pipeline.py` | 19 | unit | Gates (pause, quota, hours), tool loop, cost |
| `test_voice.py` | 17 | unit | STT/TTS resolve, voice metering, audio cap, image data-URI |
| `test_rag.py` | 18 | unit | Retrieval, min-score, context budget + dedup |
| `test_skills.py` | 29 | unit | All 8 skills, gating, handoff mute pref |
| `test_reminders.py` | 14 | unit | Booking reminder cron, caps, opt-out |
| `test_send_gateway.py` | 10 | unit | Pacing, daily cap, own-send fingerprint |
| `test_debounce.py` / `test_dedupe.py` / `test_lock.py` | 13 | unit | Buffer/coalesce, dedupe, conversation lock |
| `test_google_oauth.py` | 26 | unit | OAuth start/callback, token cache, revoke guard |
| `test_integrations.py` | 30 | unit | Calendar/Sheets clients, resolver |
| `test_filtering.py` / `test_tenancy.py` | 2 | unit | Chat-id filter, tenant GUC |
| `test_auth.py` | 5 | pg | Login, signup, Google SSO |
| `test_conversations.py` | 7 | pg | Inbox list, messages, takeover/release/reply |
| `test_admin.py` | 13 | pg | Tenant CRUD, fleet control, reset-password, impersonate, RLS scoping |
| `test_team.py` | 3 | pg | **Invite → accept → member, staff-can't-invite, bad token** |
| `test_takeover.py` | 10 | pg | Takeover state machine + auto-resume |
| `test_rls_postgres.py` | 2 | pg | Cross-tenant isolation is actually enforced |
| `test_knowledge_api.py` | 6 | pg | Source CRUD, ingest enqueue (⚠️ §4) |

---

## 3. Feature matrix (functionality → how it's verified)

Legend: **A** = automated (pytest) · **M** = manual check needed · **A+M** = both.

### Core messaging pipeline
| Feature | Test | Where |
|---|---|---|
| Inbound webhook → tenant resolve → reply | A+M | `test_pipeline`, `test_filtering` + manual WhatsApp |
| RAG grounded answer (no hallucination) | A+M | `test_rag`, `test_pipeline` + manual |
| Multilingual reply (Urdu / Roman Urdu) | M | Manual WhatsApp |
| Voice in (STT) → transcript | A+M | `test_voice` + manual voice note |
| Voice out (TTS) → voice note | A+M | `test_voice` + manual |
| Image → vision model (data URI) | A+M | `test_voice` (helper) + manual photo |
| Debounce (merge rapid messages) | A | `test_debounce` |
| Dedupe (ignore duplicate delivery) | A | `test_dedupe` |
| Own-send echo skip (no self-silence) | A | `test_send_gateway` |
| Implicit takeover (owner replies on phone) | A+M | `test_takeover` + manual |

### Cost & abuse controls (this cycle's headline work)
| Feature | Test | Where |
|---|---|---|
| Trial hard quota (300 msgs) | A | `test_pipeline` (quota gate) |
| Real per-model cost recording | A | `test_pipeline` (compute_cost) |
| Per-conversation rate limit (20/60s) | A | `test_debounce` (is_rate_limited) |
| Voice metering + 8 MB audio cap | A | `test_voice` |
| RAG context budget + dedup | A | `test_rag` |
| Suspended / expired-trial gate | A | `test_pipeline` |
| Send pacing + daily cap | A | `test_send_gateway` |

### Skills (agent actions)
| Feature | Test |
|---|---|
| book_appointment / check_availability | A `test_skills` + `test_integrations` (Calendar) |
| append_to_sheet / lookup_sheet | A `test_skills` + `test_integrations` (Sheets) |
| take_order / capture_lead / share_payment_details | A `test_skills` |
| human_handoff (+ notify-on-handoff mute) | A `test_skills` |

### Auth & accounts
| Feature | Test |
|---|---|
| Email+password login, JWT | A `test_auth`, `test_security` |
| Self-serve signup + trial | A `test_auth` + M (welcome email) |
| Sign in with Google (SSO) | A `test_auth`, `test_google_oauth` + M |
| Change / forgot / reset password | A (helpers) + M (email link) |
| **Team invite → accept → login** | A `test_team` + M (invite email + UI) |

### Admin / ops console
| Feature | Test |
|---|---|
| Tenant list/create/get/update/delete | A `test_admin` |
| Fleet session control (start/stop/restart/logout) | A `test_admin` + M (real WAHA) |
| Reset owner password / impersonate | A `test_admin` |
| Usage rollup, overview | A `test_admin` |
| RLS: cross-tenant access blocked | A `test_rls_postgres`, `test_admin` |

### Owner dashboard
| Feature | Test |
|---|---|
| Inbox + takeover/reply | A `test_conversations` + M |
| Knowledge CRUD + URL sources | A `test_knowledge_api` (⚠️§4) + M |
| Settings (persona/hours/voice/notify) | A (config) + M |
| Billing / trial visibility | M (UI) |
| **Onboarding checklist** | M (UI) |
| **Team management + data export** | A `test_team` + M (UI download) |

### Integrations
| Feature | Test |
|---|---|
| Google Calendar/Sheets OAuth connect | A `test_google_oauth` + M (real Google) |
| Sheets Picker select/create | A `test_integrations` + M |
| Disconnect (revoke-grant guard) | A `test_google_oauth` |

---

## 4. Known test gaps / flakes (honest list)

- **5 `test_knowledge_api.py` failures from the host.** They call `get_redis()`
  directly (default host `redis:6379`, which the host can't resolve — the host
  talks to Redis on `localhost:6380`) and expect the async ingest worker to flip a
  source from `pending_ingest` to `ready`, which needs a running worker. **Not a
  code defect.** Fixing them properly means overriding `get_redis` in the fixture
  and mocking/awaiting ingestion — a test-harness fix, tracked separately.
- **No automated end-to-end WhatsApp test.** The full "real phone → WAHA → bot →
  reply" loop is manual (§5) — WAHA + a linked number can't run in CI yet.
- **Voice minutes are estimated** from byte size, so metering assertions check
  "> 0", not exact seconds.
- **Payments / CRM sync** have no tests because they aren't built (need a provider
  decision — see FEATURES.md §4).

---

## 5. Manual end-to-end test plan

Run this after any pipeline/WAHA change. Needs the stack up (`./qonvo-up.sh`), a
linked WhatsApp number, and a provider key (Gemini for text; Groq/OpenAI for voice).

### A. Live API smoke (fast, no phone)
```bash
API=http://localhost:8000
TOKEN=$(curl -s -X POST $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"owner@dev.dev","password":"<pass>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
H="Authorization: Bearer $TOKEN"
for ep in /api/me /api/billing /api/onboarding /api/config /api/conversations \
  /api/knowledge/sources /api/sessions /api/integrations /api/analytics/summary \
  /api/notifications /api/team /api/account/export /metrics /healthz; do
  printf "%-26s %s\n" "$ep" "$(curl -s -o /dev/null -w '%{http_code}' "$API$ep" -H "$H")"
done   # expect all 200
```

### B. WhatsApp conversation (needs the phone)
1. **Text Q&A** — message a question answerable from knowledge → grounded reply.
2. **Unknown question** — ask something not in knowledge → "I'll connect you" + handoff.
3. **Language** — message in Roman Urdu → reply in Roman Urdu.
4. **Voice in/out** — send a voice note → transcript understood → (if voice mode on) voice reply.
5. **Image** — send a photo with a question → the bot references what's in it.
6. **Flood guard** — send 25+ messages fast from one chat → extra ones dropped (`rate_limited` in logs).
7. **Skill** — trigger a booking/order → row created; check Calendar/Sheet.
8. **Takeover** — reply to the customer from the owner's phone → bot goes quiet; wait for auto-resume.

### C. Dashboard (owner)
1. Sign up a new business → welcome email (logged) → **onboarding checklist** shows steps.
2. Connect WhatsApp (scan QR) → checklist "WhatsApp" ticks.
3. Add knowledge (text + URL) → appears; ask about it on WhatsApp.
4. Settings → toggle **notify-on-handoff** off → trigger a handoff → no WhatsApp/email alert, but in-app notification still appears.
5. **Team** → invite a teammate → open the emailed `/accept-invite` link → set password → land on login → sign in → they see the inbox.
6. **Team → Export data** → downloads a JSON with conversations/leads/etc.
7. Billing shows trial days left.

### D. Admin console
1. Log in as `admin@qonvo.dev` → Overview tiles populate.
2. Tenants → open one → suspend → bot goes silent on WhatsApp → reactivate.
3. Tenant → reset owner password → one-time password shown.
4. Fleet → Restart/Logout a session → status updates (logout needs a re-scan).
5. Try an `/api/admin/*` route with an owner token → 403.

---

## 6. Regression checklist before any release

- [ ] `uv run pytest -q` → 219 passed, ruff clean.
- [ ] `uv run pytest -m postgres -q` (with the two test DSNs) → 36/41 (only the 5 §4 knowledge tests fail).
- [ ] `cd dashboard && npx tsc --noEmit && npm run build` → clean.
- [ ] §5.A live API smoke → all 200.
- [ ] §5.B steps 1, 2, 6 (text, handoff, rate-limit) at minimum.
- [ ] `/metrics` and `/healthz` return 200.

_Last updated: 2026-08-16._
