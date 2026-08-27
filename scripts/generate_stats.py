#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api.github.com/graphql"
OUT = Path("assets/github_stats.svg")

QUERY = r"""
query ProfileStats($login: String!, $from: DateTime!, $to: DateTime!, $after: String) {
  user(login: $login) {
    repositories(
      first: 100,
      after: $after,
      ownerAffiliations: OWNER,
      privacy: PUBLIC
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { stargazerCount }
    }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { contributionCount }
        }
      }
    }
  }
}
"""

BG = "#0D0221"
PANEL = "#120827"
BORDER = "#2B1749"
CYAN = "#00F0FF"
PINK = "#FF2079"
PURPLE = "#9D4EDD"
TEXT = "#E2E8F0"
MUTED = "#8B7AAE"


def query_github(token: str, variables: dict) -> dict:
    request = Request(
        API,
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "hamzahghazi2001-profile-stats",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    user = payload.get("data", {}).get("user")
    if not user:
        raise RuntimeError("GitHub returned no user data")
    return user


def collect(token: str, username: str) -> dict:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    variables = {
        "login": username,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
        "after": None,
    }

    first = query_github(token, variables)
    repos = first["repositories"]
    repo_count = repos["totalCount"]
    stars = sum(repo["stargazerCount"] for repo in repos["nodes"])

    while repos["pageInfo"]["hasNextPage"]:
        variables["after"] = repos["pageInfo"]["endCursor"]
        page = query_github(token, variables)
        repos = page["repositories"]
        stars += sum(repo["stargazerCount"] for repo in repos["nodes"])

    contributions = first["contributionsCollection"]
    weeks = contributions["contributionCalendar"]["weeks"][-12:]
    weekly = [
        sum(day["contributionCount"] for day in week["contributionDays"])
        for week in weeks
    ]

    return {
        "year": now.year,
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "commits": contributions["totalCommitContributions"],
        "prs": contributions["totalPullRequestContributions"],
        "reviews": contributions["totalPullRequestReviewContributions"],
        "repos": repo_count,
        "stars": stars,
        "weekly": weekly,
        "updated": now.strftime("%Y-%m-%d %H:%M UTC"),
    }


def metric(x: int, label: str, value: int, color: str) -> str:
    return f'''<g transform="translate({x} 48)">
      <rect width="145" height="58" rx="8" fill="{PANEL}" stroke="{BORDER}"/>
      <rect width="3" height="58" rx="2" fill="{color}"/>
      <text x="15" y="21" class="label">{escape(label)}</text>
      <text x="15" y="47" class="value" fill="{color}">{value}</text>
    </g>'''


def render(stats: dict) -> str:
    metrics = [
        ("CONTRIB", stats["contributions"], CYAN),
        ("COMMIT CONTRIB", stats["commits"], TEXT),
        ("PULL REQS", stats["prs"], PINK),
        ("REVIEWS", stats["reviews"], PURPLE),
        ("PUBLIC REPOS", stats["repos"], CYAN),
        ("STARS", stats["stars"], PINK),
    ]
    blocks = "".join(metric(34 + i * 158, *item) for i, item in enumerate(metrics))

    weekly = stats["weekly"]
    peak = max(weekly) if weekly else 1
    bars = []
    start_x = 36
    base_y = 136
    bar_w = 55
    gap = 25
    for i, count in enumerate(weekly):
        height = 3 + (count / peak) * 15 if peak else 3
        x = start_x + i * (bar_w + gap)
        y = base_y - height
        color = CYAN if i < 8 else PURPLE if i < 10 else PINK
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{height:.1f}" '
            f'rx="3" fill="{color}" opacity="0.82"><title>{count} contributions</title></rect>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="150" viewBox="0 0 1000 150" role="img" aria-labelledby="title desc">
  <title id="title">Live GitHub activity</title>
  <desc id="desc">GitHub contribution statistics generated from the GitHub GraphQL API.</desc>
  <defs>
    <linearGradient id="line" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="0.52" stop-color="{PURPLE}"/>
      <stop offset="1" stop-color="{PINK}"/>
    </linearGradient>
    <style>
      .label {{ font: 600 9.5px Consolas, 'Courier New', monospace; fill: {MUTED}; letter-spacing: .8px; }}
      .value {{ font: 700 21px 'Segoe UI', Arial, sans-serif; }}
      .meta {{ font: 500 9px Consolas, 'Courier New', monospace; fill: {MUTED}; }}
      .head {{ font: 700 12px Consolas, 'Courier New', monospace; fill: {CYAN}; letter-spacing: 1.5px; }}
    </style>
  </defs>
  <rect x="1" y="1" width="998" height="148" rx="12" fill="{BG}" stroke="{BORDER}" stroke-width="2"/>
  <rect x="18" y="14" width="964" height="3" rx="2" fill="url(#line)"/>
  <text x="34" y="35" class="head">GITHUB // LIVE // {stats['year']}</text>
  <text x="966" y="35" class="meta" text-anchor="end">{escape(stats['updated'])}</text>
  {blocks}
  <text x="34" y="122" class="meta">LAST 12 WEEKS</text>
  {''.join(bars)}
</svg>'''


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("PROFILE_USERNAME", "hamzahghazi2001")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(render(collect(token, username)), encoding="utf-8")
        print(f"updated {OUT}")
        return 0
    except (HTTPError, URLError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(f"stats generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
