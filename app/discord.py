"""Discord REST: 포럼 글 만들기와 글에 메시지 이어 쓰기."""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
# 링크 미리보기 카드가 다섯 개씩 붙으면 글이 길어져서 끄고, 푸시도 보내지 않는다
SUPPRESS_EMBEDS = 1 << 2
SUPPRESS_NOTIFICATIONS = 1 << 12
FLAGS = SUPPRESS_EMBEDS | SUPPRESS_NOTIFICATIONS


def _post(path: str, payload: dict) -> dict:
    for _ in range(3):
        resp = requests.post(f"{API_BASE}{path}", json=payload, timeout=15,
                             headers={"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"})
        if resp.status_code == 429:
            time.sleep(float(resp.json().get("retry_after", 2)))
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}


def create_post(forum_id: str, title: str, messages: list[str], tags: list[str] | None = None) -> str:
    """포럼에 글을 만들고 나머지 메시지를 이어 쓴다. 글(스레드) ID."""
    payload = {"name": title[:100], "message": {"content": messages[0], "flags": FLAGS,
                                               "allowed_mentions": {"parse": []}}}
    if tags:
        payload["applied_tags"] = tags
    thread = _post(f"/channels/{forum_id}/threads", payload)
    for content in messages[1:]:
        time.sleep(1)
        _post(f"/channels/{thread['id']}/messages", {"content": content, "flags": FLAGS,
                                                    "allowed_mentions": {"parse": []}})
    return thread["id"]
