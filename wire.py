#!/usr/bin/env python3
"""
PR STARPOWER — The Wire
Pulls live headlines from entertainment and technology trades and rebuilds
the wire block inside newsroom.html.

No API key. No cost. Runs on GitHub Actions free tier.
Headlines and links only, with source attribution and outbound links —
standard aggregation practice. No article text is reproduced.
"""

import re
import html
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- feeds
# Grouped by beat. Add or remove freely — the script adapts.
FEEDS = [
    # The Pulse — entertainment trades
    ("Variety",        "https://variety.com/feed/",                        "Pulse"),
    ("Deadline",       "https://deadline.com/feed/",                       "Pulse"),
    ("The Wrap",       "https://www.thewrap.com/feed/",                    "Pulse"),
    ("Billboard",      "https://www.billboard.com/feed/",                  "Pulse"),
    ("Rolling Stone",  "https://www.rollingstone.com/music/feed/",         "Pulse"),

    # The Business of the Business
    ("Hollywood Reporter", "https://www.hollywoodreporter.com/feed/",      "Business"),
    ("Music Business Worldwide", "https://www.musicbusinessworldwide.com/feed/", "Business"),

    # Technology and AI
    ("TechCrunch AI",  "https://techcrunch.com/category/artificial-intelligence/feed/", "Tech"),
    ("The Verge AI",   "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "Tech"),
    ("Ars Technica",   "https://feeds.arstechnica.com/arstechnica/technology-lab", "Tech"),
]

# House items — PR STARPOWER's own wire copy.
# Edit wire-house.txt to add them. One item per line, pipe separated:
#   headline | link | beat | YYYY-MM-DD HH:MM | image (optional)
# Beat is Pulse, Business or Tech. Link may be a local page (news-x.html).
HOUSE_FILE = "wire-house.txt"

MAX_PER_FEED = 4
MAX_TOTAL = 18
TIMEOUT = 20

BEAT_LABEL = {
    "Pulse":    "The Pulse",
    "Business": "The Business",
    "Tech":     "Tech &amp; AI",
}

UA = "Mozilla/5.0 (compatible; PRStarpowerWire/1.0; +https://prstarpower.com)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for f in fmts:
        try:
            d = datetime.strptime(text, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except ValueError:
            continue
    # handle "+0000" style offsets that strptime chokes on
    try:
        cleaned = re.sub(r"\s+\(.*\)$", "", text)
        return datetime.strptime(cleaned, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return None


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def load_house():
    """Read PR STARPOWER's own items so they take a slot in the wire."""
    items = []
    try:
        lines = open(HOUSE_FILE, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return items

    for raw in lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 3:
            print("  house: skipping malformed line -> %s" % raw[:60])
            continue

        title, link, beat = parts[0], parts[1], parts[2]
        image = parts[4].strip() if len(parts) >= 5 and parts[4].strip() else None
        when = datetime.now(timezone.utc)
        if len(parts) >= 4 and parts[3]:
            try:
                when = datetime.strptime(parts[3], "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc)
            except ValueError:
                print("  house: bad date on '%s', using now" % title[:40])

        if beat not in BEAT_LABEL:
            beat = "Pulse"

        items.append({
            "title": title,
            "link": link,
            "source": "PR STARPOWER",
            "beat": beat,
            "when": when,
            "house": True,
            "image": image,
        })

    print("  house items: %d" % len(items))
    return items


def collect():
    items = []
    for name, url, beat in FEEDS:
        try:
            raw = fetch(url)
            root = ET.fromstring(raw)
        except Exception as e:
            print("  skip %s (%s)" % (name, type(e).__name__))
            continue

        entries = root.findall(".//item")
        atom = "{http://www.w3.org/2005/Atom}"
        if not entries:
            entries = root.findall(".//%sentry" % atom)

        count = 0
        for e in entries:
            if count >= MAX_PER_FEED:
                break

            t = e.find("title")
            if t is None:
                t = e.find("%stitle" % atom)
            title = strip_tags(html.unescape(t.text)) if t is not None and t.text else None

            l = e.find("link")
            link = None
            if l is not None:
                link = (l.text or "").strip() or l.get("href")
            if not link:
                l2 = e.find("%slink" % atom)
                if l2 is not None:
                    link = l2.get("href")

            d = e.find("pubDate")
            if d is None:
                d = e.find("%supdated" % atom)
            if d is None:
                d = e.find("%spublished" % atom)
            when = parse_date(d.text if d is not None else None)

            if not title or not link:
                continue
            if len(title) > 130:
                title = title[:127].rstrip() + "…"

            items.append({
                "title": title,
                "link": link,
                "source": name,
                "beat": beat,
                "when": when or datetime.now(timezone.utc),
            })
            count += 1

        print("  %s: %d" % (name, count))

    house = load_house()
    # House items are never crowded out by wire copy. We reserve their slots
    # first, then fill the remainder with the newest trade headlines, and only
    # then sort — otherwise older house items get truncated off the bottom.
    wire_only = [i for i in items if not i.get("house")]
    wire_only.sort(key=lambda x: x["when"], reverse=True)
    room = max(0, MAX_TOTAL - len(house))
    merged = house + wire_only[:room]
    merged.sort(key=lambda x: x["when"], reverse=True)
    return merged


def relative(when, now):
    delta = now - when
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return "%dm ago" % mins
    hrs = mins // 60
    if hrs < 24:
        return "%dh ago" % hrs
    days = hrs // 24
    if days == 1:
        return "yesterday"
    return "%dd ago" % days


def build_block(items):
    now = datetime.now(timezone.utc)
    pacific = now - timedelta(hours=7)
    stamp = pacific.strftime("%d %B %Y, %H:%M") + " PT"

    rows = []
    for it in items:
        is_house = it.get("house")
        cls = "wire-row house" if is_house else "wire-row"
        target = "" if is_house else ' target="_blank" rel="noopener nofollow"'
        src_label = ("<b>PR STARPOWER</b>" if is_house
                     else html.escape(it["source"]))
        beat_label = (BEAT_LABEL.get(it["beat"], it["beat"])
                      if not is_house else "Ours")
        pic = ""
        if is_house and it.get("image"):
            pic = ('<img class="wire-pic" src="%s" alt="" loading="lazy">'
                   % html.escape(it["image"], quote=True))
            cls += " haspic"
        tmpl = (
            '      <a class="%s" href="%s"%s>\n'
            '        <span class="wire-beat">%s</span>\n'
            '        <span class="wire-title">' + pic + '%s</span>\n'
            '        <span class="wire-meta">%s &middot; %s</span>\n'
            '      </a>'
        )
        rows.append(tmpl % (
            cls,
            html.escape(it["link"], quote=True),
            target,
            beat_label,
            html.escape(it["title"]),
            src_label,
            relative(it["when"], now),
        ))

    return (
        '<!-- WIRE:START -->\n'
        '<section class="wire-sec">\n'
        '  <div class="wrap">\n'
        '    <div class="wire-head">\n'
        '      <span class="wire-label"><i class="dot"></i>The Wire — Live</span>\n'
        '      <span class="wire-stamp">Updated %s</span>\n'
        '    </div>\n'
        '    <div class="wire-list">\n%s\n    </div>\n'
        '    <p class="wire-note">Headlines aggregated from industry trades and '
        'linked to their original publishers. PR STARPOWER original reporting and '
        'analysis appears below.</p>\n'
        '  </div>\n'
        '</section>\n'
        '<!-- WIRE:END -->'
        % (stamp, "\n".join(rows))
    )


WIRE_CSS = """
  /* ---- The Wire ---- */
  .wire-sec{border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
    background:var(--surface);padding:34px 0;margin-bottom:8px}
  .wire-head{display:flex;justify-content:space-between;align-items:center;
    gap:16px;flex-wrap:wrap;margin-bottom:20px}
  .wire-label{font-family:var(--wire);font-size:10px;letter-spacing:.28em;
    text-transform:uppercase;color:var(--brass);display:flex;align-items:center;gap:9px}
  .wire-label .dot{width:6px;height:6px;border-radius:50%;background:#7BE3A0;
    display:inline-block;animation:pulse 2.4s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  .wire-stamp{font-family:var(--wire);font-size:9.5px;letter-spacing:.16em;
    text-transform:uppercase;color:var(--ash)}
  .wire-list{display:grid;grid-template-columns:1fr 1fr;gap:0 40px}
  .wire-row{display:grid;grid-template-columns:96px 1fr;gap:14px;
    padding:11px 0;border-bottom:1px solid rgba(176,141,87,.14);
    text-decoration:none;align-items:baseline;transition:opacity .25s}
  .wire-row:hover{opacity:.62}
  .wire-beat{font-family:var(--wire);font-size:8.5px;letter-spacing:.16em;
    text-transform:uppercase;color:var(--brass);padding-top:3px}
  .wire-title{font-size:14px;line-height:1.5;color:var(--bone);font-weight:300}
  .wire-meta{grid-column:2;font-family:var(--wire);font-size:9px;
    letter-spacing:.12em;text-transform:uppercase;color:var(--ash);margin-top:5px}
  .wire-pic{width:100%;max-width:150px;aspect-ratio:16/9;object-fit:cover;
    display:block;margin-bottom:9px;border:1px solid var(--rule)}
  .wire-row.house{border-bottom-color:rgba(232,217,181,.34)}
  .wire-row.house .wire-beat{color:var(--champagne)}
  .wire-row.house .wire-title{color:var(--champagne)}
  .wire-row.house .wire-meta b{font-weight:700;color:var(--brass)}
  .wire-note{margin-top:20px;font-size:11.5px;line-height:1.6;color:var(--ash);
    max-width:60ch}
  @media(max-width:860px){.wire-list{grid-template-columns:1fr;gap:0}}
"""



def build_rss(items):
    """Generate an RSS feed of PR STARPOWER house items.

    This is the plumbing that makes social automation possible. Free services
    (Buffer, IFTTT, Zapier, dlvr.it) watch an RSS feed and post to social
    accounts automatically. No API keys needed on our side.
    """
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%a, %d %b %Y %H:%M:%S +0000")

    entries = []
    for it in items:
        if not it.get("house"):
            continue
        link = it["link"]
        if not link.startswith("http"):
            link = "https://prstarpower.com/" + link.lstrip("/")
        pub = it["when"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        img = ""
        if it.get("image"):
            src = it["image"]
            if not src.startswith("http"):
                src = "https://prstarpower.com/" + src.lstrip("/")
            img = ('\n      <enclosure url="%s" type="image/jpeg" length="0"/>'
                   % html.escape(src, quote=True))
        entries.append(
            "    <item>\n"
            "      <title>%s</title>\n"
            "      <link>%s</link>\n"
            "      <guid isPermaLink=\"true\">%s</guid>\n"
            "      <pubDate>%s</pubDate>\n"
            "      <description>%s</description>%s\n"
            "    </item>"
            % (html.escape(it["title"]), html.escape(link, quote=True),
               html.escape(link, quote=True), pub,
               html.escape(it["title"]), img)
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        '    <title>PR STARPOWER Newsroom</title>\n'
        '    <link>https://prstarpower.com/newsroom.html</link>\n'
        '    <description>Announcements, releases and analysis from '
        'PR STARPOWER, a Hollywood representation house.</description>\n'
        '    <language>en-us</language>\n'
        '    <lastBuildDate>%s</lastBuildDate>\n'
        '%s\n'
        '  </channel>\n'
        '</rss>\n' % (stamp, "\n".join(entries))
    )
    open("feed.xml", "w", encoding="utf-8").write(feed)
    print("feed.xml written with %d items." % len(entries))


def main():
    print("Fetching feeds...")
    items = collect()
    if not items:
        print("No items retrieved — leaving the page untouched.")
        return

    print("Collected %d items." % len(items))

    path = "newsroom.html"
    page = open(path, encoding="utf-8").read()

    # ensure CSS present
    if ".wire-sec{" not in page:
        page = page.replace("  @media(max-width:860px){",
                            WIRE_CSS + "\n  @media(max-width:860px){", 1)

    block = build_block(items)

    if "<!-- WIRE:START -->" in page:
        page = re.sub(r"<!-- WIRE:START -->.*?<!-- WIRE:END -->",
                      lambda m: block, page, flags=re.S)
    else:
        # insert directly above the feed
        page = page.replace('<div class="wrap">\n  <div class="feed">',
                            block + '\n\n<div class="wrap">\n  <div class="feed">', 1)

    open(path, "w", encoding="utf-8").write(page)
    print("newsroom.html updated.")

    build_rss(items)


if __name__ == "__main__":
    main()
