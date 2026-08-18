/**
 * Rendered by components/marketing/faq.tsx and emitted as FAQPage JSON-LD from
 * this same array, so the visible text and the structured data cannot drift.
 *
 * Answers open with a direct one-sentence response before elaborating, which
 * is what makes them quotable by AI search. Keep that shape when editing.
 */
export const FAQ = [
  {
    q: "Does it use my own WhatsApp number?",
    a: "Yes. Qonvo connects to the number you already give customers, so nothing changes for them. You scan one QR code and carry on using WhatsApp on your phone as normal.",
  },
  {
    q: "Can a customer tell they are talking to AI?",
    a: "It replies in your business's voice, in whatever language the customer wrote in. You choose the persona and tone, and you can have it say plainly that it is an assistant if you prefer.",
  },
  {
    q: "What happens when it does not know something?",
    a: "It says so rather than guessing. Qonvo answers from the knowledge you give it, and when a question falls outside that it hands the conversation to you.",
  },
  {
    q: "How do I take over a conversation?",
    a: "Just reply from your phone. Qonvo notices you have stepped in and goes quiet for that chat, so you never talk over each other. You can also take over from the inbox.",
  },
  {
    q: "Which languages does it handle?",
    a: "It detects the customer's language and replies in it. English, Urdu, Roman Urdu, Arabic, Hindi, Spanish and French all work today, by text or by voice note.",
  },
  {
    q: "Can it book into my existing calendar?",
    a: "Yes, into Google Calendar. Qonvo checks when you are genuinely busy before offering a slot, so it will not double-book you, and it writes the confirmed booking straight to your calendar.",
  },
  {
    q: "Does Qonvo sync to my CRM?",
    a: "Not yet. Today Qonvo logs every lead to a Google Sheet you control, which you can import or connect to most CRMs. Direct sync is on the roadmap.",
  },
  {
    q: "What are the limits during the free trial?",
    a: "The trial runs 14 days or 300 customer messages, whichever comes first. No card is required to start.",
  },
  {
    q: "How long does setup take?",
    a: "About a day, and no code. Connect the number, paste in your hours, prices and the questions you answer most, then send it a test message.",
  },
  {
    q: "Who can see my customer conversations?",
    a: "Only you and the people you invite. Each business's data is isolated at the database level, so no other Qonvo customer can reach your conversations.",
  },
] as const;
