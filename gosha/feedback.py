"""User feedback system — learns preferences from Interested/Not Relevant reactions.

Builds a per-user preference profile that adjusts future matching scores.
Uses a simple TF-IDF + logistic regression model trained on the user's
feedback history.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from gosha.database import get_session
from gosha.models import Job, UserJob

log = logging.getLogger(__name__)


async def record_feedback(
    user_job_id: int,
    feedback: str,
) -> bool:
    """Record user feedback on a delivered job.

    Args:
        user_job_id: The UserJob record ID.
        feedback: "interested" or "not_relevant".

    Returns:
        True if feedback was recorded, False if not found.
    """
    if feedback not in ("interested", "not_relevant"):
        return False

    async with get_session() as session:
        result = await session.execute(
            select(UserJob).where(UserJob.id == user_job_id)
        )
        uj = result.scalar_one_or_none()
        if uj is None:
            return False

        uj.feedback = feedback
        uj.feedback_at = datetime.now(timezone.utc)
        await session.commit()

        # Emit event (best-effort)
        try:
            from gosha.events import emit_user_feedback
            await emit_user_feedback(uj.job_id, uj.user_id, feedback)
        except Exception:
            pass

        return True


async def get_user_feedback_history(
    user_id: int,
) -> list[tuple[Job, str]]:
    """Get all jobs a user has given feedback on.

    Returns list of (Job, feedback_string) tuples.
    """
    async with get_session() as session:
        result = await session.execute(
            select(Job, UserJob.feedback)
            .join(UserJob, UserJob.job_id == Job.id)
            .where(
                UserJob.user_id == user_id,
                UserJob.feedback != None,  # noqa: E711
            )
        )
        return [(job, fb) for job, fb in result.all()]


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer for building preference profiles."""
    text = text.lower()
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Keep only alphanumeric and spaces
    text = re.sub(r"[^a-z0-9\s+#.]", " ", text)
    words = text.split()
    # Filter stopwords and very short tokens
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "shall",
        "can", "this", "that", "these", "those", "it", "its", "we",
        "you", "they", "our", "your", "their", "my", "his", "her",
        "from", "as", "not", "no", "so", "if", "about", "up", "out",
        "all", "some", "any", "each", "every", "more", "most", "other",
    }
    return [w for w in words if len(w) >= 2 and w not in stopwords]


class UserPreferenceProfile:
    """Lightweight preference model built from feedback history.

    Tracks which terms appear more in "interested" vs "not_relevant" jobs.
    Produces a score adjustment that can boost or penalize candidate jobs.
    """

    def __init__(self) -> None:
        self.positive_terms: Counter = Counter()
        self.negative_terms: Counter = Counter()
        self.positive_companies: Counter = Counter()
        self.negative_companies: Counter = Counter()
        self.total_positive: int = 0
        self.total_negative: int = 0

    @classmethod
    def from_feedback(
        cls, feedback_history: list[tuple[Job, str]]
    ) -> UserPreferenceProfile:
        """Build a preference profile from a user's feedback history."""
        profile = cls()

        for job, feedback in feedback_history:
            text = f"{job.title} {job.description or ''}"
            tokens = _tokenize(text)
            company = job.company.lower().strip() if job.company else ""

            if feedback == "interested":
                profile.positive_terms.update(tokens)
                if company and company != "unknown":
                    profile.positive_companies[company] += 1
                profile.total_positive += 1
            elif feedback == "not_relevant":
                profile.negative_terms.update(tokens)
                if company and company != "unknown":
                    profile.negative_companies[company] += 1
                profile.total_negative += 1

        return profile

    @property
    def has_data(self) -> bool:
        """True if we have enough feedback to adjust scores."""
        return (self.total_positive + self.total_negative) >= 3

    def score_adjustment(self, job: Job) -> float:
        """Calculate a score adjustment for a candidate job.

        Returns a value between -0.3 and +0.3 that should be added
        to the base relevance score.
        """
        if not self.has_data:
            return 0.0

        text = f"{job.title} {job.description or ''}"
        tokens = _tokenize(text)
        company = job.company.lower().strip() if job.company else ""

        if not tokens:
            return 0.0

        # Term-based signal
        pos_hits = sum(self.positive_terms.get(t, 0) for t in tokens)
        neg_hits = sum(self.negative_terms.get(t, 0) for t in tokens)

        total_hits = pos_hits + neg_hits
        if total_hits == 0:
            term_signal = 0.0
        else:
            # Range: -1.0 to +1.0
            term_signal = (pos_hits - neg_hits) / total_hits

        # Company-based signal
        company_signal = 0.0
        if company and company != "unknown":
            pos_c = self.positive_companies.get(company, 0)
            neg_c = self.negative_companies.get(company, 0)
            total_c = pos_c + neg_c
            if total_c > 0:
                company_signal = (pos_c - neg_c) / total_c

        # Weighted combination (terms matter more than company alone)
        raw = 0.7 * term_signal + 0.3 * company_signal

        # Clamp to [-0.3, +0.3]
        return max(-0.3, min(0.3, raw * 0.3))


async def build_user_profile(user_id: int) -> UserPreferenceProfile:
    """Build a preference profile from a user's feedback history in the DB."""
    history = await get_user_feedback_history(user_id)
    return UserPreferenceProfile.from_feedback(history)
