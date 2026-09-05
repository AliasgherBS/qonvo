"""Where uploaded knowledge files live, and how they are removed.

Uploads are written by the API and read by the worker, so the directory below
must be a volume shared by both containers — see the note on the `api` service
in docker-compose.yml. Without that, every file upload fails with
FileNotFoundError because the worker looks inside its own container.

Deletion matters as much as storage. A tenant's uploads are their price lists,
policy documents and contracts; leaving them on the volume after the tenant is
offboarded is a privacy problem before it is a disk problem.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger


def _root() -> Path:
    return Path(settings.knowledge_upload_dir)


def _segment(value: uuid.UUID | str) -> str:
    """One path segment, proven to be a UUID.

    These ids come from the database rather than from a request, so this is
    belt-and-braces — but a directory built by string concatenation is one
    refactor away from being attacker-controlled, and this module deletes trees.
    """
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"not a valid id for a storage path: {value!r}") from exc


def tenant_dir(tenant_id: uuid.UUID | str) -> Path:
    return _root() / _segment(tenant_id)


def source_dir(tenant_id: uuid.UUID | str, source_id: uuid.UUID | str) -> Path:
    return tenant_dir(tenant_id) / _segment(source_id)


def _purge(path: Path, **log_fields: object) -> None:
    # missing_ok by design: most sources are pasted text or a URL and have no
    # directory at all, and a delete must not half-complete because of that.
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        logger.bind(**log_fields).info("purged uploaded files")
    except OSError as exc:  # noqa: BLE001 — never block an offboarding on this
        logger.bind(**log_fields, error=str(exc)).warning("could not purge uploaded files")


def purge_source_files(tenant_id: uuid.UUID | str, source_id: uuid.UUID | str) -> None:
    """Remove one knowledge source's uploads."""
    _purge(
        source_dir(tenant_id, source_id),
        tenant_id=str(tenant_id),
        source_id=str(source_id),
    )


def purge_tenant_files(tenant_id: uuid.UUID | str) -> None:
    """Remove every upload a tenant owns. Called when the tenant is deleted."""
    _purge(tenant_dir(tenant_id), tenant_id=str(tenant_id))


__all__ = ["purge_source_files", "purge_tenant_files", "source_dir", "tenant_dir"]
