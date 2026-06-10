"""Probe candidate job-board endpoints to design Phase 2 adapters.

Throwaway dev tool: prints status + a sample of each source's response
shape so the adapters get built against reality.
"""

from __future__ import annotations

import json
import sys

import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
}


def show(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        print(f"{label} FAIL: {type(exc).__name__}: {str(exc)[:200]}")
    print("-" * 70)


def remoteok() -> None:
    r = httpx.get("https://remoteok.com/api", headers=UA, timeout=20, follow_redirects=True)
    data = r.json()
    print("REMOTEOK", r.status_code, "items:", len(data))
    for j in [d for d in data if isinstance(d, dict) and d.get("position")][:2]:
        keys = ("position", "company", "location", "url", "date", "salary_min", "salary_max", "tags")
        print(json.dumps({k: str(j.get(k))[:70] for k in keys}))


def ejobs() -> None:
    url = "https://api.ejobs.ro/jobs"
    params = {"page": 1, "pageSize": 2, "keyword": "software"}
    r = httpx.get(url, params=params, headers=UA, timeout=20, follow_redirects=True)
    print("EJOBS", r.status_code, r.headers.get("content-type", ""))
    body = r.text[:1500]
    print(body)


def bestjobs() -> None:
    url = "https://api.bestjobs.eu/v1/jobs"
    params = {"limit": 2, "keyword": "software"}
    r = httpx.get(url, params=params, headers=UA, timeout=20, follow_redirects=True)
    print("BESTJOBS", r.status_code, r.headers.get("content-type", ""))
    print(r.text[:1500])


def hipo() -> None:
    url = "https://www.hipo.ro/locuri-de-munca/cautajob/Toate-Domeniile/Toate-Orasele"
    r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    print("HIPO", r.status_code, r.headers.get("content-type", ""), "len:", len(r.text))
    # look for job card markers
    for marker in ("job-title", "jobs-list", "JobPosting", "job_link"):
        print(f"  marker {marker!r}:", r.text.count(marker))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    probes = {"remoteok": remoteok, "ejobs": ejobs, "bestjobs": bestjobs, "hipo": hipo}
    for name, fn in probes.items():
        if which in ("all", name):
            show(name, fn)
