"""A name and a number are worth keeping (E4).

``capture_lead`` was never invoked once in the whole of the live period. A
booking exchange collected a name, a phone number, a city and a service and
captured nothing: that lead exists only inside a WhatsApp transcript.

The cause was the prompt, and is fixed there
(``pipeline.LEAD_CAPTURE_INSTRUCTION``, covered in
``test_prompt_guard_rails``). What is tested here is the two things in the
handler that made obeying that instruction harder than it needed to be: the
number being treated as something the model has to supply, and a standing
instruction to call the skill turning into a row on every turn.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.models.business import Lead
from app.skills.registry import SKILL_REGISTRY, SkillContext

# Through the registry, not straight at the module: importing
# app.skills.capture_lead first is a circular import, because the registry
# imports every handler at module scope.

handle = SKILL_REGISTRY["capture_lead"].handler
DEFINITION = SKILL_REGISTRY["capture_lead"]


def _ctx(db, **overrides) -> SkillContext:
    defaults = {
        "db": db,
        "tenant_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "idempotency_key": f"{uuid.uuid4()}:call_1",
        "chat_id": "923001234567@c.us",
    }
    defaults.update(overrides)
    return SkillContext(**defaults)


def _db(*, existing: Lead | None = None) -> AsyncMock:
    db = AsyncMock()
    added: list = []
    db.add = MagicMock(side_effect=added.append)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=existing)
    db.execute = AsyncMock(return_value=result)
    db.added = added
    return db


# --- the number is already known ---------------------------------------------- #
async def test_a_name_alone_is_enough():
    """The customer is messaging from a WhatsApp number, so the chat id *is* a
    phone number. Refusing "capture Ali, wants a facial" for lacking the one
    detail the system already had is how a skill ends up never being called."""
    db = _db()

    result = await handle(_ctx(db), {"name": "Ali", "intent": "wants a facial"})

    assert result["status"] == "captured"
    lead = db.added[0]
    assert lead.name == "Ali"
    assert lead.phone == "923001234567"
    assert lead.notes == "wants a facial"


async def test_a_number_the_customer_gave_wins_over_the_chat_number():
    db = _db()

    await handle(_ctx(db), {"name": "Ali", "phone": "+92 321 9999999"})

    assert db.added[0].phone == "+92 321 9999999"


async def test_the_whatsapp_push_name_fills_in_a_missing_name():
    """It is what the inbox already labels the conversation with, so a nameless
    lead is a worse record than one carrying the name the customer chose."""
    db = _db()
    conversation = SimpleNamespace(customer_name="Ayesha K.")

    await handle(_ctx(db, conversation=conversation), {"intent": "laser, Lahore"})

    assert db.added[0].name == "Ayesha K."


async def test_no_number_anywhere_is_still_refused():
    """A lead with no way to reach the person is not a lead. Unreachable from
    the pipeline, where a chat id always exists, and kept as the floor."""
    db = _db()

    result = await handle(_ctx(db, chat_id=None), {"name": "Ali"})

    assert result["status"] == "error"
    assert db.added == []


# --- one lead per conversation ------------------------------------------------- #
# The execution ledger keys on the tool call id, so it stops a *redelivery*
# double-writing but not a second, honest call on a later turn. Now that the
# prompt tells the model to call this whenever details appear, that matters.
async def test_a_second_call_updates_the_same_lead():
    existing = Lead(
        tenant_id=uuid.uuid4(), name=None, phone="923001234567", notes=None, data={}
    )
    existing.id = uuid.uuid4()
    db = _db(existing=existing)

    result = await handle(_ctx(db), {"name": "Ali", "intent": "facial, Friday"})

    assert result["status"] == "captured"
    assert db.added == []
    assert existing.name == "Ali"
    assert existing.notes == "facial, Friday"


async def test_a_later_call_never_overwrites_with_less():
    """A turn that has dropped the name must not blank what an earlier turn
    recorded. Enrich, never replace."""
    existing = Lead(
        tenant_id=uuid.uuid4(), name="Ali", phone="923001234567", notes="facial", data={}
    )
    existing.id = uuid.uuid4()
    db = _db(existing=existing)

    await handle(_ctx(db), {})

    assert existing.name == "Ali"
    assert existing.notes == "facial"


async def test_a_new_intent_is_appended_rather_than_replacing_the_old_one():
    existing = Lead(
        tenant_id=uuid.uuid4(), name="Ali", phone="923001234567", notes="facial", data={}
    )
    existing.id = uuid.uuid4()
    db = _db(existing=existing)

    await handle(_ctx(db), {"intent": "also asked about laser"})

    assert existing.notes == "facial\nalso asked about laser"


# --- what the model is told ----------------------------------------------------- #
def test_the_description_tells_the_model_not_to_ask_for_a_number():
    assert "do not need to ask for their phone number" in DEFINITION.description
    assert "safe" in DEFINITION.description


def test_the_skill_needs_no_integration():
    """Which is why "seven of eight skills were never invoked" cannot be blamed
    on Google for this one: nothing was ever gating it."""
    assert DEFINITION.requires_integration is None
    assert DEFINITION.requires_config_key is None
