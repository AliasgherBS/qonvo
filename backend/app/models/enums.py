"""Enumerations used across the data model (DESIGN.md §5, §11)."""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    owner = "owner"
    staff = "staff"


class SessionStatus(enum.StrEnum):
    """Mirrors the WAHA session lifecycle (DESIGN.md §1)."""

    stopped = "STOPPED"
    starting = "STARTING"
    scan_qr_code = "SCAN_QR_CODE"
    working = "WORKING"
    failed = "FAILED"


class ConversationState(enum.StrEnum):
    """Human-takeover state machine (DESIGN.md §5.5)."""

    bot_active = "bot_active"
    paused_by_agent = "paused_by_agent"
    paused_by_owner = "paused_by_owner"
    needs_human = "needs_human"


class MessageDirection(enum.StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class MessageAuthor(enum.StrEnum):
    customer = "customer"
    bot = "bot"
    human = "human"


class MessageType(enum.StrEnum):
    text = "text"
    voice = "voice"
    image = "image"
    file = "file"
    location = "location"
    other = "other"


class KnowledgeSourceType(enum.StrEnum):
    manual = "manual"
    file = "file"
    website = "website"


class HandoffStatus(enum.StrEnum):
    open = "open"
    resolved = "resolved"


class NotificationType(enum.StrEnum):
    escalation = "escalation"
    disconnect = "disconnect"
    quota_warning = "quota_warning"
    session_failed = "session_failed"


class BookingStatus(enum.StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
