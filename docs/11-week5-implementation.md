# Week 5：重试、幂等与任务控制

Week 5 在 Week 4 的异步任务、取消和超时基础上，补齐可靠性闭环：每次实际执行都有可追踪的 attempt；临时故障自动重试；重复提交不会重复创建任务；失败任务可以手动重新执行。

## 1. 已实现内容

### 自动重试

- Worker 从 Redis 消息读取一-based `attempt_no`，旧格式的裸 job ID 兼容为第 1 次尝试。
- 默认最多执行 3 次，配置项为 `MAX_JOB_ATTEMPTS`。
- 默认退避为 5 秒、30 秒、120 秒，配置项为 `RETRY_BACKOFF_SECONDS`。
- 临时数据库/Redis/批量写入/超时/Worker 重启错误进入 `RETRYING`，等待后回到 `PENDING` 并重新入队。
- CSV 格式、字段校验、文件不可读、重复业务 ID、用户取消等确定性错误不会自动重试。
- 超过最大次数后记录最后错误并进入 `FAILED`。

分类逻辑集中在 `backend/app/retry_policy.py`，Worker 只负责执行状态转换和重新入队。

### 执行尝试记录

`backend/migrations/003_week5_reliability.sql` 创建 `job_attempts`。Worker 开始时写 `RUNNING`，结束时写 `SUCCESS`、`PARTIAL_SUCCESS`、`FAILED`、`RETRYING` 或 `CANCELED`，并保存错误码、错误信息和时间。API 通过 `GET /api/v1/jobs/{job_id}/attempts` 返回历史。

### 24 小时幂等

创建任务时先把文件保存并计算 SHA-256，再在 `job_idempotency_keys` 中检查 `Idempotency-Key`：

1. 24 小时内键和 SHA 相同：返回原任务，不再次入队。
2. 24 小时内键相同但 SHA 不同：返回 409 `IDEMPOTENCY_KEY_CONFLICT`。
3. 键已过期：清理旧映射，允许创建新任务。

前端在一次创建页面生命周期内复用同一个 key，网络重试不会产生重复任务；用户换文件时生成新 key。

### 手动重试

`POST /api/v1/jobs/{job_id}/retry` 只接受 `FAILED` 任务。数据库事务会锁定任务、清理上一轮的成功记录和错误记录、重置统计字段，然后复用原文件和 job ID 重新入队。手动重试使用新的 attempt 编号，不受上一轮自动重试次数影响。

### 前端控制

- 失败任务显示“重新执行”，并在操作前确认。
- 任务详情显示 `retry_count / max_attempts` 和最近错误。
- 取消任务前弹出确认框。
- 幂等冲突和不可重试错误显示面向用户的提示。

## 2. 关键文件职责

| 文件 | 作用 |
| --- | --- |
| `backend/app/retry_policy.py` | 错误分类、退避计算、环境变量解析 |
| `backend/app/db.py` | 幂等键事务、attempt 记录、手动重试重置、任务查询 |
| `backend/app/main.py` | 创建任务、重试接口、attempt 查询接口和统一错误响应 |
| `backend/worker/worker.py` | 消费队列、执行 CSV、自动重试、取消和 attempt 状态更新 |
| `backend/migrations/003_week5_reliability.sql` | 新增 attempt 和幂等键窗口表，移除旧的永久唯一约束 |
| `frontend/src/api.ts` | 幂等 key、重试 API 和任务数据类型 |
| `frontend/src/App.tsx` | 创建重试、取消确认和失败任务操作界面 |

## 3. 本地验证

如果 MySQL 数据卷是在 Week 5 之前创建的，初始化目录不会自动重新执行新脚本，需要手动执行一次：

```bash
docker compose exec -T mysql mysql -uroot -proot123 syncflow < backend/migrations/003_week5_reliability.sql
docker compose up --build -d
curl http://localhost:8000/readyz
```

代码检查：

```bash
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm run lint
npm run build
```

Week 5 测试覆盖退避规则、错误分类、手动重试接口、非法重试状态、幂等冲突和 OpenAPI 路由；实际端到端验证还应观察任务详情中的状态和 `/attempts` 结果。
