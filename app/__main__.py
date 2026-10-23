"""Scouty: 여러 출처에서 소식을 모아 목적지(디스코드 채널)마다 정해진 시각에 올린다.

목적지는 config/destinations.json에 있다 (첫 목적지: 친구들 개발 서버의 #tech-news). 지금 형식은 daily-forum(날짜별 포럼 글) 하나.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv()

from . import digest, discord, pages, sources
from .sources import SOURCE_NAMES
from .store import KST, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CONFIG = Path("config/destinations.json")
PREVIEW = Path("data/preview.json")  # --dry-run 결과 (미리보기 페이지용)
LATE_LIMIT = timedelta(hours=3)  # Actions가 늦게 돌아도 이 안이면 그 시간대 글을 올린다
DAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]
RANK_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣"}
RELEASES = {"claude-code", "codex"}  # 릴리스는 늘 싣고, 블로그 글은 큰 발표만
MAX_OFFICIAL, MAX_VIDEOS = 4, 3
# 카드 왼쪽 띠 색: 캐릭터의 민트 별, 남색 모자, 유튜브 빨강
COLOR = {"top": 0x2EC4B6, "official": 0x3B4A7A, "videos": 0xFF3B3B}
MORE = [("긱뉴스", "https://news.hada.io/"), ("Hacker News", "https://news.ycombinator.com/")]


def destinations() -> list[dict]:
    return json.loads(CONFIG.read_text())["destinations"]


def _link_text(text: str) -> str:
    return text.replace("[", "［").replace("]", "］")


def _reaction(item: dict) -> str:
    name = SOURCE_NAMES[item["source"]] + (f" r/{item['sub']}" if item.get("sub") else "")
    stats = "".join(x for x in (f" ▲{item['points']}" if item["points"] else "",
                                 f" 💬{item['comments']}" if item["comments"] else ""))
    # 링크 글자에 💬 같은 이모지가 있으면 디스코드가 링크로 읽지 않아서, 숫자는 링크 밖에 둔다
    return f"[{name}]({item['discuss']}){stats}" if item.get("discuss") else name + stats


def _section(text: str, image: str | None) -> dict:
    """글 한 줄 카드. 썸네일이 있으면 오른쪽에 붙인다."""
    if not image:
        return {"type": 10, "content": text}
    return {"type": 9, "components": [{"type": 10, "content": text}],
            "accessory": {"type": 11, "media": {"url": quote(image, safe=":/?&=%#+,;@~!$'()*[]")}}}


def _container(title: str, cards: list[dict], color: int, extra: list[dict] = ()) -> dict:
    items = [{"type": 10, "content": title}]
    for card in cards:
        items += [{"type": 14, "divider": True, "spacing": 1}, card]
    return {"type": 17, "accent_color": color, "components": items + list(extra)}


def build(dest: dict, store: Store, now: datetime) -> tuple[str, list[dict], list[str]] | None:
    """(글 제목, 메시지 payload들, 올렸다고 기록할 키). 올릴 게 없으면 None."""
    since = now - timedelta(hours=24)
    until = now if now < datetime.now(KST) - timedelta(hours=1) else None  # 지난 날짜로 만들 때
    community, failed = sources.collect(dest["community"], since, until, subreddits=dest.get("reddit", []))
    official, failed2 = sources.collect(dest.get("official", []), since, until)
    videos, failed3 = sources.collect(["youtube"] if dest.get("videos") else [], since, until, channels=dest.get("videos", {}))
    if failed + failed2 + failed3:
        logger.warning("failed sources: %s", failed + failed2 + failed3)

    exclude = store.posted_keys(dest["id"])
    n = dest.get("top", 5)
    candidates = digest.top(community, n * 3, exclude)  # 개발과 상관없는 글을 Gemini가 걸러낼 여유
    official = [i for i in official if digest.url_key(i["url"]) not in exclude]
    videos = [i for i in videos if digest.url_key(i["url"]) not in exclude][:MAX_VIDEOS]
    if not (candidates or official):
        return None

    page = pages.previews([g["head"]["url"] for g in candidates] + [i["url"] for i in official + videos])
    entries = [{"id": g["key"], "kind": "community", "title": g["head"]["title"],
                "text": page[g["head"]["url"]]["description"]} for g in candidates]
    entries += [{"id": digest.url_key(i["url"]), "kind": "official", "title": f"{SOURCE_NAMES[i['source']]}: {i['title']}",
                 "text": i.get("text") or page[i["url"]]["description"]} for i in official]
    ko, headline = digest.summarize(entries)
    picks = [g for g in candidates if ko.get(g["key"], {}).get("relevant", True)][:n]
    lead_pick = next((g for g in candidates if headline and g["key"] == headline["id"]), None)
    if lead_pick and lead_pick not in picks:  # 헤드라인으로 고른 소식은 TOP에 꼭 들어가게 (맨 아래 대신)
        picks = picks[:n - 1] + [lead_pick]
    official = [i for i in official if i["source"] in RELEASES
                or ko.get(digest.url_key(i["url"]), {}).get("major", False)][:MAX_OFFICIAL]

    date = f"{now.month}/{now.day} ({DAYS_KO[now.weekday()]})"
    # 글 제목에 오늘 꼭 알아야 할 소식을 넣어, 포럼 목록만 봐도 알 수 있게
    title = f"{date} {headline['title']}" if headline else f"{date} {dest['name']}"
    lead = f"\n> 📌 **{headline['title']}** — {headline['line']}" if headline else ""
    messages = []
    if picks:
        cards = []
        for rank, g in enumerate(picks, 1):
            head, info = g["head"], ko.get(g["key"], {})
            lines = [f"{RANK_EMOJI.get(rank, f'{rank}.')} **[{_link_text(info.get('title') or head['title'])}]({head['url']})**"]
            if info.get("summary"):
                lines.append(info["summary"])
            lines.append("-# " + " · ".join(_reaction(i) for i in sorted(g["members"], key=lambda i: -i["points"])))
            cards.append(_section("\n".join(lines), page[head["url"]]["image"]))
        buttons = {"type": 1, "components": [{"type": 2, "style": 5, "label": f"{label} 더 보기", "url": url}
                                              for label, url in MORE]}
        messages.append({"components": [
            {"type": 10, "content": f"## 📰 {date} {dest['name']}{lead}\n-# 지난 24시간 커뮤니티에서 반응이 컸던 소식 TOP {len(picks)}"},
            _container(f"### 🔥 오늘의 TOP {len(picks)}", cards, COLOR["top"],
                       [{"type": 14, "divider": False, "spacing": 1}, buttons])]})

    rest = []
    if official:
        cards = []
        for i in official:
            info = ko.get(digest.url_key(i["url"]), {})
            text = f"**{SOURCE_NAMES[i['source']]}** · [{_link_text(info.get('title') or i['title'])}]({i['url']})"
            if info.get("summary"):
                text += f"\n-# {info['summary']}"
            cards.append(_section(text, None if i["source"] in RELEASES else page[i["url"]]["image"]))
        rest.append(_container("### 📢 공식 발표·릴리스", cards, COLOR["official"]))
    if videos:
        cards = [_section(f"[{_link_text(i['title'])}]({i['url']})\n-# {i['author']}{' · 쇼츠' if i.get('short') else ''} · 👀 {i['points']:,}",
                          page[i["url"]]["image"]) for i in videos]
        rest.append(_container("### 📺 새 영상", cards, COLOR["videos"]))
    rest.append({"type": 10, "content": "-# 번호로 이야기해 주세요. 예: \"2번 써봤는데…\""})
    messages.append({"components": rest})

    keys = [g["key"] for g in picks] + [digest.url_key(i["url"]) for i in official + videos]
    return title, messages, keys


def post(dest: dict, store: Store, dry_run: bool, now: datetime | None = None) -> bool:
    built = build(dest, store, now or datetime.now(KST))
    if built is None:
        logger.warning("%s — 올릴 소식 없음", dest["name"])
        return False
    title, messages, keys = built
    if dry_run:
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW.write_text(json.dumps({"title": title, "messages": messages}, ensure_ascii=False, indent=1))
        print(f"[DRY RUN] {title}: {len(messages)} messages → {PREVIEW}")
        return True
    channel = os.environ[dest["channel_env"]]
    thread = discord.create_post(channel, title, messages, dest.get("tags"))
    store.mark_posted(dest["id"], keys)
    logger.info("%s — posted thread %s (%d items)", dest["name"], thread, len(keys))
    return True


def due(dest: dict, store: Store, now: datetime) -> list[str]:
    keys = []
    for hour in dest["slots"]:
        slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        key = f"posted:{dest['id']}:{slot:%Y-%m-%d-%H}"
        if slot <= now < slot + LATE_LIMIT and store.get_meta(key) is None:
            keys.append(key)
    return keys


def cycle(dry_run: bool) -> bool:
    store, ok = Store(), True
    for dest in destinations():
        for key in due(dest, store, datetime.now(KST)):
            try:
                if post(dest, store, dry_run) and not dry_run:
                    store.set_meta(key, datetime.now(KST).isoformat(timespec="seconds"))
            except Exception:  # 한 목적지가 실패해도 나머지는 올리고, 다음 실행에서 다시 시도한다
                logger.exception("%s failed", dest["id"])
                ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(prog="app")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("cycle", help="정해진 시각이 된 목적지에 글 올리기")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("post", help="지금 바로 올리기 (시험용)")
    p.add_argument("ids", nargs="*", help="목적지 id (없으면 전부)")
    p.add_argument("--date", help="지난 날짜로 만들기 YYYY-MM-DD (그날 첫 시각 기준 24시간)")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd == "cycle":
        if not cycle(args.dry_run):
            sys.exit(1)
    elif args.cmd == "post":
        store = Store()
        for dest in destinations():
            if not args.ids or dest["id"] in args.ids:
                now = None
                if args.date:
                    now = datetime.strptime(args.date, "%Y-%m-%d").replace(hour=dest["slots"][0], tzinfo=KST)
                post(dest, store, args.dry_run, now)
    else:
        parser.print_help()


main()
