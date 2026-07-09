"""Per-conversation Redis lock for serialized processing (DESIGN.md §5.3).

One conversation = one job at a time. A worker that cannot acquire the lock
re-enqueues its job with a delay rather than blocking, guaranteeing ordered
replies and preventing doubled tool calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import redis.asyncio as redis

# Lua: release only if we still own the lock (compare-and-delete).
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def lock_key(conversation_id: str) -> str:
    return f"conv:lock:{conversation_id}"


@dataclass(slots=True)
class ConversationLock:
    """A held (or not) conversation lock with a fencing token."""

    client: redis.Redis
    conversation_id: str
    token: str
    acquired: bool

    async def release(self) -> bool:
        """Release iff we still hold it. Safe to call when not acquired."""
        if not self.acquired:
            return False
        released = await self.client.eval(
            _RELEASE_SCRIPT, 1, lock_key(self.conversation_id), self.token
        )
        self.acquired = False
        return bool(released)

    async def __aenter__(self) -> ConversationLock:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.release()


async def acquire_conversation_lock(
    client: redis.Redis,
    conversation_id: str,
    *,
    ttl_ms: int,
) -> ConversationLock:
    """Attempt ``SET NX PX``. The returned lock's ``acquired`` says whether we won."""
    token = uuid.uuid4().hex
    ok = await client.set(lock_key(conversation_id), token, nx=True, px=ttl_ms)
    return ConversationLock(
        client=client,
        conversation_id=conversation_id,
        token=token,
        acquired=bool(ok),
    )


__all__ = ["ConversationLock", "acquire_conversation_lock", "lock_key"]
