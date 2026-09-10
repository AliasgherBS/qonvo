"""Does this turn actually ask the knowledge base anything? (F9)

A knowledge gap is logged whenever retrieval comes back empty, and the top
entry in the owner's report was ``Hi``, twice, above a real refund complaint.
The analytics tile then advertised it under "Answer these in Knowledge", so the
most valuable feedback loop in the product was telling a salon owner to write a
knowledge article about hello.

"Hi" retrieves nothing because there is nothing to retrieve, not because the
knowledge is missing. So the gate is intent, not retrieval: a greeting, a thank
you, a goodbye or a bare acknowledgement is not a question that failed.

Kept deliberately narrow. Only a *short* message made up *entirely* of these
words is discarded; "hi, do you do laser?" has informational intent and is
logged as before. The cost of being wrong in one direction is a polluted
report, and in the other a lost signal, so anything with a single unrecognised
word is treated as a real question.
"""

from __future__ import annotations

import re

#: Greetings, thanks, farewells and acknowledgements, in the three forms this
#: product actually sees: English, Roman Urdu, Urdu script.
_PLEASANTRIES = frozenset(
    {
        # English greetings and openers
        "hi", "hii", "hiii", "hey", "heya", "hello", "helo", "hallo", "yo",
        "good", "morning", "afternoon", "evening", "night", "day",
        # thanks
        "thanks", "thank", "thankyou", "thanx", "thx", "ty", "tysm", "cheers",
        "appreciate", "appreciated",
        # Only ever load-bearing next to one of the above: "thank you", "see
        # you", "thanks so much". Any real question carries a word that is not
        # in this set, which is what keeps "how much is a facial" a question.
        "you", "u", "so", "much", "very", "well",
        # farewells
        "bye", "byee", "goodbye", "later", "see", "ya", "take", "care",
        # acknowledgements
        "ok", "okay", "okey", "oki", "k", "kk", "sure", "great", "cool", "nice",
        "perfect", "noted", "got", "it", "alright", "right", "fine", "yes",
        "yeah", "yep", "no", "nope", "welcome",
        # Roman Urdu
        "salam", "salaam", "assalam", "assalamualaikum", "asalamualaikum",
        "walaikum", "walaikumsalam", "wasalam", "aoa", "adab",
        "shukriya", "shukria", "shukriyah", "jazakallah", "mehrbani",
        "acha", "achha", "theek", "thik", "thanda", "jee", "ji", "haan", "han",
        "khuda", "hafiz", "allah", "inshallah", "mashallah",
        # Urdu script
        "سلام", "السلام", "علیکم", "اسلام", "وعلیکم", "شکریہ", "مہربانی",
        "جی", "ہاں", "اچھا", "ٹھیک", "خدا", "حافظ", "اللہ", "انشاءاللہ",
        # Small talk. "Hello how are you doing?" reached the owner's report as
        # a knowledge gap on 2026-09-10, which is the same failure as "Hi" in a
        # longer coat: it asks the business nothing, so the knowledge did not
        # fail to answer it.
        #
        # These are common words, and adding them looks riskier than it is: a
        # message is only discarded when EVERY word is in this set, so a real
        # question survives on the strength of its own vocabulary. "how much is
        # a facial" keeps facial, "are you open on Sunday" keeps open and
        # Sunday, "what are your opening hours" keeps opening and hours.
        "how", "hows", "are", "is", "am", "doing", "going", "what", "whats",
        "up", "sup", "wassup", "there", "hope", "today", "everything",
        "kaise", "kaisay", "kya", "haal", "kesa", "kesi", "ho", "hai", "hain", "aap", "tum",
        "کیسے", "کیا", "حال", "کیسا",
    }
)

#: Words, in either script. Punctuation and emoji are dropped, so "Hi!! 👋"
#: is one word.
_WORD = re.compile(r"[0-9A-Za-zÀ-ɏ؀-ۿ']+")

#: A pleasantry is short. Past this many words it is a message that happens to
#: open politely, and whatever else it contains deserves to be counted.
_MAX_PLEASANTRY_WORDS = 6


def has_informational_intent(text: str) -> bool:
    """Whether this turn asked the business something.

    False only for a short message made entirely of pleasantries, or one with
    no words at all (an emoji, a sticker caption). Everything else is True,
    including anything this function does not recognise: an unknown word is far
    more likely to be a real question than a greeting in a language the set
    does not list yet.
    """
    words = _WORD.findall((text or "").lower())
    if not words:
        # An emoji or a bare "?" retrieved nothing because it asked nothing.
        return False
    if len(words) > _MAX_PLEASANTRY_WORDS:
        return True
    return not all(word in _PLEASANTRIES for word in words)


__all__ = ["has_informational_intent"]
