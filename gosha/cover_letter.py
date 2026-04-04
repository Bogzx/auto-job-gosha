"""AI cover letter generation using the free Google Gemini API.

Flow:
  1. User uploads CV once (/upload_cv) — stored as plain text.
  2. User requests a cover letter for a specific job (/cover_letter <job_id>).
  3. This module sends CV + job details to Gemini and returns the letter.
  4. The letter is stored in the DB so it can be retrieved later.

Requires: GEMINI_API_KEY env var (free tier from https://aistudio.google.com/apikey)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from gosha.database import get_session
from gosha.models import CoverLetter, Job, User

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemma-4-31b-it",
]

# CV storage directory
CV_DIR = Path(__file__).resolve().parent.parent / "data" / "cvs"


# ---------------------------------------------------------------------------
# CV management
# ---------------------------------------------------------------------------


def get_cv_path(user_id: int) -> Path:
    """Return the path where a user's CV text is stored."""
    return CV_DIR / f"{user_id}.txt"


def save_cv(user_id: int, text: str) -> Path:
    """Save CV text to disk. Creates the directory if needed."""
    CV_DIR.mkdir(parents=True, exist_ok=True)
    path = get_cv_path(user_id)
    path.write_text(text, encoding="utf-8")
    return path


def load_cv(user_id: int) -> str | None:
    """Load a user's CV text. Returns None if not uploaded."""
    path = get_cv_path(user_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def delete_cv(user_id: int) -> bool:
    """Delete a user's stored CV. Returns True if it existed."""
    path = get_cv_path(user_id)
    if path.exists():
        path.unlink()
        return True
    return False


def _clean_pdf_text(text: str) -> str:
    """Clean up common PDF extraction artifacts from LaTeX CVs."""
    # Remove LaTeX \csuse{...} icon commands
    text = re.sub(r"\\csuse\s*\{[^}]*\}:?\s*", "", text)
    # Remove Unicode Private Use Area chars (icon fonts like FontAwesome)
    text = re.sub(r"[\ue000-\uf8ff\U000f0000-\U000ffffd]", "", text)
    # Remove stray icon-font remnants (single non-ASCII symbols on contact lines)
    text = re.sub(r"^[#§ï*]\s+", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def extract_text_from_attachment(attachment) -> str | None:
    """Extract text from a Discord attachment (PDF or plain text).

    For PDFs, tries PyPDF2/pypdf. For .txt/.md, reads directly.
    Returns None on failure.
    """
    filename = attachment.filename.lower()
    content = await attachment.read()

    if filename.endswith(".txt") or filename.endswith(".md"):
        return content.decode("utf-8", errors="replace")

    if filename.endswith(".pdf"):
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            pages = [page.get_text() for page in doc]
            text = "\n".join(pages).strip()
            text = _clean_pdf_text(text)
            return text if text else None
        except ImportError:
            log.warning("pymupdf not installed — cannot extract PDF text. Install with: pip install pymupdf")
            return None
        except Exception as exc:
            log.error("PDF extraction failed: %s", exc)
            return None

    if filename.endswith(".docx"):
        try:
            import io
            import zipfile
            import xml.etree.ElementTree as ET

            # Minimal .docx text extraction without python-docx dependency
            zf = zipfile.ZipFile(io.BytesIO(content))
            xml_content = zf.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            texts = [node.text for node in tree.iter(f"{{{ns['w']}}}t") if node.text]
            return " ".join(texts).strip() or None
        except Exception as exc:
            log.error("DOCX extraction failed: %s", exc)
            return None

    return None


# ---------------------------------------------------------------------------
# Monthly usage tracking
# ---------------------------------------------------------------------------


async def get_monthly_usage(user_id: int) -> int:
    """Return the number of cover letters generated this calendar month."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        result = await session.execute(
            select(func.count(CoverLetter.id)).where(
                CoverLetter.user_id == user_id,
                CoverLetter.created_at >= month_start,
            )
        )
        return result.scalar() or 0


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


async def _call_gemini(prompt: str) -> str | None:
    """Call the Gemini API, trying each model in GEMINI_MODELS until one succeeds."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set — cover letter generation unavailable")
        return None

    try:
        import httpx
    except ImportError:
        log.error("httpx not installed — Gemini API unavailable")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in GEMINI_MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            try:
                resp = await client.post(url, json=payload)

                if resp.status_code == 429:
                    log.warning("Gemini model %s rate-limited (429) — trying next", model)
                    continue

                if resp.status_code != 200:
                    log.error("Gemini API error %d for %s: %s", resp.status_code, model, resp.text[:500])
                    continue

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    log.error("Gemini %s returned no candidates: %s", model, data)
                    continue

                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    continue

                log.info("Cover letter generated using model: %s", model)
                return parts[0].get("text", "").strip()

            except Exception as exc:
                log.error("Gemini API call failed for %s: %s", model, exc)
                continue

    log.error("All Gemini models exhausted — cover letter generation failed")
    return None


# ---------------------------------------------------------------------------
# Cover letter generation
# ---------------------------------------------------------------------------


def _build_prompt(cv_text: str, job: Job) -> str:
    """Build the prompt for Gemini combining CV + job details."""
    job_info = f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location or 'Not specified'}"
    if job.description:
        # Limit description to prevent token overflow
        desc = job.description[:3000]
        job_info += f"\n\nJob Description:\n{desc}"
    if job.salary_min or job.salary_max:
        parts = []
        if job.salary_min:
            parts.append(f"{job.salary_min:,.0f}")
        if job.salary_max:
            parts.append(f"{job.salary_max:,.0f}")
        salary = " - ".join(parts)
        if job.salary_currency:
            salary += f" {job.salary_currency}"
        job_info += f"\nSalary: {salary}"

    return f"""You are a professional career coach helping a computer science student write a cover letter.

Given the candidate's CV and a job posting, write a concise, professional cover letter (250-350 words).

Rules:
- Be specific: reference actual skills/experience from the CV that match the job requirements
- Be natural: avoid generic phrases like "I am excited to apply" or "I am a passionate individual"
- Be honest: don't fabricate experience, but highlight transferable skills
- Match the tone to the company (startup = casual, corporate = formal)
- Include a clear opening, 2-3 body paragraphs connecting CV to job, and a brief closing
- Do NOT include the date, addresses, or "Dear Hiring Manager" header — just the letter body
- Write in English unless the job description is in another language

---

CANDIDATE CV:
{cv_text[:15000]}

---

JOB POSTING:
{job_info}

---

Write the cover letter now:"""


