# Qonvo — Privacy Policy

**Effective date:** _[fill in on launch]_
**Provider:** _[Legal entity name — to be filled once formalized]_ ("Qonvo", "we", "us")

> ⚠️ **Starter template — not legal advice.** Drafted from the product's actual
> data flows. Have a qualified lawyer review and adapt it (especially entity
> details and jurisdiction) before you rely on it publicly.

---

## 1. Who this covers

- **Business owners** — the people who sign up for Qonvo to run an AI rep on
  their WhatsApp number ("Customers").
- **End customers** — the people who message a Customer's WhatsApp number and
  whose messages our AI answers ("End Users").

**Roles.** For End-User conversation data, the **business owner is the data
controller** (it's their customer relationship) and **Qonvo is the data
processor** acting on their instructions. For business-owner account data, Qonvo
is the controller.

## 2. What we collect

- **Account data:** business name, owner name, email, hashed password, settings
  (persona, hours, language, payment details you choose to store).
- **WhatsApp conversation data:** inbound/outbound message content, voice-note
  transcripts, language, timestamps, and the End User's WhatsApp identifier —
  processed so the AI can reply and so the owner can see the inbox.
- **Business records the AI creates:** leads, orders, bookings, handoffs.
- **Usage/technical data:** message counts, token/cost metering, session status,
  and standard server logs.

We do **not** ask End Users for card numbers or store payment-card data.

## 3. How we use it

- To operate the service: receive messages, generate grounded AI replies (text
  and voice), take actions (bookings/orders/leads), and show the owner's inbox
  and analytics.
- To meter usage for billing.
- To maintain security, debug, and prevent abuse.

We do **not** sell personal data, and we do **not** use conversation content to
train our own models.

## 4. Third-party sub-processors

To deliver the service we send relevant data to:

| Provider | Purpose | Data shared |
|---|---|---|
| WhatsApp gateway (WAHA, self-hosted) | Send/receive WhatsApp messages | message content, WhatsApp IDs |
| Google (Gemini) | LLM replies + embeddings | message text, business knowledge |
| Groq | Voice transcription (STT) / optional TTS | audio, transcripts |
| OpenAI _(if enabled)_ | Optional voice (TTS) | reply text |
| Google Calendar / Sheets _(if the owner connects them)_ | Bookings / logging | booking + row data |
| Hosting/infrastructure provider | Run the platform | all of the above at rest |

Each processes data only to provide its function.

## 5. Retention

**Conversation data (messages, transcripts) is retained on a rolling 90-day
basis and automatically deleted after 90 days.** Account data and business
records (leads/orders/bookings) are kept while the account is active. On account
closure we delete or anonymize personal data within a reasonable period, except
where law requires retention.

## 6. Your choices & rights

- **Business owners** can edit account data in Settings and request account
  deletion.
- **End Users** exercise their rights (access, correction, deletion) through the
  **business they messaged**, who is the controller; we assist that business as
  their processor.
- Requests to us: _[contact email]_.

## 7. Security

Tenant data is isolated at the database level (row-level security so one
business can never see another's), secrets are encrypted, passwords are hashed
(argon2), and webhooks are signed. No system is perfectly secure, but we take
reasonable technical measures.

## 8. International note

The service is operated from Pakistan; sub-processors above may process data
outside Pakistan. By using Qonvo you consent to this processing.

## 9. Changes & contact

We may update this policy; material changes will be notified in-product.
Questions: _[contact email]_.
