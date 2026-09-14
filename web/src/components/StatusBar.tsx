import type { HealthInfo } from '../api/types'
import { isBusy, type AgentState } from '../state/agentState'

const LABELS: Record<string, string> = {
  idle: '待命',
  pending: '提交中',
  running: '运行中',
  completed: '已完成',
  max_iterations: '达到迭代上限',
  consecutive_failures: '连续失败已停止',
  provider_error: '模型调用失败',
  stopped: '已中断',
  error: '出错',
}

const TONES: Record<string, string> = {
  idle: 'bg-zinc-800 text-zinc-400',
  pending: 'bg-sky-500/15 text-sky-300',
  running: 'bg-amber-500/15 text-amber-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  stopped: 'bg-zinc-700 text-zinc-300',
  error: 'bg-rose-500/15 text-rose-300',
}

function toneOf(status: string): string {
  if (TONES[status]) return TONES[status]!
  if (status === 'max_iterations' || status === 'consecutive_failures') {
    return 'bg-orange-500/15 text-orange-300'
  }
  return 'bg-rose-500/15 text-rose-300'
}

interface Props {
  state: AgentState
  health: HealthInfo | null
  onStop: () => void
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-zinc-500">{label}</span>
      <span className="font-mono text-zinc-300">{value}</span>
    </span>
  )
}

export function StatusBar({ state, health, onStop }: Props) {
  const busy = isBusy(state)
  const status = state.status

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs">
      <span className={`rounded-full px-2 py-0.5 text-[11px] ${toneOf(status)}`}>
        {LABELS[status] ?? status}
      </span>

      <Metric label="模型" value={health?.model ?? '未知'} />
      <Metric label="轮次" value={state.iterations === null ? '—' : String(state.iterations)} />
      <Metric
        label="tokens"
        value={state.usage === null ? '—' : String(state.usage.total_tokens)}
      />

      <span className="min-w-0 flex-1 truncate text-zinc-500" title={health?.workspace ?? ''}>
        工作区 {health?.workspace ?? '未连接'}
      </span>

      {busy && (
        <button
          type="button"
          onClick={onStop}
          className="rounded-lg border border-rose-500/40 px-2.5 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10"
        >
          停止
        </button>
      )}
    </div>
  )
}
