import logging
import os
import time

import redis

from app.db import update_job_status

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.worker")

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
REDIS_ADDR = os.getenv("REDIS_ADDR", "localhost:6379")
REDIS_HOST, REDIS_PORT = REDIS_ADDR.rsplit(":", 1)
REDIS_PORT = int(REDIS_PORT)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def process_job(job_id: str) -> None:
    affected = update_job_status(job_id, "RUNNING")
    if affected == 0:
        logger.warning("job_id=%s was not pending; skipping", job_id)
        return

    logger.info("job_id=%s status=RUNNING", job_id)

    # Week 2 deliberately simulates the business work. CSV parsing and record
    # writes are the Week 3 implementation; the queue-to-SUCCESS path is the
    # acceptance target for this week.
    time.sleep(1)

    update_job_status(job_id, "SUCCESS")
    logger.info("job_id=%s status=SUCCESS", job_id)


def main() -> None:
    logger.info("SyncFlow Worker started")
    logger.info("Waiting for jobs from Redis queue: %s", QUEUE_NAME)

    while True:
        try:
            _, job_id = redis_client.brpop(QUEUE_NAME)
            logger.info("job_id=%s received", job_id)
            process_job(job_id)
        except Exception:
            logger.exception("Worker loop failed; retrying in 2 seconds")
            time.sleep(2)


if __name__ == "__main__":
    main()
