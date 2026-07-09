"""Portable column types.

``JSONBType`` is JSONB on Postgres and plain JSON on SQLite (used by the test
suite), so models import cleanly in both environments.
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONBType = JSONB().with_variant(JSON(), "sqlite")
