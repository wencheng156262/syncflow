import { useEffect, useState } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
} from 'react-router-dom'
import './App.css'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function StatusPill({ children }: { children: string }) {
  return <span className="status-pill">{children}</span>
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
          <NavLink to="/" end>
            任务
          </NavLink>
          <NavLink to="/jobs/new">创建任务</NavLink>
        </nav>
        <span className="environment-label">LOCAL</span>
      </header>
      <main className="page-content">
        <Routes>
          <Route path="/" element={<JobsPage />} />
          <Route path="/jobs/new" element={<CreateJobPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  )
}

function JobsPage() {
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking')

  useEffect(() => {
    fetch(`${apiBaseUrl}/healthz`)
      .then((response) => {
        if (!response.ok) throw new Error('health check failed')
        setApiStatus('online')
      })
      .catch(() => setApiStatus('offline'))
  }, [])

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">DATA OPERATIONS</p>
          <h1>任务中心</h1>
          <p className="page-description">集中查看 CSV 同步任务的状态、进度和结果。</p>
        </div>
        <Link className="primary-button" to="/jobs/new">
          创建同步任务
        </Link>
      </div>

      <div className="overview-grid">
        <div className="overview-card">
          <span>全部任务</span>
          <strong>-</strong>
          <small>连接 API 后显示</small>
        </div>
        <div className="overview-card">
          <span>处理中</span>
          <strong>-</strong>
          <small>等待后续任务查询功能</small>
        </div>
        <div className="overview-card">
          <span>API 状态</span>
          <strong>{apiStatus === 'online' ? '正常' : apiStatus === 'offline' ? '离线' : '检查中'}</strong>
          <small>{apiBaseUrl}</small>
        </div>
      </div>

      <div className="empty-state">
        <div className="empty-icon">↗</div>
        <h2>还没有同步任务</h2>
        <p>上传一份 CSV 文件，创建你的第一个异步同步任务。</p>
        <Link className="secondary-button" to="/jobs/new">
          开始创建
        </Link>
      </div>
    </section>
  )
}

function CreateJobPage() {
  return (
    <section className="narrow-page">
      <div className="page-heading compact-heading">
        <div>
          <p className="eyebrow">NEW JOB</p>
          <h1>创建同步任务</h1>
          <p className="page-description">选择 CSV 文件并提交后台处理。</p>
        </div>
      </div>
      <div className="form-card">
        <label htmlFor="job-name">任务名称（可选）</label>
        <input id="job-name" placeholder="例如：商品导入 2026-01-01" disabled />
        <label htmlFor="job-file">CSV 文件</label>
        <input id="job-file" type="file" accept=".csv,text/csv" disabled />
        <p className="form-hint">Week 2 将接入 POST /api/v1/jobs 文件上传接口。</p>
        <button className="primary-button" type="button" disabled>
          提交任务
        </button>
      </div>
    </section>
  )
}

function JobDetailPage() {
  return (
    <section className="narrow-page">
      <Link className="back-link" to="/">
        ← 返回任务列表
      </Link>
      <div className="page-heading compact-heading">
        <div>
          <p className="eyebrow">JOB DETAIL</p>
          <h1>任务详情</h1>
          <p className="page-description">任务数据将在接入查询接口后展示。</p>
        </div>
        <StatusPill>PENDING</StatusPill>
      </div>
      <div className="detail-placeholder">GET /api/v1/jobs/:jobId</div>
    </section>
  )
}

function NotFoundPage() {
  return (
    <section className="empty-state compact-empty">
      <h1>页面不存在</h1>
      <p>请返回任务列表继续操作。</p>
      <Link className="secondary-button" to="/">
        返回任务列表
      </Link>
    </section>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  )
}
