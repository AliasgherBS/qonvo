"""What counts as an acceptable password (teardown X5).

``Field(min_length=8, max_length=128)`` was the whole policy, on signup, on
change and on reset. ``password1``, ``qonvo123`` and the business's own name all
passed. Argon2 makes each guess expensive and the throttle makes bulk guessing
slow, which is why this was medium rather than high, but neither does anything
about a password already sitting in a breach corpus.

Shaped to NIST 800-63B: longer minimum, **no composition rules**, and screening
against known-compromised passwords. The test that asserts there are no
composition rules is as load-bearing as the others -- complexity requirements
push people towards ``Passw0rd!`` and away from a phrase, and somebody will
eventually want to add them back.

The breach check is exercised against a stub. Hitting the real API from the
suite would make it depend on somebody else's uptime, and the k-anonymity
protocol is what needs testing rather than their data.
"""

from __future__ import annotations

import httpx
import pytest
from app.core import passwords
from app.core.passwords import (
    MIN_LENGTH,
    PasswordRejected,
    check_password,
    is_breached,
    reasons_password_is_weak,
)


@pytest.fixture
def hibp(monkeypatch):
    """Stand in for the range API, and record what was actually sent."""
    sent: dict[str, object] = {}

    def install(body: str, *, status: int = 200):
        def handler(request: httpx.Request) -> httpx.Response:
            sent["url"] = str(request.url)
            sent["headers"] = dict(request.headers)
            return httpx.Response(status, text=body)

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        monkeypatch.setattr(
            passwords.httpx, "AsyncClient", lambda **kw: real(**kw, transport=transport)
        )
        return sent

    return install


# --- length ---------------------------------------------------------------------- #
@pytest.mark.parametrize("password", ["password1", "qonvo123", "short", "elevenchar"])
def test_the_old_policy_no_longer_passes(password):
    """Every one of these cleared the previous eight-character rule."""
    assert reasons_password_is_weak(password)


def test_twelve_characters_is_enough():
    assert reasons_password_is_weak("a-fine-phrase") == []


def test_the_minimum_is_twelve():
    assert MIN_LENGTH == 12


def test_an_absurdly_long_password_is_refused():
    """Not a strength rule. An unbounded field is a cheap way to make somebody
    argon2-hash a megabyte per request."""
    assert reasons_password_is_weak("x" * 500)


# --- no composition rules -------------------------------------------------------- #
@pytest.mark.parametrize(
    "password",
    [
        "correct horse battery staple",
        "all lower case and long enough",
        "ALL UPPER CASE AND LONG ENOUGH",
        "no digits or symbols at all here",
    ],
)
def test_there_are_no_composition_rules(password):
    """Deliberate, and the thing most likely to be "fixed" back. NIST 800-63B
    is explicit: complexity requirements make passwords worse. They are why
    `Tr0ub4dor&3` exists, and that one is in the breach corpus."""
    assert reasons_password_is_weak(password) == []


# --- the obvious ones ------------------------------------------------------------ #
def test_the_business_name_is_refused():
    reasons = reasons_password_is_weak("theclinic-karachi", business_name="The Clinic")

    assert reasons
    assert "business name" in reasons[0]


def test_the_email_local_part_is_refused():
    assert reasons_password_is_weak("aliasghar-is-here", email="aliasghar@qonvo.org")


def test_the_email_domain_is_not_treated_as_a_forbidden_word():
    """Otherwise every customer on gmail would be unable to use a passphrase
    containing "gmail", and worse, the domain says nothing about them."""
    assert reasons_password_is_weak("gmail is a fine service", email="someone@gmail.com") == []


def test_short_fragments_do_not_reject_half_the_dictionary():
    """A business called "Go" must not forbid every password containing "go"."""
    assert reasons_password_is_weak("a good long password", business_name="Go") == []


@pytest.mark.parametrize("password", ["aaaaaaaaaaaa", "abababababab", "            "])
def test_a_repetitive_string_is_not_a_password(password):
    assert reasons_password_is_weak(password)


def test_every_reason_is_reported_at_once():
    """A form that reveals one problem per submission is a form people fight."""
    reasons = reasons_password_is_weak("clinic", business_name="Clinic")

    assert len(reasons) >= 2


