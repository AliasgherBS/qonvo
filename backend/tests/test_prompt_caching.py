"""The request prefix must be stable, or automatic prompt caching never fires.

OpenAI and Gemini 2.5+ both cache automatically, with no parameter to set: they
match the longest common prefix of the request against a recent one and bill the
hit at roughly a tenth of the input rate. The minimum cacheable prefix is ~1,024
tokens.

That makes prompt *order* the whole game. The system message is position 0, so
anything volatile in it breaks the prefix at the first token and guarantees a
miss on every request. Retrieved knowledge changes with each question, and the
rolling summary is rewritten every few turns -- so both belong at the end, after
the history, not in the system prompt.

Input is roughly 95% of LLM spend at the measured 3,312 tokens per reply, so
this ordering is the single largest cost lever available.
"""

from __future__ import annotations

from app.workers.pipeline import build_system_prompt, build_turn_prompt

PERSONA = {
    "business_name": "Glow Salon",
    "persona": "Warm, brisk, never pushy.",
    "tone": "friendly",
    "custom_instructions": "Never quote a price without confirming the branch.",
    "primary_language": "ur",
}


# --- the property that makes caching work ------------------------------------ #
def test_the_system_prompt_is_identical_across_turns():
    """The cacheable prefix. If this ever differs between two turns of the same
    tenant, every request is a cache miss and the input bill is 10x."""
    first = build_system_prompt(**PERSONA)
    later = build_system_prompt(**PERSONA)

    assert first == later


def test_the_system_prompt_carries_nothing_that_changes_per_question():
    prompt = build_system_prompt(**PERSONA)

    assert "Glow Salon" in prompt
    assert "Warm, brisk" in prompt
    # The two things that used to live here and broke the prefix:
    assert "Business knowledge" not in prompt
    assert "conversation so far" not in prompt


def test_two_tenants_do_not_share_a_prefix():
    """Sanity: caching is per-prefix, so different personas must differ."""
    other = {**PERSONA, "business_name": "Other Co", "persona": "Formal."}

    assert build_system_prompt(**PERSONA) != build_system_prompt(**other)


# --- the volatile half ------------------------------------------------------- #
def test_the_turn_carries_the_knowledge_and_the_question():
    turn = build_turn_prompt(
        context_block="Open 9 to 7. Refunds within 14 days.",
        conversation_summary="Customer asked about branches earlier.",
        message="kitne ka hai haircut?",
    )

    assert "Open 9 to 7" in turn
    assert "asked about branches" in turn
    assert "kitne ka hai haircut?" in turn


def test_the_customer_question_comes_last():
    """Whatever precedes it is context; the model should answer the question,
    and the question is also the part most likely to change."""
    turn = build_turn_prompt(
        context_block="Some knowledge.",
        conversation_summary="Some summary.",
        message="the actual question",
    )

    assert turn.rstrip().endswith("the actual question")


def test_a_turn_with_no_knowledge_says_so():
    """The grounding instruction depends on the model being told when nothing
    was retrieved, or it will answer from its own training."""
    turn = build_turn_prompt(context_block="", conversation_summary=None, message="hi")

    assert "no relevant business knowledge" in turn.lower()


def test_a_turn_without_a_summary_omits_the_section():
    turn = build_turn_prompt(
        context_block="Knowledge.", conversation_summary=None, message="hi"
    )

    assert "conversation so far" not in turn.lower()
