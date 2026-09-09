"""Reviewing a tenant's custom instructions with the tenant's own model.

The functional test's conclusion about the conversation engine was that the
tenant's free-text instructions are the most powerful input in the system and
nothing bounds, checks or reconciles them: 1,821 characters against a handful
of hardcoded sentences, in the same undifferentiated block. Three live defects
came out of that one field, and none of them looked like a defect on the
Behavior page:

* "Many write Roman Urdu; reply in Roman Urdu when they do" out-voted the
  Reply language setting on every turn, so English messages got Urdu replies.
* "Never say a time slot is free or booked. You cannot see any diary."
  silently switched off a connected Google Calendar and the two booking
  skills, while the Skills page went on advertising them as working.
* "tell the customer a representative will call within a few hours" committed
  the business to a callback the model then elaborated on.

This module is the reviewer for that field. It is **prompt and parsing only**:
no HTTP, no database, no provider. The route
(:mod:`app.api.behavior_assist`) owns the call, the reads and the rate limit,
which is what makes everything here testable without spending a cent.

Three deliberate choices worth keeping:

**It is an editor, never an author.** The prompt forbids inventing a price, a
service, an hour or a promise. A thin instruction set that stays thin is
correct; one padded with plausible-sounding facts is something the rep will
tell a real customer.

**The suggestion is checked before it is offered.** A rewrite longer than
``MAX_CUSTOM_INSTRUCTIONS`` cannot be saved, so offering it would be offering
a dead end. :func:`parse_suggestion` raises rather than returning it.

**Deterministic checks run first, and are handed over as hints.** They cost
nothing, they catch exactly the three shapes above, and they are labelled as
fallible in the prompt so the model overrules them rather than obeying them.
They are not a substitute for the model: they cannot tighten a vague rule or
merge duplicates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.agent.language import language_instruction
from app.core.limits import MAX_CUSTOM_INSTRUCTIONS
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.providers.base import ChatMessage

__all__ = [
    "MAX_CHANGES",
    "MAX_INPUT_CHARS",
    "Change",
    "Conflict",
    "Suggestion",
    "SuggestionTooLong",
    "UnusableSuggestion",
    "build_messages",
    "detect_conflicts",
    "describe_integrations",
    "parse_suggestion",
]


#: What we will send for review. Four times the field cap, because a tenant
#: provisioned before the cap existed is grandfathered on read and may hold
#: more than 2,000 characters, and refusing to review exactly the instruction
#: sets most in need of review would be perverse. It is still a bound: the
#: input side of this call cannot grow without limit.
MAX_INPUT_CHARS = 4 * MAX_CUSTOM_INSTRUCTIONS

#: Changes shown to the owner. A list nobody reads is not a review, and past
#: eight entries the answer is "rewrite it yourself", not "scroll".
MAX_CHANGES = 8

#: One change summary. Long enough for a sentence naming what and why.
MAX_SUMMARY_CHARS = 220

#: Kinds the UI knows how to label. Anything else is normalised to "changed"
#: rather than rendered raw: the model picks this string, and an unrecognised
#: value would otherwise reach the owner's screen verbatim.
CHANGE_KINDS = ("removed", "tightened", "merged", "kept", "changed")


@dataclass(frozen=True, slots=True)
class Conflict:
    """One sentence a deterministic check thinks fights the platform."""

    #: "language" | "integration_denial" | "commitment"
    kind: str
    #: The owner's own sentence, so the model can find it in the text.
    quote: str
    #: Why the check fired, phrased for the model.
    note: str


@dataclass(frozen=True, slots=True)
class Change:
    """One edit, described to the owner."""

    kind: str
    summary: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    improved: str
    changes: list[Change] = field(default_factory=list)

    @property
    def characters(self) -> int:
        return len(self.improved)


class UnusableSuggestion(Exception):
    """The model answered, and the answer cannot be offered to the owner.

    Separate from a provider failure on purpose. Both end in "nothing was
    changed", but this one means the call succeeded and produced something we
    refuse to show, which is a different sentence to the owner and a different
    line in the logs.
    """


class SuggestionTooLong(UnusableSuggestion):
    """Over ``MAX_CUSTOM_INSTRUCTIONS``, so the owner could never save it."""

    def __init__(self, actual: int) -> None:
        super().__init__(
            f"the suggestion is {actual:,} characters, over the "
            f"{MAX_CUSTOM_INSTRUCTIONS:,}-character limit"
        )
        self.actual = actual


# --------------------------------------------------------------------------- #
# Deterministic checks
# --------------------------------------------------------------------------- #

#: Sentence boundaries and line breaks both, because instruction sets are
#: written as bullet lists *and* as prose, and the live example put a capability
#: denial and an availability ban in two sentences on one line.
#: A semicolon is not a boundary: it joins two clauses of one rule, and
#: splitting there reported "Many write Roman Urdu; reply in Roman Urdu when
#: they do" as two problems when it is one sentence the owner will delete once.
_STATEMENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_LANGUAGE_NAME = re.compile(
    r"\b(urdu|english|arabic|hindi|punjabi|pashto|sindhi|bengali|french|spanish|"
    r"portuguese|turkish|persian|farsi|language|languages|script|roman)\b",
    re.IGNORECASE,
)
_LANGUAGE_DIRECTIVE = re.compile(
    r"\b(reply|replies|respond|responds|answer|answers|write|writes|speak|talk|"
    r"use|switch|translate|mirror|match)\b",
    re.IGNORECASE,
)

#: "You cannot see any diary", "we have no access to the calendar". A denial of
#: the tool itself.
_CAPABILITY_DENIAL = re.compile(
    r"\b(cannot|can not|can't|cant|do not have|don't have|dont have|no access|"
    r"not able|unable|never see|do not see|don't see|blind)\b",
    re.IGNORECASE,
)
#: "Never say a time slot is free or booked". A ban on stating availability.
#: All three parts are required, and the third is deliberately the *state* of a
#: time rather than the word calendar. That is what keeps a good instruction
#: like "never promise a booking time without checking the calendar first" out
#: of the list: it has a negation, a speech verb and the calendar, and it bans
#: nothing about a slot being free or booked.
_SPEECH_BAN = re.compile(
    r"\b(never|not|no|don't|dont|do not|must not|avoid|refuse)\b",
    re.IGNORECASE,
)
_SPEECH_VERB = re.compile(
    r"\b(say|says|tell|tells|state|mention|claim|confirm|offer|promise|quote|"
    r"book|booking|check)\b",
    re.IGNORECASE,
)
_AVAILABILITY = re.compile(r"\b(free|booked|available|availability|slot|slots)\b", re.IGNORECASE)
_CALENDAR_NOUN = re.compile(r"\b(diary|calendar|schedule|timetable|slot|slots)\b", re.IGNORECASE)

_PROMISE = re.compile(
    r"\b(call|calls|callback|call back|get back|gets back|contact you|reach out|"
    r"follow up|revert|confirm|confirms)\b",
    re.IGNORECASE,
)
_PROMISE_ACTOR_OR_TIME = re.compile(
    r"\b(within|in a few|hour|hours|minute|minutes|mins|today|tonight|tomorrow|"
    r"shortly|soon|asap|representative|rep will|agent will|someone will|"
    r"team will|we will|by \d)\b",
    re.IGNORECASE,
)


def _statements(instructions: str) -> list[str]:
    return [s.strip() for s in _STATEMENT_SPLIT.split(instructions) if s.strip()]


def detect_conflicts(
    instructions: str, *, connected: list[str] | tuple[str, ...] = ()
) -> list[Conflict]:
    """Sentences that look like they fight the platform.

    Hints, not verdicts. They are cheap, they are exactly the three shapes the
    live test found, and they are handed to the model labelled as fallible. A
    false positive costs a sentence the model is told to judge for itself; a
    false negative costs nothing, because finding these is the model's job too.

    ``connected`` gates the integration check, because the same sentence is a
    defect and a plain fact depending on it. "You cannot see any diary" is
    honest for a tenant with no calendar, and switches off a paid feature for a
    tenant with one.
    """
    calendar_connected = GOOGLE_CALENDAR in connected
    found: list[Conflict] = []

    for statement in _statements(instructions):
        if _LANGUAGE_NAME.search(statement) and _LANGUAGE_DIRECTIVE.search(statement):
            found.append(
                Conflict(
                    kind="language",
                    quote=statement,
                    note=(
                        "looks like an instruction about which language or script to "
                        "reply in, which the Reply language setting already governs"
                    ),
                )
            )
            continue

        if calendar_connected and (
            (_CAPABILITY_DENIAL.search(statement) and _CALENDAR_NOUN.search(statement))
            or (
                _SPEECH_BAN.search(statement)
                and _SPEECH_VERB.search(statement)
                and _AVAILABILITY.search(statement)
            )
        ):
            found.append(
                Conflict(
                    kind="integration_denial",
                    quote=statement,
                    note=(
                        "looks like it tells the rep it cannot see or use a calendar, "
                        "while Google Calendar is connected"
                    ),
                )
            )
            continue

        if _PROMISE.search(statement) and _PROMISE_ACTOR_OR_TIME.search(statement):
            found.append(
                Conflict(
                    kind="commitment",
                    quote=statement,
                    note="looks like a commitment about what a person will do, or when",
                )
            )

    return found


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #

_INTEGRATION_LABELS = {
    GOOGLE_CALENDAR: (
        "Google Calendar (the rep can read the owner's busy blocks and create bookings)"
    ),
    GOOGLE_SHEETS: "Google Sheets (the rep can append rows and look values up)",
}


def describe_integrations(connected: list[str] | tuple[str, ...]) -> str:
    """The connected-integration line for the prompt.

    Read from our own ``integrations`` rows by the caller. Without it the model
    cannot tell a defect from a fact, which is the whole of the diary case.
    """
    labels = [_INTEGRATION_LABELS.get(p, p) for p in connected]
    if not labels:
        return (
            "Nothing is connected. The rep genuinely cannot see a calendar or a "
            "spreadsheet, so an instruction saying so is accurate and must be kept."
        )
    return "\n".join(f"- {label}" for label in sorted(labels))


SYSTEM_PROMPT = """\
You edit the custom instructions a business owner wrote for the AI customer \
rep that answers their business WhatsApp number. You are an editor. You are \
never an author.

