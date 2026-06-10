"""Tests for the embeddings module (fake encoder — never loads the real model)."""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gosha import embeddings
from gosha.models import Job, User


def fake_encode(texts: list[str]) -> np.ndarray:
    """Deterministic stand-in: vector filled with the text length."""
    out = np.stack(
        [np.full(embeddings.EMBEDDING_DIM, float(len(t)), dtype=np.float32) for t in texts]
    )
    return out


def test_vec_roundtrip():
    v = np.random.rand(embeddings.EMBEDDING_DIM).astype(np.float32)
    restored = embeddings.bytes_to_vec(embeddings.vec_to_bytes(v))
    assert restored.dtype == np.float32
    assert np.allclose(restored, v)


@pytest.mark.asyncio
async def test_embed_new_jobs_fills_missing(patched_db, session: AsyncSession, monkeypatch):
    monkeypatch.setattr(embeddings, "encode_texts", fake_encode)

    j1 = Job(url="https://e.com/1", title="Python Dev", company="A", source="indeed")
    j2 = Job(url="https://e.com/2", title="QA Intern", company="B", source="linkedin")
    j3 = Job(
        url="https://e.com/3", title="Done", company="C", source="indeed",
        embedding=b"\x00" * 4,
    )
    session.add_all([j1, j2, j3])
    await session.commit()

    n = await embeddings.embed_new_jobs()
    assert n == 2

    result = await session.execute(select(Job).where(Job.embedding.is_(None)))
    assert result.scalars().all() == []

    refreshed = (
        await session.execute(select(Job).where(Job.url == "https://e.com/1"))
    ).scalar_one()
    await session.refresh(refreshed)
    vec = embeddings.bytes_to_vec(refreshed.embedding)
    assert vec.shape == (embeddings.EMBEDDING_DIM,)


@pytest.mark.asyncio
async def test_embed_new_jobs_noop_without_model(patched_db, session, monkeypatch):
    monkeypatch.setattr(embeddings, "encode_texts", lambda texts: None)

    session.add(Job(url="https://e.com/n", title="X", company="Y", source="indeed"))
    await session.commit()

    assert await embeddings.embed_new_jobs() == 0


@pytest.mark.asyncio
async def test_embed_user_cv(patched_db, session, monkeypatch):
    monkeypatch.setattr(embeddings, "encode_texts", fake_encode)

    user = User(discord_user_id=77)
    session.add(user)
    await session.commit()

    ok = await embeddings.embed_user_cv(user.id, "Python, React, Docker experience")
    assert ok is True

    await session.refresh(user)
    assert user.cv_embedding is not None
    vec = embeddings.bytes_to_vec(user.cv_embedding)
    assert vec.shape == (embeddings.EMBEDDING_DIM,)
