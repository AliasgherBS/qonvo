# Conversation lab

Drives whole conversations through the webhook ingress, **without WhatsApp and
without a person**.

Everything worth testing about the rep happens between the webhook arriving and
the reply being written: language matching, debounce, grounding, refusals,
handover, the skills. WhatsApp's only job is delivery. So the lab posts the
same signed payload WAHA posts, and reads what the pipeline did with it.

```bash
python3 scripts/conversation-lab/lab.py --list
python3 scripts/conversation-lab/lab.py --tenant dental --script grounding
python3 scripts/conversation-lab/lab.py --tenant all --script all
```

Staging only. It refuses to run against production, because it creates tenants,
writes knowledge and spends real model requests.

## Why there is a WAHA stub

The reply is written and sent inside **one transaction** -- `db.add(Message(...))`
then `_send`, which re-raises. On staging no session is linked to a real phone,
so every send fails, the transaction rolls back, and the reply is never
recorded. The first run of this lab reported "no reply within 90s" four times
for that reason and nothing else.

`waha_stub.py` answers every send endpoint with a plausible 2xx, including a
unique message `id`, which the gateway needs to fingerprint its own send -- or
the bot treats its own echo as the owner replying and takes itself over
(section 5.5).

```bash
docker run -d --name qonvo-waha-stub --network qonvo-staging_default \
  -v "$PWD/scripts/conversation-lab/waha_stub.py:/stub.py:ro" \
  python:3.12-alpine python /stub.py

QONVO_ENV_FILE=.env.staging docker compose -p qonvo-staging --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.override.yml \
  -f scripts/conversation-lab/docker-compose.lab.yml \
  up -d --no-deps worker
```

Put the worker back by bringing it up without the lab compose file, and
`docker rm -f qonvo-waha-stub`.

## Four businesses, on purpose

| | Shape | What it stresses |
|---|---|---|
| `salon` | Beauty salon | No prices, bookings are requests |
| `dental` | Dental practice | No clinical advice; one published fee it may quote |
| `clinic` | Multi-department clinic | No medical advice at all |
| `info` | Design studio, information only | No booking, no diary, no payment |

Everything had been proved on one beauty salon whose own instructions forbid
quoting a price and forbid looking at a diary. A rule that holds for that
tenant and nowhere else is not a rule the product has -- and the first full run
proved the point: the rep can only name its own trade when the business NAME
happens to contain it, because the system prompt carries the name and the trade
lives in retrieved knowledge, which an out-of-scope question retrieves none of.

## Reading a failure

Checks assert shape, not wording, because asserting prose fails the first time
the prompt improves. Three of the first seven "failures" were the checks' fault
and are worth knowing about:

* markers were counted once each rather than per occurrence, so
  "rehti hai ... jati hai" scored 1 and read as English;
* the model types a typographic apostrophe, and a check looking for `don't`
  missed `don’t` four times;
* "offer a person" did not list `dentist`, so a dental practice offering a
  dentist read as a refusal to escalate.

The full transcript of every run lands in `/tmp/conversation-lab.json`.
