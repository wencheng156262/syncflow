import logging
import os
import time

import pymysql
import redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.worker")

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "syncflow")
MYSQL_USER = os.getenv("MYSQL_USER", "syncflow")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "syncflow123")
REDIS_HOST, REDIS_PORT = os.getenv("REDIS_ADDR", "localhost:6379").split(":", 1)
REDIS_PORT = int(REDIS_PORT)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_db_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def update_job_status(job_id, status):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            if status == "RUNNING":
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'RUNNING', started_at = COALESCE(started_at, UTC_TIMESTAMP(3))
                    WHERE id = %s AND status = 'PENDING'
                    """,
                    (job_id,),
                )
            elif status == "SUCCESS":
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'SUCCESS', finished_at = UTC_TIMESTAMP(3)
                    WHERE id = %s AND status = 'RUNNING'
                    """,
                    (job_id,),
                )
            else:
                cursor.execute(
                    "UPDATE sync_jobs SET status = %s WHERE id = %s",
                    (status, job_id),
                )
        connection.commit()
    finally:
        connection.close()


def main():
    logger.info("SyncFlow Worker started")
    logger.info("Waiting for jobs from Redis queue: %s", QUEUE_NAME)

    while True:
        _, job_id = redis_client.brpop(QUEUE_NAME)
        logger.info("job_id=%s received", job_id)

        update_job_status(job_id, "RUNNING")
        logger.info("job_id=%s status=RUNNING", job_id)

        # Week 1/2 baseline: reserve the asynchronous execution slot.
        # Real CSV parsing and record writes are introduced in a later week.
        time.sleep(1)

        update_job_status(job_id, "SUCCESS")
        logger.info("job_id=%s status=SUCCESS", job_id)


if __name__ == "__main__":
    main()
