import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  DailyReview,
  EntryRow,
  IssueDetail,
  IssueSummary,
  OverviewResult,
  PageResult,
  ReviewOptions,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ---------------------------------------------------------------------------
// 预测复盘：发布轮、实测版本、日报签发与回查
// ---------------------------------------------------------------------------

async function reviewRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  return (await response.json()) as T
}

export async function loadReviewOptions(): Promise<ReviewOptions> {
  return reviewRequest<ReviewOptions>('/api/review/options')
}

export async function loadDailyReview(params: {
  businessDate: string
  targetMetric?: string
}): Promise<DailyReview> {
  const query = new URLSearchParams({ business_date: params.businessDate })
  if (params.targetMetric) query.set('target_metric', params.targetMetric)
  return reviewRequest<DailyReview>(`/api/review/daily?${query.toString()}`)
}

export async function confirmActual(params: {
  targetMetric: string
  businessDate: string
  actualValue: string
  confirmedBy?: string
}): Promise<{ ok: boolean; message: string }> {
  return reviewRequest('/api/review/forecast-actuals', {
    method: 'POST',
    body: JSON.stringify({
      target_metric: params.targetMetric,
      business_date: params.businessDate,
      actual_value: Number(params.actualValue),
      confirmed_by: params.confirmedBy ?? '',
    }),
  })
}

export async function issueDailyReport(params: {
  reportId: number
  businessDate: string
  targetMetric: string
  accuracyTarget: string
}): Promise<{ ok: boolean; message: string; issue_id?: number }> {
  return reviewRequest('/api/review/issues', {
    method: 'POST',
    body: JSON.stringify({
      report_id: params.reportId,
      business_date: params.businessDate,
      target_metric: params.targetMetric,
      accuracy_target: Number(params.accuracyTarget),
    }),
  })
}

export async function listReportIssues(
  params: { reportId?: number; businessDate?: string } = {},
): Promise<{ ok: boolean; items: IssueSummary[]; total: number }> {
  const query = new URLSearchParams()
  if (params.reportId) query.set('report_id', String(params.reportId))
  if (params.businessDate) query.set('business_date', params.businessDate)
  return reviewRequest(`/api/review/issues?${query.toString()}`)
}

export async function loadIssue(issueId: number): Promise<{ ok: boolean; issue: IssueDetail }> {
  return reviewRequest(`/api/review/issues/${issueId}`)
}
