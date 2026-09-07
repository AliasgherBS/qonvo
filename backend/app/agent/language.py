"""Which language the rep replies in — a setting, not a hope.

Voice already worked this way: a validated mode the owner picks. Language was
governed only by prose in ``custom_instructions``, so it drifted; an Urdu-script
question came back in Roman Urdu.

Three choices, deliberately:

* ``match``  — mirror the customer, including the script
* ``en``     — always English, the common explicit choice
* anything else — a language the owner types

The third is open on purpose. Which languages are available is a property of
the model in use, not of Qonvo, so shipping a fixed list would be us guessing
on the model's behalf and going stale every time it improves.

Being able to type it also solves the script problem better than a menu could:
"Roman Urdu" and "Urdu script" are both just things you can write, and the
model understands them. A menu would have to enumerate every script of every
language to say the same thing.
"""

from __future__ import annotations

import re

MATCH = "match"
ENGLISH = "en"

#: Free text reaches the system prompt, so it is kept to something that is
#: plausibly a language name. The owner can already write arbitrary instructions
#: in custom_instructions, so this is not a defence against them -- it is about
#: keeping the setting coherent: a sentence pasted here would read as
#: "Always reply in do as I say not as I do" and behave unpredictably.
MAX_LANGUAGE_LENGTH = 40
#: Language names are short. "Chinese (Simplified)", "Brazilian Portuguese" and
#: "Urdu (Urdu script)" all fit; a sentence does not.
MAX_LANGUAGE_WORDS = 3

_ALLOWED = re.compile(r"^[A-Za-zÀ-ɏ؀-ۿ\s()'\-/,.]+$")

MATCH_INSTRUCTION = (
    "Reply in the same language AND the same script the customer used. If they "
    "write Urdu in Roman/Latin letters, reply in Roman/Latin letters too; if "
    "they write in Urdu script, reply in Urdu script."
)


def sanitise_language(value: str | None) -> str | None:
    """A safe, single-line language name, or None if it is not usable.

    Collapses whitespace, then requires something that is plausibly a language
    name: single line, at most a few words, no punctuation beyond what names
    actually use. "Roman Urdu" passes; a sentence does not, because it would be
    spliced into the prompt as "Always reply in <sentence>" and behave
    unpredictably.
    """
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.replace("\n", " ").replace("\r", " ")).strip()
    if not cleaned or len(cleaned) > MAX_LANGUAGE_LENGTH:
        return None
    if len(cleaned.split(" ")) > MAX_LANGUAGE_WORDS:
        return None
    if not _ALLOWED.match(cleaned):
        return None
    return cleaned


def normalise_reply_language(value: str | None) -> str:
    """``match``, ``en``, or a sanitised language name. Falls back to ``match``.

    Falling back rather than raising matters: a value stored by an older build,
    or one that no longer passes sanitising, must not break every reply for
    that tenant.
    """
    if value in (MATCH, ENGLISH):
        return value
    return sanitise_language(value) or MATCH


def language_instruction(value: str | None) -> str:
    """The sentence handed to the model for this setting."""
    mode = normalise_reply_language(value)
    if mode == MATCH:
        return MATCH_INSTRUCTION
    if mode == ENGLISH:
        return "Always reply in English, regardless of what the customer writes."
    return f"Always reply in {mode}, regardless of what the customer writes."


def is_valid(value: str | None) -> bool:
    """Whether the API should accept this value."""
    return value in (MATCH, ENGLISH) or sanitise_language(value) is not None


__all__ = [
    "ENGLISH",
    "MATCH",
    "MATCH_INSTRUCTION",
    "MAX_LANGUAGE_LENGTH",
    "MAX_LANGUAGE_WORDS",
    "is_valid",
    "language_instruction",
    "normalise_reply_language",
    "sanitise_language",
]
