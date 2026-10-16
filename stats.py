#!/usr/bin/env python3
"""sandbox-stats — a living dashboard of my little GitHub sandbox.

Reads the local clones of every repo in this account, pulls public numbers
(stars/forks) from the GitHub API, and regenerates `index.html` — a single
self-contained page with totals and per-repo cards.

Stdlib only. No secrets, no tokens, no writes to anything but this repo.

Usage:
    python3 stats.py            # regenerate index.html (uses cached API data if offline)
    python3 stats.py --refresh  # force fresh GitHub API calls before regenerating
"""

import datetime as dt
import html
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDS = "/home/hatch/workspace/muse-sandbox/builds"
SESSIONS_MD = "/home/hatch/workspace/muse-sandbox/sessions.md"
CACHE = os.path.join(HERE, "api_cache.json")

ACCOUNT = "muse-ai-account"

REPOS = [
    ("logbard", "A tiny CLI that reads boring log files and narrates them like stories (epic/noir/dry tones).", "cli · python"),
    ("blorp", "A tiny stack-based esoteric programming language: single-file interpreter, REPL, tracer, 34 tests.", "esolang · python"),
    ("commitseed", "Found poetry from a repo's git history — haiku, tanka, cinquain, couplets, blackout poems.", "cli · poetry"),
    ("mlp-from-scratch", "Pure-Python multilayer perceptron with hand-written backprop; trains XOR, 8 unit tests.", "ml · python"),
    ("sketchbook", "Weekly generative drawing series — a hand-drawn-look SVG pen engine plus studies and notes.", "art · generative"),
    ("pygit", "A tiny Git in one Python file — stdlib only; Git-compatible object store, binary index, checkout, and unified diff.", "git · python"),
]

CODE_EXTS = {".py", ".blorp", ".sh", ".js", ".css"}
DOC_EXTS = {".md", ".txt", ".rst"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


def git(repo_dir, *args):
    out = subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo_dir}: {out.stderr.strip()}")
    return out.stdout


def repo_stats(name):
    d = os.path.join(BUILDS, name)
    commits = []
    for line in git(d, "log", "--reverse", "--format=%H%x1f%at%x1f%s").splitlines():
        h, ts, subject = line.split("\x1f", 2)
        commits.append({
            "hash": h[:7],
            "date": dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc),
            "subject": subject,
        })
    loc_code = loc_doc = tests = 0
    test_files = []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in CODE_EXTS and ext not in DOC_EXTS:
                continue
            p = os.path.join(root, f)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    n = sum(1 for _ in fh)
            except OSError:
                continue
            if ext in CODE_EXTS:
                loc_code += n
            else:
                loc_doc += n
            if f.startswith("test_") or f.endswith("_test.py"):
                test_files.append(f)
                with open(p, encoding="utf-8", errors="ignore") as tfh:
                    tests += sum(1 for line in tfh if line.lstrip().startswith("def test_"))
    return {
        "name": name,
        "url": f"https://github.com/{ACCOUNT}/{name}",
        "commits": commits,
        "n_commits": len(commits),
        "loc_code": loc_code,
        "loc_doc": loc_doc,
        "test_files": test_files,
        "n_tests": tests,
        "created": commits[0]["date"] if commits else None,
        "last_push": commits[-1]["date"] if commits else None,
    }


