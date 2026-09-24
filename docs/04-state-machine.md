# SyncFlow 任务状态机

## 状态定义

| 状态 | 含义 | 是否终态 |
| --- | --- | --- |
| `PENDING` | 任务已创建，等待 Worker 消费 | 否 |
| `RUNNING` | Worker 已开始处理 | 否 |
| `SUCCESS` | 所有记录处理成功 | 是 |
| `PARTIAL_SUCCESS` | 至少有一条成功记录，同时存在失败记录 | 是 |
| `FAILED` | 文件级或任务级处理失败 | 是 |
| `CANCELED` | 用户或系统取消任务 | 是 |

## 合法转换

```text
PENDING  -> RUNNING
PENDING  -> FAILED       (入队失败、文件不可读)
PENDING  -> CANCELED
RUNNING  -> SUCCESS
RUNNING  -> PARTIAL_SUCCESS
RUNNING  -> FAILED
RUNNING  -> CANCELED     (仅在取消策略允许时)
```

终态默认不可再次转换。重试时由应用创建一次新的执行尝试，增加 `retry_count`，再按策略回到 `PENDING`；不得直接覆盖已完成的历史结果。

## 状态与统计约束

- `PENDING`：`started_at`、`finished_at` 为空。
- `RUNNING`：首次进入时记录 `started_at`。
- 终态：必须记录 `finished_at`。
- `total_records >= success_records + failed_records`。
- `SUCCESS` 要求失败数为 0；`PARTIAL_SUCCESS` 要求成功数和失败数都大于 0。
- Worker 更新状态必须带当前状态条件，避免重复消费覆盖新状态。
