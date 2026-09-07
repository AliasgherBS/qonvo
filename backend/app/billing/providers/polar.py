"""Polar as merchant of record (spec §7).

The second real adapter behind the seam, so nothing downstream learns Polar's
vocabulary: the webhook route, the reconciler and the dashboard still speak only
``BillingEvent`` and ``Checkout``.

Two things here are genuinely fiddly, and both are Polar's rather than ours.

**The signing scheme changed on 8 September 2026.** A secret created before that
date is a raw HMAC key that Standard Webhooks libraries expect base64-encoded;
one created after is a proper Standard Webhooks ``whsec_`` secret passed
through as-is. Polar's own SDKs sniff which they have. So does
``_candidate_keys`` below: it tries both derivations and accepts either. Picking
one would work perfectly until the day the account was created moved, and then
fail with a 401 that looks like a wrong secret.

**Status is not the same question as event type.** ``subscription.canceled``
fires when a cancellation is *scheduled*, and the subscription keeps working
until the period ends. ``subscription.revoked`` is when it actually stops.
Treating the first as "off" would cut a paying customer off early, which is
exactly the kind of billing bug that costs trust rather than money.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.billing.plans import plan_for_price_id
from app.billing.providers.base import BillingEvent, Checkout, InvalidWebhookSignature
from app.core.config import settings
from app.core.logging import logger

__all__ = ["PolarProvider"]

#: Standard Webhooks tolerance. Outside this a replayed delivery is rejected
#: even with a valid signature, which is the only thing stopping a captured
#: request from being useful forever.
TIMESTAMP_TOLERANCE_SECONDS = 5 * 60

_SANDBOX_API = "https://sandbox-api.polar.sh/v1"
_PRODUCTION_API = "https://api.polar.sh/v1"

#: How Polar's events map onto what ``service_state`` already understands.
#: Deliberately not one-to-one: several events mean the same thing to us, and
#: two that look alike mean opposite things.
_STATUS_BY_EVENT: dict[str, str] = {
    "subscription.created": "active",
    "subscription.active": "active",
    "subscription.uncanceled": "active",
    "subscription.cycled": "active",
    "subscription.resumed": "active",
    # Scheduled, not stopped. The tenant keeps service to the end of the period,
    # which service_state already handles through current_period_end.
    "subscription.canceled": "canceled",
    # Actually stopped.
    "subscription.revoked": "canceled",
    # Wired to the existing 7-day grace rather than a second failure path.
    "subscription.past_due": "past_due",
    "subscription.paused": "paused",
}

#: Events we accept but which assert nothing about state on their own.
_PASSTHROUGH_EVENTS = frozenset(
    {"subscription.updated", "order.created", "order.paid", "order.updated", "order.refunded"}
)


class PolarProvider:
    key = "polar"

    # --- checkout ---------------------------------------------------------- #
    @property
    def _api(self) -> str:
        return _SANDBOX_API if settings.polar_server == "sandbox" else _PRODUCTION_API

    def checkout(self, *, tenant_id: str, plan_key: str) -> Checkout:
        """Create a hosted checkout and return its URL.

        The tenant id goes in ``metadata`` so the webhook can resolve who paid
        without a lookup table of our own. A mapping table would be a second
        source of truth about the same fact, and the one that goes stale.
        """
        price_id = self._price_id_for(plan_key)
        if not price_id:
            return Checkout(
                instructions=(
                    f"The {plan_key} plan is not connected to a price yet. "
                    "Message us and we will switch it over for you."
                )
            )
        if not settings.polar_access_token:
            return Checkout(
                instructions=(
                    "Card payment is not switched on yet. Message us to move onto "
                    f"the {plan_key} plan."
                )
            )

        try:
            response = httpx.post(
                f"{self._api}/checkouts/",
                headers={"Authorization": f"Bearer {settings.polar_access_token}"},
                json={
                    "products": [price_id],
                    "metadata": {"tenant_id": tenant_id, "plan_key": plan_key},
                    "success_url": f"{settings.dashboard_base_url}/billing?upgraded=1",
                },
                timeout=20,
            )
            response.raise_for_status()
            url = response.json().get("url")
        except Exception as exc:  # noqa: BLE001 - an upgrade must not 500
            # Degrade to the manual path. An owner trying to give us money and
            # meeting an error page is the worst possible moment to be down.
            logger.warning(f"polar checkout failed: {exc}")
            return Checkout(
                instructions=(
                    "We could not open the payment page just now. Message us and "
                    f"we will move you onto the {plan_key} plan."
                )
            )

        if not url:
            return Checkout(instructions="Message us and we will move you onto this plan.")
        return Checkout(url=url)

    @staticmethod
    def _price_id_for(plan_key: str) -> str | None:
        """Reverse ``billing_price_map``, which is stored provider-id first.

        That direction is the one the webhook needs, and it is the direction
        that must stay authoritative: two products can point at one plan, but a
        plan resolving to two prices would make checkout ambiguous.
        """
        for price_id, mapped in (settings.billing_price_map or {}).items():
            if mapped == plan_key:
                return price_id
        return None

    # --- webhooks ---------------------------------------------------------- #
    @staticmethod
    def _candidate_keys(secret: str) -> list[bytes]:
        """Every HMAC key this secret might be.

        Polar's scheme changed on 8 September 2026. Rather than ask an operator
        which side of that date their account was created, try both: the raw
        secret bytes, and the base64 decoding of it with any ``whsec_`` prefix
        stripped. Trying both costs one extra HMAC on a request that is already
        doing one.
        """
        keys: list[bytes] = [secret.encode()]
        body = secret.removeprefix("whsec_")
        if body != secret:
            keys.append(body.encode())
        for candidate in (secret, body):
            # Pad before decoding. Standard Webhooks secrets are unpadded
            # base64, so a real one fails a strict decode on length alone: a
            # 32-byte key is 43 characters, and 43 % 4 == 3. Skipping it left
            # the post-2026-09-08 scheme unverifiable, which is precisely the
            # 401-that-looks-like-a-bad-secret this function exists to avoid.
            padded = candidate + "=" * (-len(candidate) % 4)
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    decoded = decoder(padded)
                except Exception:  # noqa: BLE001 - not base64, which is fine
                    continue
                # A signing key is 32 bytes. Anything much shorter is almost
                # certainly a coincidental decode of a non-base64 string, and
                # adding it would only widen what counts as a valid signature.
                if len(decoded) >= 16 and decoded not in keys:
                    keys.append(decoded)
        return keys

    def _verify(self, headers: dict[str, str], raw: bytes) -> bool:
        secret = settings.polar_webhook_secret or settings.billing_webhook_secret
        if not secret:
            # No secret configured means no way to tell a real delivery from a
            # forged one, so nothing is authentic. Failing closed here is the
            # difference between "billing is not set up" and "anyone can grant
            # themselves a plan".
            logger.warning("polar webhook received with no signing secret configured")
            return False

        lower = {k.lower(): v for k, v in headers.items()}
        webhook_id = lower.get("webhook-id")
        timestamp = lower.get("webhook-timestamp")
        signature_header = lower.get("webhook-signature")
        if not (webhook_id and timestamp and signature_header):
            return False

        try:
            age = abs(time.time() - int(timestamp))
        except ValueError:
            return False
        if age > TIMESTAMP_TOLERANCE_SECONDS:
            # A valid signature on an old delivery is a replay. Without this the
            # signature alone would make a captured request useful forever.
            logger.warning(f"polar webhook outside timestamp tolerance ({age:.0f}s)")
            return False

        signed = b".".join([webhook_id.encode(), timestamp.encode(), raw])
        expected = {
            base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
            for key in self._candidate_keys(secret)
        }

        # The header carries space-separated versioned signatures, plural during
        # a secret rotation. Any match is a match, which is what makes rotating
        # possible without an outage.
        for part in signature_header.split():
            version, _, value = part.partition(",")
            if version != "v1" or not value:
                continue
            if any(hmac.compare_digest(value, candidate) for candidate in expected):
                return True
        return False

    def parse_event(self, headers: dict[str, str], raw: bytes) -> BillingEvent | None:
        if not self._verify(headers, raw):
            raise InvalidWebhookSignature("polar webhook signature did not verify")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Signed by us and still unparseable means the payload format is
            # wrong, which in practice means the endpoint was configured with
            # Polar's Discord or Slack format instead of Raw. Worth a loud log,
            # since it is authentic and completely unusable.
            logger.warning("polar webhook verified but body is not JSON: check the format is Raw")
            raise InvalidWebhookSignature("polar webhook body is not JSON") from None

        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return None
        if event_type not in _STATUS_BY_EVENT and event_type not in _PASSTHROUGH_EVENTS:
            # Polar sends far more than we act on, so this is the common case,
            # not an edge one. It returns None rather than raising, and the
            # route answers 200: an error here would let one extra ticked
            # checkbox in the Polar dashboard get the endpoint disabled.
            logger.info(f"polar event ignored: {event_type}")
            return None

        data = payload.get("data") or {}
        # An order event nests the subscription; a subscription event *is* it.
        # `or data` matters: an order with a null subscription would otherwise
        # give None here and every field lookup below would raise.
        nested = data.get("subscription")
        subscription = nested if isinstance(nested, dict) else data
        if not isinstance(subscription, dict):
            subscription = {}

        return BillingEvent(
            provider=self.key,
            tenant_id=self._tenant_id(data, subscription),
            # Standard Webhooks guarantees this is unique per delivery, and it
            # is what billing_events dedupes on. Merchants of record retry.
            event_id=self._event_id(headers, payload),
            type=event_type,
            status=_STATUS_BY_EVENT.get(event_type),
            plan_key=self._plan_key(subscription),
            subscription_id=_str_or_none(subscription.get("id")),
            customer_id=_str_or_none(subscription.get("customer_id")),
            current_period_end=_parse_time(subscription.get("current_period_end")),
        )

    @staticmethod
    def _event_id(headers: dict[str, str], payload: dict[str, Any]) -> str:
        lower = {k.lower(): v for k, v in headers.items()}
        # webhook-id first: it identifies the delivery, so a retry of the same
        # event dedupes correctly. The body id is a fallback for a hand-crafted
        # replay in a test.
        return str(lower.get("webhook-id") or payload.get("id") or "")

    @staticmethod
    def _tenant_id(data: dict[str, Any], subscription: dict[str, Any]) -> str | None:
        """Our own tenant id, echoed back through checkout metadata.

        Checked in several places for the same reason ``_plan_key`` is: Polar
        copies checkout metadata onto the objects it creates, but which object
        carries it depends on the event. An order event nests the subscription;
        a subscription event is the subscription; and a checkout may be attached
        to either.

        This is the only thing that makes a customer's *first* payment
        resolvable, since before it no ``subscriptions`` row exists for the
        provider ids to match.
        """
        for holder in (subscription, data, data.get("checkout") or {}):
            if not isinstance(holder, dict):
                continue
            metadata = holder.get("metadata")
            if isinstance(metadata, dict) and metadata.get("tenant_id"):
                return str(metadata["tenant_id"])
        return None

    @staticmethod
    def _plan_key(subscription: dict[str, Any]) -> str | None:
        """Which of our plans this subscription is, via the price map.

        Checked against several id fields because Polar's payload shape depends
        on the event, and a missing plan key silently leaves a tenant on their
        old entitlements after an upgrade they paid for.
        """
        candidates = [
            subscription.get("price_id"),
            subscription.get("product_id"),
            (subscription.get("price") or {}).get("id"),
            (subscription.get("product") or {}).get("id"),
        ]
        for prices in (subscription.get("prices") or []):
            if isinstance(prices, dict):
                candidates.append(prices.get("id"))
        for candidate in candidates:
            if not candidate:
                continue
            plan = plan_for_price_id(str(candidate))
            if plan is not None:
                return plan.key
        return None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value else None


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Naive timestamps would compare badly against the aware `now` in
    # service_state, so everything is normalised on the way in.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
