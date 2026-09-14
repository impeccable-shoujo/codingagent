import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Approval } from '../state/agentState'
import { ApprovalDialog } from './ApprovalDialog'

const approval: Approval = {
  id: 'ap1',
  command: 'rm -f build/output.log',
  requestedAt: 1,
  state: 'pending',
}

describe('ApprovalDialog', () => {
  it('完整展示命令原文——用户就是凭它做判断的', () => {
    render(<ApprovalDialog approval={approval} onDecide={() => {}} />)
    expect(screen.getByText('rm -f build/output.log')).toBeInTheDocument()
  })

  it('以对话框语义暴露，便于读屏和测试定位', () => {
    render(<ApprovalDialog approval={approval} onDecide={() => {}} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('点击批准回调 true', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<ApprovalDialog approval={approval} onDecide={onDecide} />)

    await user.click(screen.getByRole('button', { name: '批准执行' }))

    expect(onDecide).toHaveBeenCalledWith(true)
  })

  it('点击拒绝回调 false', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<ApprovalDialog approval={approval} onDecide={onDecide} />)

    await user.click(screen.getByRole('button', { name: '拒绝' }))

    expect(onDecide).toHaveBeenCalledWith(false)
  })

  it('告知用户不响应的后果', () => {
    render(<ApprovalDialog approval={approval} onDecide={() => {}} />)
    expect(screen.getByText(/按「拒绝」处理/)).toBeInTheDocument()
  })
})
