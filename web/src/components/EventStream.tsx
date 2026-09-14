import type { ReactNode } from 'react'

import type { AgentState } from '../state/agentState'
import { ToolCard } from './ToolCard'

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: ReactNode }) {
  const tone =
    role === 'user'
      ? 'border-sky-500/30 bg-sky-500/5'
      : 'border-zinc-800 bg-zinc-900/40'
  return (
    <div className={`rounded-xl border px-3 py-2 ${tone}`}>
      <div className="mb-1 text-[11px] tracking-wide text-zinc-500">
        {role === 'user' ? '任务' : 'agent'}
      </div>
      <div className="whitespace-pre-wrap text-sm text-zinc-200">{children}</div>
    </div>
  )
}

export function EventStream({ state }: { state: AgentState }) {
  // 提交阶段就失败时还没有 taskId，但错误必须让用户看见，
  // 所以这里不能只看 taskId 就退化成空状态。
  if (!state.taskId && !state.error) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-800 px-4 py-10 text-center text-sm text-zinc-500">
        还没有任务。上面输入一句话，agent 会在工作区里读代码、改代码、跑测试。
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {state.taskId && <Bubble role="user">{state.task}</Bubble>}

      {state.turns.map((turn, index) => (
        <div key={`${turn.index}-${index}`} className="space-y-2">
          {turn.assistantText && <Bubble role="assistant">{turn.assistantText}</Bubble>}
          {turn.tools.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
        </div>
      ))}

      {state.finalText && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2">
          <div className="mb-1 text-[11px] tracking-wide text-emerald-400">
            最终回复{state.stopReason && state.stopReason !== 'completed' ? `（${state.stopReason}）` : ''}
          </div>
          <div className="whitespace-pre-wrap text-sm text-zinc-200">{state.finalText}</div>
        </div>
      )}

      {state.error && (
        <div
          role="alert"
          className="rounded-xl border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {state.error}
        </div>
      )}
    </div>
  )
}
