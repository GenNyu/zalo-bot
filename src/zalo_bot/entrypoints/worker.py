from arq.connections import RedisSettings

from zalo_bot.config.settings import get_settings
from zalo_bot.lib.logging import configure_logging
from zalo_bot.queue.jobs import process_answer_job

_settings = get_settings()
configure_logging(_settings.log_level)


class WorkerSettings:
    functions = [process_answer_job]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_tries = 3
    job_timeout = _settings.external_call_timeout_seconds * 3
    # arq retries failed jobs with exponential backoff by default.
