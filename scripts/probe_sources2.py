"""Round 2: pin down eJobs filter params, BestJobs filters, Hipo HTML shape."""

from __future__ import annotations

import json
import re
import sys

import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
}


def ejobs_params() -> None:
    for params in (
        {"page": 1, "pageSize": 3, "q": "software"},
        {"page": 1, "pageSize": 3, "search": "software"},
        {"page": 1, "pageSize": 3, "keywords": "software"},
        {"page": 1, "pageSize": 3, "filters.keyword": "software"},
    ):
        r = httpx.get("https://api.ejobs.ro/jobs", params=params, headers=UA, timeout=20)
        titles = [j.get("title", "")[:40] for j in r.json().get("jobs", [])]
        total = r.json().get("totalCount")
        print(list(params.keys())[-1], r.status_code, "total:", total, titles)


def ejobs_detail() -> None:
    r = httpx.get("https://api.ejobs.ro/jobs", params={"page": 1, "pageSize": 1}, headers=UA, timeout=20)
    job = r.json()["jobs"][0]
    jid = job["id"]
    for url in (f"https://api.ejobs.ro/jobs/{jid}",):
        d = httpx.get(url, headers=UA, timeout=20)
        print("detail", d.status_code, d.text[:600])


def bestjobs_filters() -> None:
    for params in (
        {"limit": 3, "keyword": "software", "location": "cluj-napoca-romania"},
        {"limit": 3, "keyword": "software", "locations": "cluj-napoca-romania"},
        {"limit": 3, "keyword": "software", "city": "cluj-napoca"},
    ):
        r = httpx.get("https://api.bestjobs.eu/v1/jobs", params=params, headers=UA, timeout=20)
        items = r.json().get("items", [])
        locs = [i["locations"][0]["name"] if i.get("locations") else "?" for i in items]
        print(list(params.keys())[-1], r.status_code, "count:", len(items), locs)


def hipo_structure() -> None:
    url = "https://www.hipo.ro/locuri-de-munca/cautajob/Toate-Domeniile/Toate-Orasele"
    r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    html = r.text
    # find one job card region around the first 'job-title'
    idx = html.find("job-title")
    print(html[max(0, idx - 1200) : idx + 800])


if __name__ == "__main__":
    which = sys.argv[1]
    {"ejobs": ejobs_params, "ejobsdetail": ejobs_detail,
     "bestjobs": bestjobs_filters, "hipo": hipo_structure}[which]()
