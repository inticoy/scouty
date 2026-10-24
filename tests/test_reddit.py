from datetime import datetime, timedelta

from app import sources

FEED = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">{}</feed>"""
ENTRY = """<entry><category term="{sub}" label="r/{sub}"/><id>t3_{n}</id><title>{sub} {n}</title>
<link href="https://www.reddit.com/r/{sub}/comments/{n}/"/><published>{at}</published>
<content type="html">&lt;a href="https://example.org/{n}"&gt;[link]&lt;/a&gt;</content></entry>"""


class Response:
    def __init__(self, content):
        self.content = content.encode()


def test_one_request_split_by_subreddit(monkeypatch):
    now = datetime.now(sources.KST)
    at = now.isoformat()
    entries = [ENTRY.format(sub="LocalLLaMA", n=n, at=at) for n in range(12)]
    entries += [ENTRY.format(sub="claudeai", n=100 + n, at=at) for n in range(3)]
    calls = []
    monkeypatch.setattr(sources, "_get", lambda url, **params: calls.append(url) or Response(FEED.format("".join(entries))))
    items = sources.reddit(now - timedelta(days=1), ["ClaudeAI", "LocalLLaMA"])
    assert calls == ["https://www.reddit.com/r/ClaudeAI+LocalLLaMA/top/.rss"]
    assert [i["rank"] for i in items if i["sub"] == "ClaudeAI"] == [0, 1, 2]
    assert len([i for i in items if i["sub"] == "LocalLLaMA"]) == 10
    assert items[0]["url"].startswith("https://example.org/")


def test_gives_up_quietly_after_retry(monkeypatch):
    def fail(url, **params):
        raise OSError("429")
    monkeypatch.setattr(sources, "_get", fail)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    assert sources.reddit(datetime.now(sources.KST) - timedelta(days=1), ["ClaudeAI"]) == []
