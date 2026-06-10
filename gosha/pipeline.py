"""Job-centric pipeline with three decoupled stages.

Stage 1 — SCRAPE:  Fetch from job boards, upsert into Job table.
Stage 2 — MATCH:   For each subscription, score jobs, enqueue deliveries.
Stage 3 — DELIVER: Pull from delivery queue, send via channels (Discord DM, etc.).

Each stage can run independently. The DB is the glue between them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import select

from gosha.database import get_session
from gosha.filters import (
    filter_dataframe,
    location_matches,
    matches_company_blacklist,
    matches_excluded_keywords,
    matches_experience_level,
    matches_salary_minimum,
    normalize_location,
    title_is_relevant,
)
from gosha.models import Job, Subscription, User, UserJob
from gosha.matching import SemanticMatcher
from gosha.queue import enqueue_deliveries_batch, get_fresh_jobs

if TYPE_CHECKING:
    from gosha.bot import JobBot
    from gosha.ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Stage 1 — SCRAPE: fetch raw jobs and store in DB
# ═══════════════════════════════════════════════════════════════════════


async def upsert_jobs(df: pd.DataFrame) -> list[Job]:
    """Insert new jobs or update last_seen_at for existing ones.

    Returns the list of Job objects (both new and updated).
    """
    if df.empty:
        return []

    jobs: list[Job] = []
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        for _, row in df.iterrows():
            url = str(
                row.get("job_url")
                or row.get("job_url_direct")
                or row.get("link")
                or ""
            )
            if not url or url == "nan":
                continue

            title = _clean(row.get("title"), "Unknown Title")
            company = _clean(row.get("company"), "Unknown")
            location = _clean(row.get("location"), "")
            description = _clean(row.get("description"), "")
            source = _clean(row.get("site"), "unknown")

            salary_min = _parse_float(row, "min_amount")
            salary_max = _parse_float(row, "max_amount")
            salary_currency = (
                str(row["currency"])
                if "currency" in row and pd.notna(row.get("currency"))
                else None
            )

            result = await session.execute(select(Job).where(Job.url == url))
            existing = result.scalar_one_or_none()

            if existing:
                existing.last_seen_at = now
                existing.is_active = True
                if title != "Unknown Title":
                    existing.title = title
                if company != "Unknown":
                    existing.company = company
                if location:
                    existing.location = location
                if description:
                    existing.description = description
                if salary_min is not None:
                    existing.salary_min = salary_min
                if salary_max is not None:
                    existing.salary_max = salary_max
                if salary_currency:
                    existing.salary_currency = salary_currency
                jobs.append(existing)
            else:
                job = Job(
                    url=url,
                    title=title,
                    company=company,
                    location=location,
                    description=description,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_currency,
                    source=source,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(job)
                jobs.append(job)

        await session.commit()

    # Emit events for new jobs (best-effort)
    try:
        from gosha.events import emit_job_discovered
        for job in jobs:
            if job.id and job.first_seen_at == now:  # Newly created
                await emit_job_discovered(job.id, job.source, job.url)
    except Exception:
        pass

    log.info("Upserted %d jobs into DB", len(jobs))
    return jobs


async def run_scrape_stage(
    tunnel_manager: SSHTunnelManager,
) -> list[Job]:
    """Stage 1: scrape all active subscriptions and upsert results.

    Returns all jobs found (new + updated).
    """
    from gosha.scraper import scrape_jobs_raw

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.is_active == True)
        )
        all_subs = result.scalars().all()

    if not all_subs:
        log.info("No active subscriptions — nothing to scrape.")
        return []

    # Group by scrape parameters to avoid duplicate scraping
    scrape_combos: dict[tuple, list[str]] = {}  # key -> list of primary keywords (for filtering)
    for sub in all_subs:
        for keyword in sub.keywords:
            for location in sub.locations:
                key = (keyword.lower(), location.lower(), tuple(sorted(sub.boards)), sub.max_age_days)
                scrape_combos.setdefault(key, []).append(keyword)

    all_jobs: list[Job] = []
    for (keyword, location, boards, max_age_days), keywords in scrape_combos.items():
        df = await scrape_jobs_raw(
            tunnel_manager, keyword, location, max_age_days, boards=list(boards),
        )
        if not df.empty:
            df = filter_dataframe(df, keywords)
            jobs = await upsert_jobs(df)
            all_jobs.extend(jobs)

    # Deduplicate by ID
    seen_ids: set[int] = set()
    unique: list[Job] = []
    for j in all_jobs:
        if j.id not in seen_ids:
            seen_ids.add(j.id)
            unique.append(j)

    log.info("Scrape stage complete: %d unique jobs", len(unique))
    return unique


# ═══════════════════════════════════════════════════════════════════════
# Stage 2 — MATCH: score jobs against subscriptions, enqueue deliveries
# ═══════════════════════════════════════════════════════════════════════


def job_matches_subscription(job: Job, sub: Subscription) -> bool:
    """Check if a stored Job matches a Subscription's criteria."""
    combined_text = f"{job.title} {job.description or ''}"
    if matches_excluded_keywords(combined_text, sub.excluded_keywords):
        return False
    if matches_company_blacklist(job.company, sub.company_blacklist):
        return False
    if not matches_salary_minimum(sub.salary_min, job.salary_min, job.salary_max):
        return False
    if not matches_experience_level(job.title, sub.experience_levels):
        return False

    # Location matching — job must match at least one subscription location
    if not sub.locations:
        # No location filter → all locations match (user didn't restrict)
        return True

    for loc in sub.locations:
        _search_loc, match_subs = normalize_location(loc)
        if location_matches(job.location, match_subs):
            return True

    # Also include remote jobs when remote_ok is enabled
    if sub.remote_ok:
        _, remote_subs = normalize_location("remote")
        if location_matches(job.location, remote_subs):
            return True

    return False


