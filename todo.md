1) revamp UI, good landing page with a short video some we already have the rest using remotion or other skills a suage of our app

2) improve signup process via either SSO from google etc or maybe via a email thrown from us, onboarding sharing password, like the usual route, and onboarding/welcome email

3) fix the calendar/sheets integration, see how that can happen in better way, also more agentic actions capability

4) test ingestion thoroughly, for docs, csv, structured/unstructured data throw everything and then check for robustness

5) test for load, liek incase of concurrent sessions, users, etc, different type of testing, load, stress, smoke, etc.

~~6) how this zrok thing is handled and learn, setup automated deployment and make tmux is working automatically to live our service, maybe convert backend to docker too, so we only have to handle the zrok side~~

7) explore mcp provision, is it possible easily or not

8) does waha overall supports whatsapp forms/polls etc etc, proper message templates
8.1) look into the provision of running campaigns, messaging a list of person or send messages/replies in particular manner

9) create an offering for personal use to, meaning sending timely/scheduled message to yourself or in a dedicated group for update or any actions that were configured and think more about how to serve individuals better as a better knowledge source, like create a spinoff as our personal intelligence helping manage anything sent to itself creating a catalouge of it thats managed.

10) finish the ops hardeing part as was emtnioned last.

11) BYOM or BYOK conecept should be introduced helping them manage their own voices,transcription services, etc, more transparent in some cases or use ours which maybe less costly

12) work on costing, first calculate recurring cost as operational one, monitoring and observability adding too to find the logs more better and insigts developer deeper good info

13) look into domain, hosting (in terms of AI), uplift.ai for urdu and regional language (for cool paki demo)

14) 


-----------------------------------------------------------------------------------------------------------------------------------



1) to verify that errors are handled gracefully from waha being unavaialble or any other service disruption, bot should be paused with an email sent or something of sorts making sure no destructive thing is happended, specially check for cases till when waha stays connected, if recoonect is needed, it should prompt the user for it, also if connection dies how should admin handle it, the pause, start, restart buttons, etc, like check every possible common possible cases we can think of, test it and make sure our sys is robust in that sense.

2) a contnious learning approach, a harness maybe to learn with mistakes overtime, so we can market thsi angle too, that it evolves overtime
2.1) knowledge gaps can be resolved by providing option to answer those question then and there so they are added as info into the knowledge so it can be referenced next time

3) 

3) 2FA backup codes for the admin account. Deferred deliberately on 2026-09-11, not
forgotten. Today the only recovery from a lost authenticator is SSH into the VPS and
`UPDATE users SET totp_enabled = false, totp_secret = NULL WHERE email = 'admin@qonvo.org'`
-- /auth/totp/disable itself requires a valid code, so the product has no way back in.
Interim mitigation: keep the TOTP secret in a password manager, so a lost phone is a
re-scan rather than a lockout.
When built: 8 single-use codes, randomly generated, shown once at enrolment, stored
hashed like passwords. NOT a memorable value -- a backup code bypasses 2FA entirely on
the account that can impersonate every customer, so anything guessable (a birth date,
a phone number) makes the second factor decorative.

4) The admin account is admin@qonvo.org as of 2026-09-11 (was admin@qonvo.dev).
seed_dev.py still creates admin@qonvo.dev, which is correct: that is the dev/staging
identity, and production's is not seeded.


5) Annual and half-yearly pricing. Deferred deliberately on 2026-09-12 with the plan
written up in docs/ANNUAL-AND-HALF-YEARLY-BILLING.md -- prerequisites, sandbox checklist,
discount ladder and the arithmetic behind it.
The one thing that must not be done in the meantime: do NOT add a second Polar product
for an existing plan to QONVO_BILLING_PRICE_MAP. _price_id_for() returns the FIRST price
mapping to a plan key, so an annual Growth product could make a customer clicking "$20 a
month" pay $204 a year, silently and with nothing in the logs. The cadence-aware lookup
in §3.3 of that doc is the blocking prerequisite.
Verified while writing it: Polar can express half-yearly (recurring_interval "month" with
recurring_interval_count 6), entitlements and quota accounting need no change at all
(quotas reset on the calendar month, not the billing period), and proration_behavior
"next_period" is how a cadence switch avoids an unquotable charge -- Polar has no
proration preview route.
