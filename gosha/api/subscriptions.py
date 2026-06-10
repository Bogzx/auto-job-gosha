"""Saved searches (subscriptions) API with tier-limit enforcement."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from gosha.api.deps import ApiError, current_user
from gosha.api.schemas import (
    OkOut,
    SubscriptionIn,
    SubscriptionOut,
    SubscriptionPatchIn,
)
from gosha.config import load_web_settings
from gosha.database import get_session
from gosha.models import Subscription, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def subscription_to_out(sub: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=sub.id,
        name=sub.name,
        keywords=sub.keywords,
        locations=sub.locations,
        excluded_keywords=sub.excluded_keywords,
        company_blacklist=sub.company_blacklist,
        experience_levels=sub.experience_levels,
        remote_ok=sub.remote_ok,
        salary_min=sub.salary_min,
        max_age_days=sub.max_age_days,
        is_active=sub.is_active,
        notify_discord=sub.notify_discord,
        created_at=sub.created_at,
    )


def _clean_list(values: list[str], cap: int = 50) -> list[str]:
    return [v.strip() for v in values if v and v.strip()][:cap]


def _check_tier_lists(user: User, keywords: list[str], locations: list[str]) -> None:
    limits = user.limits
    if len(keywords) > int(limits["max_keywords_per_sub"]):
        raise ApiError(
            403,
            "tier_limit",
            f"Your plan allows {limits['max_keywords_per_sub']} keywords per search.",
        )
    if len(locations) > int(limits["max_locations_per_sub"]):
        raise ApiError(
            403,
            "tier_limit",
            f"Your plan allows {limits['max_locations_per_sub']} locations per search.",
        )


@router.get("")
async def list_subscriptions(user: User = Depends(current_user)) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.created_at.desc())
        )
        subs = result.scalars().all()
    return {"items": [subscription_to_out(s).model_dump(mode="json") for s in subs]}


@router.post("", response_model=SubscriptionOut)
async def create_subscription(
    body: SubscriptionIn, user: User = Depends(current_user),
) -> SubscriptionOut:
    keywords = _clean_list(body.keywords)
    locations = _clean_list(body.locations)
    if not keywords or not locations:
        raise ApiError(422, "invalid_request", "At least one keyword and one location are required.")
    _check_tier_lists(user, keywords, locations)

    async with get_session() as session:
        count = (
            await session.execute(
                select(func.count(Subscription.id)).where(
                    Subscription.user_id == user.id
                )
            )
        ).scalar() or 0
        if count >= int(user.limits["max_subscriptions"]):
            raise ApiError(
                403,
                "tier_limit",
                f"Your plan allows {user.limits['max_subscriptions']} searches — "
                "delete one first or upgrade.",
            )

        sub = Subscription(
            user_id=user.id,
            name=body.name,
            remote_ok=body.remote_ok,
            salary_min=body.salary_min,
            max_age_days=body.max_age_days,
            notify_discord=body.notify_discord,
        )
        sub.keywords = keywords
        sub.locations = locations
        sub.excluded_keywords = _clean_list(body.excluded_keywords)
        sub.company_blacklist = _clean_list(body.company_blacklist)
        sub.experience_levels = _clean_list(body.experience_levels) or ["any"]
        session.add(sub)
        await session.commit()
        is_first = count == 0

    try:
        from gosha.events import emit_subscription_created
        await emit_subscription_created(user.id, sub.id, keywords)
    except Exception:
        pass

    # First search + reachable on Discord -> welcome DM so the user knows
    # alerts are live (the zero-setup funnel).
    if is_first and user.in_guild:
        try:
            from gosha.outbox import enqueue
            await enqueue(user.id, "welcome", {
                "search_name": body.name or ", ".join(keywords[:2]),
                "site_url": load_web_settings().public_base_url,
            })
        except Exception as exc:
            log.warning("Welcome DM enqueue failed: %s", exc)

    return subscription_to_out(sub)


async def _own_subscription(user_id: int, subscription_id: int) -> Subscription:
    async with get_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.id == subscription_id,
                    Subscription.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
    if sub is None:
        raise ApiError(404, "not_found", "Search not found.")
    return sub


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
async def update_subscription(
    subscription_id: int,
    body: SubscriptionPatchIn,
    user: User = Depends(current_user),
) -> SubscriptionOut:
    sub = await _own_subscription(user.id, subscription_id)

    keywords = _clean_list(body.keywords) if body.keywords is not None else sub.keywords
    locations = _clean_list(body.locations) if body.locations is not None else sub.locations
    if not keywords or not locations:
        raise ApiError(422, "invalid_request", "At least one keyword and one location are required.")
    _check_tier_lists(user, keywords, locations)

    async with get_session() as session:
        sub = await session.merge(sub)
        sub.keywords = keywords
        sub.locations = locations
        if body.name is not None:
            sub.name = body.name
        if body.excluded_keywords is not None:
            sub.excluded_keywords = _clean_list(body.excluded_keywords)
        if body.company_blacklist is not None:
            sub.company_blacklist = _clean_list(body.company_blacklist)
        if body.experience_levels is not None:
            sub.experience_levels = _clean_list(body.experience_levels) or ["any"]
        if body.remote_ok is not None:
            sub.remote_ok = body.remote_ok
        if body.salary_min is not None:
            sub.salary_min = body.salary_min
        if body.max_age_days is not None:
            sub.max_age_days = body.max_age_days
        if body.notify_discord is not None:
            sub.notify_discord = body.notify_discord
        await session.commit()
    return subscription_to_out(sub)


@router.post("/{subscription_id}/pause", response_model=SubscriptionOut)
async def pause_subscription(
    subscription_id: int, user: User = Depends(current_user),
) -> SubscriptionOut:
    return await _set_active(user.id, subscription_id, False)


@router.post("/{subscription_id}/resume", response_model=SubscriptionOut)
async def resume_subscription(
    subscription_id: int, user: User = Depends(current_user),
) -> SubscriptionOut:
    return await _set_active(user.id, subscription_id, True)


async def _set_active(user_id: int, subscription_id: int, active: bool) -> SubscriptionOut:
    sub = await _own_subscription(user_id, subscription_id)
    async with get_session() as session:
        sub = await session.merge(sub)
        sub.is_active = active
        await session.commit()
    return subscription_to_out(sub)


@router.delete("/{subscription_id}", response_model=OkOut)
async def delete_subscription(
    subscription_id: int, user: User = Depends(current_user),
) -> OkOut:
    sub = await _own_subscription(user.id, subscription_id)
    async with get_session() as session:
        sub = await session.merge(sub)
        await session.delete(sub)
        await session.commit()
    try:
        from gosha.events import emit_subscription_deleted
        await emit_subscription_deleted(user.id, subscription_id)
    except Exception:
        pass
    return OkOut()
