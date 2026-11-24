/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

// ---------------------------------------------------------------------------
// 预测复盘
// ---------------------------------------------------------------------------

export type ReviewRelease = {
  id: number
  task_id: number | null
  target_metric: string
  business_date: string
  release_round: number
  released_at: string
  predicted_value: number
  lower_bound: number
  upper_bound: number
  confidence: number
  note: string
  hit: boolean | null
  scored: boolean
}

export type ReviewActual = {
  id: number
  actual_value: number
  confirmed_at: string
  confirmed_by: string
  note: string
}

export type DailyReview = {
  ok: boolean
  message?: string
  business_date: string
  target_metric: string
  caliber: string
  caliber_rule: string
  accuracy_target: number
  as_of: string | null
  actual: ReviewActual | null
  actual_versions: ReviewActual[]
  release_count: number
  releases: ReviewRelease[]
  scored_release: ReviewRelease | null
  scored_hit: boolean | null
  unscored_releases: ReviewRelease[]
  accuracy_value: number | null
  target_met: boolean | null
  latest_issue?: IssueDetail | null
}

export type IssueSummary = {
  issue_id: number
  report_id: number
  report_name: string
  business_date: string
  target_metric: string
  issued_at: string
  scored_release_id: number
  scored_release_round: number | null
  scored_interval: string | null
  actual_value: number | null
  scored_hit: boolean
  accuracy_value: number | null
  accuracy_target: number
  target_met: boolean | null
  release_count: number
}

export type IssueContent = {
  report_id: number
  report_name: string
  business_date: string
  target_metric: string
  issued_at: string
  caliber: string
  caliber_rule: string
  accuracy_target: number
  actual: ReviewActual
  releases: ReviewRelease[]
  scored_release: ReviewRelease
  scored_release_id: number
  scored_hit: boolean
  unscored_releases: ReviewRelease[]
  release_count: number
  accuracy_value: number
  target_met: boolean
  conclusion: string
}

export type IssueDetail = {
  issue_id: number
  report_id: number
  business_date: string
  target_metric: string
  issued_at: string
  frozen: boolean
  content: IssueContent
}

export type ReviewOptions = {
  reports: { id: number; report_name: string; status: string }[]
  target_metrics: string[]
}
