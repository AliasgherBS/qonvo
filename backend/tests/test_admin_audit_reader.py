"""Reading the audit log back (finding A2).

``audit_log`` was write-only. Three things populate it -- the ops console, rep
activation, and every owner-side action since X8 -- and nothing read it: no
route, no page, so "who suspended this tenant", "who reset that password" and
"when was this rep switched off" all needed psql. Impersonation is audited
precisely so somebody can review it later, and nobody could.

The awkward part of the read side is that the actor was recorded three
different ways, so a naive reader shows a third of the rows as anonymous:

* ``app.services.audit`` writes ``actor_email`` + ``actor_role`` into ``meta``
  and resolves ``actor_user_id``.
* ``app.api.admin._audit`` wrote only ``meta["admin"]``, and now writes both.
* An impersonated session presents the *customer's* identity, with the admin
  behind it in ``meta["impersonated_by"]`` -- without which every row an
  impersonated session writes reads as the customer having done it.

These tests pin the reconciliation, because a row that displays no actor is
worse than no row: it looks answered.
"""

from __future__ import annotations

import uuid

from app.api import admin
from app.core.security import TokenClaims
from app.models.tenant import AuditLog


def _claims(subject: str = "admin@qonvo.dev") -> TokenClaims:
    return TokenClaims(
        subject=subject, tenant_id=None, role="qonvo_admin", is_qonvo_admin=True, raw={}
    )


class _Session:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)


# --- the writer names the actor the same way the owner side does ----------------- #
async def test_the_console_writes_the_actor_under_the_shared_keys():
    """Both admin writers used ``meta["admin"]`` alone, which the reader would
    have had to special-case forever. The old key stays too: rows written
    before this change carry only that, and dropping it would make the
    console's own history anonymous."""
    db = _Session()

    await admin._audit(
        db,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        claims=_claims(),
        action="tenant.update",
        target="t",
    )

    meta = db.added[0].meta
    assert meta["actor_email"] == "admin@qonvo.dev"
    assert meta["actor_role"] == "qonvo_admin"
    assert meta["admin"] == "admin@qonvo.dev"


async def test_the_writers_extra_meta_survives_the_actor_keys():
    db = _Session()

    await admin._audit(
        db,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        claims=_claims(),
        action="tenant.subscription.set",
        target="t",
        meta={"plan_key": "growth"},
    )

    assert db.added[0].meta["plan_key"] == "growth"
    assert db.added[0].meta["actor_email"] == "admin@qonvo.dev"


# --- the reader reconciles all three shapes -------------------------------------- #
def test_an_owner_side_row_reads_its_actor_and_role():
    email, role, impersonated = admin._audit_actor(
        {"actor_email": "owner@salon.pk", "actor_role": "owner"}
    )

    assert (email, role, impersonated) == ("owner@salon.pk", "owner", None)


def test_a_legacy_console_row_is_still_attributed():
    """Rows already in the table carry only ``admin``. Reading them as
    anonymous would mean the console's history begins at this commit."""
    email, role, impersonated = admin._audit_actor({"admin": "admin@qonvo.dev"})

    assert (email, role, impersonated) == ("admin@qonvo.dev", "qonvo_admin", None)


def test_an_impersonated_row_names_the_admin_behind_the_customer():
    """The whole point of auditing impersonation. Without this the row says the
    customer changed their own config."""
    email, role, impersonated = admin._audit_actor(
        {
            "actor_email": "owner@salon.pk",
            "actor_role": "owner",
            "impersonated_by": "admin@qonvo.dev",
        }
    )

    assert email == "owner@salon.pk"
    assert impersonated == "admin@qonvo.dev"


def test_a_row_with_no_actor_in_meta_reads_as_unknown_rather_than_guessing():
    """Activation writes its own ``AuditLog`` with a readiness snapshot and no
    actor keys. The reader falls back to ``actor_user_id`` in the route; here it
    must simply not invent one."""
    assert admin._audit_actor({"reason": "quota_exhausted"}) == (None, None, None)


# --- the page cannot ask for the whole table ------------------------------------- #
def test_the_page_size_is_capped():
    """A console with a year of history must not be able to request all of it
    by typing a larger number into the query string."""
    import inspect

    def bounds(name: str) -> dict:
        field = inspect.signature(admin.audit_log).parameters[name].default
        return {
            type(c).__name__.lower(): getattr(c, type(c).__name__.lower())
            for c in field.metadata
        }

    assert bounds("limit")["le"] == admin._AUDIT_PAGE_MAX
    assert bounds("limit")["ge"] == 1
    assert admin._AUDIT_PAGE_MAX <= 200
    assert bounds("offset")["ge"] == 0


def test_the_reader_hides_the_actor_keys_from_the_meta_column():
    """The actor is rendered as its own column, so leaving the same values in
    ``meta`` would print every row's actor twice."""
    import inspect

    source = inspect.getsource(admin.audit_log)

    assert 'k not in ("admin", "actor_email", "actor_role", "impersonated_by")' in source


def test_rows_are_ordered_newest_first_with_a_stable_tiebreak():
    """Several rows of one request share a timestamp to the microsecond. An
    unstable sort makes paging repeat and skip rows, which is the one thing an
    audit trail may not do."""
    import inspect

    source = inspect.getsource(admin.audit_log)

    assert "AuditLog.created_at.desc(), AuditLog.id.desc()" in source


def test_the_audit_reader_is_admin_only():
    """Cross-tenant by construction: it lists every tenant's rows."""
    import inspect

    from app.api.deps import require_admin

    gates = {
        getattr(p.default, "dependency", None)
        for p in inspect.signature(admin.audit_log).parameters.values()
    }
    assert require_admin in gates


def test_the_audit_reader_is_a_read_only_route():
    """It must never mutate: the trail is append-only, written by the actions
    it describes."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(admin.audit_log).lstrip())
    unparsed = ast.unparse(tree)

    assert "db.add" not in unparsed
    assert "_audit(" not in unparsed
    for banned in ("delete(", "update(", "insert("):
        assert banned not in unparsed


def test_the_reader_looks_for_the_actor_in_every_place_it_is_recorded():
    """Filtering only ``meta.actor_email`` would silently hide the console's own
    rows and every owner-side row that names its actor by id."""
    import inspect

    source = inspect.getsource(admin.audit_log)

    assert 'AuditLog.meta["actor_email"]' in source
    assert 'AuditLog.meta["admin"]' in source
    assert "AuditLog.actor_user_id.in_(" in source


def test_an_audit_row_is_still_tenant_scoped():
    """The console filters by tenant, which only works because the column
    exists on every row -- including the console's own."""
    assert hasattr(AuditLog, "tenant_id")