def _title_relevant_for_any_keyword(title: str, keywords: list[str]) -> bool:
    """Check if title is relevant for at least one subscription keyword."""
    for kw in keywords:
        if title_is_relevant(title, kw):
            return True
    return False


async def match_jobs_for_subscription(
    sub: Subscription,
    jobs: list[Job],
    semantic_matcher: SemanticMatcher | None = None,
) -> list[tuple[Job, float]]:
    """Return (job, score) pairs for jobs matching a subscription.

    If a SemanticMatcher is provided and available, uses cosine similarity
    for scoring. Otherwise falls back to regex with score=1.0.
    """
    # Pre-filter: hard filters that must pass regardless of matching mode
    candidates: list[Job] = []
    for job in jobs:
        if not job_matches_subscription(job, sub):
            continue
        candidates.append(job)

    if not candidates:
        return []

    keywords = sub.keywords

    # Semantic matching path
    if semantic_matcher and semantic_matcher.available:
        query_emb = semantic_matcher.encode_subscription(
            keywords, sub.locations, sub.experience_levels,
        )
        if query_emb is not None:
            from gosha.matching import build_job_text

            job_texts = [
                build_job_text(j.title, j.company, j.description)
                for j in candidates
            ]
            scores = semantic_matcher.score_jobs(query_emb, job_texts)
            matches = [
                (job, score)
                for job, score in zip(candidates, scores)
                if semantic_matcher.is_match(score)
            ]
            # Sort by score descending
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches

    # Regex fallback path
    matches: list[tuple[Job, float]] = []
    for job in candidates:
        if keywords and not _title_relevant_for_any_keyword(job.title, keywords):
            continue
        matches.append((job, 1.0))
    return matches


async def run_match_stage(
    jobs: list[Job],
    semantic_matcher: SemanticMatcher | None = None,
) -> int:
    """Stage 2: match jobs against all active subscriptions and enqueue deliveries.

    Applies user feedback profiles to adjust scores when available.

    Returns total number of new deliveries enqueued.
    """
    async with get_session() as session:
        result = await session.execute(
            select(Subscription, User)
            .join(User)
            .where(Subscription.is_active == True)
        )
        sub_user_pairs = result.all()

    if not sub_user_pairs:
        return 0

    # Build per-user feedback profiles for score adjustment
    from gosha.feedback import build_user_profile

    user_profiles: dict[int, object] = {}  # user_id -> UserPreferenceProfile

    # Build batch delivery items
    delivery_items: list[dict] = []

    for sub, user in sub_user_pairs:
        matches = await match_jobs_for_subscription(sub, jobs, semantic_matcher)

        # Build user profile lazily (once per user)
        if user.id not in user_profiles:
            try:
                user_profiles[user.id] = await build_user_profile(user.id)
            except Exception:
                user_profiles[user.id] = None

        profile = user_profiles.get(user.id)

        for job, score in matches:
            # Apply feedback-based score adjustment
            adjusted_score = score
            if profile and profile.has_data:
                adjusted_score = max(0.0, min(1.0, score + profile.score_adjustment(job)))

            delivery_items.append({
                "user_id": user.id,
                "job_id": job.id,
                "subscription_id": sub.id,
                "score": adjusted_score,
            })

    if not delivery_items:
        log.info("Match stage: no new matches found.")
        return 0

    created = await enqueue_deliveries_batch(delivery_items)
    log.info("Match stage complete: %d new deliveries enqueued", created)
    return created


