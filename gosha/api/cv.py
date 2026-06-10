"""CV upload and management for the web platform.

Reuses the bot's CV storage (gosha/cover_letter.py) so a CV uploaded on
the web works for Discord cover letters and vice versa. Uploading also
(re)computes the user's CV embedding that powers the personalized feed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile

import gosha.cover_letter as cl
from gosha.api.deps import ApiError, current_user
from gosha.api.schemas import OkOut
from gosha.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cv", tags=["cv"])

MAX_CV_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


def _cv_response(user_id: int) -> dict:
    text = cl.load_cv(user_id)
    uploaded_at = None
    if text is not None:
        path = cl.get_cv_path(user_id)
        try:
            uploaded_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            pass
    return {"has_cv": text is not None, "text": text, "uploaded_at": uploaded_at}


@router.get("")
async def get_cv(user: User = Depends(current_user)) -> dict:
    return _cv_response(user.id)


@router.put("")
async def upload_cv(file: UploadFile, user: User = Depends(current_user)) -> dict:
    filename = file.filename or "cv"
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise ApiError(
            422,
            "invalid_request",
            "Supported CV formats: PDF, DOCX, TXT, MD.",
        )

    content = await file.read()
    if len(content) > MAX_CV_BYTES:
        raise ApiError(413, "file_too_large", "CV files can be at most 5 MB.")

    text = cl.extract_text(filename, content)
    if not text or not text.strip():
        raise ApiError(
            422,
            "invalid_request",
            "Couldn't read any text from that file — try a different format.",
        )

    cl.save_cv(user.id, text)

    # Refresh the personalization vector (best-effort: feed falls back
    # gracefully when the embedding model is unavailable)
    try:
        from gosha.embeddings import embed_user_cv
        await embed_user_cv(user.id, text)
    except Exception as exc:
        log.warning("CV embedding failed for user %d: %s", user.id, exc)

    return _cv_response(user.id)


@router.delete("", response_model=OkOut)
async def delete_cv(user: User = Depends(current_user)) -> OkOut:
    cl.delete_cv(user.id)
    try:
        from gosha.embeddings import clear_user_cv_embedding
        await clear_user_cv_embedding(user.id)
    except Exception as exc:
        log.warning("CV embedding cleanup failed for user %d: %s", user.id, exc)
    return OkOut()
