from datetime import datetime
from unittest.mock import Mock, patch

import pytest

with patch("dotenv.load_dotenv"):
    from app import __main__ as app
from app import discord
from app.store import KST, Store


NOW = datetime(2026, 10, 25, 21, 5, tzinfo=KST)
DEST = {"id": "tech", "name": "Tech", "channel_env": "TEST_FORUM", "slots": [21]}
MESSAGES = [{"components": [{"type": 10, "content": "top"}]},
            {"components": [{"type": 10, "content": "official"}]}, {"content": "comment"}]
KEYS = [["top-key"], ["official-key"], []]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("network")))
    monkeypatch.setenv("TEST_FORUM", "forum")
    monkeypatch.setattr(discord.time, "sleep", Mock())


@pytest.mark.parametrize("failed_message", [1, 2])
def test_partial_send_resumes_after_reopening_store(tmp_path, monkeypatch, failed_message):
    path = tmp_path / "state.db"
    store = Store(path)
    build = Mock(return_value=("title", MESSAGES, KEYS))
    monkeypatch.setattr(app, "build", build)
    calls = []

    def send(path, payload):
        calls.append((path, payload))
        if len(calls) == failed_message + 1:
            raise RuntimeError("send failed")
        return {"id": "thread"}

    monkeypatch.setattr(discord, "_post", send)
    with pytest.raises(RuntimeError, match="send failed"):
        app.post(DEST, store, False, NOW)
    assert store.get_delivery("tech", "2026-10-25")["sent"] == failed_message
    assert store.posted_keys("tech") == set(sum(KEYS[:failed_message], []))
    store.db.close()

    store = Store(path)
    retry = Mock(return_value={"id": "message"})
    monkeypatch.setattr(discord, "_post", retry)
    assert app.post(DEST, store, False, NOW)
    assert build.call_count == 1
    assert retry.call_count == len(MESSAGES) - failed_message
    for call, message in zip(retry.call_args_list, MESSAGES[failed_message:]):
        assert call.args == ("/channels/thread/messages", discord._v2(message))
    assert calls[0] == ("/channels/forum/threads", {"name": "title", "message": discord._v2(MESSAGES[0])})
    assert store.posted_keys("tech") == {"top-key", "official-key"}
    assert store.get_delivery("tech", "2026-10-25")["sent"] == 3
    retry.reset_mock()
    assert app.post(DEST, store, False, NOW)
    retry.assert_not_called()


def test_cycle_records_slot_on_retry_without_duplicate_thread(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    monkeypatch.setattr(app, "Store", lambda: store)
    monkeypatch.setattr(app, "destinations", lambda: [DEST])
    clock = Mock()
    clock.now.return_value = NOW
    monkeypatch.setattr(app, "datetime", clock)
    monkeypatch.setattr(app, "build", Mock(return_value=("title", MESSAGES, KEYS)))
    request = Mock(side_effect=[{"id": "thread"}, RuntimeError("failed")])
    monkeypatch.setattr(discord, "_post", request)
    assert not app.cycle(False)
    assert app.due(DEST, store, NOW) == ["posted:tech:2026-10-25-21"]
    request = Mock(return_value={"id": "message"})
    monkeypatch.setattr(discord, "_post", request)
    assert app.cycle(False)
    assert app.due(DEST, store, NOW) == []
    assert all(call.args[0] == "/channels/thread/messages" for call in request.call_args_list)


def test_completed_delivery_recovers_failed_slot_write(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    monkeypatch.setattr(app, "Store", lambda: store)
    monkeypatch.setattr(app, "destinations", lambda: [DEST])
    clock = Mock()
    clock.now.return_value = NOW
    monkeypatch.setattr(app, "datetime", clock)
    monkeypatch.setattr(app, "build", Mock(return_value=("title", MESSAGES, KEYS)))
    request = Mock(return_value={"id": "thread"})
    monkeypatch.setattr(discord, "_post", request)
    with patch.object(store, "set_meta", side_effect=RuntimeError("slot write failed")):
        assert not app.cycle(False)
    assert store.get_delivery("tech", "2026-10-25")["sent"] == 3
    request.reset_mock()
    assert app.cycle(False)
    request.assert_not_called()
    assert app.due(DEST, store, NOW) == []


def test_delivery_is_scoped_to_destination_and_date(tmp_path):
    store = Store(tmp_path / "state.db")
    store.save_delivery("tech", "2026-10-25", {"thread": "thread"})
    assert store.get_delivery("tech", "2026-10-25") == {"thread": "thread"}
    assert store.get_delivery("other", "2026-10-25") is None
    assert store.get_delivery("tech", "2026-10-26") is None


@pytest.mark.parametrize("community", [False, True])
def test_build_associates_keys_with_messages(tmp_path, monkeypatch, community):
    item = {"url": "https://example.org/?p=101", "source": "codex", "title": "Release"}
    news = {"url": "https://example.org/?p=102", "source": "hackernews", "title": "News",
            "points": 1000, "comments": 1, "rank": 1}
    monkeypatch.setattr(app.sources, "collect", Mock(side_effect=[([news] if community else [], []),
                                                                ([item], []), ([], [])]))
    monkeypatch.setattr(app.pages, "previews", lambda urls: {url: {"description": "", "image": None} for url in urls})
    monkeypatch.setattr(app.digest, "summarize", lambda entries: ({}, None))
    monkeypatch.setattr(app.voice, "comment", lambda unusual: ["hello"] if unusual else [])
    _, messages, keys = app.build(DEST | {"community": [], "official": ["codex"]}, Store(tmp_path / "state.db"), NOW)
    assert len(keys) == len(messages)
    assert keys == ([["example.org?p=102"], ["example.org?p=101"], []] if community
                    else [["example.org?p=101"]])
