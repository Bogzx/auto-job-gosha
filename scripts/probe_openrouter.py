"""List DeepSeek model slugs on OpenRouter (public endpoint, no key needed)."""

from __future__ import annotations

import httpx

resp = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
models = resp.json().get("data", [])
print("total models:", len(models))
for m in models:
    mid = m.get("id", "")
    if "deepseek" in mid.lower():
        pricing = m.get("pricing", {})
        print(f"{mid:55s} prompt={pricing.get('prompt')} completion={pricing.get('completion')}")
