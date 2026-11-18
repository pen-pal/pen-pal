#!/usr/bin/env python3
"""Render dark_mode.svg / light_mode.svg: a neofetch-style GitHub profile card.

Stdlib only. Needs GH_TOKEN (a PAT with `repo` scope also counts private work).
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from html import escape

USER = os.environ.get("GH_USER", "pen-pal")
TOKEN = os.environ["GH_TOKEN"]
TITLE = "manish@pen-pal"
WIDTH = 58  # info column, in characters
ABOUT = [("Location", "Nepal"), ("Focus", "Cloud · DevOps · Security")]  # edit me

THEMES = {
    "dark": dict(bg="#161b22", fg="#c9d1d9", key="#ffa657", value="#a5d6ff", add="#3fb950", dele="#f85149", cc="#616e7f"),
    "light": dict(bg="#f6f8fa", fg="#24292f", key="#953800", value="#0a3069", add="#1a7f37", dele="#cf222e", cc="#c2cfde"),
}


def api(path, body=None):
    url = "https://api.github.com" + path
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                 {"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-card"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return r.status, json.loads(raw) if raw else None


def gql(query, **variables):
    data = api("/graphql", {"query": query, "variables": variables})[1]
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]["user"]


def fetch():
    now = dt.datetime.now(dt.timezone.utc)
    user = gql("""query($u:String!){user(login:$u){createdAt followers{totalCount}
        repositories(ownerAffiliations:OWNER){totalCount}
        repositoriesContributedTo(includeUserRepositories:false,
          contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY]){totalCount}}}""", u=USER)
    created = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))

    repos, cursor = [], None
    while True:
        page = gql("""query($u:String!,$c:String){user(login:$u){repositories(first:100,after:$c,
            ownerAffiliations:OWNER,isFork:false){pageInfo{hasNextPage endCursor}
            nodes{nameWithOwner stargazerCount
              languages(first:10,orderBy:{field:SIZE,direction:DESC}){edges{size node{name color}}}}}}}""",
                   u=USER, c=cursor)["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    # contributionsCollection spans at most one year, so alias one per year in a single query.
    fields = "totalCommitContributions contributionCalendar{weeks{contributionDays{date contributionCount}}}"
    parts = [f'week:contributionsCollection(from:"{(now - dt.timedelta(days=7)).isoformat()}"){{totalCommitContributions}}']
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        parts.append(f'y{year}:contributionsCollection(from:"{start.isoformat()}",to:"{end.isoformat()}"){{{fields}}}')
    contrib = gql(f"query($u:String!){{user(login:$u){{{' '.join(parts)}}}}}", u=USER)
    years = [v for k, v in contrib.items() if k.startswith("y")]
    days = {d["date"]: d["contributionCount"]
            for y in years for w in y["contributionCalendar"]["weeks"] for d in w["contributionDays"]}

    day = now.date() if days.get(now.date().isoformat()) else now.date() - dt.timedelta(days=1)
    streak = 0
    while days.get(day.isoformat()):
        streak, day = streak + 1, day - dt.timedelta(days=1)

    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            size, color = langs.get(name, (0, None))
            langs[name] = (size + e["size"], e["node"]["color"] or "#8b949e")

    added, deleted = loc([r["nameWithOwner"] for r in repos])
    return dict(
        created=created, now=now, langs=langs, added=added, deleted=deleted, streak=streak,
        repos=user["repositories"]["totalCount"], contributed=user["repositoriesContributedTo"]["totalCount"],
        followers=user["followers"]["totalCount"], stars=sum(r["stargazerCount"] for r in repos),
        commits=sum(y["totalCommitContributions"] for y in years), week=contrib["week"]["totalCommitContributions"],
    )


def loc(names):
    """Sum my additions/deletions from /stats/contributors (GitHub computes these async, 202 = not ready)."""
    added = deleted = 0
    for _ in range(5):
        pending = []
        for name in names:
            try:
                status, data = api(f"/repos/{name}/stats/contributors")
            except urllib.error.HTTPError:
                continue
            if status == 202:
                pending.append(name)
                continue
            for c in data or []:
                if (c.get("author") or {}).get("login", "").lower() == USER.lower():
                    added += sum(w["a"] for w in c["weeks"])
                    deleted += sum(w["d"] for w in c["weeks"])
        if not pending:
            break
        names = pending
        time.sleep(10)
    # ponytail: repos still computing after 5 rounds are skipped this run; add a cache if numbers wobble.
    return added, deleted


# --- layout: a line is a list of (text, style) where style is a class name, a #color, or None ---

def width(segs):
    return sum(len(t) for t, _ in segs)


def header(title):
    return [(f"- {title} ", None), ("—" * (WIDTH - len(title) - 4) + "-", None)]


def row(*pairs):
    """'. key: ..... value | key: ..... value', pairs dot-filled so the line spans WIDTH."""
    segs = [(". ", "cc")]
    for i, (key, value) in enumerate(pairs):
        value = [(value, "value")] if isinstance(value, str) else value
        if i:
            segs.append((" | ", None))
        left = len(pairs) - i  # last pair absorbs the rounding remainder
        share = (WIDTH - width(segs) - 3 * (left - 1)) // left
        dots = share - len(key) - width(value) - 2
        segs += [(key, "key"), (" " + "." * dots + " " if dots > 0 else " ", "cc"), *value]
    return segs


def lines(d):
    age = d["now"].date() - d["created"].date()
    years, days = divmod(age.days, 365)
    total = sum(s for s, _ in d["langs"].values()) or 1
    top = sorted(d["langs"].items(), key=lambda kv: -kv[1][0])[:5]

    out = [[(TITLE, None), (" " + "—" * (WIDTH - len(TITLE) - 2) + "-", None)]]
    out += [row(("Uptime:", f"{years} years, {days // 30} months, {days % 30} days"))]
    out += [row((f"{k}:", v)) for k, v in ABOUT]
    out += [[], header("Most used languages")]
    for i, (name, (size, color)) in enumerate(top, 1):
        out.append(row((f"{i}.", [(name, color), (f" {100 * size / total:.1f}%", "value"),
                                 (f" ({size / 1e6:.1f}MB)", "cc")])))
    bar, cols = [], WIDTH - 2
    for name, (size, color) in top:
        bar.append(("█" * round(cols * size / total), color))
    bar.append(("█" * max(cols - width(bar), 0), "cc"))
    out += [[("  ", None), *bar]]
    out += [[], header("GitHub Stats")]
    out += [
        row(("Repos:", f"{d['repos']:,}"), ("Contributed:", f"{d['contributed']:,}")),
        row(("Stars:", f"{d['stars']:,}"), ("Followers:", f"{d['followers']:,}")),
        row(("Commits:", f"{d['commits']:,}"), ("Commits (7d):", f"{d['week']:,}")),
        row(("Streak:", f"{d['streak']} days")),
        row(("Lines of Code:", [(f"{d['added'] - d['deleted']:,}", "value"), (" ( ", None),
                               (f"{d['added']:,}++", "add"), (", ", None), (f"{d['deleted']:,}--", "dele"), (" )", None)])),
    ]
    return out


def svg(info, art, t):
    art_x, info_x, lh = 15, 390, 20
    w = info_x + round(WIDTH * 9.7) + 30
    h = max(len(info) * lh, len(art) * 12) + 40
    tspan = lambda text, s: (f'<tspan class="{s}">' if s and not s.startswith("#") else
                             f'<tspan fill="{s}">' if s else "<tspan>") + escape(text) + "</tspan>"
    body = "".join(f'<tspan x="{info_x}" y="{30 + i * lh}"></tspan>' + "".join(tspan(*s) for s in line)
                   for i, line in enumerate(info))
    art_y = 20 + (h - 40 - len(art) * 12) // 2  # vertically centred
    art_body = "".join(f'<tspan x="{art_x}" y="{art_y + i * 12}">{escape(line)}</tspan>' for i, line in enumerate(art))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{w}" height="{h}" font-family="Consolas,Menlo,monospace" font-size="16px">
<style>
.key{{fill:{t['key']}}} .value{{fill:{t['value']}}} .add{{fill:{t['add']}}} .dele{{fill:{t['dele']}}} .cc{{fill:{t['cc']}}}
text,tspan{{white-space:pre}}
</style>
<rect width="{w}" height="{h}" fill="{t['bg']}" rx="15"/>
<text font-size="10px" fill="{t['fg']}" opacity=".7">{art_body}</text>
<text fill="{t['fg']}">{body}</text>
</svg>
"""


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    art = open(os.path.join(here, "ascii.txt")).read().splitlines()
    info = lines(fetch())
    for name, theme in THEMES.items():
        with open(os.path.join(here, f"{name}_mode.svg"), "w") as f:
            f.write(svg(info, art, theme))
