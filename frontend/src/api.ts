export type JobStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCESS'
  | 'PARTIAL_SUCCESS'
  | 'FAILED'
  | 'CANCELED'

export interface Job {
  id: string
  name: string
  status: JobStatus
  source_file_name: string
  total_records: number
  success_records: number
  failed_records: number
  retry_count: number
  last_error_code: string | null
  last_error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface JobError {
  job_id: string
  row_number: number | null
  field_name: string | null
  error_code: string
  error_message: string
  raw_row: Record<string, unknown> | { values: string[] } | null
  created_at: string
}

export interface ApiErrorPayload {
  code: string
  message: string
  details: unknown[]
}

export interface ApiResponse<T> {
  data: T
  meta: Record<string, unknown>
}

export class ApiRequestError extends Error {
  code: string
  details: unknown[]

  constructor(payload: ApiErrorPayload) {
    super(payload.message)
    this.name = 'ApiRequestError'
    this.code = payload.code
    this.details = payload.details
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init)
  } catch {
    throw new ApiRequestError({
      code: 'NETWORK_ERROR',
      message: '无法连接 API 服务，请确认 Docker 服务正在运行。',
      details: [],
    })
  }

  const payload = (await response.json().catch(() => null)) as
    | ApiResponse<T>
    | { error?: ApiErrorPayload }
    | null

  if (!response.ok) {
    const error = payload && 'error' in payload ? payload.error : undefined
    throw new ApiRequestError(
      error ?? {
        code: 'HTTP_ERROR',
        message: `请求失败（${response.status}）`,
        details: [],
      },
    )
  }

  return payload as ApiResponse<T>
}

export function listJobs(page: number, pageSize: number, status?: JobStatus | '') {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  return request<Job[]>(`/api/v1/jobs?${params.toString()}`)
}

export function getJob(jobId: string) {
  return request<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`)
}

export function getJobErrors(jobId: string, page: number, pageSize: number) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return request<JobError[]>(`/api/v1/jobs/${encodeURIComponent(jobId)}/errors?${params.toString()}`)
}

export function createJob(file: File, name?: string) {
  const formData = new FormData()
  formData.append('file', file)
  if (name?.trim()) formData.append('name', name.trim())
  return request<Job>('/api/v1/jobs', {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: formData,
  })
}

export function healthCheck() {
  return request<{ status: string }>('/healthz')
}