# ═══════════════════════════════════════════════════════════════════════
# Stage 3 — DELIVER: send notifications to users
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator — runs all three stages in sequence
# ═══════════════════════════════════════════════════════════════════════


async def run_scrape_cycle(
    bot: JobBot,
    tunnel_manager: SSHTunnelManager,
    alert_channel_id: int,
    use_semantic: bool = False,
    semantic_model: str = "all-mpnet-base-v2",
    semantic_threshold: float = 0.40,
) -> int:
    """Execute one full scrape -> match -> deliver cycle.

    Returns total number of new jobs delivered.
    """
    log.info("=== Scrape cycle started ===")
    cycle_start = datetime.now(timezone.utc)

    # Stage 1: Scrape
    jobs = await run_scrape_stage(tunnel_manager)
    if not jobs:
        log.info("No jobs found — cycle complete.")
        return 0

    # Embed freshly scraped jobs so the web feed can rank them (best-effort)
    try:
        from gosha.embeddings import embed_new_jobs
        await embed_new_jobs()
    except Exception as exc:
        log.warning("Job embedding step failed: %s", exc)

    # Stage 2: Match (with optional semantic scoring)
    matcher = None
    if use_semantic:
        matcher = SemanticMatcher(
            model_name=semantic_model, threshold=semantic_threshold
        )
        if matcher.available:
            log.info("Using semantic matching (model=%s, threshold=%.2f)", semantic_model, semantic_threshold)
        else:
            log.warning("Semantic matching requested but not available — falling back to regex")
            matcher = None

    new_deliveries = await run_match_stage(jobs, matcher)
    if new_deliveries == 0:
        log.info("No new matches — cycle complete.")
        return 0

    # Stage 3: Deliver
    # Only deliver the newly enqueued items (from this cycle)
    total_sent = await _deliver_new(bot, cycle_start)

    # Post summary
    if alert_channel_id and total_sent > 0:
        try:
            import discord
            channel = bot.get_channel(alert_channel_id)
            if channel is not None:
                await channel.send(  # type: ignore[union-attr]
                    f"Scrape complete — sent **{total_sent}** new job alerts via DM."
                )
        except Exception:
            pass

    log.info("=== Scrape cycle finished — %d new jobs sent ===", total_sent)
    return total_sent


