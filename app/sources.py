"""소식 모으기. 출처마다 같은 모양의 dict 목록을 돌려준다.

item: id, source, title, url, discuss(토론 링크), points, comments, published(datetime, KST), rank(출처 안 순위, 0부터)
"""
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import requests
from bs4 import BeautifulSoup

from .store import KST

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
SOURCE_NAMES = {"geeknews": "긱뉴스", "hackernews": "HN", "reddit": "Reddit", "openai": "OpenAI",
                "google-ai": "Google AI", "claude-code": "Claude Code", "codex": "Codex", "youtube": "YouTube"}


def _get(url: str, **params) -> requests.Response:
    resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
    resp.raise_for_status()
    return resp


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(KST)


# ── 커뮤니티 (반응 수로 순위) ──────────────────────────
def geeknews(since: datetime, **_) -> list:
    soup = BeautifulSoup(_get("https://news.hada.io/").text, "html.parser")
    items = []
    for rank, row in enumerate(soup.select("div.topic_row")):
        topic_id = row.get("data-topic-state-id")
        link, heading = row.select_one("a.topic-title-link"), row.select_one("h2")
        points, when = row.select_one(f"#tp{topic_id}"), row.select_one("time")
        comments = row.select_one("[data-topic-comment-count]")
        if not (topic_id and link and heading):
            continue
        discuss = f"https://news.hada.io/topic?id={topic_id}"
        href = link["href"]
        items.append({"id": topic_id, "source": "geeknews", "title": heading.get_text(strip=True),
                      "url": discuss if href.startswith("topic?") else href, "discuss": discuss,
                      "points": int(points.get_text()) if points else 0,
                      "comments": int(comments["data-topic-comment-count"]) if comments else 0,
                      "published": _date(when.get("datetime") if when else None), "rank": rank})
    return [i for i in items if i["published"] is None or i["published"] >= since]


def hackernews(since: datetime, **_) -> list:
    data = _get("https://hn.algolia.com/api/v1/search", tags="story", hitsPerPage=40,
                numericFilters=f"created_at_i>{int(since.timestamp())},points>30").json()
    hits = sorted(data["hits"], key=lambda h: h.get("points") or 0, reverse=True)
    return [{"id": h["objectID"], "source": "hackernews", "title": h["title"],
             "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
             "discuss": f"https://news.ycombinator.com/item?id={h['objectID']}",
             "points": h.get("points") or 0, "comments": h.get("num_comments") or 0,
             "published": _date(h.get("created_at")), "rank": rank}
            for rank, h in enumerate(hits)]


def reddit(since: datetime, subreddits: list = (), **_) -> list:
    """RSS에는 추천 수가 없어서 '오늘 TOP' 순서를 순위로 쓴다. 서브레딧 하나가 막혀도 나머지는 읽는다."""
    items = []
    for n, sub in enumerate(subreddits):
        if n:
            time.sleep(3)  # 연달아 부르면 429
        try:
            root = ET.fromstring(_get(f"https://www.reddit.com/r/{sub}/top/.rss", t="day", limit=10).content)
        except Exception as exc:
            logger.warning("reddit r/%s: %s", sub, exc)
            continue
        for rank, entry in enumerate(root.findall(f"{ATOM}entry")):
            published = _date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated"))
            link = entry.find(f"{ATOM}link").get("href")
            # 링크 글이면 본문의 [link]가 원문, 아니면 레딧 글 자체
            content = unescape(entry.findtext(f"{ATOM}content") or "")
            outbound = re.search(r'<a href="([^"]+)">\[link\]</a>', content)
            url = outbound[1] if outbound and "reddit.com" not in outbound[1] else link
            items.append({"id": entry.findtext(f"{ATOM}id"), "source": "reddit", "sub": sub,
                          "title": entry.findtext(f"{ATOM}title"), "url": url, "discuss": link,
                          "points": 0, "comments": 0, "published": published, "rank": rank})
    return [i for i in items if i["published"] is None or i["published"] >= since]


# ── 공식 발표·릴리스 (순위 없이 새로 나온 것 전부) ───────
def _feed(url: str, source: str, since: datetime) -> list:
    root = ET.fromstring(_get(url).content)
    items = []
    for entry in root.iter():
        if entry.tag not in ("item", f"{ATOM}entry"):
            continue
        if entry.tag == "item":
            title, link = entry.findtext("title"), entry.findtext("link")
            published = _date(entry.findtext("pubDate"))
        else:
            title = entry.findtext(f"{ATOM}title")
            link_el = entry.find(f"{ATOM}link")
            link = link_el.get("href") if link_el is not None else None
            published = _date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated"))
        if title and link and published and published >= since:
            items.append({"id": link, "source": source, "title": title.strip(), "url": link, "discuss": None,
                          "points": 0, "comments": 0, "published": published, "rank": len(items)})
    return items


def openai(since: datetime, **_) -> list:
    return _feed("https://openai.com/news/rss.xml", "openai", since)


def google_ai(since: datetime, **_) -> list:
    return _feed("https://blog.google/technology/ai/rss/", "google-ai", since)


def claude_code(since: datetime, **_) -> list:
    return _feed("https://github.com/anthropics/claude-code/releases.atom", "claude-code", since)[:1]  # 하루에 여러 번 나와도 최신 하나만


def codex(since: datetime, **_) -> list:
    # 알파·베타 태그가 하루에도 여러 개라 정식 릴리스만
    return [i for i in _feed("https://github.com/openai/codex/releases.atom", "codex", since)
            if not re.search(r"alpha|beta|rc", i["title"], re.I)][:1]


def youtube(since: datetime, channels: list = (), **_) -> list:
    items = []
    for channel in channels:
        try:
            root = ET.fromstring(_get("https://www.youtube.com/feeds/videos.xml", channel_id=channel).content)
        except Exception as exc:
            logger.warning("youtube %s: %s", channel, exc)
            continue
        author = root.findtext(f"{ATOM}title")
        for entry in root.findall(f"{ATOM}entry"):
            published = _date(entry.findtext(f"{ATOM}published"))
            if published and published >= since:
                url = entry.find(f"{ATOM}link").get("href")
                items.append({"id": url, "source": "youtube", "author": author,
                              "title": entry.findtext(f"{ATOM}title"), "url": url, "discuss": None,
                              "points": 0, "comments": 0, "published": published, "rank": len(items),
                              "short": "/shorts/" in url})
    return items


SOURCES = {"geeknews": geeknews, "hackernews": hackernews, "reddit": reddit, "openai": openai,
           "google-ai": google_ai, "claude-code": claude_code, "codex": codex, "youtube": youtube}


def collect(names: list, since: datetime, **options) -> tuple[list, list]:
    """(items, 실패한 출처). 출처 하나가 실패해도 나머지는 모은다."""
    items, failed = [], []
    for name in names:
        try:
            got = SOURCES[name](since, **options)
            logger.info("%s: %d", name, len(got))
            items += got
        except Exception as exc:
            logger.warning("%s failed: %s", name, exc)
            failed.append(name)
    return items, failed


def default_since(hours: int = 24) -> datetime:
    return datetime.now(KST) - timedelta(hours=hours)
