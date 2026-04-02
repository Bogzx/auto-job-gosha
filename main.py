"""Shim — delegates to gosha.main for backward compatibility.

Existing deployments using ``python main.py`` or Docker CMD ["python", "main.py"]
continue to work without changes.
"""

from gosha.main import main  # noqa: F401
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
