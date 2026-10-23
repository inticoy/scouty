<h1 align="center">Scouty</h1>

여러 출처에서 소식을 모아, 디스코드 채널마다 정해진 시각에 정리해 올려 주는 봇입니다.
첫 목적지는 친구들 개발 서버의 **패치노트** 포럼으로, 매일 아침 9시에 날짜별 글 하나를 올립니다.

- **🔥 오늘의 TOP 5**: 긱뉴스·Hacker News·Reddit에서 지난 24시간 동안 반응이 컸던 글. 같은 원문은 하나로 묶고, 여러 커뮤니티에 올라왔으면 순위를 올립니다.
- **📢 공식 발표·릴리스**: OpenAI·Google AI 블로그, Claude Code·Codex 새 버전.
- **📺 새 영상**: 등록한 유튜브 채널(조코딩 등)의 새 영상·쇼츠.
- 제목과 한 줄 요약은 Gemini가 한국어로 씁니다. 정치·연예처럼 개발과 상관없는 글은 걸러 냅니다.
- 한 번 올린 소식은 14일 동안 다시 올리지 않습니다. 링크 미리보기와 푸시 알림은 끕니다.

## 목적지 추가

`config/destinations.json`에 목적지를 하나 더 적고, 그 채널 ID를 `.env`(`channel_env`에 적은 이름)에 넣습니다. 그 서버에도 봇을 초대해야 합니다.

| 키 | 뜻 |
|---|---|
| `format` | `daily-forum`: 포럼 채널에 날짜별 글 |
| `slots` | 올리는 시각(KST) |
| `community` · `reddit` | 순위를 매길 커뮤니티와 서브레딧 |
| `official` | 공식 발표 출처 (`openai`, `google-ai`, `claude-code`, `codex`) |
| `videos` | 유튜브 채널 ID |

## 실행

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                    # 봇 토큰·채널 ID·Gemini 키
.venv/bin/python -m app post --dry-run  # 전송 없이 오늘 글 미리 보기
.venv/bin/python -m app post            # 지금 바로 올리기
```

GitHub Actions(`.github/workflows/cycle.yml`)가 9·10·11시에 확인해 아직 안 올렸으면 올립니다. 비밀값 `ENV_FILE`에 `.env` 내용을 넣습니다.

Python 3.14 · requests · BeautifulSoup · Gemini · Discord REST.
