# SyncFlow API 设计

Base URL：`/api/v1`。成功响应统一为 `{ "data": ..., "meta": ... }`，失败响应统一为 `{ "error": { "code": ..., "message": ..., "details": [...] } }`。

## 接口总览

| 方法 | 路径 | 用途 | 成功状态 |
| --- | --- | --- | --- |
| GET | `/healthz` | 进程存活检查 | 200 |
| GET | `/readyz` | MySQL、Redis 就绪检查 | 200 |
| POST | `/api/v1/jobs` | 创建同步任务 | 201 |
| GET | `/api/v1/jobs` | 分页查询任务 | 200 |
| GET | `/api/v1/jobs/{job_id}` | 查询任务详情 | 200 |
| POST | `/api/v1/jobs/{job_id}/cancel` | 请求取消任务 | 202 |

## 创建任务

`POST /api/v1/jobs`，`Content-Type: multipart/form-data`。

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `file` | 是 | `.csv` 文件，默认最大 10 MB |
| `name` | 否 | 最长 128 字符；不传时使用文件名 |
| `Idempotency-Key` | 否 | 请求头，最长 128 字符；相同键返回同一任务 |

成功示例：

```json
{
  "data": {
    "id": "01JABC...",
    "name": "商品导入",
    "status": "PENDING",
    "source_file_name": "products.csv",
    "created_at": "2026-01-01T10:00:00Z"
  },
  "meta": {}
}
```

创建接口只负责接收、保存和入队，不等待 CSV 全部处理完成。

## 取消任务

`POST /api/v1/jobs/{job_id}/cancel` 不会强制杀死 Worker：`PENDING`/`RETRYING` 直接进入 `CANCELED`，`RUNNING` 先进入 `CANCELING`，由 Worker 在批次边界安全停止。终态任务取消返回 409 `INVALID_STATE_TRANSITION`。

## 查询详情

`GET /api/v1/jobs/{job_id}` 返回任务状态、源文件名、总数、成功数、失败数、重试次数、最近错误以及创建/开始/完成时间。不得返回 `stored_file_path`、SQL 或异常堆栈。

## 查询列表

`GET /api/v1/jobs?page=1&page_size=20&status=SUCCESS`。

- `page` 最小值为 1，默认 1。
- `page_size` 默认 20，范围 1-100。
- `status` 可选，只允许状态机中的状态。
- 按 `created_at DESC, id DESC` 排序，确保排序稳定。
- `meta` 返回 `page`、`page_size`、`total`。

## 错误码

| HTTP | 错误码 | 场景 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | 参数或分页参数不合法 |
| 400 | `INVALID_FILE_EXTENSION` | 文件不是 CSV |
| 400 | `FILE_TOO_LARGE` | 文件超过大小限制 |
| 404 | `JOB_NOT_FOUND` | 任务不存在 |
| 503 | `DEPENDENCY_UNAVAILABLE` | MySQL 或 Redis 未就绪 |
| 503 | `QUEUE_UNAVAILABLE` | 任务入队失败 |
| 500 | `INTERNAL_ERROR` | 未预期的内部错误 |

错误消息面向用户，`details` 只放可行动的字段或参数信息，不放敏感内部细节。
