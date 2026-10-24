from datetime import datetime
from unittest.mock import Mock, patch

with patch("dotenv.load_dotenv"):
    from app import __main__ as app
from app import monitoring
from app.store import KST, Store

DEST = {"id": "tech", "name": "Tech News", "channel_env": "TEST_FORUM", "slots": [21],
        "community": ["hackernews", "reddit"], "official": [], "videos": {}}


def test_cycle_reports_failed_sources_and_post(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_ENV", "prod")
    monkeypatch.setenv("MONITOR_ENDPOINT", "https://monitoring.example")
    sent = Mock(return_value=True)
    monkeypatch.setattr(monitoring, "send", sent)
    store = Store(tmp_path / "state.db")
    monkeypatch.setattr(app, "Store", lambda: store)
    monkeypatch.setattr(app, "destinations", lambda: [DEST])
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 25, 21, 5, tzinfo=KST)
    monkeypatch.setattr(app, "datetime", clock)
    monkeypatch.setattr(app.sources, "collect", Mock(side_effect=[([], ["reddit"]), ([], []), ([], [])]))
    assert app.cycle(False)  # 올릴 게 없어도 실행은 정상
    events = {e["component"]: e for e in sent.call_args.args[1]}
    assert events["source.reddit"]["severity"] == "degraded"
    assert events["source.hackernews"]["severity"] == "ok"
    assert events["post.tech"]["severity"] == "ok"
    assert sent.call_args.args[0] == "scouty"
