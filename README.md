# SyncFlow

SyncFlow 是一个本地可运行的 CSV 数据同步与任务管理服务。用户提交 CSV 后，API 创建任务并立即返回，Redis 负责排队，Worker 在后台处理，MySQL 保存任务和处理结果。

## 技术栈

- Web：React、TypeScript、Vite
- API：Python、FastAPI、PyMySQL
- Worker：Python、Redis 客户端
- 基础设施：MySQL 8、Redis 7、Docker Compose

## 本地启动

```bash
cp .env.example .env
docker compose up --build -d
```

启动后：

- Web：http://localhost:5173
- API：http://localhost:8000
- OpenAPI：http://localhost:8000/docs
- API 健康检查：http://localhost:8000/healthz
- 依赖就绪检查：http://localhost:8000/readyz

数据库迁移脚本位于 `backend/migrations/`，MySQL 首次初始化时会自动执行。查看日志：

```bash
docker compose logs -f api worker
```

停止服务但保留数据库：

```bash
docker compose down
```

停止服务并删除本地数据库卷：

```bash
docker compose down -v
```

## API 快速验证

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl 'http://localhost:8000/api/v1/jobs?page=1&page_size=20'
```

创建任务需要 multipart CSV 文件：

```bash
curl -F 'file=@./sample.csv' -F 'name=示例导入' http://localhost:8000/api/v1/jobs
```

## 目录说明

- `backend/app/`：FastAPI 路由、配置、数据库和队列访问
- `backend/worker/`：Redis 消费和任务状态更新
- `backend/migrations/`：可重复执行的 MySQL 初始化脚本
- `frontend/src/`：React Web 页面
- `docs/`：Week 1 规范设计包
- `data/uploads/`：本地受控上传目录，不提交到仓库

## 开发检查

```bash
cd frontend
npm run lint
npm run build
```

后端依赖安装：

```bash
cd backend
python -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
```

后端测试依赖和测试：

```bash
.venv/bin/python3 -m pip install -r requirements-dev.txt
.venv/bin/python3 -m pytest -q
```
