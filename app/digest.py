"""커뮤니티 소식 묶기·순위, Gemini 한국어 요약."""
import json
import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
# 출처 안에서 1위는 1.0, 아래로 갈수록 줄어든다. 레딧은 추천 수를 몰라 순서만 보니 조금 낮게
WEIGHT = {"hackernews": 1.0, "geeknews": 1.0, "reddit": 0.7}
CROSS_BONUS = 0.4  # 다른 커뮤니티에도 올라왔으면 화제성이 높다
MAX_PER_SOURCE = 3


def url_key(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/")
    if "youtube.com" in host or "news.hada.io" in host or "ycombinator" in host:
        return f"{host}{path}?{parts.query}"
    return f"{host}{path}"


def group(items: list) -> list:
    """같은 원문 링크는 하나로 묶는다. 묶음: key, head, members, sources, score."""
    groups: dict[str, dict] = {}
    for item in items:
        key = url_key(item["url"])
        g = groups.setdefault(key, {"key": key, "members": []})
        g["members"].append(item)
    counts = {s: sum(1 for i in items if i["source"] == s) for s in WEIGHT}
    for g in groups.values():
        scores = []
        for item in g["members"]:
            n = max(counts.get(item["source"], 1), 1)
            scores.append(WEIGHT.get(item["source"], 0.5) * (1 - item["rank"] / (n + 1)))
        g["sources"] = sorted({i["source"] for i in g["members"]})
        g["score"] = max(scores) + CROSS_BONUS * (len(g["sources"]) - 1)
        g["head"] = max(g["members"], key=lambda i: (i["source"] == "geeknews", i["points"]))  # 한국어 제목 우선
    return sorted(groups.values(), key=lambda g: g["score"], reverse=True)


def tier(g: dict) -> str | None:
    """Scouty가 한마디 할 만큼 이례적인지: '대박'·'논란'·None. 기준은 우리끼리만 쓰고 디스코드에는 말하지 않는다."""
    best = {s: max((i for i in g["members"] if i["source"] == s), key=lambda i: i["points"], default=None) for s in WEIGHT}
    hn, gn = best["hackernews"], best["geeknews"]
    # 기준은 지난 일주일 글로 맞췄다: HN 첫 화면 글이 대개 400~800, 긱뉴스 인기 글이 10~30
    if hn and hn["comments"] >= 300 and hn["comments"] > hn["points"]:  # 추천보다 댓글이 많으면 싸우는 중
        return "논란"
    if (hn and hn["points"] >= 1000) or (gn and gn["points"] >= 30):
        return "대박"
    if hn and gn and hn["points"] >= 500 and gn["points"] >= 15:  # 긱뉴스 번역 글은 흔해서, 둘 다 뜨거울 때만
        return "대박"
    return None


def top(items: list, n: int, exclude: set) -> list:
    picks, per_source = [], {}
    for g in group(items):
        if g["key"] in exclude:
            continue
        lead = max(g["members"], key=lambda i: WEIGHT.get(i["source"], 0) * (1 - i["rank"] / 50))["source"]
        if per_source.get(lead, 0) >= MAX_PER_SOURCE:
            continue
        per_source[lead] = per_source.get(lead, 0) + 1
        picks.append(g)
        if len(picks) == n:
            break
    return picks


_PROMPT = """개발자 친구들 디스코드에 올릴 오늘의 IT·개발 소식이야. 각 항목을 한국어로 정리해.
- title: 무슨 소식인지 바로 알 수 있는 한국어 제목. 40자 이내. 제품·회사·API 이름은 원문 철자를 한 글자도 바꾸지 말고 그대로 써.
- summary: text를 읽고 "그래서 뭐가 새롭거나 흥미로운지"를 한국어 한 문장으로. 60자 이내.
  "~에 대한 글입니다", "최신 업데이트입니다"처럼 제목을 되풀이하는 말은 쓰지 마. text에 없는 내용은 지어내지 마.
  릴리스 노트면 눈에 띄는 새 기능이나 변경 한두 개를 이름으로 짚어.
- relevant: 개발·IT·AI·스타트업·테크 업계 소식이면 true. 정치·연예·일반 사회 뉴스처럼 개발자와 상관없으면 false.
- major: kind가 official일 때만 의미 있어. 새 모델·새 제품·새 API·가격 변경처럼 개발자들이 이야기할 만한 큰 발표면 true.
  파트너십, 고객 사례, 행사, 엔지니어링 블로그, 정책 글은 false.

headline: 오늘 개발자 친구들이 절대 놓치면 안 되는 소식 하나를 relevant인 항목 중에서 골라.
OpenAI·ChatGPT·Codex나 Anthropic·Claude의 새 모델·제품·큰 변화가 있으면 그것을 고르고, 없으면 커뮤니티에서 가장 화제인 소식을 골라.
- id: 고른 항목의 id
- title: 글 제목에 쓸 아주 짧은 한국어 헤드라인. 25자 이내, 마침표 없이.
- line: 왜 중요한지 한국어 한 문장. 60자 이내.

items: {items}"""

_SCHEMA = {
    "type": "object",
    "properties": {"headline": {"type": "object", "properties": {
        "id": {"type": "string"}, "title": {"type": "string"}, "line": {"type": "string"}},
        "required": ["id", "title", "line"]},
                   "items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "summary": {"type": "string"},
                       "relevant": {"type": "boolean"}, "major": {"type": "boolean"}},
        "required": ["id", "title", "summary", "relevant", "major"],
    }}},
    "required": ["items", "headline"],
}


def summarize(entries: list[dict]) -> tuple[dict[str, dict], dict | None]:
    """entries: id, kind(community/official), title, text. ({id: {title, summary, relevant, major}}, headline).

    실패하면 ({}, None): 원래 제목으로, 헤드라인 없이 올린다.
    """
    if not entries or not os.environ.get("GEMINI_API_KEY"):
        return {}, None
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"timeout": 90_000})  # ms
    prompt = _PROMPT.format(items=json.dumps(entries, ensure_ascii=False))
    for model in (MODEL, FALLBACK_MODEL):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config={
                "response_mime_type": "application/json", "response_schema": _SCHEMA})
            data = json.loads(resp.text)
            return {i["id"]: i for i in data["items"]}, data.get("headline")
        except Exception as exc:
            logger.warning("summarize with %s failed: %s", model, str(exc)[:200])
    return {}, None

