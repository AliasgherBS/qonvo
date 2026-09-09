"""What language *this* message is in, computed per turn (E1).

``app/agent/language.py`` is the *setting*: what the owner asked for. This
module is the *observation*: what the customer actually wrote, on this turn.
Nothing computed it before, which is the whole of the bug it exists to fix.

The live failure it comes from
------------------------------
A customer wrote English, got one English reply, then three Roman Urdu replies
in a row. One of the three answered a voice note whose transcript was flawless
English, which rules out the audio path: the prompt behaved the same way for
text and for speech.

The cause was structural rather than a bug in any one line. "Reply in the same
language the customer used" sat at position 0 of the request, roughly forty
turns and a rolling summary away from the message it governed, and both the
history and the summary were Urdu-heavy. The rule was outvoted by the evidence.

So the fix is not a better rule. It is a **fact**, placed immediately above the
customer's words: "The customer's current message is in English (Latin script).
Reply in that language and that script." A rule about "the language the
customer used" is ambiguous when forty of them are visible. A stated fact about
*this* message is not, and history cannot outvote it.

Precision over recall, deliberately
-----------------------------------
Calling English "Roman Urdu" is the bug being fixed, so a heuristic that does
it in a new way would be no better than the one it replaces. Every rule here is
therefore biased towards saying **less**:

* Roman Urdu needs two distinct markers, or one plus a postposition, or one in
  a message of three words or fewer.
* English is claimed only when English function words are actually present.
* When neither is established, only the *script* is stated, and the owner's
  ``reply_language`` setting decides the language, exactly as it does today.

Saying "this is written in Latin script" and nothing more is always safe: it is
observable from the code points, and it still fixes the visible half of the bug
(an English message coming back in Urdu script, or the reverse).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.language import MATCH, normalise_reply_language

#: Arabic script, in the ranges Urdu actually uses: Arabic, Arabic Supplement,
#: Arabic Extended-A, and the presentation forms some keyboards emit.
_ARABIC = re.compile(
    r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]"
)
#: Latin letters including the accented ranges, so "Français" is Latin script.
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

#: Letters that exist in Urdu (and Persian) but not in Arabic. Their presence
#: is what lets an Arabic-script message be named as Urdu rather than left as
#: "Arabic script"; without one of these the language is genuinely unknown and
#: is not guessed.
_URDU_LETTERS = frozenset("ٹڈڑںھہےۓگچپژکی")

#: URLs, mentions, prices and emoji tell us nothing about language and would
#: skew the letter counts, so they go before anything is counted.
_NOISE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+|[\d_]+")
_WORD = re.compile(r"[A-Za-zÀ-ɏ']+")

#: Roman Urdu markers that are **not** English words, so a hit means something.
#: Deliberately excludes every collision: "is", "us", "par", "hum", "ab", "ya",
#: "to", "in", "so", "hi", "they", "hay", "kar" and "kia" are all either English
#: words, plausible abbreviations or a car marque, and each one of them would
#: turn an English sentence into a false Roman Urdu verdict.
_ROMAN_URDU_STRONG = frozenset(
    {
        # to be / to do, the highest-frequency giveaways
        "hai", "hain", "hoga", "hogi", "honge", "hun", "hoon", "tha", "thi", "thay",
        "hogya", "hogaya", "hojaye", "hojayega", "hota", "hoti", "hote",
        # questions
        "kya", "kyaa", "kyun", "kyu", "kyon", "kaise", "kaisay", "kaisa", "kaisi",
        "kitna", "kitne", "kitni", "kahan", "kahaan", "kab", "kaunsa", "kaunsi",
        # pronouns and possessives
        "mera", "meri", "mere", "mujhe", "mujhay", "aap", "aapka", "aapki", "aapko",
        "apna", "apni", "apne", "tum", "woh", "yeh", "unka", "unki", "iska", "iski",
        # verbs
        "karna", "karni", "karne", "karo", "karain", "karein", "karwana", "karwa",
        "krna", "krdo", "kro", "krein", "sakta", "sakti", "sakte", "chahiye",
        "chahye", "chahta", "chahti", "chahte", "dena", "deni", "dedo", "batao",
        "bataen", "batayen", "milega", "milegi", "chalega", "dikhao", "raha",
        "rahi", "rahe", "lagta", "lagti", "banwana",
        # everyday adjectives, adverbs, courtesies
        "nahi", "nahin", "acha", "achha", "theek", "thik", "bilkul", "zaroori",
        "shukriya", "shukria", "assalamualaikum", "assalam", "walaikum", "matlab",
        "abhi", "sirf", "saath", "magar", "lekin", "agar", "phir", "jaldi", "zyada",
        "ziada", "thora", "thoda", "bohat", "bohot", "bahut", "buhat", "koi",
        "kuch", "kuchh", "sabhi", "pehle", "waqt", "aaj", "subah", "shaam",
        "liye", "liay", "wala", "wali", "walay", "rupay", "rupaye", "paisay",
    }
)

#: Postpositions and conjunctions. On their own they prove nothing (two letters,
#: and several are product codes), so they never establish Roman Urdu by
#: themselves. They exist only to let a single strong marker over the line,
#: which is what makes "aap ka rate" read as Roman Urdu.
_ROMAN_URDU_WEAK = frozenset({"ka", "ke", "ki", "ko", "se", "aur", "bhi", "mein", "ne"})

#: English function words. Only consulted once Roman Urdu has been ruled out,
#: so the overlaps with Roman Urdu ("do", "me", "us") cannot mislead. Content
#: words are left out on purpose: "facial", "laser" and "booking" appear in a
#: Roman Urdu sentence just as happily.
_ENGLISH_MARKERS = frozenset(
    {
        "the", "is", "are", "was", "were", "am", "be", "been", "being",
        "do", "does", "did", "don't", "doesn't",
        "i", "you", "your", "yours", "my", "mine", "me", "we", "our", "us",
        "he", "she", "it", "they", "them", "their",
        "can", "cannot", "could", "would", "should", "will", "won't", "may", "must",
        "what", "when", "where", "which", "who", "whose", "how", "why",
        "and", "or", "but", "if", "because", "than", "then",
        "for", "with", "from", "about", "into", "of", "at", "on", "in", "to",
        "have", "has", "had", "need", "needs", "want", "wants", "get", "got",
        "please", "thanks", "thank", "sorry", "hello", "there", "this", "that",
        "these", "those", "any", "some", "much", "many", "more", "also", "just",
        "tell", "give", "send", "let", "know", "like", "make", "take",
        "available", "open", "closed", "still", "already", "again",
    }
)

#: What the fact calls each script. Named rather than formatted from a code so
#: the sentence reads as English prose to the model.
LATIN = "Latin"
ARABIC = "Arabic"

#: Below this, a message is too short for markers to mean much and one strong
#: Roman Urdu marker is accepted on its own ("assalamualaikum", "kitna hai").
_SHORT_MESSAGE_WORDS = 3


@dataclass(frozen=True, slots=True)
class Detected:
    """What was observed about one inbound message.

    ``language`` is None whenever the script is legible but the language is
    not established. That is a real and common answer, not a failure: a bare
    "ok thanks" is Latin script and could be either language, and the honest
    move is to say Latin and let the setting decide.
    """

    script: str | None = None
    language: str | None = None

    @property
    def known(self) -> bool:
        return self.script is not None


def _words(text: str) -> list[str]:
    return _WORD.findall(_NOISE.sub(" ", text).lower())


def _roman_urdu(words: list[str]) -> bool:
    """Whether these Latin-script words are Roman Urdu. High bar on purpose."""
    strong = {w for w in words if w in _ROMAN_URDU_STRONG}
    if len(strong) >= 2:
        return True
    if not strong:
        return False
    weak = {w for w in words if w in _ROMAN_URDU_WEAK}
    return bool(weak) or len(words) <= _SHORT_MESSAGE_WORDS


def detect(text: str) -> Detected:
    """Script and, where it is genuinely established, language.

    Cheap and deterministic: two regex counts and two set lookups, no model
    call. It runs on every turn, so it has to cost nothing, and it has to give
    the same answer twice for the same message or the reply language would
    wobble for reasons no one could explain.
    """
    if not text or not text.strip():
        return Detected()
    stripped = _NOISE.sub(" ", text)
    arabic = len(_ARABIC.findall(stripped))
    latin = len(_LATIN.findall(stripped))
    if arabic == 0 and latin == 0:
        # Emoji, digits, a URL on its own. Nothing to say, so nothing is said.
        return Detected()
    if arabic > latin:
        # Urdu-specific letters distinguish Urdu from Arabic. Without one, the
        # script is all we know, and claiming "Urdu" for an Arabic message
        # would be the same kind of mistake in the other direction.
        if _URDU_LETTERS.intersection(stripped):
            return Detected(script=ARABIC, language="Urdu")
        return Detected(script=ARABIC)
    words = _words(text)
    if _roman_urdu(words):
        # Named as "Roman Urdu" rather than "Urdu": the script half of the
        # instruction is the half that was failing, and "Urdu" would invite a
        # reply in Urdu script.
        return Detected(script=LATIN, language="Roman Urdu")
    if any(w in _ENGLISH_MARKERS for w in words):
        return Detected(script=LATIN, language="English")
    return Detected(script=LATIN)


def language_fact(text: str, *, reply_language: str | None = None) -> str | None:
    """The sentence to place immediately above the customer's message, or None.

    Two cases return None, and both matter.

    A tenant who pinned a language ("always English", "always Roman Urdu") has
    already been told so unconditionally in the system prompt. Adding an
    observation about the inbound message there would hand the model two
    instructions and a choice, which is how this class of bug starts.

    And a message with no legible letters at all (an emoji, a photo caption of
    digits) supports no claim, so none is made.
    """
    if normalise_reply_language(reply_language) != MATCH:
        return None
    detected = detect(text)
    if not detected.known:
        return None
    if detected.language:
        return (
            f"The customer's current message is in {detected.language} "
            f"({detected.script} script). Reply in that language and that script."
        )
    return (
        f"The customer's current message is written in {detected.script} script. "
        "Reply in that same script."
    )


__all__ = ["ARABIC", "LATIN", "Detected", "detect", "language_fact"]