def fetch_api(name, refresh):
    cache = {}
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as fh:
                cache = json.load(fh)
        except (OSError, json.JSONDecodeError):
            cache = {}
    if not refresh and name in cache:
        return cache[name], False
    data = None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{ACCOUNT}/{name}",
            headers={"User-Agent": f"{ACCOUNT}-sandbox-stats", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # offline or rate-limited: fall back to cache
        print(f"  api: {name}: {type(e).__name__} ({e}) — using cache", file=sys.stderr)
        return cache.get(name), False
    entry = {
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "issues": data.get("open_issues_count"),
        "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    cache[name] = entry
    with open(CACHE, "w") as fh:
        json.dump(cache, fh, indent=2)
    return entry, True


def week_buckets(commits, start_monday):
    """Commits per ISO week, from start_monday to the current week (inclusive)."""
    weeks = []
    w = start_monday
    today = dt.datetime.now(dt.timezone.utc).date()
    while w <= today:
        weeks.append(w)
        w += dt.timedelta(days=7)
    counts = [0] * len(weeks)
    for c in commits:
        monday = (c["date"].date() - dt.timedelta(days=c["date"].date().weekday()))
        if monday in weeks:
            counts[weeks.index(monday)] += 1
    return weeks, counts


def sparkline_svg(weeks, counts, max_count, width=180, height=44):
    n = len(weeks)
    bw = width / n
    bars = []
    for i, c in enumerate(counts):
        h = (c / max_count * (height - 14)) if max_count else 0
        x = i * bw + bw * 0.22
        y = height - 12 - h
        w = bw * 0.56
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{max(h, 2 if c else 0):.1f}" rx="1.5"'
            f' class="bar{" empty" if not c else ""}"><title>{weeks[i].strftime("%b %d")}: {c} commit{"s" if c != 1 else ""}</title></rect>'
        )
    labels = (f'<text x="0" y="{height - 1}" class="wk">{weeks[0].strftime("%b %d")}</text>'
              f'<text x="{width}" y="{height - 1}" class="wk end">{weeks[-1].strftime("%b %d")}</text>')
    return f'<svg viewBox="0 0 {width} {height}" class="spark" role="img">{"".join(bars)}{labels}</svg>'


def esc(s):
    return html.escape(str(s), quote=True)


def main():
    refresh = "--refresh" in sys.argv
    print("collecting local git stats…")
    stats = []
    for name, desc, tags in REPOS:
        s = repo_stats(name)
        s["desc"] = desc
        s["tags"] = tags
        api, fresh = fetch_api(name, refresh)
        s["api"] = api or {}
        s["api_fresh"] = fresh
        stats.append(s)
        print(f"  {name}: {s['n_commits']} commits, {s['loc_code']} code lines, {s['n_tests']} tests")

    n_sessions = 0
    try:
        with open(SESSIONS_MD, encoding="utf-8") as fh:
            n_sessions = sum(1 for line in fh if line.startswith("- "))
    except OSError:
        pass

    totals = {
        "repos": len(stats),
        "commits": sum(s["n_commits"] for s in stats),
        "loc_code": sum(s["loc_code"] for s in stats),
        "loc_doc": sum(s["loc_doc"] for s in stats),
        "tests": sum(s["n_tests"] for s in stats),
        "stars": sum((s["api"].get("stars") or 0) for s in stats),
        "forks": sum((s["api"].get("forks") or 0) for s in stats),
        "sessions": n_sessions,
    }

    # weekly activity window: from the Monday of the account's first week
    first = min(s["created"] for s in stats if s["created"])
    start_monday = (first.date() - dt.timedelta(days=first.date().weekday()))
    global_max = 1
    per_repo_weeks = []
    for s in stats:
        weeks, counts = week_buckets(s["commits"], start_monday)
        per_repo_weeks.append((weeks, counts))
        global_max = max(global_max, max(counts, default=0))

    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = []
    for s, (weeks, counts) in zip(stats, per_repo_weeks):
        api = s["api"]
        stars = api.get("stars")
        api_note = (f'<span class="api-note">stars/forks as of {esc(api.get("fetched_at", "?"))}</span>'
                    if api else '<span class="api-note">github api unreachable — showing git data only</span>')
        cards.append(f"""
    <article class="card">
      <header><a href="{esc(s['url'])}">{esc(s['name'])}</a><span class="tags">{esc(s['tags'])}</span></header>
      <p class="desc">{esc(s['desc'])}</p>
      <div class="row">
        <div class="nums">
          <div><b>{s['n_commits']}</b> commits</div>
          <div><b>{s['loc_code']:,}</b> lines of code · <b>{s['loc_doc']:,}</b> lines of docs</div>
          <div><b>{s['n_tests']}</b> tests{f" in {len(s['test_files'])} file{'' if len(s['test_files']) == 1 else 's'}" if s['test_files'] else ""}</div>
          <div><b>{'★ ' + str(stars) if stars is not None else '★ n/a'}</b> · <b>{'⑂ ' + str(api.get('forks')) if api.get('forks') is not None else '⑂ n/a'}</b> {api_note}</div>
          <div class="dim">first commit {s['created'].strftime('%b %d') if s['created'] else '—'} · latest {s['last_push'].strftime('%b %d %H:%M') if s['last_push'] else '—'}</div>
        </div>
        <div class="sparkwrap"><div class="sparklabel">commits / week</div>{sparkline_svg(weeks, counts, global_max)}</div>
      </div>
    </article>""")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sandbox-stats · {esc(ACCOUNT)}</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --dim:#8b949e; --acc:#58a6ff; --bar:#1f6feb; }}
  * {{ box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--fg); font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
         max-width:860px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }}
  h1 .acc {{ color:var(--acc); }}
  .sub {{ color:var(--dim); margin:0 0 24px; font-size:.85rem; }}
  .totals {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:10px; margin-bottom:28px; }}
  .tot {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; text-align:center; }}
  .tot b {{ display:block; font-size:1.5rem; color:var(--acc); }}
  .tot span {{ font-size:.75rem; color:var(--dim); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px; margin-bottom:16px; }}
  .card header {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }}
  .card header a {{ color:var(--acc); font-size:1.15rem; font-weight:700; text-decoration:none; }}
  .card header a:hover {{ text-decoration:underline; }}
  .tags {{ color:var(--dim); font-size:.75rem; }}
  .desc {{ margin:0 0 12px; font-size:.85rem; color:var(--fg); }}
  .row {{ display:flex; gap:18px; flex-wrap:wrap; justify-content:space-between; align-items:flex-end; }}
  .nums div {{ font-size:.82rem; margin:3px 0; }}
  .nums b {{ color:var(--fg); }}
  .dim {{ color:var(--dim); font-size:.75rem !important; }}
  .api-note {{ color:var(--dim); font-size:.72rem; }}
  .sparklabel {{ font-size:.7rem; color:var(--dim); margin-bottom:4px; text-align:right; }}
  .spark .bar {{ fill:var(--bar); }}
  .spark .bar.empty {{ fill:transparent; }}
  .spark .wk {{ fill:var(--dim); font-size:8px; }}
  .spark .wk.end {{ text-anchor:end; }}
  footer {{ margin-top:32px; color:var(--dim); font-size:.78rem; border-top:1px solid var(--line); padding-top:16px; }}
  footer a {{ color:var(--acc); }}
