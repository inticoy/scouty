"""Scouty 한마디: 그날 카드 아래 친구처럼 짧게 다는 댓글. 특별한 게 없으면 아무 말도 하지 않는다."""
import json
import logging
import os

logger = logging.getLogger(__name__)

MODELS = (os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"), os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"))

STYLE = """말투 규칙:
- 디시·커뮤니티 친구 말투. 반말 음슴체. 한 줄에 20자 안팎, 짧게.
- ㄷㄷ ㅋㅋ ;; ㄹㅇ 실화냐 개쩐다 이거 뭐임 갓 미쳤다 같은 표현을 자연스럽게. 매 줄에 다 넣지는 마.
- 숫자·점수·추천 수·댓글 수·커뮤니티 이름(HN, 긱뉴스, 레딧 등)은 절대 말하지 마. 내용이 왜 놀랍거나 이상한지만 말해.
- 사람·회사를 향한 욕설, 비하, 혐오 표현은 쓰지 마. '~충' 같은 말도 쓰지 마.
- 이모지 쓰지 마. "나머지는 무난" 같은 마무리 말도 하지 마."""

_PROMPT = """너는 개발자 친구들 디스코드에서 매일 IT 소식을 물어오는 Scouty야.
아래는 오늘 소식 중 우리가 이례적이라고 판단한 것들이야.
tier가 대박이면 놀라운 점을, 논란이면 뭐가 수상하거나 말이 많은지를 말해. (tier라는 말 자체는 쓰지 마)
한 항목에 한 줄, 최대 2줄. 정말 할 말이 없으면 빈 배열.
각 줄은 그 항목의 n을 그대로 써서 "4번 "처럼 시작해 (새로 1, 2로 매기지 마).
줄마다 "무엇이 왜" 놀랍거나 이상한지가 꼭 들어가야 해. "화력 미쳤네", "대박이네"처럼 내용 없는 감탄만 하면 안 돼.

{style}

items: {items}"""

_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
           "required": ["lines"]}


def comment(items: list[dict]) -> list[str]:
    """items: n, tier(대박/논란), title, summary. 할 말 줄들 (없으면 빈 목록)."""
    if not items or not os.environ.get("GEMINI_API_KEY"):
        return []
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"timeout": 90_000})
    prompt = _PROMPT.format(style=STYLE, items=json.dumps(items, ensure_ascii=False))
    for model in MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config={
                "response_mime_type": "application/json", "response_schema": _SCHEMA})
            return json.loads(resp.text)["lines"][:2]
        except Exception as exc:
            logger.warning("comment with %s failed: %s", model, str(exc)[:200])
    return []
