# Week 2 实现记录

## 本周范围

Week 2 聚焦任务管理基础链路：

```text
创建任务 -> 写入 MySQL -> 投递 Redis -> Worker 消费
         -> RUNNING -> SUCCESS -> 查询任务结果
```

## 后端

- `backend/app/db.py`：集中管理 MySQL 连接、事务、任务查询、任务写入和状态更新。
- `backend/app/main.py`：提供统一响应格式、参数校验、创建任务、任务详情、任务列表和分页筛选。
- `backend/worker/worker.py`：从 Redis 阻塞取任务，将任务从 `PENDING` 更新为 `RUNNING`，再模拟处理后更新为 `SUCCESS`。
- `backend/migrations/002_create_sync_tables.sql`：初始化 `sync_jobs`、`sync_records`、`sync_errors`。

## 前端

- `frontend/src/api.ts`：统一封装 API 请求、错误处理和任务类型。
- `frontend/src/App.tsx`：实现任务列表、状态筛选、分页、创建任务和任务详情页。
- 每个页面都有加载、空数据、请求失败状态；任务状态使用文字和颜色同时展示。

## 验收方式

```bash
docker compose up --build -d
curl http://localhost:8000/readyz
curl 'http://localhost:8000/api/v1/jobs?page=1&page_size=20'

cd backend
./.venv/bin/python3 -m pytest -q

cd ../frontend
npm run lint
npm run build
```

Week 2 只模拟 Worker 的处理过程；CSV 逐行解析、成功记录写入和错误记录写入留到 Week 3。
