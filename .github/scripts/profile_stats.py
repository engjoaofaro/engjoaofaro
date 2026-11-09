#!/usr/bin/env python3
"""Generate the profile's stats and top-languages cards as static SVGs.

Runs inside GitHub Actions with the default GITHUB_TOKEN, so the cards are
built from public data and never depend on a third-party server. If the
METRICS_TOKEN secret (a personal access token) is set, the workflow passes it
instead and private repositories also count toward the totals.

Output: <out>/stats-<lang>-<theme>.svg and <out>/langs-<lang>-<theme>.svg
for lang in (pt, en) and theme in (dark, light).

Usage: profile_stats.py <login> <out_dir>
       profile_stats.py --sample <out_dir>   (render with fake data, no network)
"""

import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"

# Languages left out of the chart: notebooks store outputs and images inline,
# so their byte count would drown out every other language.
EXCLUDED_LANGS = {"Jupyter Notebook"}
TOP_LANGS = 8

QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    pullRequests { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar { totalContributions }
    }
  }
}
"""

THEMES = {
    "dark": {
        "bg": "#1a1b27", "border": "#2a2e42", "title": "#00d9ff",
        "text": "#a9b1d6", "value": "#ffffff", "bar_bg": "#2a2e42",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "title": "#0969da",
        "text": "#57606a", "value": "#1f2328", "bar_bg": "#eaeef2",
    },
}

LABELS = {
    "pt": {
        "stats_title": "Estatísticas no GitHub",
        "contribs": "Contribuições (último ano)",
        "commits": "Commits (último ano)",
        "prs": "Pull requests",
        "repos": "Repositórios",
        "stars": "Estrelas recebidas",
        "langs_title": "Linguagens mais usadas",
    },
    "en": {
        "stats_title": "GitHub Stats",
        "contribs": "Contributions (last year)",
        "commits": "Commits (last year)",
        "prs": "Pull requests",
        "repos": "Repositories",
        "stars": "Stars earned",
        "langs_title": "Most Used Languages",
    },
}

FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
WIDTH = 420
HEIGHT = 200  # both cards share it so they line up side by side


def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-script",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


def summarize(user):
    repos = user["repositories"]
    cc = user["contributionsCollection"]
    langs = {}
    for repo in repos["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in EXCLUDED_LANGS:
                continue
            entry = langs.setdefault(name, {"size": 0, "color": edge["node"]["color"] or "#8b949e"})
            entry["size"] += edge["size"]
    stats = {
        "contribs": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "repos": repos["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos["nodes"]),
    }
    return stats, langs


def svg_frame(theme, title, body):
    t = THEMES[theme]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">\n'
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" '
        f'fill="{t["bg"]}" stroke="{t["border"]}"/>\n'
        f'<text x="24" y="38" font-family="{FONT}" font-size="18" font-weight="600" '
        f'fill="{t["title"]}">{escape(title)}</text>\n'
        f"{body}</svg>\n"
    )


def fmt(n):
    return f"{n / 1000:.1f}k" if n >= 10000 else str(n)


def stats_card(stats, lang, theme):
    t, lab = THEMES[theme], LABELS[lang]
    rows = []
    for i, key in enumerate(("contribs", "commits", "prs", "repos", "stars")):
        y = 76 + i * 25
        rows.append(
            f'<text x="24" y="{y}" font-family="{FONT}" font-size="14" fill="{t["text"]}">'
            f"{escape(lab[key])}</text>\n"
            f'<text x="{WIDTH - 24}" y="{y}" text-anchor="end" font-family="{FONT}" '
            f'font-size="14" font-weight="600" fill="{t["value"]}">{fmt(stats[key])}</text>\n'
        )
    return svg_frame(theme, lab["stats_title"], "".join(rows))


def langs_card(langs, lang, theme):
    t, lab = THEMES[theme], LABELS[lang]
    top = sorted(langs.items(), key=lambda kv: kv[1]["size"], reverse=True)[:TOP_LANGS]
    total = sum(v["size"] for _, v in top) or 1
    bar_x, bar_w, bar_y = 24, WIDTH - 48, 58
    parts = [
        f'<clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="8" rx="4"/></clipPath>\n'
        f'<g clip-path="url(#bar)"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="8" fill="{t["bar_bg"]}"/>\n'
    ]
    x = float(bar_x)
    for _, v in top:
        w = bar_w * v["size"] / total
        parts.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{w:.2f}" height="8" fill="{v["color"]}"/>\n')
        x += w
    parts.append("</g>\n")
    for i, (name, v) in enumerate(top):
        col, row = i % 2, i // 2
        cx, cy = 24 + col * (WIDTH - 48) / 2, 98 + row * 26
        pct = 100 * v["size"] / total
        parts.append(
            f'<circle cx="{cx + 5:.1f}" cy="{cy - 4}" r="5" fill="{v["color"]}"/>\n'
            f'<text x="{cx + 16:.1f}" y="{cy}" font-family="{FONT}" font-size="13" fill="{t["text"]}">'
            f'{escape(name)} <tspan fill="{t["value"]}" font-weight="600">{pct:.1f}%</tspan></text>\n'
        )
    return svg_frame(theme, lab["langs_title"], "".join(parts))


SAMPLE_USER = {
    "repositories": {
        "totalCount": 31,
        "nodes": [
            {"stargazerCount": 3, "languages": {"edges": [
                {"size": 420000, "node": {"name": "Python", "color": "#3572A5"}},
                {"size": 260000, "node": {"name": "TypeScript", "color": "#3178c6"}},
                {"size": 90000, "node": {"name": "HCL", "color": "#844FBA"}},
                {"size": 900000, "node": {"name": "Jupyter Notebook", "color": "#DA5B0B"}},
            ]}},
            {"stargazerCount": 2, "languages": {"edges": [
                {"size": 120000, "node": {"name": "JavaScript", "color": "#f1e05a"}},
                {"size": 80000, "node": {"name": "Java", "color": "#b07219"}},
                {"size": 60000, "node": {"name": "C#", "color": "#178600"}},
                {"size": 30000, "node": {"name": "CSS", "color": "#663399"}},
                {"size": 15000, "node": {"name": "C++", "color": "#f34b7d"}},
                {"size": 9000, "node": {"name": "Shell", "color": "#89e051"}},
            ]}},
        ],
    },
    "pullRequests": {"totalCount": 214},
    "contributionsCollection": {
        "totalCommitContributions": 1180,
        "contributionCalendar": {"totalContributions": 1532},
    },
}


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    out_dir = argv[2]
    if argv[1] == "--sample":
        user = SAMPLE_USER
    else:
        token = os.environ.get("GH_TOKEN")
        if not token:
            sys.exit("GH_TOKEN is not set")
        user = fetch(argv[1], token)
    stats, langs = summarize(user)
    os.makedirs(out_dir, exist_ok=True)
    for lang in LABELS:
        for theme in THEMES:
            with open(os.path.join(out_dir, f"stats-{lang}-{theme}.svg"), "w", encoding="utf-8") as f:
                f.write(stats_card(stats, lang, theme))
            with open(os.path.join(out_dir, f"langs-{lang}-{theme}.svg"), "w", encoding="utf-8") as f:
                f.write(langs_card(langs, lang, theme))
    print(f"stats={stats} languages={len(langs)} -> {out_dir}")


if __name__ == "__main__":
    main(sys.argv)
