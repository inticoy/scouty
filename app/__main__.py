"""Scouty: 여러 출처에서 소식을 모아 목적지(디스코드 채널)마다 정해진 시각에 올린다.

목적지는 config/destinations.json에 있다. 지금 형식은 daily-forum(날짜별 포럼 글) 하나.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from . import digest, discord, sources
from .sources import SOURCE_NAMES
from .store import KST, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CONFIG = Path("config/destinations.json")
LATE_LIMIT = timedelta(hours=3)  # Actions가 늦게 돌아도 이 안이면 그 시간대 글을 올린다
DAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]
MAX_MESSAGE = 1900


def destinations() -> list[dict]:
    return json.loads(CONFIG.read_text())["destinations"]


def _link_text(text: str) -> str:
    return text.replace("[", "［").replace("]", "］")


def _reaction(item: dict) -> str:
    name = SOURCE_NAMES[item["source"]] + (f" r/{item['sub']}" if item.get("sub") else "")
    stats = "".join(x for x in (f" ▲{item['points']}" if item["points"] else "",
                                 f" 💬{item['comments']}" if item["comments"] else ""))
    return f"[{name}{stats}](<{item['discuss']}>)" if item.get("discuss") else name + stats


def build(dest: dict, store: Store, now: datetime) -> tuple[str, list[str], list[str]] | None:
    """(글 제목, 메시지들, 올렸다고 기록할 키). 올릴 게 없으면 None."""
    since = now - timedelta(hours=24)
    community, failed = sources.collect(dest["community"], since, subreddits=dest.get("reddit", []))
    official, failed2 = sources.collect(dest.get("official", []), since)
    videos, failed3 = sources.collect(["youtube"] if dest.get("videos") else [], since, channels=dest.get("videos", []))
    if failed + failed2 + failed3:
        logger.warning("failed sources: %s", failed + failed2 + failed3)

    exclude = store.posted_keys(dest["id"])
    n = dest.get("top", 5)
    candidates = digest.top(community, n * 3, exclude)  # 개발과 상관없는 글을 Gemini가 걸러낼 여유
    official = [i for i in official if digest.url_key(i["url"]) not in exclude]
    videos = [i for i in videos if digest.url_key(i["url"]) not in exclude]
    if not (candidates or official):
        return None

    entries = [{"id": g["key"], "title": g["head"]["title"]} for g in candidates]
    entries += [{"id": digest.url_key(i["url"]), "title": f"{SOURCE_NAMES[i['source']]}: {i['title']}"} for i in official]
    ko = digest.summarize(entries)
    picks = [g for g in candidates if ko.get(g["key"], {}).get("relevant", True)][:n]

    lines = [f"## 🔥 오늘의 TOP {len(picks)}"] if picks else []
    for n, g in enumerate(picks, 1):
        head, info = g["head"], ko.get(g["key"], {})
        lines.append(f"**{n}. [{_link_text(info.get('title') or head['title'])}](<{head['url']}>)**")
        if info.get("summary"):
            lines.append(info["summary"])
        lines.append("-# " + " · ".join(_reaction(i) for i in sorted(g["members"], key=lambda i: -i["points"])))
    first = "\n".join(lines)

    rest = []
    if official:
        rest.append("## 📢 공식 발표·릴리스")
        for i in official:
            info = ko.get(digest.url_key(i["url"]), {})
            rest.append(f"- **{SOURCE_NAMES[i['source']]}** [{_link_text(info.get('title') or i['title'])}](<{i['url']}>)")
            if info.get("summary"):
                rest.append(f"  -# {info['summary']}")
    if videos:
        rest.append("## 📺 새 영상")
        rest += [f"- {i['author']} · [{_link_text(i['title'])}](<{i['url']}>){' (쇼츠)' if i.get('short') else ''}" for i in videos]
    rest.append("-# 번호로 이야기해 주세요. 예: \"2번 써봤는데…\"")

    messages = _split([first] if first else []) + _split(["\n".join(rest)])
    title = f"{now.month}/{now.day} ({DAYS_KO[now.weekday()]}) {dest['name']}"
    keys = [g["key"] for g in picks] + [digest.url_key(i["url"]) for i in official + videos]
    return title, messages, keys


def _split(blocks: list[str]) -> list[str]:
    """2000자 제한에 맞춰 줄 단위로 나눈다."""
    out = []
    for block in blocks:
        current = ""
        for line in block.split("\n"):
            if len(current) + len(line) + 1 > MAX_MESSAGE:
                out.append(current)
                current = ""
            current += ("\n" if current else "") + line
        if current:
            out.append(current)
    return out


def post(dest: dict, store: Store, dry_run: bool) -> bool:
    built = build(dest, store, datetime.now(KST))
    if built is None:
        logger.warning("%s — 올릴 소식 없음", dest["name"])
        return False
    title, messages, keys = built
    if dry_run:
        print(f"[DRY RUN] {title}\n" + "\n\n----- (다음 메시지) -----\n".join(messages))
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
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd == "cycle":
        if not cycle(args.dry_run):
            sys.exit(1)
    elif args.cmd == "post":
        store = Store()
        for dest in destinations():
            if not args.ids or dest["id"] in args.ids:
                post(dest, store, args.dry_run)
    else:
        parser.print_help()


main()
