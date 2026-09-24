# SyncFlow 系统边界与核心流程

## 系统边界

```mermaid
flowchart LR
    User[数据操作人员] --> Web[React Web]
    Web -->|HTTP REST| API[FastAPI API]
    API -->|读写任务| MySQL[(MySQL 8)]
    API -->|LPUSH 任务 ID| Redis[(Redis 7)]
    Redis -->|BRPOP 任务 ID| Worker[Worker]
    Worker -->|读写文件 / 更新结果| MySQL
    Worker -->|读取受控文件| Storage[(本地上传目录)]
    Maintainer[系统维护人员] -.查看日志/维护环境.-> API
    Maintainer -.查看日志/维护环境.-> Worker
```

## 核心流程

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as React Web
    participant API as FastAPI API
    participant DB as MySQL
    participant Queue as Redis
    participant Worker as Worker

    User->>Web: 选择 CSV 并提交
    Web->>API: POST /api/v1/jobs multipart/form-data
    API->>API: 校验文件并保存到受控目录
    API->>DB: INSERT sync_jobs(PENDING)
    API->>Queue: LPUSH job_id
    API-->>Web: 201 返回任务信息
    Worker->>Queue: BRPOP job_id
    Worker->>DB: PENDING -> RUNNING
    Worker->>Worker: 读取、校验和处理 CSV
    Worker->>DB: 写入成功/错误记录和统计
    Worker->>DB: 更新终态
    Web->>API: GET 任务列表或详情
    API->>DB: 查询任务
    API-->>Web: 返回状态和统计
```

## 职责边界

- Web 负责展示和交互，不直接访问 MySQL/Redis。
- API 负责请求校验、文件接收、任务入库和入队，不执行耗时 CSV 处理。
- Worker 负责异步处理和任务状态更新，不接受浏览器请求。
- MySQL 负责持久化任务、成功记录和错误记录。
- Redis 只负责短期任务队列，不作为任务最终事实来源。
