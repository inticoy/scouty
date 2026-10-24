"""Discord REST: 포럼 글 만들기와 글에 메시지 이어 쓰기."""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
# 카드형(Components V2) 메시지로, 푸시는 보내지 않는다
IS_COMPONENTS_V2 = 1 << 15
SUPPRESS_NOTIFICATIONS = 1 << 12
FLAGS = IS_COMPONENTS_V2 | SUPPRESS_NOTIFICATIONS


def _post(path: str, payload: dict) -> dict:
    for _ in range(3):
        resp = requests.post(f"{API_BASE}{path}", json=payload, timeout=15,
                             headers={"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"})
        if resp.status_code == 429:
            time.sleep(float(resp.json().get("retry_after", 2)))
            continue
        if not resp.ok:
            logger.error("Discord %s: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}


def _v2(message: dict) -> dict:  # 카드는 Components V2, Scouty 한마디는 일반 메시지
    flags = SUPPRESS_NOTIFICATIONS if "content" in message else FLAGS
    return message | {"flags": flags, "allowed_mentions": {"parse": []}}


def create_post(forum_id: str, title: str, message: dict, tags: list[str] | None = None) -> str:
    """첫 메시지로 포럼 글을 만들고 글(스레드) ID를 돌려준다."""
    payload = {"name": title[:100], "message": _v2(message)}
    if tags:
        payload["applied_tags"] = tags
    thread = _post(f"/channels/{forum_id}/threads", payload)
    return thread["id"]


def send_message(thread_id: str, message: dict):
    time.sleep(1)
    _post(f"/channels/{thread_id}/messages", _v2(message))