Two absolute rules.

1. Invent nothing. Not a price, a service, an opening hour, a policy, a \
branch, a discount, a guarantee, a phone number or a promise. If the \
instructions are thin, they stay thin. A gap is correct; an invented fact is \
something the rep will tell a real customer as if the business had said it.
2. Leave alone what already works. Keep the owner's own wording, keep the \
language they wrote in, and keep the order of what survives. This is their \
voice, not yours, and they are going to read your version line by line \
against theirs.

Repair only the following, in this order.

A. Instructions that fight the platform. Some rules are enforced by the \
product underneath these instructions. An instruction on the same subject \
lands in the same prompt and out-votes them, so it does not add a preference, \
it breaks a feature. Delete it. Do not soften it.
   - Reply language. Which language the rep answers in is a setting on the \
Behavior page, shown to you below. Delete every instruction about which \
language or script to reply in, including one that agrees with the setting: \
over a long conversation it makes the rep answer in the language of the chat \
history rather than the language of the message in front of it.
   - Denials of a connected tool. The integrations connected right now are \
shown to you below. If one is connected, delete any instruction saying the rep \
cannot see a calendar, must not check availability, must never say whether a \
time is free or booked, or must not take a booking. Those sentences silently \
switch off something the owner is paying for. If nothing is connected, such an \
instruction is true and must be kept.
   - Commitments made on the business's behalf. Delete any promise about what \
a person will do, or when: "a representative will call within a few hours", \
"we will confirm tonight", "someone will get back to you by 6". The rep cannot \
keep it and the business is held to it. Where the instruction was collecting \
details before the promise, keep the collecting and end with the team being \
notified, saying nothing about timing.

