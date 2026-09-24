# SyncFlow 数据库设计

数据库：MySQL 8.x。时间统一存 UTC，金额使用 `DECIMAL`，表之间通过应用层维护关联，不依赖数据库外键。

## `sync_jobs` 任务表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `varchar(36)` | UUID 主键 |
| `name` | `varchar(128)` | 任务名称 |
| `status` | `varchar(32)` | 当前任务状态 |
| `source_file_name` | `varchar(255)` | 原始文件名，仅用于展示 |
| `stored_file_path` | `varchar(512)` | 受控存储路径，不通过 API 返回 |
| `file_sha256` | `char(64)` | 文件摘要 |
| `idempotency_key` | `varchar(128)` | 幂等键，可空且唯一 |
| `total_records` | `int unsigned` | 总记录数 |
| `success_records` | `int unsigned` | 成功记录数 |
| `failed_records` | `int unsigned` | 失败记录数 |
| `retry_count` | `tinyint unsigned` | 已执行重试次数 |
| `last_error_code` | `varchar(64)` | 最近错误码 |
| `last_error_message` | `varchar(512)` | 最近错误摘要 |
| `created_at` | `datetime(3)` | 创建时间，UTC |
| `started_at` | `datetime(3)` | 首次执行时间，可空 |
| `finished_at` | `datetime(3)` | 完成时间，可空 |
| `updated_at` | `datetime(3)` | 更新时间 |

索引：主键 `id`，唯一索引 `idempotency_key`，列表查询索引 `(status, created_at)` 和 `(created_at)`。

## `sync_records` 成功记录表

字段包括自增主键 `id`、`job_id`、`external_id`、`name`、`amount DECIMAL(12,2)`、`record_date`、`created_at`、`updated_at`。唯一约束为 `(job_id, external_id)`，防止同一任务重复写入同一业务记录；增加 `(job_id)` 索引支持详情查询。

## `sync_errors` 错误记录表

字段包括自增主键 `id`、`job_id`、`row_number`、`field_name`、`error_code`、`error_message`、`raw_row JSON`、`created_at`。索引为 `(job_id, row_number)`，支持按任务分页查看错误明细。

## 迁移规则

- 所有迁移使用 `CREATE TABLE IF NOT EXISTS`，允许重复执行。
- 当前可执行脚本为 `backend/migrations/001_create_jobs.sql` 和 `002_create_sync_tables.sql`。
- 新业务代码使用 `sync_jobs`、`sync_records`、`sync_errors`；旧 `jobs` 表保留用于兼容已有本地数据，后续再单独清理。
