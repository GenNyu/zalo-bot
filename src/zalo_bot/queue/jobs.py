from typing import Any, TypedDict

from zalo_bot.deps import build_rag, build_zalo_client
from zalo_bot.lib.logging import get_logger

log = get_logger("queue")
_BUSY_MESSAGE = "Hệ thống đang bận, bạn vui lòng thử lại sau ít phút nhé."


class AnswerJob(TypedDict):
    user_id: str
    text: str
    msg_id: str
    received_at: int


async def enqueue_answer_job(arq: Any, job: AnswerJob) -> None:
    await arq.enqueue_job("process_answer_job", job, _job_id=job["msg_id"])


async def process_answer_job(ctx: dict, job: AnswerJob) -> None:
    correlation_id = job["msg_id"]
    try:
        rag = build_rag()
        answer = await rag.answer_question(job["text"])
        await build_zalo_client().send_text_message(job["user_id"], answer)
        log.info("answered", correlation_id=correlation_id)
    except Exception:
        log.exception("process_failed", correlation_id=correlation_id)
        # On the final attempt, tell the user instead of going silent.
        if ctx.get("job_try", 1) >= ctx.get("max_tries", 1):
            try:
                await build_zalo_client().send_text_message(job["user_id"], _BUSY_MESSAGE)
            except Exception:
                log.exception("fallback_send_failed", correlation_id=correlation_id)
        raise
