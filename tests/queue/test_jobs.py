import pytest

from zalo_bot.queue.jobs import enqueue_answer_job, process_answer_job


class _Arq:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, name, payload, _job_id=None):
        self.calls.append((name, payload, _job_id))


@pytest.mark.asyncio
async def test_enqueue_uses_msg_id_as_job_id():
    arq = _Arq()
    job = {"user_id": "u1", "text": "hi", "msg_id": "m1", "received_at": 1}
    await enqueue_answer_job(arq, job)
    name, payload, job_id = arq.calls[0]
    assert name == "process_answer_job"
    assert job_id == "m1"
    assert payload == job


@pytest.mark.asyncio
async def test_process_answers_and_sends(monkeypatch):
    sent = {}

    class _Rag:
        async def answer_question(self, q):
            return f"ans:{q}"

    class _Zalo:
        async def send_text_message(self, user_id, text):
            sent["user_id"] = user_id
            sent["text"] = text

    monkeypatch.setattr("zalo_bot.queue.jobs.build_rag", lambda: _Rag())
    monkeypatch.setattr("zalo_bot.queue.jobs.build_zalo_client", lambda: _Zalo())

    job = {"user_id": "u1", "text": "câu hỏi", "msg_id": "m1", "received_at": 1}
    await process_answer_job({}, job)
    assert sent == {"user_id": "u1", "text": "ans:câu hỏi"}


@pytest.mark.asyncio
async def test_process_sends_fallback_on_error(monkeypatch):
    sent = {}

    class _Rag:
        async def answer_question(self, q):
            raise RuntimeError("boom")

    class _Zalo:
        async def send_text_message(self, user_id, text):
            sent["text"] = text

    monkeypatch.setattr("zalo_bot.queue.jobs.build_rag", lambda: _Rag())
    monkeypatch.setattr("zalo_bot.queue.jobs.build_zalo_client", lambda: _Zalo())

    job = {"user_id": "u1", "text": "q", "msg_id": "m1", "received_at": 1}
    with pytest.raises(RuntimeError):
        await process_answer_job({"job_try": 3, "max_tries": 3}, job)
    assert "đang bận" in sent["text"]
