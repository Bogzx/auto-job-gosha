"""Tests for the feedback and user preference system."""

from __future__ import annotations

from collections import Counter

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gosha.feedback import (
    UserPreferenceProfile,
    _tokenize,
    build_user_profile,
    get_user_feedback_history,
    record_feedback,
)
from gosha.models import Job, User, UserJob


@pytest_asyncio.fixture
async def patched_db(engine, monkeypatch):
    import gosha.database as db_mod

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory


@pytest_asyncio.fixture
async def feedback_data(session: AsyncSession):
    """Create a user with jobs and deliveries for feedback testing."""
    user = User(discord_user_id=5001)
    session.add(user)
    await session.flush()

    jobs = []
    for i, (title, company, desc) in enumerate([
        ("Junior Python Developer", "TechCo", "Build APIs with Django and FastAPI. Python programming."),
        ("Senior Marketing Manager", "AdCorp", "Lead marketing campaigns and brand strategy."),
        ("Data Scientist Intern", "MLStartup", "Machine learning with Python, TensorFlow, PyTorch."),
        ("Sales Representative", "SellCo", "Cold calling and lead generation for B2B products."),
        ("Backend Engineer", "CloudInc", "Microservices with Python, Kubernetes, Docker."),
    ]):
        job = Job(
            url=f"https://test.com/job/{i}",
            title=title,
            company=company,
            description=desc,
            source="indeed",
            location="Cluj",
        )
        session.add(job)
        jobs.append(job)

    await session.flush()

    # Create user_jobs (deliveries)
    user_jobs = []
    for job in jobs:
        uj = UserJob(user_id=user.id, job_id=job.id)
        session.add(uj)
        user_jobs.append(uj)

    await session.commit()
    return {"user": user, "jobs": jobs, "user_jobs": user_jobs}


# ── _tokenize ─────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Junior Python Developer")
        assert "junior" in tokens
        assert "python" in tokens
        assert "developer" in tokens

    def test_removes_stopwords(self):
        tokens = _tokenize("the developer is working on a project")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "developer" in tokens

    def test_removes_urls(self):
        tokens = _tokenize("Apply at https://example.com/job for this role")
        assert "https" not in tokens
        assert "example" not in tokens
        assert "apply" in tokens

    def test_removes_short_tokens(self):
        tokens = _tokenize("a b cd efg")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens
        assert "efg" in tokens


# ── record_feedback ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_feedback_interested(patched_db, feedback_data):
    uj = feedback_data["user_jobs"][0]
    result = await record_feedback(uj.id, "interested")
    assert result is True


@pytest.mark.asyncio
async def test_record_feedback_not_relevant(patched_db, feedback_data):
    uj = feedback_data["user_jobs"][1]
    result = await record_feedback(uj.id, "not_relevant")
    assert result is True


@pytest.mark.asyncio
async def test_record_feedback_invalid(patched_db, feedback_data):
    uj = feedback_data["user_jobs"][0]
    result = await record_feedback(uj.id, "invalid_feedback")
    assert result is False


@pytest.mark.asyncio
async def test_record_feedback_nonexistent(patched_db):
    result = await record_feedback(99999, "interested")
    assert result is False


# ── get_user_feedback_history ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_feedback_history_empty(patched_db, feedback_data):
    user = feedback_data["user"]
    history = await get_user_feedback_history(user.id)
    assert len(history) == 0  # No feedback given yet


@pytest.mark.asyncio
async def test_feedback_history_after_feedback(patched_db, feedback_data):
    ujs = feedback_data["user_jobs"]
    user = feedback_data["user"]

    await record_feedback(ujs[0].id, "interested")
    await record_feedback(ujs[1].id, "not_relevant")

    history = await get_user_feedback_history(user.id)
    assert len(history) == 2

    feedbacks = {fb for _, fb in history}
    assert feedbacks == {"interested", "not_relevant"}


# ── UserPreferenceProfile ─────────────────────────────────────────────


