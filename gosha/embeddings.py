"""Job and CV embeddings stored as float32 bytes on the row.

Vectors come from the same sentence-transformers model the semantic matcher
uses (lazy singleton in gosha/matching.py). At the current scale (thousands
of jobs) numpy brute-force cosine scoring beats running a vector database.
"""

from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import select

from gosha.database import get_session
from gosha.matching import build_job_text
from gosha.matching import encode_texts as _encode_texts
from gosha.models import Job, User

log = logging.getLogger(__name__)

EMBEDDING_DIM = 768  # all-mpnet-base-v2
DEFAULT_BATCH = 500


def encode_texts(texts: list[str]) -> np.ndarray | None:
    """Encode texts with the shared semantic model. None when unavailable."""
    return _encode_texts(texts)


def vec_to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def bytes_to_vec(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


async def embed_new_jobs(limit: int = DEFAULT_BATCH) -> int:
    """Embed up to `limit` active jobs that have no embedding yet.

    Returns the number of jobs embedded (0 when the model is unavailable).
    """
    async with get_session() as session:
        result = await session.execute(
            select(Job)
            .where(Job.embedding.is_(None), Job.is_active.is_(True))
            .limit(limit)
        )
        jobs = list(result.scalars().all())

        if not jobs:
            return 0

        texts = [build_job_text(j.title, j.company, j.description) for j in jobs]
        vectors = encode_texts(texts)
        if vectors is None:
            log.debug("Embedding model unavailable — skipping %d jobs", len(jobs))
            return 0

        for job, vec in zip(jobs, vectors):
            job.embedding = vec_to_bytes(vec)
        await session.commit()

    log.info("Embedded %d jobs", len(jobs))
    return len(jobs)


def score_jobs_against_query(query_vec: np.ndarray, jobs: list[Job]) -> list[float]:
    """Cosine scores of jobs vs a query vector, reusing stored embeddings.

    Jobs without a stored vector are encoded on the fly (one batch); when
    the model is unavailable they score 0.0. This is what lets the match
    stage avoid re-encoding the same postings for every subscription.
    """
    if not jobs:
        return []

    vectors: list[np.ndarray | None] = [
        bytes_to_vec(job.embedding) if job.embedding else None for job in jobs
    ]

    missing = [i for i, vec in enumerate(vectors) if vec is None]
    if missing:
        texts = [
            build_job_text(jobs[i].title, jobs[i].company, jobs[i].description)
            for i in missing
        ]
        encoded = encode_texts(texts)
        if encoded is not None:
            for idx, vec in zip(missing, encoded):
                vectors[idx] = np.asarray(vec, dtype=np.float32)

    return [
        float(vec @ query_vec) if vec is not None else 0.0
        for vec in vectors
    ]


async def embed_user_cv(user_id: int, cv_text: str) -> bool:
    """Compute and store the embedding of a user's CV text."""
    vectors = encode_texts([cv_text[:8000]])
    if vectors is None:
        return False

    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return False
        user.cv_embedding = vec_to_bytes(vectors[0])
        await session.commit()
    return True


async def clear_user_cv_embedding(user_id: int) -> None:
    """Remove the stored CV embedding (CV deleted)."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.cv_embedding = None
            await session.commit()
