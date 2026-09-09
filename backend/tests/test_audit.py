"""What the audit log records, and who it names (teardown X8).

``audit_log`` was written by the admin console and by activation, and by
nothing else -- not on integration connect or disconnect, not on knowledge
delete, not on member removal, not on plan cancellation, not on config change,
and not on takeover. In a product with staff seats those are exactly the
actions worth attributing.

**Both existing writers passed ``actor_user_id=None``.** So even the rows that
did exist said what happened and never who, which is the half that matters:
with one owner "the plan was cancelled" is enough because there is only one
candidate, and with a receptionist on a staff seat it is not.

The last test is the one that will still be true in a year: it walks the route
table and fails when a state-changing owner route has no audit call, so the
next one added is caught rather than quietly missing.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest
from app.core.security import TokenClaims
from app.services import audit


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    """Enough session to add a row and resolve an actor."""

    def __init__(self, *, actor_id=None, broken: bool = False) -> None:
        self.added: list = []
        self.actor_id = actor_id
        self.broken = broken

    async def execute(self, *_args, **_kwargs):
        if self.broken:
            raise RuntimeError("database is unhappy")
        return FakeResult(self.actor_id)

    def add(self, row) -> None:
        if self.broken:
            raise RuntimeError("database is unhappy")
        self.added.append(row)

    async def flush(self) -> None:
        if self.broken:
            raise RuntimeError("database is unhappy")


def claims(email: str = "staff@theclinic.pk", role: str = "staff") -> TokenClaims:
    return TokenClaims(
        subject=email, tenant_id=None, role=role, is_qonvo_admin=False, raw={}
    )


TENANT = __import__("uuid").uuid4()
ACTOR = __import__("uuid").uuid4()


# --- the row names a person ------------------------------------------------------- #
async def test_the_row_records_who_not_just_what():
    """The finding. Both previous writers hard-coded actor_user_id=None."""
    db = FakeSession(actor_id=ACTOR)

    await audit.record(db, tenant_id=TENANT, claims=claims(), action="config_updated")

    [row] = db.added
    assert row.actor_user_id == ACTOR
    assert row.meta["actor_email"] == "staff@theclinic.pk"
    assert row.meta["actor_role"] == "staff"


async def test_the_email_is_kept_as_well_as_the_id():
    """The id is a foreign key that says nothing when somebody reads the table,
    and a removed member's row would become anonymous the moment the user is
    deleted -- which is precisely the row you would be reading."""
    db = FakeSession(actor_id=ACTOR)

    await audit.record(db, tenant_id=TENANT, claims=claims(), action="team_member_removed")

    assert db.added[0].meta["actor_email"] == "staff@theclinic.pk"


async def test_an_unknown_actor_still_writes_a_row():
    """A row without an actor beats no row at all."""
    db = FakeSession(actor_id=None)

    await audit.record(db, tenant_id=TENANT, claims=None, action="integration_connected")

    [row] = db.added
    assert row.actor_user_id is None
    assert row.action == "integration_connected"


async def test_extra_meta_is_merged_not_replaced():
    db = FakeSession(actor_id=ACTOR)

    await audit.record(
        db, tenant_id=TENANT, claims=claims(), action="plan_changed", meta={"to_plan": "growth"}
    )

    assert db.added[0].meta == {
        "actor_email": "staff@theclinic.pk",
        "actor_role": "staff",
        "to_plan": "growth",
    }


# --- it must never break the thing it is recording -------------------------------- #
async def test_a_failure_to_audit_does_not_raise():
    """These are called inside the request's transaction, so a raise would roll
    back the action being recorded. A missing row is bad; a cancellation that
    reports failure because its audit row would not write is worse."""
    db = FakeSession(broken=True)

    await audit.record(db, tenant_id=TENANT, claims=claims(), action="subscription_cancelled")

    assert db.added == []


# --- config: names, never values -------------------------------------------------- #
def test_changed_fields_reports_only_what_differs():
    row = SimpleNamespace(persona="friendly", timezone="UTC", payment_details="IBAN PK00")

    changed = audit.changed_fields(
        row, {"persona": "friendly", "timezone": "Asia/Karachi", "payment_details": "IBAN PK99"}
    )

    assert changed == ["payment_details", "timezone"]


def test_changed_fields_ignores_keys_the_row_does_not_have():
    """The update body carries fields that live in JSON maps rather than
    columns, and treating those as changed columns would report noise."""
    row = SimpleNamespace(persona="friendly")

    assert audit.changed_fields(row, {"voice_reply_mode": "always"}) == []


async def test_the_config_audit_records_field_names_and_not_the_value():
    """``payment_details`` is the text the rep reads out verbatim when a
    customer asks how to pay, and a staff seat substituting their own account
    number was the whole of X1. Knowing that it changed and who changed it is
    the record; copying the value into a second table with a different
    retention story is not."""
    source = inspect.getsource(__import__("app.api.config", fromlist=["x"]).update_config)

    assert "changed_fields" in source
    assert '"fields": changed' in source
    # The value itself must not be in the meta.
    assert "body.payment_details" not in source


# --- the property, so the next route added is caught ------------------------------ #
#: Owner-only routes that deliberately write no audit row, with the reason.
AUDIT_EXEMPT = {
    # Reads dressed as POSTs, or handing back a URL. Nothing changes.
    "start_checkout",  # the provider's webhook records the purchase
    "billing_portal",  # mints a session token; the provider logs its own access
    "oauth_start",  # the connect is recorded by the callback that completes it
    "test_integration",
    "session_qr",
    "payment_history",
    "invoice_link",
    # Sends the owner's own instructions to the tenant's model and hands back a
    # suggestion. It is a POST because it carries a body, and it writes
    # nothing: accepting a suggestion is an ordinary PUT /api/config, and that
    # one is audited.
    "review_instructions",
    # Recorded by the ledger they write, which is a better record than a
    # duplicate audit row.
    "set_activation",  # writes its own AuditLog with the readiness snapshot
}


def test_every_state_changing_owner_route_writes_an_audit_row():
    """Asserted over the route table rather than per route.

    A test per endpoint passes happily while the next endpoint somebody adds
    quietly records nothing, which is how twenty-one modules ended up with two
    writers between them.
    """
    from app.api.deps import require_owner, require_verified_owner
    from app.main import app

    def walk(routes):
        found = []
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None and hasattr(inner, "routes"):
                found += walk(inner.routes)
            elif getattr(route, "path", None):
                found.append(route)
        return found

    missing = []
    for route in walk(app.routes):
        methods = getattr(route, "methods", set()) or set()
        if not (methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or endpoint.__name__ in AUDIT_EXEMPT:
            continue
        gates = {
            getattr(p.default, "dependency", None)
            for p in inspect.signature(endpoint).parameters.values()
        }
        if not gates & {require_owner, require_verified_owner}:
            continue
        # Docstrings are stripped so prose mentioning "audit" cannot pass this.
        tree = ast.parse(inspect.getsource(endpoint).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                node.value = ast.Constant(value="")
        if "audit.record" not in ast.unparse(tree) and "AuditLog(" not in ast.unparse(tree):
            verb = sorted(methods & {"POST", "PUT", "PATCH", "DELETE"})[0]
            missing.append(f"{verb} {route.path}")

    assert not missing, (
        "these change state as an owner and record nothing. Either call "
        "audit.record, or add the handler to AUDIT_EXEMPT with a reason: "
        + ", ".join(sorted(missing))
    )


@pytest.mark.parametrize(
    "module,function,action",
    [
        ("app.api.config", "update_config", "config_updated"),
        ("app.api.knowledge", "delete_source", "knowledge_source_deleted"),
        ("app.api.team", "remove_member", "team_member_removed"),
        ("app.api.billing", "cancel_subscription", "subscription_cancelled"),
        ("app.api.billing", "change_plan", "plan_changed"),
        ("app.api.integrations", "delete_integration", "integration_disconnected"),
        ("app.api.conversations", "take_over", "conversation_taken_over"),
    ],
)
def test_the_named_actions_are_recorded(module, function, action):
    """Each one the teardown listed, pinned individually so a regression names
    the action rather than a count."""
    source = inspect.getsource(getattr(__import__(module, fromlist=["x"]), function))

    assert f'action="{action}"' in source