class TestUserPreferenceProfile:
    def _make_job(self, title: str, company: str, desc: str) -> Job:
        return Job(
            url=f"https://x.com/{hash(title)}",
            title=title,
            company=company,
            description=desc,
            source="test",
            location="Test",
        )

    def test_empty_profile(self):
        profile = UserPreferenceProfile()
        assert profile.has_data is False
        job = self._make_job("Dev", "Co", "Stuff")
        assert profile.score_adjustment(job) == 0.0

    def test_needs_minimum_feedback(self):
        profile = UserPreferenceProfile()
        profile.total_positive = 1
        profile.total_negative = 1
        assert profile.has_data is False

        profile.total_positive = 2
        assert profile.has_data is True

    def test_from_feedback_positive(self):
        jobs_feedback = [
            (self._make_job("Python Developer", "TechCo", "Python Django APIs"), "interested"),
            (self._make_job("Python Engineer", "StartupX", "Python Flask microservices"), "interested"),
            (self._make_job("Sales Rep", "SellCo", "Cold calling B2B"), "not_relevant"),
        ]
        profile = UserPreferenceProfile.from_feedback(jobs_feedback)
        assert profile.total_positive == 2
        assert profile.total_negative == 1
        assert profile.has_data is True
        assert profile.positive_terms["python"] > 0

    def test_positive_job_boosted(self):
        jobs_feedback = [
            (self._make_job("Python Developer", "TechCo", "Python Django APIs backend"), "interested"),
            (self._make_job("Python Engineer", "CloudCo", "Python microservices backend"), "interested"),
            (self._make_job("Python Backend Dev", "StartupX", "Python APIs development"), "interested"),
            (self._make_job("Sales Rep", "SellCo", "Cold calling B2B sales"), "not_relevant"),
        ]
        profile = UserPreferenceProfile.from_feedback(jobs_feedback)

        # A Python job should get a positive adjustment
        python_job = self._make_job("Python Backend Developer", "NewCo", "Python REST API development")
        adj = profile.score_adjustment(python_job)
        assert adj > 0

        # A Sales job should get a negative adjustment
        sales_job = self._make_job("Sales Manager", "BizCo", "Sales strategy and cold calling")
        adj_sales = profile.score_adjustment(sales_job)
        assert adj_sales < adj  # Sales should be boosted less (or penalized)

    def test_company_preference(self):
        jobs_feedback = [
            (self._make_job("Dev", "Google", "Programming"), "interested"),
            (self._make_job("Dev", "Google", "Engineering"), "interested"),
            (self._make_job("Dev", "Google", "Building"), "interested"),
            (self._make_job("Dev", "SpamCorp", "Spam stuff"), "not_relevant"),
        ]
        profile = UserPreferenceProfile.from_feedback(jobs_feedback)

        assert profile.positive_companies["google"] == 3
        assert profile.negative_companies["spamcorp"] == 1

    def test_adjustment_clamped(self):
        profile = UserPreferenceProfile()
        # Even with extreme data, adjustment should be clamped
        profile.positive_terms = Counter({"python": 1000})
        profile.total_positive = 100
        profile.total_negative = 1

        job = self._make_job("Python Python Python", "Co", "Python")
        adj = profile.score_adjustment(job)
        assert -0.3 <= adj <= 0.3


# ── build_user_profile (integration) ──────────────────────────────────


@pytest.mark.asyncio
async def test_build_user_profile(patched_db, feedback_data):
    ujs = feedback_data["user_jobs"]
    user = feedback_data["user"]

    # Give feedback on enough jobs
    await record_feedback(ujs[0].id, "interested")  # Python Developer
    await record_feedback(ujs[2].id, "interested")  # Data Scientist
    await record_feedback(ujs[1].id, "not_relevant")  # Marketing Manager

    profile = await build_user_profile(user.id)
    assert profile.has_data is True
    assert profile.total_positive == 2
    assert profile.total_negative == 1
    assert profile.positive_terms["python"] > 0
