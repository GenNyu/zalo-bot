from zalo_bot.entrypoints.worker import WorkerSettings
from zalo_bot.queue.jobs import process_answer_job


def test_worker_registers_job_and_retries():
    assert process_answer_job in WorkerSettings.functions
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.redis_settings is not None