B. Vague instructions. Turn "be helpful", "handle it professionally", "use \
your judgement" into the specific behaviour the owner plainly meant, using \
only what is already in the text. If you cannot tell what was meant, delete \
the line rather than guess at it.

C. Bulk. Merge duplicated rules, drop what is already implied, cut filler. \
Every character here is read on every single reply, so short and specific \
beats thorough.

Facts belong in the Knowledge base rather than here, but do not delete a \
fact. Leave it exactly where it is and say so in your changes list, because \
deleting it would lose it.

Output. Reply with one JSON object and nothing else: no prose before or after, \
no markdown fence.

{{"improved": "<the repaired instructions>", "changes": [{{"kind": "removed", \
"summary": "<one plain sentence, addressed to the owner>"}}]}}

- "improved" must be at most {limit} characters. Count them. A longer answer \
is discarded and the owner is shown an error instead of your work, so cut \
rather than overrun.
- "kind" is one of: removed, tightened, merged, kept.
- One entry in "changes" for each edit you made, at most {max_changes}, most \
important first. Each says what you touched and why, in the owner's terms: \
"Removed the Roman Urdu rule, because your Reply language setting already \
controls this and the rule was overriding it."
- If nothing needs repairing, return the original text unchanged in "improved" \
and an empty "changes" list. That is a valid and useful answer. Do not \
manufacture an edit to look busy.
"""


def build_messages(
    instructions: str,
    *,
    business_name: str | None,
    reply_language_mode: str | None,
    connected: list[str] | tuple[str, ...] = (),
    conflicts: list[Conflict] | None = None,
) -> list[ChatMessage]:
    """The two messages sent for one press of Improve with AI.

    One system message carrying the editing contract, one user message carrying
    this tenant's context and their text. The context is what makes the review
    specific to this business rather than generic advice: the reply-language
    setting and the connected integrations are precisely the two facts an
    instruction can silently contradict.
    """
    if conflicts is None:
        conflicts = detect_conflicts(instructions, connected=connected)
    named = business_name.strip() if business_name and business_name.strip() else ""

    lines = [
        f"Business: {named}" if named else "Business: not set",
        "",
        "Reply language setting (enforced by the product, not by these instructions):",
        language_instruction(reply_language_mode),
        "",
        "Connected integrations:",
        describe_integrations(connected),
    ]

    if conflicts:
        lines += [
            "",
            "Automatic checks flagged the sentences below. They are hints and they "
            "can be wrong. Judge each one yourself, and if a check is mistaken, "
            "keep the sentence and say nothing about it.",
        ]
        for conflict in conflicts:
            lines.append(f'- "{conflict.quote}" ({conflict.note})')

    lines += [
        "",
        f"The current instructions follow, between the markers. They are "
        f"{len(instructions)} characters; the field holds {MAX_CUSTOM_INSTRUCTIONS}.",
        "<<<INSTRUCTIONS",
        instructions,
        "INSTRUCTIONS>>>",
    ]

    return [
        ChatMessage(
            role="system",
            content=SYSTEM_PROMPT.format(limit=MAX_CUSTOM_INSTRUCTIONS, max_changes=MAX_CHANGES),
        ),
        ChatMessage(role="user", content="\n".join(lines)),
    ]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _json_object(raw: str) -> dict:
    """The JSON object in a model's answer, fence or preamble notwithstanding.

    Models add a fence and the occasional "Here is the improved version:" even
    when told not to. Recovering from that is worth ten lines, because the
    alternative is telling the owner their press failed and charging them for
    it.
    """
    text = _FENCE.sub("", raw.strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise UnusableSuggestion("the model did not return JSON") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise UnusableSuggestion(f"the model's JSON did not parse: {exc}") from exc
    if not isinstance(parsed, dict):
        raise UnusableSuggestion("the model returned JSON that is not an object")
    return parsed


def _changes(raw: object) -> list[Change]:
    if not isinstance(raw, list):
        return []
    changes: list[Change] = []
    for item in raw[:MAX_CHANGES]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("why") or "").strip()
        if not summary:
            continue
        kind = str(item.get("kind") or "").strip().lower()
        changes.append(
            Change(
                kind=kind if kind in CHANGE_KINDS else "changed",
                summary=summary[:MAX_SUMMARY_CHARS],
            )
        )
    return changes


def parse_suggestion(raw: str) -> Suggestion:
    """Validate a model answer into something the owner can be shown.

    Raises :class:`UnusableSuggestion` rather than returning a partial one. A
    truncated rewrite, an empty rewrite or one that cannot be saved is not a
    suggestion, and presenting it beside the owner's real instructions with an
    Accept button would be the one failure mode this feature exists to avoid.
    """
    parsed = _json_object(raw)

    improved = parsed.get("improved")
    if not isinstance(improved, str) or not improved.strip():
        raise UnusableSuggestion("the model returned no improved text")
    improved = improved.strip()

    # Checked here rather than in the route so that no caller can skip it. The
    # field validator would refuse the save, which means the owner would accept
    # a suggestion, press Save, and be told no.
    if len(improved) > MAX_CUSTOM_INSTRUCTIONS:
        raise SuggestionTooLong(len(improved))

    return Suggestion(improved=improved, changes=_changes(parsed.get("changes")))
