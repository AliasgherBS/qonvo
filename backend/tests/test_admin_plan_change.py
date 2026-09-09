"""The ops console's plan control, and what it must derive (finding F3).

The console shipped a two-state toggle: "Mark as paid" against "Start 14-day
trial". Both went through ``PATCH /api/admin/tenants/{id}``, which wrote
``tenants.plan`` straight through. That column is a *label*. The numbers the
pipeline actually enforces live in ``tenant_config.entitlements``, and they are
only ever written by ``app.billing.service.apply_plan`` from the catalogue in
``app.billing.plans``.

So marking a customer paid produced this, read back from the live API during the
functional test:

    test01              | plan: paid | messages allowed: 1000
    QA Throwaway Salon  | plan: paid | messages allowed:  300   <- trial quota

Take a bank transfer, mark the customer paid, and they hit a wall at 300
messages while the console reports a paid plan. The billing design's stated
invariant is that "a plan change can never leave a stale quota", and the manual
path -- which exists precisely for taking payment outside a gateway -- was the
one place that broke it.

The fix is that the label has no writer: ``PUT .../subscription`` takes a
catalogue key and routes it through ``apply_plan``, and the PATCH route refuses
``plan`` with a message naming the endpoint that does it properly. These tests
pin both halves, plus the property that keeps them true: no admin handler may
assign ``tenant.plan``.
"""

from __future__ import annotations

import ast
import inspect
import uuid

import pytest
from app.api import admin
from app.billing.plans import PLANS, TRIAL_PLAN
from app.core.security import TokenClaims
from app.models.billing import Subscription
from app.models.tenant import AuditLog, Tenant, TenantConfig
from fastapi import HTTPException


# --- a session just big enough to serve the handlers ----------------------------- #
class _Result:
    def __init__(self, value, rows=None) -> None:
        self._value = value
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """Answers ``select(Model)`` from a dict keyed by the model class.

    The handlers under test each read one or two rows by primary key and then
    mutate them, so serving the entity of the select is enough and keeps the
    test about the plan logic rather than about SQLAlchemy.
    """

    def __init__(self, rows: dict) -> None:
        self.rows = rows
        self.added: list = []

    async def execute(self, stmt, *_args, **_kwargs):
        entity = stmt.column_descriptions[0]["entity"]
        return _Result(self.rows.get(entity))

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


def _claims() -> TokenClaims:
    return TokenClaims(
        subject="admin@qonvo.dev",
        tenant_id=None,
        role="qonvo_admin",
        is_qonvo_admin=True,
        raw={},
    )


def _world(plan: str = "trial"):
    """A tenant on the trial plan, with the trial's entitlements in force."""
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="QA Throwaway Salon", slug="qa-throwaway", plan=plan)
    config = TenantConfig(
        tenant_id=tenant_id,
        entitlements={**PLANS[TRIAL_PLAN].entitlements},
    )
    db = FakeSession({Tenant: tenant, TenantConfig: config, Subscription: None})
    return tenant_id, tenant, config, db


# --- the bug ---------------------------------------------------------------------- #
async def test_the_patch_route_will_not_set_the_plan_label():
    """The exact call the "Mark as paid" button used to make.

    Under the old code this returned 200, set ``tenants.plan = "paid"`` and left
    ``entitlements`` on the trial's 300 messages. It has to refuse, because
    "paid" names no plan in the catalogue and so implies no entitlements: there
    are three paid tiers and nothing in the request says which one was sold.
    """
    tenant_id, tenant, config, db = _world()

    with pytest.raises(HTTPException) as exc:
        await admin.update_tenant(
            tenant_id,
            admin.UpdateTenantRequest(plan="paid"),
            claims=_claims(),
            db=db,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 400
    # The refusal has to say where to go instead, or the operator's next move is
    # psql.
    assert "subscription" in exc.value.detail
    # And nothing may have changed on the way out.
    assert tenant.plan == "trial"
    assert config.entitlements["monthly_message_quota"] == PLANS[TRIAL_PLAN].entitlements[
        "monthly_message_quota"
    ]


async def test_the_patch_route_still_edits_the_rest_of_the_lifecycle():
    """Refusing ``plan`` must not take ``trial_ends_at`` with it -- that field
    works, and finding A4 is that nothing was setting it."""
    import datetime as dt

    tenant_id, tenant, _config, db = _world()
    ends = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)

    await admin.update_tenant(
        tenant_id,
        admin.UpdateTenantRequest(name="Renamed Salon", trial_ends_at=ends),
        claims=_claims(),
        db=db,  # type: ignore[arg-type]
    )

    assert tenant.name == "Renamed Salon"
    assert tenant.trial_ends_at == ends


