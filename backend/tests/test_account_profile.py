"""Your own name is editable, and only your own (teardown V5).

The Profile card said "How you appear to your team" and let you set nothing.
The display name behind it -- the avatar menu, the Team list, every invitation
sent -- was captured once at signup and could never be changed, so a typo, or a
Google profile reading "aliasgher (work)", was permanent.

These are unit tests over the request model and the handler's shape rather than
request tests, because the interesting properties are the cleaning rule and the
absence of a user id in the payload, and neither needs a database.
"""

from __future__ import annotations

import inspect

import pytest
from app.api.account import MAX_FULL_NAME, ProfileUpdateRequest, update_profile
from pydantic import ValidationError


def test_a_name_is_trimmed_and_internally_collapsed():
    assert ProfileUpdateRequest(full_name="  Ali   Asghar  ").full_name == "Ali Asghar"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_a_blank_name_is_refused(value):
    """A blank name leaves an initial-less avatar and an unnamed row in Team,
    which is a worse outcome than the typo somebody came here to fix."""
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(full_name=value)


def test_a_pasted_essay_is_refused():
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(full_name="x" * (MAX_FULL_NAME + 1))


def test_the_cap_is_inside_the_column():
    """String(255) in the model. A cap above it would turn a validation error
    into a database error, which surfaces as a 500."""
    assert MAX_FULL_NAME <= 255


def test_the_payload_cannot_name_somebody_else():
    """The only field is the name. No user id, no email: the row updated is
    always the subject of the caller's own token, so this can never become a
    way to rename a teammate."""
    assert set(ProfileUpdateRequest.model_fields) == {"full_name"}


def test_the_route_is_not_tenant_gated():
    """A display name belongs to the person, not to a workspace.

    Gating this on require_tenant would lock a cross-tenant admin out of their
    own name, and gating it on require_owner would leave a staff seat with
    exactly the finding this fixes. It is listed in STAFF_ALLOWED for that
    reason, so this pins the intent rather than leaving it to a comment.
    """
    from app.api.deps import require_owner, require_tenant, require_verified_owner

    gates = {
        getattr(param.default, "dependency", None)
        for param in inspect.signature(update_profile).parameters.values()
    }
    assert require_tenant not in gates
    assert require_owner not in gates
    assert require_verified_owner not in gates
