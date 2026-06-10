"""One-off live check of the configured LLM provider (.env credentials)."""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv

load_dotenv()

from gosha import llm  # noqa: E402


async def main() -> None:
    print("provider:", llm.active_provider())
    result = await llm.generate(
        "Reply with exactly one short sentence confirming you are working."
    )
    print("result:", result)


if __name__ == "__main__":
    asyncio.run(main())
