"""원문 페이지에서 썸네일(og:image)과 설명(og:description)을 읽는다. 카드 그림과 Gemini 요약 재료."""
import ipaddress
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .sources import UA

logger = logging.getLogger(__name__)


def _youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([\w-]{11})", url)
    return m[1] if m else None


MAX_BYTES = 512 * 1024
DEADLINE = 10  # 초: 한 페이지에 쓰는 전체 시간


def _public(url: str) -> bool:
    """링크는 커뮤니티 글에서 온다: 러너 안쪽(사설·루프백·메타데이터 주소)으로는 가지 않는다."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def _fetch_html(url: str) -> str | None:
    """공개 주소만, 리다이렉트도 하나씩 확인하며, 크기·시간을 정해 두고 읽는다."""
    started = time.monotonic()
    for _ in range(4):
        if not _public(url):
            return None
        with requests.get(url, headers={"User-Agent": UA}, timeout=5, stream=True, allow_redirects=False) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("location", ""))
                continue
            if not resp.ok or "html" not in resp.headers.get("content-type", ""):
                return None
            body = b""
            for chunk in resp.iter_content(16 * 1024):
                body += chunk
                if len(body) >= MAX_BYTES or time.monotonic() - started > DEADLINE:
                    break
            return body[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
    return None


def preview(url: str) -> dict:
    """{image, description}. 못 읽으면 빈 값."""
    if vid := _youtube_id(url):
        return {"image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "description": ""}
    try:
        html = _fetch_html(url)
        if html is None:
            return {"image": None, "description": ""}
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.info("preview %s: %s", url, exc)
        return {"image": None, "description": ""}

    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    image = meta("og:image", "twitter:image")
    return {"image": urljoin(url, image) if image else None,
            "description": (meta("og:description", "description", "twitter:description") or "")[:400]}


def previews(urls: list[str]) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(urls, pool.map(preview, urls)))
