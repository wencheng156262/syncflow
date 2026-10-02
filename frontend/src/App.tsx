/* oxlint-disable react/set-state-in-effect -- API loading effects update view state by design. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
} from 'react-router-dom'
import { ApiRequestError, cancelJob, createJob, getJob, getJobErrors, healthCheck, listJobs } from './api'
import type { Job, JobError, JobStatus } from './api'
import './App.css'

const PAGE_SIZE = 10
const MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024
const TERMINAL_STATUSES = new Set<JobStatus>(['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELED'])

const statusLabels: Record<JobStatus, string> = {
  PENDING: '等待中',
  RUNNING: '处理中',
  RETRYING: '重试中',
  SUCCESS: '已完成',
  PARTIAL_SUCCESS: '部分成功',
  FAILED: '失败',
  CANCELING: '取消中',
  CANCELED: '已取消',
}

function formatDate(value: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function StatusPill({ status }: { status: JobStatus }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{statusLabels[status]}</span>
}

function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner" role="alert">{message}</div>
}

function getErrorMessage(error: unknown) {
  if (error instanceof ApiRequestError) return error.message
  return '请求失败，请稍后重试。'
}

function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">S</span>
          <span>SyncFlow</span>
        </Link>
        <nav className="nav-links" aria-label="主导航">
          <NavLink to="/" end>任务</NavLink>
          <NavLink to="/jobs/new">创建任务</NavLink>
        </nav>
        <span className="environment-label">LOCAL</span>
      </header>
      <main className="page-content">
        <Routes>
          <Route path="/" element={<JobsPage />} />
          <Route path="/jobs/new" element={<CreateJobPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/errors" element={<JobErrorsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  )
}

function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [status, setStatus] = useState<JobStatus | ''>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [apiOnline, setApiOnline] = useState(false)

  const loadJobs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await listJobs(page, PAGE_SIZE, status)
      setJobs(response.data)
      setTotal(Number(response.meta.total ?? 0))
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [page, status])

  useEffect(() => {
    void healthCheck().then(() => setApiOnline(true)).catch(() => setApiOnline(false))
  }, [])

  useEffect(() => {
    // The initial API load is intentionally started by this effect.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadJobs()
  }, [loadJobs])

  const processingCount = useMemo(
    () => jobs.filter((job) => !TERMINAL_STATUSES.has(job.status)).length,
    [jobs],
  )
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  function changeStatus(nextStatus: JobStatus | '') {
    setStatus(nextStatus)
    setPage(1)
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">DATA OPERATIONS</p>
          <h1>任务中心</h1>
          <p className="page-description">集中查看 CSV 同步任务的状态、进度和结果。</p>
        </div>
        <Link className="primary-button" to="/jobs/new">创建同步任务</Link>
      </div>

      <div className="overview-grid">
        <div className="overview-card"><span>全部任务</span><strong>{total}</strong><small>当前筛选结果</small></div>
        <div className="overview-card"><span>本页处理中</span><strong>{processingCount}</strong><small>等待中或执行中</small></div>
        <div className="overview-card"><span>API 状态</span><strong>{apiOnline ? '正常' : '离线'}</strong><small>健康检查 /healthz</small></div>
      </div>

      <div className="toolbar">
        <label htmlFor="status-filter">状态筛选</label>
        <select id="status-filter" value={status} onChange={(event) => changeStatus(event.target.value as JobStatus | '')}>
          <option value="">全部状态</option>
          {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button className="secondary-button" type="button" onClick={() => void loadJobs()} disabled={loading}>刷新</button>
      </div>

      {error && <ErrorBanner message={error} />}
      {loading ? <div className="loading-state">正在加载任务...</div> : jobs.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">↗</div>
          <h2>还没有同步任务</h2>
          <p>上传一份 CSV 文件，创建你的第一个异步同步任务。</p>
          <Link className="secondary-button" to="/jobs/new">开始创建</Link>
        </div>
      ) : (
        <>
          <div className="table-card">
            <div className="job-table job-table-head"><span>任务</span><span>状态</span><span>记录数</span><span>创建时间</span><span /></div>
            {jobs.map((job) => (
              <Link className="job-table job-table-row" key={job.id} to={`/jobs/${job.id}`}>
                <span><strong>{job.name}</strong><small>{job.source_file_name}</small></span>
                <span><StatusPill status={job.status} /></span>
                <span>{job.total_records || '-'}</span>
                <span>{formatDate(job.created_at)}</span>
                <span className="row-arrow">→</span>
              </Link>
            ))}
          </div>
          <div className="pagination">
            <span>第 {page} / {totalPages} 页，共 {total} 条</span>
            <div>
              <button className="secondary-button" type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => current - 1)}>上一页</button>
              <button className="secondary-button" type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => current + 1)}>下一页</button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function CreateJobPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) {
      setError('请选择 CSV 文件。')
      return
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('只支持 CSV 文件。')
      return
    }
    if (file.size > MAX_UPLOAD_FILE_SIZE) {
      setError('文件不能超过 10 MB。')
      return
    }
    setLoading(true)
    setError('')
    try {
      const response = await createJob(file, name)
      navigate(`/jobs/${response.data.id}`)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="narrow-page">
      <div className="page-heading compact-heading">
        <div><p className="eyebrow">NEW JOB</p><h1>创建同步任务</h1><p className="page-description">选择 CSV 文件并提交后台处理。</p></div>
      </div>
      <form className="form-card" onSubmit={submit}>
        <label htmlFor="job-name">任务名称（可选）</label>
        <input id="job-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={128} placeholder="例如：商品导入 2026-01-01" />
        <label htmlFor="job-file">CSV 文件</label>
        <input id="job-file" type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        {file && <p className="file-summary">已选择：{file.name}（{(file.size / 1024).toFixed(1)} KB）</p>}
        <p className="form-hint">文件提交后进入 Redis 队列，由 Worker 异步处理。</p>
        {error && <ErrorBanner message={error} />}
        <button className="primary-button" type="submit" disabled={loading}>{loading ? '提交中...' : '提交任务'}</button>
      </form>
    </section>
  )
}

function JobDetailPage() {
  const { jobId = '' } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [canceling, setCanceling] = useState(false)

  const loadJob = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError('')
    try {
      const response = await getJob(jobId)
      setJob(response.data)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [jobId])

  async function requestCancel() {
    setCanceling(true)
    setError('')
    try {
      const response = await cancelJob(jobId)
      setJob(response.data)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setCanceling(false)
    }
  }

  useEffect(() => {
    // The detail request is intentionally started when the route parameter changes.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadJob()
  }, [loadJob])

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return undefined
    const timer = window.setInterval(() => void loadJob(false), 3000)
    return () => window.clearInterval(timer)
  }, [job, loadJob])

  return (
    <section className="narrow-page">
      <Link className="back-link" to="/">← 返回任务列表</Link>
      {loading ? <div className="loading-state">正在加载任务详情...</div> : error ? (
        <><ErrorBanner message={error} /><Link className="secondary-button" to="/">返回任务列表</Link></>
      ) : job ? (
        <>
          <div className="page-heading compact-heading"><div><p className="eyebrow">JOB DETAIL</p><h1>{job.name}</h1><p className="page-description">{job.source_file_name}</p></div><StatusPill status={job.status} /></div>
          <div className="detail-card">
            <div className="detail-grid">
              <DetailItem label="任务 ID" value={job.id} />
              <DetailItem label="创建时间" value={formatDate(job.created_at)} />
              <DetailItem label="开始时间" value={formatDate(job.started_at)} />
              <DetailItem label="完成时间" value={formatDate(job.finished_at)} />
              <DetailItem label="总记录数" value={String(job.total_records)} />
              <DetailItem label="成功记录数" value={String(job.success_records)} />
              <DetailItem label="失败记录数" value={String(job.failed_records)} />
              <DetailItem label="重试次数" value={String(job.retry_count)} />
            </div>
            {job.last_error_message && <div className="last-error"><strong>{job.last_error_code ?? '处理错误'}</strong><span>{job.last_error_message}</span></div>}
            {(job.failed_records > 0 || job.last_error_code !== null) && <Link className="secondary-button error-link" to={`/jobs/${job.id}/errors`}>查看错误明细</Link>}
            {!TERMINAL_STATUSES.has(job.status) && <button className="secondary-button cancel-button" type="button" onClick={() => void requestCancel()} disabled={canceling || job.status === 'CANCELING'}>{canceling || job.status === 'CANCELING' ? '取消中...' : '取消任务'}</button>}
          </div>
          <button className="secondary-button refresh-detail" type="button" onClick={() => void loadJob()}>刷新详情</button>
        </>
      ) : null}
    </section>
  )
}

function JobErrorsPage() {
  const { jobId = '' } = useParams()
  const [errors, setErrors] = useState<JobError[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadErrors = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await getJobErrors(jobId, page, PAGE_SIZE)
      setErrors(response.data)
      setTotal(Number(response.meta.total ?? 0))
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [jobId, page])

  useEffect(() => {
    // The error list request is intentionally tied to the route and page.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadErrors()
  }, [loadErrors])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section className="narrow-page error-page">
      <Link className="back-link" to={`/jobs/${jobId}`}>← 返回任务详情</Link>
      <div className="page-heading compact-heading">
        <div><p className="eyebrow">ERROR DETAILS</p><h1>错误明细</h1><p className="page-description">按行查看 CSV 校验失败原因。</p></div>
      </div>
      {error && <ErrorBanner message={error} />}
      {loading ? <div className="loading-state">正在加载错误明细...</div> : errors.length === 0 ? (
        <div className="empty-state compact-empty"><h2>暂无错误记录</h2><p>这个任务没有可展示的错误明细。</p></div>
      ) : (
        <>
          <div className="error-table-card">
            <div className="error-table error-table-head"><span>行号</span><span>字段</span><span>错误码</span><span>错误信息</span><span>原始行</span></div>
            {errors.map((item, index) => (
              <div className="error-table error-table-row" key={`${item.row_number ?? 'file'}-${item.error_code}-${index}`}>
                <span>{item.row_number ?? '-'}</span>
                <span>{item.field_name ?? '-'}</span>
                <span><code>{item.error_code}</code></span>
                <span>{item.error_message}</span>
                <code>{item.raw_row ? JSON.stringify(item.raw_row) : '-'}</code>
              </div>
            ))}
          </div>
          <div className="pagination">
            <span>第 {page} / {totalPages} 页，共 {total} 条</span>
            <div>
              <button className="secondary-button" type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => current - 1)}>上一页</button>
              <button className="secondary-button" type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => current + 1)}>下一页</button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return <div className="detail-item"><span>{label}</span><strong>{value}</strong></div>
}

function NotFoundPage() {
  return <section className="empty-state compact-empty"><h1>页面不存在</h1><p>请返回任务列表继续操作。</p><Link className="secondary-button" to="/">返回任务列表</Link></section>
}

export default function App() {
  return <BrowserRouter><Layout /></BrowserRouter>
}
