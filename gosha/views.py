"""Discord UI components — buttons, views, and interaction handlers."""

from __future__ import annotations

import logging

import discord

log = logging.getLogger(__name__)


class JobFeedbackView(discord.ui.View):
    """View with Interested / Not Relevant buttons on job embeds.

    The custom_id encodes the UserJob ID so the handler can record feedback
    even after a bot restart (handled by setup_interaction_handler).
    """

    def __init__(self, user_job_id: int) -> None:
        # timeout=None makes the view persistent (survives bot restarts)
        super().__init__(timeout=None)
        self.user_job_id = user_job_id

        interested_btn = discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="Interested",
            custom_id=f"job_feedback:interested:{user_job_id}",
            emoji="\U0001f44d",
        )
        interested_btn.callback = self._on_interested

        not_relevant_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Not Relevant",
            custom_id=f"job_feedback:not_relevant:{user_job_id}",
            emoji="\U0001f44e",
        )
        not_relevant_btn.callback = self._on_not_relevant

        self.add_item(interested_btn)
        self.add_item(not_relevant_btn)

    async def _on_interested(self, interaction: discord.Interaction) -> None:
        await _handle_feedback_interaction(interaction, "interested", self.user_job_id)

    async def _on_not_relevant(self, interaction: discord.Interaction) -> None:
        await _handle_feedback_interaction(interaction, "not_relevant", self.user_job_id)


async def _handle_feedback_interaction(
    interaction: discord.Interaction,
    feedback: str,
    user_job_id: int,
) -> None:
    """Shared handler for feedback button clicks (works for both fresh and persistent buttons)."""
    from gosha.feedback import record_feedback

    success = await record_feedback(user_job_id, feedback)
    if success:
        label = "Interested" if feedback == "interested" else "Not Relevant"
        # Disable both buttons on the message
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.success if feedback == "interested" else discord.ButtonStyle.secondary,
            label=f"Feedback: {label}",
            disabled=True,
        ))
        try:
            await interaction.response.edit_message(view=view)
        except discord.HTTPException:
            pass
        log.info("Feedback %s recorded for UserJob %d", feedback, user_job_id)
    else:
        try:
            await interaction.response.send_message(
                "Could not record feedback.", ephemeral=True
            )
        except discord.HTTPException:
            pass


def setup_interaction_handler(bot: discord.Client) -> None:
    """Register an on_interaction listener that catches feedback button clicks.

    This handles buttons after a bot restart, since the original JobFeedbackView
    instances are gone but the buttons in DM messages still have their custom_ids.

    Call this once in bot setup_hook.
    """
    @bot.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if not custom_id.startswith("job_feedback:"):
            return

        # Parse: "job_feedback:{feedback}:{user_job_id}"
        parts = custom_id.split(":")
        if len(parts) != 3:
            return

        feedback = parts[1]
        if feedback not in ("interested", "not_relevant"):
            return

        try:
            user_job_id = int(parts[2])
        except ValueError:
            return

        await _handle_feedback_interaction(interaction, feedback, user_job_id)


def build_job_embed_with_buttons(
    job,
    user_job_id: int,
    relevance_score: float | None = None,
) -> tuple[discord.Embed, JobFeedbackView]:
    """Build a Discord embed + feedback buttons for a job delivery.

    Returns (embed, view) tuple.
    """
    embed = discord.Embed(
        title=job.title,
        url=job.url,
        color=discord.Color.green(),
    )
    embed.add_field(name="Company", value=job.company, inline=True)
    embed.add_field(name="Location", value=job.location or "N/A", inline=True)

    if job.salary_min or job.salary_max:
        parts = []
        if job.salary_min:
            parts.append(f"{job.salary_min:,.0f}")
        if job.salary_max:
            parts.append(f"{job.salary_max:,.0f}")
        salary = " - ".join(parts)
        if job.salary_currency:
            salary += f" {job.salary_currency}"
        embed.add_field(name="Salary", value=salary, inline=True)

    if job.description:
        desc = (
            job.description[:200] + "..."
            if len(job.description) > 200
            else job.description
        )
        embed.add_field(name="Description", value=desc, inline=False)

    score_str = f"{relevance_score:.0%}" if relevance_score else "N/A"
    embed.set_footer(text=f"Source: {job.source} | Score: {score_str}")

    view = JobFeedbackView(user_job_id)
    return embed, view
