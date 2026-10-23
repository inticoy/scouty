"""원문 페이지에서 썸네일(og:image)과 설명(og:description)을 읽는다. 카드 그림과 Gemini 요약 재료."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .sources import UA

logger = logging.getLogger(__name__)


def _youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([\w-]{11})", url)
    return m[1] if m else None


def preview(url: str) -> dict:
    """{image, description}. 못 읽으면 빈 값."""
    if vid := _youtube_id(url):
        return {"image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "description": ""}
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=8)
        if not resp.ok or "html" not in resp.headers.get("content-type", ""):
            return {"image": None, "description": ""}
        soup = BeautifulSoup(resp.text[:300_000], "html.parser")
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
