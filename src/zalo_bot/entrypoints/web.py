import json

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response

from zalo_bot.config.settings import get_settings
from zalo_bot.lib.logging import configure_logging, get_logger
from zalo_bot.modules.zalo.events import parse_event
from zalo_bot.modules.zalo.signature import verify_signature
from zalo_bot.queue.jobs import enqueue_answer_job

log = get_logger("web")
_pool = None


async def _init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))


def get_arq_pool():
    return _pool


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="zalo-oa-rag")

    @app.on_event("startup")
    async def _startup() -> None:
        await _init_pool()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/webhook/zalo")
    async def webhook(request: Request) -> Response:
        raw = await request.body()
        mac_header = request.headers.get("X-ZEvent-Signature", "")
        timestamp = request.headers.get("X-ZEvent-Timestamp", "")
        if not verify_signature(
            raw_body=raw, header=mac_header, app_id=settings.zalo_app_id,
            timestamp=timestamp, oa_secret=settings.zalo_oa_secret,
        ):
            log.warning("invalid_signature")
            return Response(status_code=401)

        body = json.loads(raw or b"{}")
        event = parse_event(body)
        if not event.is_text_question:
            return Response(status_code=200)  # ack non-text events, nothing to do

        await enqueue_answer_job(
            get_arq_pool(),
            {
                "user_id": event.user_id, "text": event.text,
                "msg_id": event.msg_id, "received_at": int(event.timestamp or 0),
            },
        )
        log.info("enqueued", correlation_id=event.msg_id)
        return Response(status_code=200)

    return app
