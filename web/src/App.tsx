import { ApprovalDialog } from './components/ApprovalDialog'
import { EventStream } from './components/EventStream'
import { StatusBar } from './components/StatusBar'
import { TaskInput } from './components/TaskInput'
import { useAgentSession } from './hooks/useAgentSession'
import { isBusy, pendingApproval } from './state/agentState'

export default function App() {
  const { state, health, run, stop, decide, reset } = useAgentSession()
  const busy = isBusy(state)
  const approval = pendingApproval(state)

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-4 p-6">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h1 className="text-base font-medium text-zinc-100">coding agent</h1>
          <p className="mt-0.5 text-xs text-zinc-500">
            让它读代码、改代码、跑测试 —— 整个过程和每一步工具调用都在这里可见
          </p>
        </div>
        {!busy && state.taskId && (
          <button
            type="button"
            onClick={reset}
            className="shrink-0 rounded-lg border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-300 hover:bg-zinc-800"
          >
            新任务
          </button>
        )}
      </header>

      <StatusBar state={state} health={health} onStop={stop} />
      <TaskInput disabled={busy} onSubmit={run} />
      <EventStream state={state} />

      {approval && <ApprovalDialog approval={approval} onDecide={decide} />}
    </div>
  )
}
