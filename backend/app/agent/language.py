"""Which language the rep replies in — a setting, not a hope.

Voice already worked this way: a validated mode the owner picks. Language was
governed only by prose in ``custom_instructions``, so it drifted; an Urdu-script
question came back in Roman Urdu.

The property that matters is that this is **script-aware**. Urdu and Roman Urdu
are one language written two ways, and a model told "reply in Urdu" will pick
the Arabic script every time. So they are separate options, and ``match`` is
explicit that the script is part of what gets mirrored.
"""

from __future__ import annotations

from dataclasses import dataclass

MATCH = "match"


@dataclass(frozen=True, slots=True)
class ReplyLanguage:
    code: str
    label: str
    #: Told to the model verbatim. Written to be unambiguous about script.
    instruction: str


#: The order here is the order the dashboard renders. Match first because it is
#: the default and the right answer for most businesses; English next because it
#: is the common explicit choice; then the regional languages this product is
#: built for, with each script an option in its own right.
SUPPORTED_REPLY_LANGUAGES: tuple[ReplyLanguage, ...] = (
    ReplyLanguage(
        MATCH,
        "Match the customer",
        "Reply in the same language AND the same script the customer used. If "
        "they write Urdu in Roman/Latin letters, reply in Roman/Latin letters "
        "too; if they write in Urdu script, reply in Urdu script.",
    ),
    ReplyLanguage(
        "en", "English", "Always reply in English, regardless of what the customer writes."
    ),
    ReplyLanguage(
        "ur",
        "Urdu (Urdu script)",
        "Always reply in Urdu written in Urdu (Arabic) script, regardless of "
        "what the customer writes.",
    ),
    ReplyLanguage(
        "ur-Latn",
        "Roman Urdu",
        "Always reply in Urdu written in Roman/Latin letters (Roman Urdu), not "
        "Urdu script, regardless of what the customer writes.",
    ),
    ReplyLanguage(
        "pa",
        "Punjabi (Shahmukhi script)",
        "Always reply in Punjabi written in Shahmukhi script, regardless of "
        "what the customer writes.",
    ),
    ReplyLanguage(
        "pa-Latn",
        "Roman Punjabi",
        "Always reply in Punjabi written in Roman/Latin letters, regardless of "
        "what the customer writes.",
    ),
    ReplyLanguage(
        "sd", "Sindhi", "Always reply in Sindhi, regardless of what the customer writes."
    ),
    ReplyLanguage(
        "ar", "Arabic", "Always reply in Arabic, regardless of what the customer writes."
    ),
)

_BY_CODE = {lang.code: lang for lang in SUPPORTED_REPLY_LANGUAGES}


def normalise_reply_language(code: str | None) -> str:
    """A known code, or ``match``.

    Falls back rather than raising: a stale value left by an older build must
    not break every reply for that tenant.
    """
    return code if code in _BY_CODE else MATCH


def language_instruction(code: str | None) -> str:
    """The sentence handed to the model for this setting."""
    return _BY_CODE[normalise_reply_language(code)].instruction


def is_supported(code: str | None) -> bool:
    return code in _BY_CODE


__all__ = [
    "MATCH",
    "SUPPORTED_REPLY_LANGUAGES",
    "ReplyLanguage",
    "is_supported",
    "language_instruction",
    "normalise_reply_language",
]
