"""Which sentences are Qonvo's and which are the owner's (E2, E3, E4).

The functional test's conclusion about the conversation engine was that the
tenant's free-text instructions are the most powerful input in the system and
nothing bounds or reconciles them: 1,821 characters against a handful of
hardcoded sentences, in the same undifferentiated block. Three separate defects
came out of that.

The answer is not to take the field away. It is to be clear about the division:
the owner sets the *policy* (what to promise, what to say, which language), and
the platform enforces the *guard rail* underneath it (do not invent, do not
commit to what was never stated, do not claim to be unable to do something a
connected tool does). These tests pin that division down, because it is the
kind of thing that erodes one helpful-sounding sentence at a time.
"""

from __future__ import annotations

from app.workers.pipeline import (
    DEFAULT_PERSONA,
    GATED_SKILL_POWERS,
    GROUNDING_INSTRUCTION,
    IDENTITY_INSTRUCTION,
    build_system_prompt,
    tool_authority,
)

TENANT = {
    "business_name": "Depilex",
    "persona": None,
    "tone": "Warm, Concise, Direct",
    "custom_instructions": (
        "A booking on WhatsApp is a request: take the city, the tier, the branch, "
        "the service, the preferred date and time, the name and the phone number, "
        "then tell the customer a representative will call within a few hours to "
        "confirm. Never say a time slot is free or booked. You cannot see any diary."
    ),
    "primary_language": "en",
}


# --- E3: line one no longer says "AI" ----------------------------------------- #
def test_line_one_does_not_call_the_rep_an_ai():
    """"You are the AI customer representative for {business}" was the single
    most influential sentence in the request and said the opposite of the goal:
    the customer is meant to experience the business answering."""
    opening = build_system_prompt(**TENANT).split(". ")[0] + "."

    assert opening == "You are the customer service team for Depilex."
    assert "AI customer representative" not in build_system_prompt(**TENANT)


def test_the_rep_speaks_as_the_business():
    assert 'say "we"' in IDENTITY_INSTRUCTION
    for word in ("AI", "a bot", "an assistant", "a model", "a representative"):
        assert word in IDENTITY_INSTRUCTION, f"{word} is not ruled out"


def test_the_persona_is_pinned_even_when_the_owner_wrote_none():
    """The gender flipped mid-conversation ("kar sakti hun" in one reply, "kar
    sakta hun" in the next), which in Urdu is glaring. Field 2 was empty, so
    nothing pinned it: an empty persona was an unpinned persona."""
    prompt = build_system_prompt(**TENANT)

    assert DEFAULT_PERSONA in prompt
    assert "feminine" in DEFAULT_PERSONA
    assert "grammatical gender" in IDENTITY_INSTRUCTION


def test_an_owner_persona_replaces_the_default_but_not_the_consistency_rule():
    """Which voice is the owner's choice. That it does not change halfway
    through a conversation is not."""
    prompt = build_system_prompt(**{**TENANT, "persona": "Formal, and always male."})

    assert "Formal, and always male." in prompt
    assert DEFAULT_PERSONA not in prompt
    assert "one grammatical gender" in prompt


def test_a_blank_persona_counts_as_no_persona():
    """A field the owner cleared to whitespace must not defeat the default."""
    assert DEFAULT_PERSONA in build_system_prompt(**{**TENANT, "persona": "   \n "})


# --- E2: the guard rail stops inventing commitments, not stating them --------- #
def test_the_hardcoded_prompt_makes_no_commitment_of_its_own():
    """It used to instruct the model to "say you'll connect them with the
    team", which is itself a first-person commitment. The prompt was making the
    promise it was meant to prevent, and the model then elaborated on it."""
    assert "connect them with the team" not in GROUNDING_INSTRUCTION
    assert "you'll" not in GROUNDING_INSTRUCTION


def test_commitments_are_forbidden_by_kind_not_by_a_list_of_four_nouns():
    """The old rule forbade inventing "facts, prices, policies, or
    availability". A promise about the future is none of the four, so nothing
    stopped one being invented."""
    for kind in ("timeline", "callback", "policy", "price", "availability"):
        assert kind in GROUNDING_INSTRUCTION, f"{kind} is not covered"
    assert "no promise about what any person will do or when" in GROUNDING_INSTRUCTION


def test_an_owner_stated_commitment_is_explicitly_allowed_through():
    """The owner's decision: the call to action is theirs. Some businesses want
    "a rep will call you", others want Qonvo to confirm. So the rule forbids
    commitments the business has *not* stated, which is the only wording under
    which the guard rail and a deliberate instruction can both be true."""
    assert "has not stated" in GROUNDING_INSTRUCTION
    assert "give it exactly as written and add nothing to it" in GROUNDING_INSTRUCTION

    # And nothing strips the owner's own call to action out of the prompt.
    assert "a representative will call within a few hours" in build_system_prompt(**TENANT)


# --- E4: a connected integration is authoritative ----------------------------- #
def test_a_connected_calendar_overrules_an_instruction_denying_it():
    """The live tenant's instructions said "You cannot see any diary" while
    Google Calendar was connected and passing its test. check_availability and
    book_appointment were never once invoked."""
    prompt = build_system_prompt(
        **TENANT,
        available_skills=["capture_lead", "human_handoff", "check_availability"],
    )

    assert "see which times are actually free in the calendar" in prompt
    assert "that text is out of date and the tool is correct" in prompt
    # After the owner's instructions, so it answers the claim rather than
    # preceding it.
    assert prompt.index("out of date") > prompt.index("You cannot see any diary")


def test_only_gated_skills_are_announced():
    """An ungated skill has always been there and needs no announcement. The
    gated ones are exactly the set an older instruction can contradict, because
    they did not exist until something was connected."""
    assert tool_authority(["human_handoff"]) is None
    assert set(GATED_SKILL_POWERS) == {
        "check_availability",
        "book_appointment",
        "append_to_sheet",
        "lookup_sheet",
        "share_payment_details",
    }


def test_capture_lead_is_announced_even_with_nothing_connected():
    """It needs no integration, so a tenant who has connected nothing still has
    to be told about it. Seven of eight skills had never been invoked and
    capture_lead was one of them."""
    text = tool_authority(["capture_lead", "human_handoff"])

    assert text is not None
    assert "call capture_lead" in text
    assert "do not mention it to the customer" in text


def test_no_skills_at_all_adds_nothing():
    assert tool_authority([]) is None
    assert tool_authority(None) is None


# --- the cacheable prefix ------------------------------------------------------ #
def test_the_system_prompt_stays_byte_stable_for_a_tenant():
    """Position 0 is the cacheable prefix and one volatile byte in it is a miss
    on every request at ~10x the input rate. Everything added here is derived
    from tenant state, never from the turn."""
    skills = {"check_availability", "book_appointment", "capture_lead"}

    first = build_system_prompt(**TENANT, available_skills=skills)
    later = build_system_prompt(**TENANT, available_skills=sorted(skills, reverse=True))

    assert first == later


def test_the_system_prompt_still_carries_nothing_per_question():
    prompt = build_system_prompt(**TENANT, available_skills=["check_availability"])

    assert "Business knowledge" not in prompt
    assert "conversation so far" not in prompt
    # And no per-turn language fact: that belongs beside the message (E1).
    assert "current message" not in prompt
