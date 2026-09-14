import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { ToolInvocation } from '../state/agentState'
import { ToolCard, formatDuration, summarizeArgs } from './ToolCard'

function makeTool(overrides: Partial<ToolInvocation> = {}): ToolInvocation {
  return {
    id: 'bash#0',
    name: 'bash',
    args: { command: 'pytest -q' },
    status: 'ok',
    content: '1 passed',
    truncated: false,
    startedAt: 100,
    finishedAt: 100.5,
    ...overrides,
  }
}

describe('summarizeArgs', () => {
  it('优先展示 command', () => {
    expect(summarizeArgs(makeTool())).toBe('pytest -q')
  })

  it('没有 command 时展示 path', () => {
    expect(summarizeArgs(makeTool({ name: 'read_file', args: { path: 'src/app.py' } }))).toBe(
      'src/app.py',
    )
  })

  it('既不是 command 也不是 path 时，列出参数名兜底', () => {
    expect(summarizeArgs(makeTool({ args: { offset: 1, limit: 2 } }))).toBe('offset, limit')
  })

  it('无参数时给个明确说法，不显示空白', () => {
    expect(summarizeArgs(makeTool({ args: {} }))).toBe('无参数')
  })
})

describe('formatDuration', () => {
  it('不足一秒显示毫秒', () => {
    expect(formatDuration(makeTool())).toBe('500ms')
  })

  it('超过一秒显示秒并保留一位小数', () => {
    expect(formatDuration(makeTool({ startedAt: 10, finishedAt: 12.34 }))).toBe('2.3s')
  })

  it('还没结束或没有起始时间时返回 null', () => {
    expect(formatDuration(makeTool({ finishedAt: null }))).toBeNull()
    expect(formatDuration(makeTool({ startedAt: 0, finishedAt: 5 }))).toBeNull()
  })
})

describe('ToolCard', () => {
  it('折叠状态下就能看到工具名和命令摘要', () => {
    render(<ToolCard tool={makeTool()} />)

    expect(screen.getByText('bash')).toBeInTheDocument()
    expect(screen.getByText('pytest -q')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
  })

  it('默认折叠，输出不渲染', () => {
    render(<ToolCard tool={makeTool()} />)
    expect(screen.queryByTestId('tool-output')).not.toBeInTheDocument()
  })

  it('展开后能看到完整输出', async () => {
    const user = userEvent.setup()
    render(<ToolCard tool={makeTool()} />)

    await user.click(screen.getByRole('button'))

    expect(screen.getByTestId('tool-output')).toHaveTextContent('1 passed')
    expect(screen.getByText('参数')).toBeInTheDocument()
  })

  it('再次点击可以收起', async () => {
    const user = userEvent.setup()
    render(<ToolCard tool={makeTool()} />)

    await user.click(screen.getByRole('button'))
    await user.click(screen.getByRole('button'))

    expect(screen.queryByTestId('tool-output')).not.toBeInTheDocument()
  })

  it('失败状态用"失败"表达', () => {
    render(<ToolCard tool={makeTool({ status: 'failed', content: 'ERROR: 退出码 1' })} />)
    expect(screen.getByText('失败')).toBeInTheDocument()
  })

  it('运行中状态用"运行中"表达', () => {
    render(<ToolCard tool={makeTool({ status: 'running', content: '', finishedAt: null })} />)
    expect(screen.getByText('运行中')).toBeInTheDocument()
  })

  it('被截断的输出会打标记', () => {
    render(<ToolCard tool={makeTool({ truncated: true })} />)
    expect(screen.getByText('已截断')).toBeInTheDocument()
  })

  it('输出为空时显示占位而非空白', async () => {
    const user = userEvent.setup()
    render(<ToolCard tool={makeTool({ content: '' })} />)

    await user.click(screen.getByRole('button'))
    expect(screen.getByTestId('tool-output')).toHaveTextContent('(无输出)')
  })
})
