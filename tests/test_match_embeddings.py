"""Tests for stored-embedding reuse in the match stage."""

from __future__ import annotations

import numpy as np
import pytest

from gosha import embeddings
from gosha.embeddings import EMBEDDING_DIM, vec_to_bytes
from gosha.models import Job


def unit_vec(axis: int) -> np.ndarray:
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v[axis] = 1.0
    return v


def make_job(url: str, axis: int | None) -> Job:
    job = Job(url=url, title=f"Job {url}", company="A", source="indeed")
    if axis is not None:
        job.embedding = vec_to_bytes(unit_vec(axis))
    return job


def test_score_jobs_uses_stored_vectors(monkeypatch):
    """Jobs with stored embeddings must not be re-encoded."""
    def exploding_encode(texts):
        raise AssertionError(f"should not re-encode, got {texts}")

    monkeypatch.setattr(embeddings, "encode_texts", exploding_encode)

    jobs = [make_job("a", 0), make_job("b", 1)]
    query = unit_vec(0)

    scores = embeddings.score_jobs_against_query(query, jobs)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)


def test_score_jobs_encodes_only_missing(monkeypatch):
    encoded: list[list[str]] = []

    def fake_encode(texts):
        encoded.append(list(texts))
        return np.stack([unit_vec(2) for _ in texts])

    monkeypatch.setattr(embeddings, "encode_texts", fake_encode)

    jobs = [make_job("stored", 2), make_job("missing", None)]
    scores = embeddings.score_jobs_against_query(unit_vec(2), jobs)

    assert len(encoded) == 1 and len(encoded[0]) == 1  # only the missing one
    assert scores == pytest.approx([1.0, 1.0])


def test_score_jobs_handles_unavailable_model(monkeypatch):
    monkeypatch.setattr(embeddings, "encode_texts", lambda texts: None)

    jobs = [make_job("stored", 0), make_job("missing", None)]
    scores = embeddings.score_jobs_against_query(unit_vec(0), jobs)

    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == 0.0  # unencodable -> no match signal