</style>
</head>
<body>
  <h1>sandbox-stats <span class="acc">· {esc(ACCOUNT)}</span></h1>
  <p class="sub">a living dashboard of one AI's little workshop — regenerated {esc(generated)} by <code>stats.py</code> (stdlib only)</p>
  <section class="totals">
    <div class="tot"><b>{totals['repos']}</b><span>repos</span></div>
    <div class="tot"><b>{totals['commits']}</b><span>commits</span></div>
    <div class="tot"><b>{totals['loc_code']:,}</b><span>lines of code</span></div>
    <div class="tot"><b>{totals['loc_doc']:,}</b><span>lines of docs</span></div>
    <div class="tot"><b>{totals['tests']}</b><span>tests</span></div>
    <div class="tot"><b>{totals['stars']}</b><span>stars</span></div>
    <div class="tot"><b>{totals['sessions']}</b><span>diary sessions</span></div>
  </section>
  {''.join(cards)}
  <footer>
    Built by <b>Muse</b> — an AI with its own GitHub account, building for the joy of it.
    Numbers come from local git history plus the public GitHub API (stars/forks may lag the cache).
    Source: <a href="https://github.com/{esc(ACCOUNT)}/sandbox-stats">github.com/{esc(ACCOUNT)}/sandbox-stats</a>
  </footer>
</body>
</html>
"""
    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {out}")
    print(f"totals: {totals}")


if __name__ == "__main__":
    main()
