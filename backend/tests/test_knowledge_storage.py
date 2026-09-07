"""Uploaded files must go away when their owner does.

Deleting a tenant purges 23 database tables, but the documents they uploaded
live on a volume, and nothing was removing them. That is a privacy problem
before it is a disk problem: a business offboards, and their price lists and
policy documents stay on the server indefinitely.
"""

from __future__ import annotations

import uuid

import pytest
from app.agent.storage import purge_source_files, purge_tenant_files, source_dir, tenant_dir


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    from app.agent import storage

    monkeypatch.setattr(storage.settings, "knowledge_upload_dir", str(tmp_path))
    return tmp_path


def _seed(root, tenant_id, source_id, name="doc.txt"):
    d = root / str(tenant_id) / str(source_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("secret price list")
    return d


# --- paths ------------------------------------------------------------------ #
def test_paths_are_scoped_by_tenant_then_source(upload_root):
    tid, sid = uuid.uuid4(), uuid.uuid4()

    assert tenant_dir(tid) == upload_root / str(tid)
    assert source_dir(tid, sid) == upload_root / str(tid) / str(sid)


def test_a_tenant_id_cannot_escape_the_upload_root(upload_root):
    """The ids come from the database, not from a request, but a path built by
    string concatenation is one refactor away from being attacker-controlled."""
    with pytest.raises(ValueError):
        tenant_dir("../../etc")


# --- deleting ---------------------------------------------------------------- #
def test_purging_a_source_removes_only_that_source(upload_root):
    tid = uuid.uuid4()
    keep, drop = uuid.uuid4(), uuid.uuid4()
    _seed(upload_root, tid, keep)
    _seed(upload_root, tid, drop)

    purge_source_files(tid, drop)

    assert (upload_root / str(tid) / str(keep)).exists()
    assert not (upload_root / str(tid) / str(drop)).exists()


def test_purging_a_tenant_removes_every_upload_it_owns(upload_root):
    tid, other = uuid.uuid4(), uuid.uuid4()
    _seed(upload_root, tid, uuid.uuid4())
    _seed(upload_root, tid, uuid.uuid4())
    _seed(upload_root, other, uuid.uuid4())

    purge_tenant_files(tid)

    assert not (upload_root / str(tid)).exists()
    assert (upload_root / str(other)).exists(), "purged a different tenant's files"


def test_purging_what_was_never_uploaded_is_not_an_error(upload_root):
    """Most tenants never upload a file. Offboarding them must not fail, and
    must not be the reason a delete only half-completes."""
    purge_tenant_files(uuid.uuid4())
    purge_source_files(uuid.uuid4(), uuid.uuid4())


def test_purging_never_removes_the_root_itself(upload_root):
    purge_tenant_files(uuid.uuid4())

    assert upload_root.exists()
