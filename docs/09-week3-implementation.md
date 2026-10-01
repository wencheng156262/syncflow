# Week 3 实现记录

Week 3 将 Week 2 的异步任务骨架扩展为可用的 CSV 同步闭环：API 创建任务后立即返回，Worker 从 Redis 获取任务，读取并校验 CSV，将合法数据写入 `sync_records`，将错误写入 `sync_errors`，最后更新任务统计和最终状态。

## 已实现

- 支持 UTF-8/UTF-8 BOM CSV，要求固定表头 `external_id,name,amount,record_date`。
- 忽略空行，限制单任务最大数据行数 `MAX_RECORDS_PER_JOB`，默认 10,000 行。
- 校验必填字段、外部 ID 格式和任务内重复、名称长度、金额格式和日期格式。
- 合法记录批量写入 `sync_records`，错误记录批量写入 `sync_errors`。
- 文件级错误直接进入 `FAILED`；行级错误继续处理其他行。
- 根据成功/失败记录数计算 `SUCCESS`、`PARTIAL_SUCCESS` 或 `FAILED`。
- 新增错误明细接口：`GET /api/v1/jobs/{job_id}/errors?page=1&page_size=20`。
- 任务详情页对非终态任务每 3 秒轮询，失败记录大于 0 时可以进入错误明细页。
- 增加 CSV 解析边界测试、错误接口测试和前端构建检查。

## 本地验证

```bash
docker compose up --build -d
curl http://localhost:8000/readyz
curl -F 'file=@docs/examples/valid.csv' \\
  -F 'name=Week3 正常样例' \\
  http://localhost:8000/api/v1/jobs
curl -F 'file=@docs/examples/invalid.csv' \\
  -F 'name=Week3 异常样例' \\
  http://localhost:8000/api/v1/jobs
```

任务详情状态应最终变为 `SUCCESS` 或 `PARTIAL_SUCCESS`，异常样例可以通过错误明细接口查询行号、字段、错误码和原始行。

## 配置项

- `MAX_UPLOAD_FILE_SIZE_MB`：上传文件大小上限，默认 10 MB。
- `MAX_RECORDS_PER_JOB`：单任务有效数据行数上限，默认 10,000 行。

## 后续发布工作

完成 Docker 端到端演示后，补充测试报告、Release Notes，并在 GitHub 上提交 Week3 PR 和 Review 记录。
