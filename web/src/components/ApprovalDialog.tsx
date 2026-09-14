import type { Approval } from '../state/agentState'

interface Props {
  approval: Approval
  onDecide: (approved: boolean) => void
}

/**
 * 危险操作的人工闸门。
 *
 * 后端对 rm / git 写操作 / 安装依赖这类命令会阻塞等待，超时按拒绝处理。
 * 所以这里必须把「命令原文」完整展示出来——用户是凭它做判断的，
 * 把命令截断等于剥夺了判断依据。
 */
export function ApprovalDialog({ approval, onDecide }: Props) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="危险命令确认"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4"
    >
      <div className="w-full max-w-xl rounded-xl border border-amber-500/40 bg-zinc-900 p-5">
        <h2 className="text-sm font-medium text-amber-300">agent 请求执行一条需要确认的命令</h2>
        <p className="mt-1 text-xs text-zinc-400">该操作可能不可逆，请确认后再继续。</p>

        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded bg-zinc-950 p-3 font-mono text-xs text-amber-200">
          {approval.command}
        </pre>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onDecide(false)}
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
          >
            拒绝
          </button>
          <button
            type="button"
            onClick={() => onDecide(true)}
            className="rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-zinc-950 hover:bg-amber-400"
          >
            批准执行
          </button>
        </div>

        <p className="mt-3 text-[11px] text-zinc-500">
          长时间不响应，后端会按「拒绝」处理，以免无人值守时误执行。
        </p>
      </div>
    </div>
  )
}