# --- the fix --------------------------------------------------------------------- #
@pytest.mark.parametrize("plan_key", sorted(PLANS))
async def test_setting_a_subscription_derives_entitlements_from_the_catalogue(plan_key):
    """Every key, not just one. A tier added to the catalogue without its
    entitlements reaching the tenant is the same bug with a different number."""
    tenant_id, tenant, config, db = _world()

    body = admin.SetSubscriptionRequest(plan_key=plan_key, status="active")
    result = await admin.set_tenant_subscription(
        tenant_id, body, claims=_claims(), db=db  # type: ignore[arg-type]
    )

    assert result["plan_key"] == plan_key
    # The whole entitlement map, not just the headline number: the quota was the
    # symptom, and seats and knowledge caps drift the same way.
    assert config.entitlements == PLANS[plan_key].entitlements
    assert tenant.plan == ("trial" if plan_key == TRIAL_PLAN else "paid")


async def test_marking_a_tenant_paid_lifts_the_message_quota_off_the_trial():
    """The finding, stated as the operator experienced it."""
    tenant_id, tenant, config, db = _world()
    assert config.entitlements["monthly_message_quota"] == 300

    await admin.set_tenant_subscription(
        tenant_id,
        admin.SetSubscriptionRequest(plan_key="starter"),
        claims=_claims(),  # type: ignore[arg-type]
        db=db,  # type: ignore[arg-type]
    )

    assert tenant.plan == "paid"
    assert config.entitlements["monthly_message_quota"] == 1_000


async def test_an_unknown_plan_key_is_refused_rather_than_applied():
    tenant_id, _tenant, _config, db = _world()

    with pytest.raises(HTTPException) as exc:
        await admin.set_tenant_subscription(
            tenant_id,
            admin.SetSubscriptionRequest(plan_key="enterprise-handshake"),
            claims=_claims(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 400


async def test_the_plan_change_is_audited_with_the_key_it_applied():
    """"Who moved this customer onto Scale" is a support question, and the
    coarse label cannot answer it."""
    tenant_id, _tenant, _config, db = _world()

    await admin.set_tenant_subscription(
        tenant_id,
        admin.SetSubscriptionRequest(plan_key="growth"),
        claims=_claims(),  # type: ignore[arg-type]
        db=db,  # type: ignore[arg-type]
    )

    rows = [r for r in db.added if isinstance(r, AuditLog)]
    assert [r.action for r in rows] == ["tenant.subscription.set"]
    assert rows[0].meta["plan_key"] == "growth"
    assert rows[0].meta["actor_email"] == "admin@qonvo.dev"


# --- the picker has to offer the real keys --------------------------------------- #
async def test_the_catalogue_endpoint_offers_every_plan():
    """The console's picker is built from this. Restating the tiers in
    TypeScript is how the toggle got out of step with the catalogue in the first
    place."""
    plans = await admin.list_plans(claims=_claims())

    assert [p["key"] for p in plans] == list(PLANS)
    for entry in plans:
        assert entry["entitlements"] == PLANS[entry["key"]].entitlements


# --- the property, so the label cannot grow a writer again ----------------------- #
def test_no_admin_handler_assigns_the_plan_label():
    """``tenants.plan`` is derived by ``apply_plan`` and by nothing else.

    A test per route passes while the next route somebody adds sets the label
    directly, which is exactly how F3 arrived, so this asserts over the module.
    """
    tree = ast.parse(inspect.getsource(admin))

    offenders = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "plan"
                and isinstance(target.value, ast.Name)
                and target.value.id in ("tenant", "row")
            ):
                offenders.append(f"line {node.lineno}")

    assert not offenders, (
        "tenants.plan must be derived from the plan catalogue by "
        "app.billing.service.apply_plan, never assigned in a route (finding F3): "
        + ", ".join(offenders)
    )


#: Admin routes that change state and deliberately record nothing, with why.
AUDIT_EXEMPT = {
    # Purges audit_log along with every other tenant-scoped row, so a row would
    # delete itself. Logged to the ops log instead (see the handler).
    "delete_tenant",
}


def test_every_state_changing_admin_route_writes_an_audit_row():
    """The mirror of ``test_audit``'s owner-side property, for the console.

    Everything the console does is cross-tenant and irreversible, and finding A2
    was that these rows had no reader. Now that they have one, a route that
    writes none is a gap in the only record of who did what.
    """
    from app.api.deps import require_admin
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
        if require_admin not in gates:
            continue
        # Docstrings stripped, so prose mentioning audit cannot pass this.
        tree = ast.parse(inspect.getsource(endpoint).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                node.value = ast.Constant(value="")
        if "_audit" not in ast.unparse(tree) and "AuditLog(" not in ast.unparse(tree):
            verb = sorted(methods & {"POST", "PUT", "PATCH", "DELETE"})[0]
            missing.append(f"{verb} {route.path}")

    assert not missing, (
        "these change state as an admin and record nothing. Either call _audit, "
        "or add the handler to AUDIT_EXEMPT with a reason: " + ", ".join(sorted(missing))
    )
