import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from zalo_bot.config.settings import get_settings
from zalo_bot.entrypoints.web import create_app


def _mac(app_id, body, ts, secret):
    return hashlib.sha256(app_id.encode() + body + ts.encode() + secret.encode()).hexdigest()


@pytest.mark.asyncio
async def test_health_ok():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_zalo_verifier_route_serves_configured_html(monkeypatch):
    monkeypatch.setenv(
        "ZALO_VERIFIER_PATH",
        "/zalo_verifierlyVaEB7OPpSmxRmKwFWtJ33ghHISbNnDCp0.html",
    )
    monkeypatch.setenv("ZALO_VERIFIER_CONTENT", "<html>verify</html>")
    get_settings.cache_clear()

    try:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/zalo_verifierlyVaEB7OPpSmxRmKwFWtJ33ghHISbNnDCp0.html")
    finally:
        get_settings.cache_clear()

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == "<html>verify</html>"


@pytest.mark.asyncio
async def test_zalo_verifier_route_is_absent_when_unconfigured(monkeypatch):
    monkeypatch.delenv("ZALO_VERIFIER_PATH", raising=False)
    monkeypatch.delenv("ZALO_VERIFIER_CONTENT", raising=False)
    get_settings.cache_clear()

    try:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/zalo_verifierlyVaEB7OPpSmxRmKwFWtJ33ghHISbNnDCp0.html")
    finally:
        get_settings.cache_clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=b'{"event_name":"user_send_text"}',
            headers={"X-ZEvent-Signature": "mac=bad", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_enqueues_text_event(monkeypatch):
    enqueued = {}

    async def _fake_enqueue(arq, job):
        enqueued.update(job)

    class _FakePool:
        pass

    monkeypatch.setattr("zalo_bot.entrypoints.web.enqueue_answer_job", _fake_enqueue)
    monkeypatch.setattr("zalo_bot.entrypoints.web.get_arq_pool", lambda: _FakePool())

    body = b'{"event_name":"user_send_text","sender":{"id":"u1"},"message":{"msg_id":"m1","text":"hi"},"timestamp":"1"}'
    mac = _mac("appid", body, "1", "secret")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=body,
            headers={"X-ZEvent-Signature": f"mac={mac}", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 200
    assert enqueued["user_id"] == "u1"
    assert enqueued["msg_id"] == "m1"


@pytest.mark.asyncio
async def test_webhook_enqueues_message_text_received_event(monkeypatch):
    enqueued = {}

    async def _fake_enqueue(arq, job):
        enqueued.update(job)

    class _FakePool:
        pass

    monkeypatch.setattr("zalo_bot.entrypoints.web.enqueue_answer_job", _fake_enqueue)
    monkeypatch.setattr("zalo_bot.entrypoints.web.get_arq_pool", lambda: _FakePool())

    body = (
        b'{"event_name":"message.text.received",'
        b'"message":{"date":1780973847282,'
        b'"chat":{"chat_type":"PRIVATE","id":"5d585b5e9b14724a2b05"},'
        b'"message_id":"0c95d167c1061b5f4210",'
        b'"from":{"id":"5d585b5e9b14724a2b05","is_bot":false,"display_name":"Nguyen"},'
        b'"text":"Hi"}}'
    )
    mac = _mac("appid", body, "1", "secret")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=body,
            headers={"X-ZEvent-Signature": f"mac={mac}", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 200
    assert enqueued == {
        "user_id": "5d585b5e9b14724a2b05",
        "text": "Hi",
        "msg_id": "0c95d167c1061b5f4210",
        "received_at": 1780973847282,
    }


@pytest.mark.asyncio
async def test_webhook_acks_message_sticker_received_without_enqueue(monkeypatch):
    calls = []

    async def _fake_enqueue(arq, job):
        calls.append(job)

    monkeypatch.setattr("zalo_bot.entrypoints.web.enqueue_answer_job", _fake_enqueue)

    body = (
        b'{"event_name":"message.sticker.received",'
        b'"message":{"date":1780973198321,'
        b'"chat":{"chat_type":"PRIVATE","id":"5d585b5e9b14724a2b05"},'
        b'"sticker":"5cb6159929dcc08299cd",'
        b'"message_id":"6af977705e12844bdd04",'
        b'"message_type":"CHAT_STICKER",'
        b'"from":{"id":"5d585b5e9b14724a2b05","is_bot":false,"display_name":"Nguyen"},'
        b'"url":"https://zalo-api.zadn.vn/api/emoticon/oasticker?eid=1&size=130"}}'
    )
    mac = _mac("appid", body, "1", "secret")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=body,
            headers={"X-ZEvent-Signature": f"mac={mac}", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 200
    assert calls == []
