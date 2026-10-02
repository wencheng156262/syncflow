# Week 4 实现记录

Week 4 聚焦 Worker 并发控制、任务状态一致性、取消和服务重启恢复。

## 实现范围

- 状态机增加 `RETRYING`、`CANCELING`，并限制所有状态转换必须带当前状态条件。
- API 创建任务先持久化，再向 Redis List 投递 JSON 消息 `{job_id, attempt_no}`；投递失败会把任务标记为 `FAILED`。
- Worker 使用 `BRPOP` 阻塞消费，使用原子 `PENDING -> RUNNING` 更新避免同一任务被多个 Worker 重复执行。
- `WORKER_CONCURRENCY` 控制线程并发数，默认 2；`JOB_TIMEOUT_SECONDS` 控制单任务超时；失败任务最多按 `MAX_JOB_RETRIES` 次重新投递。
- Worker 收到 SIGTERM/SIGINT 后停止消费新任务，等待当前任务在批次边界结束；超时任务进入 `RETRYING` 并重新入队。
- Worker 启动时扫描超时的 `RUNNING` 任务并恢复，避免服务重启留下无法解释的孤儿任务。
- 任务详情页继续轮询 `PENDING`、`RUNNING`、`RETRYING`、`CANCELING`，并支持取消任务；进入终态或离开页面后停止轮询。

## 配置项

- `WORKER_CONCURRENCY`：Worker 并发任务数，默认 2。
- `JOB_TIMEOUT_SECONDS`：单个任务执行超时时间，默认 300 秒。
- `WORKER_SHUTDOWN_TIMEOUT_SECONDS`：优雅停止等待时间，默认 30 秒。
- `MAX_JOB_RETRIES`：任务最大重试次数，默认 2 次。

## 验收方式

```bash
docker compose up --build -d
curl http://localhost:8000/readyz
curl -X POST http://localhost:8000/api/v1/jobs/{job_id}/cancel
docker compose logs -f worker
```

重点观察：同一任务不会重复执行；失败任务会经过 `RETRYING -> PENDING`；取消任务会经过 `CANCELING -> CANCELED`；Worker 重启后不会留下长期 `RUNNING` 任务。
