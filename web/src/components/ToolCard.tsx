import { useState } from 'react'

import type { ToolInvocation } from '../state/agentState'

const STATUS_STYLE: Record<ToolInvocation['status'], { dot: string; text: string; label: string }> = {
  running: { dot: 'bg-amber-400 animate-pulse', text: 'text-amber-300', label: '运行中' },
  ok: { dot: 'bg-emerald-400', text: 'text-emerald-300', label: '成功' },
  failed: { dot: 'bg-rose-500', text: 'text-rose-300', label: '失败' },
}

/** 折叠状态下也要能一眼看出这一步在干什么，所以取最关键的参数做摘要。 */
export function summarizeArgs(tool: ToolInvocation): string {
  const command = tool.args['command']
  if (typeof command === 'string') return command
  const path = tool.args['path']
  if (typeof path === 'string') return path
  const keys = Object.keys(tool.args)
  return keys.length > 0 ? keys.join(', ') : '无参数'
}

export function formatDuration(tool: ToolInvocation): string | null {
  if (tool.finishedAt === null || tool.startedAt === 0) return null
  // 后端时间戳单位是秒
  const ms = Math.max(0, (tool.finishedAt - tool.startedAt) * 1000)
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

export function ToolCard({ tool }: { tool: ToolInvocation }) {
  const [open, setOpen] = useState(false)
  const style = STATUS_STYLE[tool.status]
  const duration = formatDuration(tool)

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-zinc-800/50"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} aria-hidden="true" />
        <span className="shrink-0 font-mono text-xs font-medium text-zinc-100">{tool.name}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-400">
          {summarizeArgs(tool)}
        </span>
        {duration && <span className="shrink-0 text-[11px] text-zinc-500">{duration}</span>}
        {tool.truncated && (
          <span className="shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-400">
            已截断
          </span>
        )}
        <span className={`shrink-0 text-[11px] ${style.text}`}>{style.label}</span>
        <span className="shrink-0 text-[11px] text-zinc-500" aria-hidden="true">
          {open ? '收起' : '展开'}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-zinc-800 px-3 py-3">
          <section>
            <h4 className="mb-1 text-[11px] tracking-wide text-zinc-500">参数</h4>
            <pre className="overflow-x-auto rounded bg-zinc-950 p-2 font-mono text-xs text-zinc-300">
              {JSON.stringify(tool.args, null, 2)}
            </pre>
          </section>
          <section>
            <h4 className="mb-1 text-[11px] tracking-wide text-zinc-500">输出</h4>
            <pre
              data-testid="tool-output"
              className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-2 font-mono text-xs text-zinc-300"
            >
              {tool.content || '(无输出)'}
            </pre>
          </section>
        </div>
      )}
    </div>
  )
}