async def generate_cover_letter(
    user_id: int, job_id: int, *, force_regenerate: bool = False,
) -> tuple[str | None, bool]:
    """Generate a cover letter for a user + job pair.

    Returns (content, was_cached) — content is None on failure.
    Stores the result in the DB for later retrieval.
    If force_regenerate is True, deletes any existing cached letter first.
    """
    # Check for existing cover letter
    async with get_session() as session:
        existing = await session.execute(
            select(CoverLetter).where(
                CoverLetter.user_id == user_id,
                CoverLetter.job_id == job_id,
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            # Auto-expire cached letters older than 30 days
            age_days = (datetime.now(timezone.utc) - found.created_at).days if found.created_at else 999
            if not force_regenerate and age_days < 30:
                return found.content, True
            # Stale or force-regenerate: delete and recreate
            await session.delete(found)
            await session.commit()

    # Load CV
    cv_text = load_cv(user_id)
    if not cv_text:
        return None, False

    # Load job
    async with get_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return None, False

    # Generate
    prompt = _build_prompt(cv_text, job)
    content = await _call_gemini(prompt)
    if not content:
        return None, False

    # Cap at 3900 chars to stay within Discord's 4096 embed description limit
    if len(content) > 3900:
        content = content[:3900] + "\n\n[Trimmed for length]"

    # Store
    async with get_session() as session:
        cl = CoverLetter(user_id=user_id, job_id=job_id, content=content)
        session.add(cl)
        await session.commit()

    log.info("Generated cover letter for user %d, job %d (%d chars)", user_id, job_id, len(content))
    return content, False