async def _deliver_new(bot: JobBot, since: datetime) -> int:
    """Deliver only UserJobs created since the given timestamp.

    Sends embeds with feedback buttons and emits delivery events.
    """
    from gosha.views import build_job_embed_with_buttons

    async with get_session() as session:
        result = await session.execute(
            select(UserJob, Job, User, Subscription)
            .join(Job, UserJob.job_id == Job.id)
            .join(User, UserJob.user_id == User.id)
            .outerjoin(Subscription, UserJob.subscription_id == Subscription.id)
            .where(UserJob.delivered_at >= since)
            .order_by(UserJob.delivered_at.asc())
        )
        items = result.all()

    # Deduplicate cross-board: same title+company from different sources
    # Group by (user_id, normalized_title, normalized_company), keep first
    seen_per_user: dict[tuple[int, str, str], bool] = {}
    deduped: list[tuple[UserJob, Job, User, Subscription | None]] = []
    skipped = 0

    for uj, job, user, sub in items:
        key = (
            user.id,
            (job.title or "").lower().strip(),
            (job.company or "").lower().strip(),
        )
        if key in seen_per_user:
            skipped += 1
            continue
        seen_per_user[key] = True
        deduped.append((uj, job, user, sub))

    if skipped:
        log.info("Cross-board dedup: skipped %d duplicate deliveries", skipped)

    sent = 0
    dm_failed_users: dict[int, str] = {}  # discord_id -> username hint

    for uj, job, user, sub in deduped:
        # Web-managed searches can opt out of Discord notifications;
        # matches still show up on the website.
        if sub is not None and not sub.notify_discord:
            continue

        # Skip users whose DMs already failed this cycle
        if user.discord_user_id in dm_failed_users:
            continue

        # Build match reason from subscription keywords
        match_info = None
        if sub:
            kw_str = ", ".join(sub.keywords[:3])[:80]
            loc_str = ", ".join(sub.locations[:2])[:60]
            match_info = f"{kw_str} in {loc_str}"
        embed, view = build_job_embed_with_buttons(job, uj.id, uj.relevance_score, match_info)
        success = await _dm_user(bot, user.discord_user_id, embed, view)
        if success:
            sent += 1
            # Emit delivery event (best-effort)
            try:
                from gosha.events import emit_job_delivered
                await emit_job_delivered(job.id, user.id, "discord_dm")
            except Exception:
                pass
        else:
            dm_failed_users[user.discord_user_id] = f"<@{user.discord_user_id}>"

    # Notify users with closed DMs in the alert channel
    if dm_failed_users and bot.alert_channel_id:
        try:
            import discord as _discord
            channel = bot.get_channel(bot.alert_channel_id)
            if channel is not None:
                mentions = " ".join(dm_failed_users.values())
                await channel.send(
                    f"**I found jobs for you but can't deliver them!**\n"
                    f"{mentions}\n\n"
                    f"Please enable DMs so I can send you job matches:\n"
                    f"**Server Settings > Privacy Settings > Allow direct messages from server members**"
                )
        except Exception as exc:
            log.error("Failed to send DM-failure notice: %s", exc)

    return sent


# ═══════════════════════════════════════════════════════════════════════
# Delivery helpers (kept for backward compat with existing tests)
# ═══════════════════════════════════════════════════════════════════════


async def get_undelivered_jobs(user_id: int, job_ids: list[int]) -> set[int]:
    """Return the subset of job_ids not yet delivered to this user."""
    if not job_ids:
        return set()
    async with get_session() as session:
        result = await session.execute(
            select(UserJob.job_id).where(
                UserJob.user_id == user_id,
                UserJob.job_id.in_(job_ids),
            )
        )
        already = {row[0] for row in result.all()}
    return set(job_ids) - already


async def record_delivery(
    user_id: int,
    job_id: int,
    subscription_id: int | None = None,
    relevance_score: float | None = None,
) -> UserJob:
    """Record that a job was delivered to a user."""
    async with get_session() as session:
        uj = UserJob(
            user_id=user_id,
            job_id=job_id,
            subscription_id=subscription_id,
            relevance_score=relevance_score,
        )
        session.add(uj)
        await session.commit()
        return uj


async def _dm_user(
    bot: JobBot, discord_id: int, embed: object, view: object | None = None,
) -> bool:
    """Send an embed to a user via DM. Silently skip if DMs are closed.

    Returns True if the message was sent successfully.
    """
    import discord as _discord

    try:
        user = bot.get_user(discord_id)
        if user is None:
            user = await bot.fetch_user(discord_id)
        dm = await user.create_dm()
        kwargs: dict = {"embed": embed}
        if view is not None:
            kwargs["view"] = view
        await dm.send(**kwargs)
        return True
    except _discord.Forbidden:
        log.warning("Cannot DM user %d — DMs are closed", discord_id)
        return False
    except _discord.HTTPException as exc:
        log.error("Failed to DM user %d: %s", discord_id, exc)
        return False


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════


def _clean(value: object, default: str) -> str:
    """Clean a DataFrame cell value into a string."""
    if value is None:
        return default
    s = str(value)
    if s in ("nan", "None", ""):
        return default
    return s


def _parse_float(row: pd.Series, col: str) -> float | None:
    """Safely parse a float from a DataFrame row."""
    if col not in row or not pd.notna(row.get(col)):
        return None
    try:
        return float(row[col])
    except (ValueError, TypeError):
        return None
