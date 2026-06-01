import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

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
