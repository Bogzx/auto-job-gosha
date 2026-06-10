"""Tests for the CV-based recommendation engine (fake vectors, no model)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from gosha import recommend
from gosha.embeddings import EMBEDDING_DIM, vec_to_bytes
from gosha.models import Application, Job, User, UserJob


def unit_vec(axis: int) -> np.ndarray:
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v[axis] = 1.0
    return v


def make_job(url: str, axis: int | None, **kwargs) -> Job:
    job = Job(
        url=url,
        title=kwargs.pop("title", "Dev"),
        company=kwargs.pop("company", "Acme"),
        source=kwargs.pop("source", "indeed"),
        **kwargs,
    )
    if axis is not None:
        job.embedding = vec_to_bytes(unit_vec(axis))
    return job


@pytest.mark.asyncio
async def test_feed_ranks_by_cosine(patched_db, session: AsyncSession):
    user = User(discord_user_id=1, cv_embedding=vec_to_bytes(unit_vec(0)))
    session.add(user)
    job_a = make_job("https://r.com/a", 0, title="Python Dev")
    job_b = make_job("https://r.com/b", 1, title="Accountant")
    session.add_all([job_a, job_b])
    await session.commit()

    items, total = await recommend.get_feed(user.id, page=1, per_page=10)

    assert total == 2
    assert [j.id for j, _, _ in items] == [job_a.id, job_b.id]
    assert items[0][1] > 0.9
    assert items[1][1] < 0.1


@pytest.mark.asyncio
async def test_feed_feedback_refinement(patched_db, session: AsyncSession):
    """Without a CV, liked jobs steer the user vector."""
    user = User(discord_user_id=2)
    session.add(user)
    liked = make_job("https://r.com/liked", 1)
    session.add(liked)
    await session.flush()
    session.add(
        UserJob(user_id=user.id, job_id=liked.id, feedback="interested")
    )
    cand_match = make_job("https://r.com/m", 1, title="Like the liked one")
    cand_other = make_job("https://r.com/o", 2, title="Different")
    session.add_all([cand_match, cand_other])
    await session.commit()

    items, _ = await recommend.get_feed(user.id, page=1, per_page=10)

    ids = [j.id for j, _, _ in items]
    # The liked job itself has feedback → excluded from the feed
    assert liked.id not in ids
    assert ids[0] == cand_match.id


@pytest.mark.asyncio
async def test_feed_excludes_not_relevant_and_applied(patched_db, session: AsyncSession):
    user = User(discord_user_id=3, cv_embedding=vec_to_bytes(unit_vec(0)))
    session.add(user)
    bad = make_job("https://r.com/bad", 0)
    applied = make_job("https://r.com/applied", 0)
    fresh = make_job("https://r.com/fresh", 0)
    session.add_all([bad, applied, fresh])
    await session.flush()
    session.add_all([
        UserJob(user_id=user.id, job_id=bad.id, feedback="not_relevant"),
        Application(user_id=user.id, job_id=applied.id, source="web"),
    ])
    await session.commit()

    items, total = await recommend.get_feed(user.id, page=1, per_page=10)
    ids = [j.id for j, _, _ in items]
    assert ids == [fresh.id]
    assert total == 1


@pytest.mark.asyncio
async def test_feed_fallback_recency_without_signal(patched_db, session: AsyncSession):
    """No CV, no feedback -> newest-first with null scores."""
    user = User(discord_user_id=4)
    session.add(user)
    now = datetime.now(timezone.utc)
    old = make_job("https://r.com/old", None)
    old.first_seen_at = now - timedelta(days=5)
    new = make_job("https://r.com/new", None)
    new.first_seen_at = now
    session.add_all([old, new])
    await session.commit()

    items, total = await recommend.get_feed(user.id, page=1, per_page=10)

    assert total == 2
    assert [j.id for j, _, _ in items] == [new.id, old.id]
    assert all(score is None for _, score, _ in items)


@pytest.mark.asyncio
async def test_feed_skips_stale_jobs(patched_db, session: AsyncSession):
    user = User(discord_user_id=5, cv_embedding=vec_to_bytes(unit_vec(0)))
    session.add(user)
    stale = make_job("https://r.com/stale", 0)
    stale.first_seen_at = datetime.now(timezone.utc) - timedelta(days=45)
    session.add(stale)
    await session.commit()

    items, total = await recommend.get_feed(user.id, page=1, per_page=10)
    assert items == [] and total == 0


@pytest.mark.asyncio
async def test_feed_pagination(patched_db, session: AsyncSession):
    user = User(discord_user_id=6, cv_embedding=vec_to_bytes(unit_vec(0)))
    session.add(user)
    for i in range(7):
        session.add(make_job(f"https://r.com/p{i}", 0))
    await session.commit()

    page1, total = await recommend.get_feed(user.id, page=1, per_page=3)
    page2, _ = await recommend.get_feed(user.id, page=2, per_page=3)
    page3, _ = await recommend.get_feed(user.id, page=3, per_page=3)

    assert total == 7
    assert len(page1) == 3 and len(page2) == 3 and len(page3) == 1
    all_ids = [j.id for j, _, _ in page1 + page2 + page3]
    assert len(set(all_ids)) == 7


def test_match_reasons_overlap():
    cv = "Experienced with Python, React and Docker deployments"
    jd = "We need Python and Docker skills. Docker is used daily, Kubernetes a plus"
    reasons = recommend.match_reasons(cv, jd)
    assert set(reasons) >= {"python", "docker"}
    # Docker appears twice in the JD -> ranked first
    assert reasons[0] == "docker"


def test_match_reasons_ignores_stopwords():
    cv = "I have experience and skills with the best team"
    jd = "We are the best team with experience and skills"
    reasons = recommend.match_reasons(cv, jd)
    assert "and" not in reasons
    assert "the" not in reasons
    assert "with" not in reasons
