# Reviews

Point-in-time reviews of the running product. Each is a snapshot: it describes what
was true on the date in the filename, not what is true now.

| Date | Document | What it covers |
|---|---|---|
| 2026-09-08 | [UI teardown](2026-09-08-ui-teardown.html) | 19 sections, ~60 findings from driving the live site: landing page, every dashboard surface, navigation and separation of concerns, a security deep read, billing redesigned against convention, tooling. Screenshots inlined. |
| 2026-09-09 | [Functional test](2026-09-09-functional-test.html) | Hands-on execution round. 95 checks planned, 68 run, with evidence from the live API, worker logs and Prometheus counters. Includes the annotated system-prompt map and an admin console review. |
| 2026-09-09 | [Test plan](2026-09-09-test-plan.md) | The 95-check list, grouped A-P. Reusable as a regression checklist. |
| 2026-09-11 | [VPS audit](2026-09-11-vps-audit.html) | First review from outside the box, after the move to a VPS. Visual and UX, an API and error-handling battery, end-to-end on production and staging, race probes, coverage accounting, and one live incident. |

Open the HTML files in a browser; they are self-contained (styles and images inlined,
nothing needed from the network beyond webfonts).

## probes/

The scripts behind the 2026-09-11 round. They take a bearer token from `/tmp` and hit
an API base defined at the top of each file, so they run against production or staging
by changing one constant. Written as one-shot probes rather than a suite, but they are
the fastest way to re-check any of these classes after a fix.

| Script | What it checks |
|---|---|
| `edge.py` | Unicode, NUL bytes, injection-shaped input, payload-size caps |
| `race.py` | Concurrent writes: config, knowledge delete, notification read |
| `authz.py` | The staff-role authorization matrix, 20 probes |
| `e2e_signup.py` | Signup, weak password, duplicate email, verification, unverified gating |
| `e2e_rest.py` | Activation, billing lifecycle, session creation, cap races |
| `pipeline.py` | Signed WAHA webhook into the ingress; HMAC, paused and rate-limit gates |
| `browser-driver.js` | Minimal CDP driver used for the UI passes (`goto`, `click`, `fill`, `upload`, `shot`, `eval`) |

`pipeline.py` reads a session HMAC secret from the staging database and posts a real
signed webhook, so it belongs on staging only.
