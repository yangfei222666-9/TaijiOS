"""
GitHub Learning Pipeline — Discover repos via GitHub Search API.
Rotating daily topics, rate-limit aware, dedup by full_name.
"""
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DATA_DIR = Path(__file__).parent / "data"

DAILY_TOPICS = {
    0: ['"autonomous agent system" language:python stars:>100'],
    1: ['"self-improving AI" OR "self-healing agent" stars:>50'],
    2: ['"multi-agent framework" language:python stars:>200'],
    3: ['"agent skill" OR "tool use agent" stars:>100'],
    4: ['"agent memory" OR "agent scheduler" stars:>100'],
    5: ['"agent observability" OR "agent monitoring" stars:>50'],
    6: ['"AIOS" OR "personal AI operating system" stars:>50'],
}


@dataclass
class DiscoveredRepo:
    full_name: str
    url: str
    description: str
    stars: int
    language: str
    topics: List[str]
    last_updated: str
    readme_excerpt: str = ""
    discovered_at: str = ""
    query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _sleep_for_rate_limit():
    token = os.environ.get("GITHUB_TOKEN", "")
    time.sleep(1.0 if token else 6.0)


def _load_seen(path: Path) -> set:
    seen = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                    seen.add(d.get("full_name", ""))
                except json.JSONDecodeError:
                    pass
    return seen


def _fetch_readme(full_name: str) -> str:
    """Fetch first 2000 chars of README via GitHub API."""
    try:
        url = f"https://api.github.com/repos/{full_name}/readme"
        resp = requests.get(url, headers=_github_headers(), timeout=15)
        if resp.status_code != 200:
            return ""
        import base64
        content = base64.b64decode(resp.json().get("content", "")).decode("utf-8", errors="replace")
        return content[:2000]
    except Exception:
        return ""


def search_repos(queries: Optional[List[str]] = None, limit: int = 30) -> List[DiscoveredRepo]:
    """Search GitHub for repos matching queries. Uses today's topic if queries=None."""
    if queries is None:
        day = datetime.now().weekday()
        queries = DAILY_TOPICS.get(day, DAILY_TOPICS[0])

    results = []
    for query in queries:
        try:
            url = "https://api.github.com/search/repositories"
            params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 30)}
            resp = requests.get(url, headers=_github_headers(), params=params, timeout=15)
            if resp.status_code != 200:
                print(f"  GitHub API {resp.status_code}: {resp.text[:200]}")
                continue
            items = resp.json().get("items", [])
            for item in items:
                results.append(DiscoveredRepo(
                    full_name=item["full_name"],
                    url=item["html_url"],
                    description=item.get("description") or "",
                    stars=item.get("stargazers_count", 0),
                    language=item.get("language") or "",
                    topics=item.get("topics", []),
                    last_updated=item.get("updated_at", ""),
                    discovered_at=datetime.utcnow().isoformat() + "Z",
                    query=query,
                ))
            _sleep_for_rate_limit()
        except Exception as e:
            print(f"  Search error: {e}")
    return results


def discover(limit: int = 30, dry_run: bool = False) -> List[DiscoveredRepo]:
    """Run discovery: search, dedup, fetch READMEs, persist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ledger = DATA_DIR / "discovered_repos.jsonl"
    seen = _load_seen(ledger)

    repos = search_repos(limit=limit)
    new_repos = [r for r in repos if r.full_name not in seen]

    if dry_run:
        print(f"[dry-run] Found {len(repos)} repos, {len(new_repos)} new")
        for r in new_repos[:10]:
            print(f"  {r.stars:>6} {r.full_name}: {r.description[:80]}")
        return new_repos

    # Fetch READMEs for new repos
    for r in new_repos:
        r.readme_excerpt = _fetch_readme(r.full_name)
        _sleep_for_rate_limit()

    # Append to ledger
    with open(ledger, "a", encoding="utf-8") as f:
        for r in new_repos:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    print(f"Discovered: {len(repos)} total, {len(new_repos)} new, {len(seen)} already known")
    return new_repos
