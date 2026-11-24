<template>
  <section class="page review-page">
    <header class="page-head">
      <div>
        <h2>预测复盘</h2>
        <p class="page-desc">
          按业务日把预测发布轮、实测和日报计分关联起来：看哪些区间命中、哪一轮计入准确性，
          以及签发的日报当时用的哪份数据。
        </p>
      </div>
    </header>

    <form class="filter-bar review-filter" @submit.prevent="refresh">
      <label class="filter-item">
        <span>业务日</span>
        <input v-model="businessDate" data-testid="review-date" type="date" required />
      </label>
      <label class="filter-item">
        <span>预测指标</span>
        <input
          v-model="targetMetric"
          data-testid="review-metric"
          list="review-metric-options"
          placeholder="留空则按业务日全部指标"
        />
        <datalist id="review-metric-options">
          <option v-for="name in options.target_metrics" :key="name" :value="name" />
        </datalist>
      </label>
      <button class="btn primary" data-testid="review-query" type="submit">查看复盘</button>
      <button class="btn" data-testid="review-refresh" type="button" @click="refresh">刷新</button>
    </form>

    <p v-if="errorMessage" class="error-text" data-testid="review-error">{{ errorMessage }}</p>
    <p v-if="actionMessage" class="action-note" data-testid="action-message">{{ actionMessage }}</p>

    <template v-if="review">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">实测值</span>
          <strong class="stat-value" data-testid="review-actual">{{ actualText }}</strong>
          <span class="stat-note">{{ actualMeta }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">发布轮次</span>
          <strong class="stat-value" data-testid="review-release-count">{{ review.release_count }}</strong>
          <span class="stat-note">业务日 {{ review.business_date }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">计分轮 / 命中</span>
          <strong class="stat-value" data-testid="review-scored">
            {{ scoredText }}
          </strong>
          <span class="stat-note">{{ review.caliber }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">准确性目标</span>
          <strong
            class="stat-value"
            :class="review.target_met === false ? 'value-bad' : review.target_met ? 'value-good' : ''"
            data-testid="review-target-met"
          >
            {{ targetText }}
          </strong>
          <span class="stat-note">
            本期准确性 {{ review.accuracy_value === null ? '—' : `${(review.accuracy_value * 100).toFixed(0)}%` }}
          </span>
        </article>
      </div>

      <p class="caliber-note" data-testid="review-caliber">
        <strong>计分口径：</strong>{{ review.caliber }}。{{ review.caliber_rule }}
      </p>

      <h3 class="section-title">发布轮与命中</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>轮次</th>
            <th>发布时间</th>
            <th>预测区间</th>
            <th>实测</th>
            <th>命中</th>
            <th>日报计分</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="release in review.releases"
            :key="release.id"
            :data-testid="`review-release-${release.release_round}`"
            :data-scored="release.scored"
            :data-hit="String(release.hit)"
            :class="{ 'row-scored': release.scored }"
          >
            <td>第 {{ release.release_round }} 轮</td>
            <td>{{ release.released_at }}</td>
            <td>{{ release.lower_bound }} ~ {{ release.upper_bound }}</td>
            <td>{{ review.actual ? review.actual.actual_value : '—' }}</td>
            <td>
              <span v-if="release.hit === null" class="badge">待实测</span>
              <span v-else class="badge" :class="release.hit ? 'badge-good' : 'badge-bad'">
                {{ release.hit ? '命中' : '未命中' }}
              </span>
            </td>
            <td>
              <span v-if="release.scored" class="badge badge-brand">计入准确性</span>
              <span v-else class="badge">未计分版本</span>
            </td>
            <td>{{ release.note || '—' }}</td>
          </tr>
          <tr v-if="!review.releases.length">
            <td colspan="7" class="empty-state">该业务日还没有发布预测区间</td>
          </tr>
        </tbody>
      </table>

      <section class="review-grid">
        <div class="panel">
          <h3 class="section-title">确认实测</h3>
          <p class="panel-hint">
            业务日结束后确认实测值。重复确认会追加一个新版本，历史签发视图不受影响。
          </p>
          <form class="inline-form" @submit.prevent="submitActual">
            <label>
              <span>实测值</span>
              <input v-model="actualInput" data-testid="actual-value" type="number" step="any" required />
            </label>
            <label>
              <span>确认人</span>
              <input v-model="confirmedBy" data-testid="actual-by" placeholder="值班员" />
            </label>
            <button class="btn primary" data-testid="actual-submit" type="submit" :disabled="busy">
              确认实测
            </button>
          </form>
          <ul v-if="review.actual_versions.length" class="version-list">
            <li v-for="version in review.actual_versions" :key="version.id">
              实测 {{ version.actual_value }} · 确认于 {{ version.confirmed_at }}
              <span v-if="version.confirmed_by"> · {{ version.confirmed_by }}</span>
            </li>
          </ul>
        </div>

        <div class="panel">
          <h3 class="section-title">签发日报</h3>
          <p class="panel-hint">
            签发会把当次计分轮、实测版本和全部发布轮冻结进签发内容，之后可原样打开。
          </p>
          <form class="inline-form" @submit.prevent="submitIssue">
            <label>
              <span>报告</span>
              <select v-model="reportId" data-testid="issue-report" required>
                <option v-for="report in options.reports" :key="report.id" :value="report.id">
                  {{ report.report_name }}
                </option>
              </select>
            </label>
            <label>
              <span>准确性目标</span>
              <input v-model="accuracyTarget" data-testid="issue-target" type="number" step="0.01" min="0" max="1" />
            </label>
            <button class="btn primary" data-testid="issue-submit" type="submit" :disabled="busy">
              签发日报
            </button>
          </form>
        </div>
      </section>

      <h3 class="section-title">已签发日报</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>版本</th>
            <th>签发时间</th>
            <th>报告</th>
            <th>计分轮</th>
            <th>计分区间</th>
            <th>计分实测</th>
            <th>结论</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="issue in issues"
            :key="issue.issue_id"
            :data-testid="`issue-${issue.issue_id}`"
          >
            <td>#{{ issue.issue_id }}</td>
            <td>{{ issue.issued_at }}</td>
            <td>{{ issue.report_name }}</td>
            <td>第 {{ issue.scored_release_round }} 轮</td>
            <td>{{ issue.scored_interval }}</td>
            <td>{{ issue.actual_value }}</td>
            <td>
              <span class="badge" :class="issue.target_met ? 'badge-good' : 'badge-bad'">
                {{ issue.scored_hit ? '命中' : '未命中' }} ·
                {{ issue.target_met ? '达标' : '未达标' }}
              </span>
            </td>
            <td>
              <button class="link" type="button" :data-testid="`open-issue-${issue.issue_id}`" @click="openIssue(issue.issue_id)">
                打开签发内容
              </button>
            </td>
          </tr>
          <tr v-if="!issues.length">
            <td colspan="8" class="empty-state">该业务日还没有签发日报</td>
          </tr>
        </tbody>
      </table>
    </template>

    <div v-if="openedIssue" class="modal-backdrop" data-testid="issue-modal">
      <div class="modal issue-modal">
        <h3>签发内容 #{{ openedIssue.issue_id }}（已冻结）</h3>
        <dl class="issue-meta">
          <dt>报告</dt><dd>{{ openedIssue.content.report_name }}</dd>
          <dt>业务日</dt><dd>{{ openedIssue.business_date }}</dd>
          <dt>签发时间</dt><dd>{{ openedIssue.issued_at }}</dd>
          <dt>计分口径</dt><dd>{{ openedIssue.content.caliber }}</dd>
          <dt>计分实测（实际用于计分）</dt>
          <dd data-testid="issue-actual">
            {{ openedIssue.content.actual.actual_value }}
            · 确认于 {{ openedIssue.content.actual.confirmed_at }}
          </dd>
          <dt>计分轮</dt>
          <dd data-testid="issue-scored-round">
            第 {{ openedIssue.content.scored_release.release_round }} 轮 ·
            {{ openedIssue.content.scored_release.lower_bound }} ~
            {{ openedIssue.content.scored_release.upper_bound }} ·
            发布于 {{ openedIssue.content.scored_release.released_at }}
          </dd>
          <dt>结论</dt><dd data-testid="issue-conclusion">{{ openedIssue.content.conclusion }}</dd>
        </dl>
        <table class="data-table">
          <thead>
            <tr><th>轮次</th><th>发布时间</th><th>区间</th><th>命中</th><th>计分</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="release in openedIssue.content.releases"
              :key="release.id"
              :data-testid="`issue-release-${release.release_round}`"
            >
              <td>第 {{ release.release_round }} 轮</td>
              <td>{{ release.released_at }}</td>
              <td>{{ release.lower_bound }} ~ {{ release.upper_bound }}</td>
              <td>{{ release.hit ? '命中' : '未命中' }}</td>
              <td>{{ release.scored ? '计入' : '未计分版本' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="page-actions">
          <button class="btn" data-testid="close-issue" type="button" @click="openedIssue = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  confirmActual,
  issueDailyReport,
  listReportIssues,
  loadDailyReview,
  loadIssue,
  loadReviewOptions,
} from '@/api/backend-service'
import type { DailyReview, IssueDetail, IssueSummary, ReviewOptions } from '@/data/types'

const today = new Date().toISOString().slice(0, 10)
const businessDate = ref(today)
const targetMetric = ref('')
const review = ref<DailyReview | null>(null)
const issues = ref<IssueSummary[]>([])
const options = ref<ReviewOptions>({ reports: [], target_metrics: [] })
const reportId = ref<number | null>(null)
const accuracyTarget = ref('1')
const actualInput = ref('')
const confirmedBy = ref('数据工程组值班员')
const openedIssue = ref<IssueDetail | null>(null)
const errorMessage = ref('')
const actionMessage = ref('')
const busy = ref(false)

const actualText = computed(() =>
  review.value?.actual ? String(review.value.actual.actual_value) : '待实测',
)
const actualMeta = computed(() => {
  const actual = review.value?.actual
  if (!actual) return '业务日结束后确认实测'
  return `确认于 ${actual.confirmed_at}${actual.confirmed_by ? ` · ${actual.confirmed_by}` : ''}`
})
const scoredText = computed(() => {
  const scored = review.value?.scored_release
  if (!scored) return '—'
  return `第 ${scored.release_round} 轮 · ${scored.hit ? '命中' : '未命中'}`
})
const targetText = computed(() => {
  if (!review.value || review.value.target_met === null) return '待判定'
  return review.value.target_met ? '达到目标' : '未达到目标'
})

async function loadReview(keepMessage = '') {
  errorMessage.value = ''
  actionMessage.value = ''
  busy.value = true
  try {
    review.value = await loadDailyReview({
      businessDate: businessDate.value,
      targetMetric: targetMetric.value.trim() || undefined,
    })
    if (!review.value.ok) throw new Error(review.value.message || '复盘视图读取失败')
    if (!targetMetric.value.trim() && review.value.target_metric) {
      targetMetric.value = review.value.target_metric
    }
    await loadIssues()
    if (review.value.actual) actualInput.value = String(review.value.actual.actual_value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复盘视图读取失败'
  } finally {
    busy.value = false
    actionMessage.value = keepMessage
  }
}

function refresh() {
  void loadReview()
}

async function loadIssues() {
  if (!reportId.value) return
  const payload = await listReportIssues({
    reportId: reportId.value,
    businessDate: businessDate.value,
  })
  issues.value = payload.items
}

async function submitActual() {
  errorMessage.value = ''
  actionMessage.value = ''
  busy.value = true
  try {
    const metric = targetMetric.value.trim()
    if (!metric) throw new Error('请先填写预测指标')
    const result = await confirmActual({
      targetMetric: metric,
      businessDate: businessDate.value,
      actualValue: actualInput.value,
      confirmedBy: confirmedBy.value,
    })
    if (!result.ok) throw new Error(result.message)
    await loadReview(result.message)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认实测失败'
  } finally {
    busy.value = false
  }
}

async function submitIssue() {
  errorMessage.value = ''
  actionMessage.value = ''
  busy.value = true
  try {
    if (!reportId.value) throw new Error('请先选择报告')
    const metric = targetMetric.value.trim()
    if (!metric) throw new Error('请先填写预测指标')
    const result = await issueDailyReport({
      reportId: reportId.value,
      businessDate: businessDate.value,
      targetMetric: metric,
      accuracyTarget: accuracyTarget.value,
    })
    if (!result.ok) throw new Error(result.message)
    await loadReview(result.message)
    if (result.issue_id) await openIssue(result.issue_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '签发日报失败'
  } finally {
    busy.value = false
  }
}

async function openIssue(issueId: number) {
  errorMessage.value = ''
  try {
    const result = await loadIssue(issueId)
    if (!result.ok) throw new Error('签发内容读取失败')
    openedIssue.value = result.issue
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '签发内容读取失败'
  }
}

onMounted(async () => {
  try {
    options.value = await loadReviewOptions()
    if (options.value.reports.length) reportId.value = options.value.reports[0].id
    await loadReview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复盘页面初始化失败'
  }
})
</script>
