import { useState } from 'react'

interface Props {
  disabled: boolean
  onSubmit: (task: string) => void
}

export function TaskInput({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState('')
  const trimmed = value.trim()

  const submit = () => {
    if (disabled || !trimmed) return
    onSubmit(trimmed)
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-3"
    >
      <label htmlFor="task-input" className="sr-only">
        任务描述
      </label>
      <textarea
        id="task-input"
        rows={3}
        value={value}
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          // Enter 换行，Ctrl/Cmd + Enter 提交，避免长任务描述被误提交
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            submit()
          }
        }}
        placeholder="描述要 agent 做什么，例如：跑一下测试并修复失败项"
        className="w-full resize-y bg-transparent font-mono text-sm text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-50"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px] text-zinc-500">Ctrl / Cmd + Enter 提交</span>
        <button
          type="submit"
          disabled={disabled || !trimmed}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
        >
          开始
        </button>
      </div>
    </form>
  )
}