# --- the breach check ------------------------------------------------------------ #
async def test_a_breached_password_is_detected(hibp):
    # SHA-1("password1") = E38AD214943DAAD1D64C102FAEC29DE4AFE9DA3D, so the
    # bucket is E38AD and the suffix is everything after it. Computed, not
    # invented: the first version of this test used a made-up digest and
    # passed the wrong assertion for the wrong reason.
    hibp("214943DAAD1D64C102FAEC29DE4AFE9DA3D:2417")

    assert await is_breached("password1") is True


async def test_an_unseen_password_is_not_breached(hibp):
    hibp("0000000000000000000000000000000000A:1\n1111111111111111111111111111111111B:2")

    assert await is_breached("a-phrase-nobody-has-used-before-2026") is False


async def test_only_five_characters_of_the_hash_are_sent(hibp):
    """The whole point of k-anonymity. Sending the full hash would hand a third
    party something equivalent to the password."""
    sent = hibp("")

    await is_breached("password1")

    assert sent["url"].endswith("/range/E38AD")  # SHA-1("password1")[:5]
    assert "password1" not in sent["url"]


async def test_padding_is_requested(hibp):
    """Without it the response size reveals how large the bucket was, which
    leaks a little about the prefix."""
    sent = hibp("")

    await is_breached("password1")

    assert sent["headers"].get("add-padding") == "true"


async def test_a_padding_entry_is_not_treated_as_a_breach(hibp):
    """Padded responses contain real suffixes with a count of zero. Counting
    those as breached would reject arbitrary good passwords."""
    hibp("214943DAAD1D64C102FAEC29DE4AFE9DA3D:0")

    assert await is_breached("password1") is False


async def test_the_check_fails_open(hibp):
    """It is an outbound call to a third party on the critical path of signing
    up. Refusing a registration because somebody else's service is slow trades
    a real customer for a hypothetical attacker."""
    hibp("nope", status=503)

    assert await is_breached("password1") is False


async def test_a_hopeless_password_costs_no_outbound_request(hibp):
    """The breach lookup is skipped when the password already fails, so a form
    full of "abc" does not generate traffic."""
    sent = hibp("")

    with pytest.raises(PasswordRejected):
        await check_password("abc")

    assert sent == {}


async def test_check_password_raises_with_every_reason(hibp):
    hibp("")

    with pytest.raises(PasswordRejected) as caught:
        await check_password("clinic", business_name="Clinic")

    assert len(caught.value.reasons) >= 2


async def test_a_good_password_passes(hibp):
    hibp("")

    await check_password("a perfectly reasonable phrase", email="a@b.com")


# --- every path that sets a password uses the policy ----------------------------- #
@pytest.mark.parametrize(
    "module,function",
    [
        ("app.api.auth", "signup"),
        ("app.api.auth", "change_password_route"),
        ("app.api.auth", "reset_password_route"),
        ("app.api.team", "accept_invitation"),
    ],
)
def test_the_policy_is_enforced_on_every_path(module, function):
    """Four paths set a password, and the invite-acceptance one is the easiest
    to forget because it creates an account rather than changing one."""
    import ast
    import inspect

    source = inspect.getsource(getattr(__import__(module, fromlist=["x"]), function))
    tree = ast.parse(source.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "check_password" in ast.unparse(tree)


def test_pydantic_no_longer_owns_half_the_policy():
    """A min_length constraint beside a validator means two error shapes for
    the same rule: a 422 field error for one character too few, and a 400 with
    sentences for anything else."""
    from app.api.auth import ChangePasswordRequest, ResetPasswordRequest, SignupRequest

    for model, field in (
        (SignupRequest, "password"),
        (ChangePasswordRequest, "new_password"),
        (ResetPasswordRequest, "new_password"),
    ):
        constraints = str(model.model_fields[field])
        assert "min_length" not in constraints, f"{model.__name__}.{field}"


def test_the_reset_path_checks_before_consuming_the_token():
    """Otherwise a rejected password burns the single-use link and the person
    has to request another email to try again."""
    import inspect

    from app.api.auth import reset_password_route

    source = inspect.getsource(reset_password_route)

    assert source.index("check_password") < source.index("await reset_password(")


def test_the_browser_and_the_server_agree_on_the_minimum():
    """The meter is guidance, not the policy, but a meter that says twelve
    while the server wants sixteen is worse than no meter."""
    from pathlib import Path

    component = (
        Path(__file__).resolve().parents[2]
        / "dashboard"
        / "components"
        / "password-strength.tsx"
    ).read_text()

    assert f"MIN_PASSWORD_LENGTH = {MIN_LENGTH}" in component
