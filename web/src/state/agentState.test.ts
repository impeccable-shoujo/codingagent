import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../api/types'
import {
  agentReducer,
  initialState,
  isBusy,
  pendingApproval,
  toolCount,
  type AgentState,
} from './agentState'

function ev(type: string, data: unknown, ts = 0): AgentEvent {
  return { type, ts, data } as AgentEvent
}

function reduce(state: AgentState, ...events: AgentEvent[]): AgentState {
  return events.reduce<AgentState>((acc, event) => agentReducer(acc, { type: 'event', event }), state)
}

const started: AgentState = agentReducer(initialState, {
  type: 'submitted',
  task: '修好测试',
  taskId: 't1',
})

describe('submitted', () => {
  it('清空上一轮结果并进入提交中', () => {
    const dirty = reduce(started, ev('done', { reason: 'completed', text: '旧结果' }))
    const fresh = agentReducer(dirty, { type: 'submitted', task: '新任务', taskId: 't2' })

    expect(fresh.taskId).toBe('t2')
    expect(fresh.task).toBe('新任务')
    expect(fresh.status).toBe('pending')
    expect(fresh.streaming).toBe(true)
    expect(fresh.turns).toEqual([])
    expect(fresh.finalText).toBe('')
  })
})

describe('轮次与工具调用', () => {
  it('iteration_start 开一轮，assistant_message 写进当前轮', () => {
    const state = reduce(
      started,
      ev('iteration_start', { iteration: 1 }, 1),
      ev('assistant_message', { content: '先看一眼代码', tool_calls: ['read_file'] }, 1.1),
    )

    expect(state.status).toBe('running')
    expect(state.iterations).toBe(1)
    expect(state.turns).toHaveLength(1)
    expect(state.turns[0]?.assistantText).toBe('先看一眼代码')
  })

  it('tool_start 与 tool_result 配对，状态从运行中转成功', () => {
    const state = reduce(
      started,
      ev('iteration_start', { iteration: 1 }, 1),
      ev('tool_start', { name: 'bash', arguments: { command: 'pytest' } }, 1.2),
      ev('tool_result', { name: 'bash', ok: true, truncated: false, content: '1 passed' }, 2.0),
    )

    const tool = state.turns[0]?.tools[0]
    expect(tool?.status).toBe('ok')
    expect(tool?.content).toBe('1 passed')
    expect(tool?.finishedAt).toBe(2.0)
  })

  it('失败结果记为 failed，并保留已截断标记', () => {
    const state = reduce(
      started,
      ev('tool_start', { name: 'bash', arguments: {} }, 1),
      ev('tool_result', { name: 'bash', ok: false, truncated: true, content: 'ERROR' }, 1.5),
    )

    expect(state.turns[0]?.tools[0]?.status).toBe('failed')
    expect(state.turns[0]?.tools[0]?.truncated).toBe(true)
  })

  it('只落到最后一个同名且仍在运行的调用上', () => {
    const state = reduce(
      started,
      ev('iteration_start', { iteration: 1 }, 1),
      ev('tool_start', { name: 'bash', arguments: { command: 'a' } }, 1),
      ev('tool_result', { name: 'bash', ok: true, truncated: false, content: '第一个' }, 1.1),
      ev('tool_start', { name: 'bash', arguments: { command: 'b' } }, 1.2),
      ev('tool_result', { name: 'bash', ok: true, truncated: false, content: '第二个' }, 1.3),
    )

    const tools = state.turns[0]?.tools ?? []
    expect(tools.map((tool) => tool.content)).toEqual(['第一个', '第二个'])
  })

  it('漏掉了 tool_start 时也能补上结果，界面不丢内容', () => {
    const state = reduce(
      started,
      ev('tool_result', { name: 'read_file', ok: true, truncated: false, content: '内容' }, 3),
    )

    expect(toolCount(state)).toBe(1)
    expect(state.turns[0]?.tools[0]?.content).toBe('内容')
  })

  it('工具 id 唯一，重复调用不会撞 key', () => {
    const state = reduce(
      started,
      ev('tool_start', { name: 'bash', arguments: {} }, 1),
      ev('tool_start', { name: 'bash', arguments: {} }, 2),
    )
    const ids = state.turns[0]?.tools.map((tool) => tool.id) ?? []
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe('审批', () => {
  const required = ev(
    'approval_required',
    { approval_id: 'ap1', command: 'rm victim.txt' },
    5,
  )

  it('入队并可通过选择器取到', () => {
    const state = reduce(started, required)
    expect(pendingApproval(state)?.command).toBe('rm victim.txt')
  })

  it('同一 id 重复到达不会叠加', () => {
    const state = reduce(started, required, required)
    expect(state.approvals).toHaveLength(1)
  })

  it('本地决定后立刻变更状态，避免重复点击', () => {
    const state = agentReducer(reduce(started, required), {
      type: 'approval_decided',
      approvalId: 'ap1',
      approved: true,
    })
    expect(state.approvals[0]?.state).toBe('approved')
    expect(pendingApproval(state)).toBeNull()
  })

  it('超时事件把审批标记为超时', () => {
    const state = reduce(started, required, ev('approval_timeout', { approval_id: 'ap1' }, 6))
    expect(state.approvals[0]?.state).toBe('timed_out')
    expect(pendingApproval(state)).toBeNull()
  })

  it('任务结束时未决审批一并取消，弹窗不会残留', () => {
    const state = reduce(
      started,
      required,
      ev('done', { reason: 'completed', text: '完', iterations: 1, usage: null }, 7),
    )
    expect(state.approvals[0]?.state).toBe('cancelled')
    expect(pendingApproval(state)).toBeNull()
  })

  it('中断也会取消未决审批', () => {
    const state = reduce(started, required, ev('interrupted', { reason: 'stopped' }, 6))
    expect(state.approvals[0]?.state).toBe('cancelled')
  })
})

describe('结束与异常', () => {
  it('done 落到终态并带上用量', () => {
    const state = reduce(
      started,
      ev('done', {
        reason: 'completed',
        text: '修好了',
        iterations: 3,
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      }),
    )

    expect(state.status).toBe('completed')
    expect(state.finalText).toBe('修好了')
    expect(state.iterations).toBe(3)
    expect(state.usage?.total_tokens).toBe(15)
    expect(state.streaming).toBe(false)
    expect(isBusy(state)).toBe(false)
  })

  it('识别非正常结束原因', () => {
    for (const reason of ['max_iterations', 'consecutive_failures', 'provider_error', 'stopped']) {
      const state = reduce(started, ev('done', { reason, text: 'x', iterations: 1, usage: null }))
      expect(state.status).toBe(reason)
      expect(state.stopReason).toBe(reason)
    }
  })

  it('未知结束原因按出错处理，不留下模糊状态', () => {
    const state = reduce(started, ev('done', { reason: 'something_new', text: '', iterations: 1 }))
    expect(state.status).toBe('error')
  })

  it('error 事件写入错误信息', () => {
    const state = reduce(started, ev('error', { message: '模型调用失败' }))
    expect(state.error).toBe('模型调用失败')
  })

  it('已拿到终态时，连接断开只是断开，不算失败', () => {
    const settled = reduce(started, ev('done', { reason: 'completed', text: '', iterations: 1 }))
    const state = agentReducer(settled, { type: 'stream_closed' })

    expect(state.streaming).toBe(false)
    expect(state.error).toBeNull()
    expect(state.status).toBe('completed')
  })

  it('没拿到终态就断开，必须显式报错——否则界面看起来像卡死', () => {
    const state = agentReducer(reduce(started, ev('iteration_start', { iteration: 1 })), {
      type: 'stream_closed',
    })

    expect(state.status).toBe('error')
    expect(state.error).toContain('意外中断')
  })

  it('请求直接失败时也进入出错状态', () => {
    const state = agentReducer(initialState, { type: 'stream_failed', message: '网络不可达' })
    expect(state.status).toBe('error')
    expect(state.error).toBe('网络不可达')
  })

  it('保留已有的错误信息，不被后到的通用错误覆盖', () => {
    const state = agentReducer(reduce(started, ev('error', { message: '具体原因' })), {
      type: 'stream_failed',
      message: '笼统原因',
    })
    expect(state.error).toBe('具体原因')
  })

  it('reset 回到初始状态', () => {
    const state = agentReducer(reduce(started, ev('iteration_start', { iteration: 1 })), {
      type: 'reset',
    })
    expect(state).toEqual(initialState)
  })
})

describe('不可变性', () => {
  it('不修改传入的 state', () => {
    const before = JSON.stringify(started)
    reduce(
      started,
      ev('iteration_start', { iteration: 1 }),
      ev('tool_start', { name: 'bash', arguments: { command: 'x' } }),
      ev('tool_result', { name: 'bash', ok: true, truncated: false, content: 'ok' }),
    )
    expect(JSON.stringify(started)).toBe(before)
  })
})
