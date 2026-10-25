"""Fetch Indian business RSS feeds and return recent, de-duplicated items.

Only headline, link, source and published time are kept for storage. The RSS
teaser is passed to the LLM as context for that run only and is never saved.
"""
import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FEEDS = [
    ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Economic Times", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    ("Economic Times", "https://economictimes.indiatimes.com/news/company/corporate-trends/rssfeeds/2143429.cms"),
    ("ET BrandEquity", "https://brandequity.economictimes.indiatimes.com/rss/topstories"),
    ("Mint", "https://www.livemint.com/rss/companies"),
    ("Mint", "https://www.livemint.com/rss/markets"),
    ("Mint", "https://www.livemint.com/rss/industry"),
    ("Mint", "https://www.livemint.com/rss/economy"),
    ("Business Standard", "https://www.business-standard.com/rss/home_page_top_stories.rss"),
    ("Business Standard", "https://www.business-standard.com/rss/companies-101.rss"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Hindu BusinessLine", "https://www.thehindubusinessline.com/companies/feeder/default.rss"),
    ("Hindu BusinessLine", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("Hindu BusinessLine", "https://www.thehindubusinessline.com/economy/feeder/default.rss"),
]

UA = "Mozilla/5.0 (compatible; IMTPulse/1.0; student news digest)"
TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def _fetch(source, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            root = ET.fromstring(r.read())
    except Exception as e:  # one bad feed must not break the run
        print(f"feed failed: {url}: {e}")
        return []
    out = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime((it.findtext("pubDate") or "").strip())
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if title and link.startswith("http"):
            out.append({
                "headline": title,
                "link": link,
                "source": source,
                "published": published.astimezone(timezone.utc).isoformat(),
                "teaser": _clean(it.findtext("description"))[:300],
            })
    return out


def _norm(title):
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:80]


def fetch_recent(now=None, max_age_hours=36, min_age_hours=0):
    now = now or datetime.now(timezone.utc)
    newest = now - timedelta(hours=min_age_hours)
    oldest = now - timedelta(hours=max_age_hours)
    with ThreadPoolExecutor(8) as pool:
        batches = list(pool.map(lambda f: _fetch(*f), FEEDS))
    seen, items = set(), []
    for item in sorted((i for b in batches for i in b), key=lambda i: i["published"], reverse=True):
        ts = datetime.fromisoformat(item["published"])
        if not (oldest <= ts <= newest):
            continue
        key = _norm(item["headline"])
        if key in seen or item["link"] in seen:
            continue
        seen.update((key, item["link"]))
        item["id"] = hashlib.sha1(item["link"].encode()).hexdigest()[:10]
        items.append(item)
    return items
