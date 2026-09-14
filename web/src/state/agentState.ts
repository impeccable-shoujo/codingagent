/**
 * 事件流的状态机。
 *
 * 界面要表达的东西全部由 SSE 事件推导，所以把推导过程收敛成一个纯函数：
 * 输入 (state, event) 输出新 state。这样"agent 跑到一半中断""审批超时"
 * 这类分支都能用单测覆盖，不需要真的起后端。
 */

import { isTerminal, type AgentEvent, type TaskStatus, type TokenUsage } from '../api/types'

export type ToolStatus = 'running' | 'ok' | 'failed'

export interface ToolInvocation {
  id: string
  name: string
  args: Record<string, unknown>
  status: ToolStatus
  content: string
  truncated: boolean
  startedAt: number
  finishedAt: number | null
}

export interface Turn {
  index: number
  assistantText: string
  tools: ToolInvocation[]
}

export type ApprovalState = 'pending' | 'approved' | 'denied' | 'timed_out' | 'cancelled'

export interface Approval {
  id: string
  command: string
  requestedAt: number
  state: ApprovalState
}

export interface AgentState {
  taskId: string | null
  task: string
  status: TaskStatus | 'idle'
  turns: Turn[]
  approvals: Approval[]
  iterations: number | null
  usage: TokenUsage | null
  finalText: string
  stopReason: string | null
  error: string | null
  /** 事件流是否还连着。断开不等于失败，正常结束也会断开。 */
  streaming: boolean
}

export const initialState: AgentState = {
  taskId: null,
  task: '',
  status: 'idle',
  turns: [],
  approvals: [],
  iterations: null,
  usage: null,
  finalText: '',
  stopReason: null,
  error: null,
  streaming: false,
}

export type Action =
  | { type: 'submitted'; task: string; taskId: string }
  | { type: 'event'; event: AgentEvent }
  | { type: 'stream_closed' }
  | { type: 'stream_failed'; message: string }
  | { type: 'approval_decided'; approvalId: string; approved: boolean }
  | { type: 'request_failed'; message: string }
  | { type: 'reset' }

export function agentReducer(state: AgentState, action: Action): AgentState {
  switch (action.type) {
    case 'submitted':
      return {
        ...initialState,
        taskId: action.taskId,
        task: action.task,
        status: 'pending',
        streaming: true,
      }

    // 连接断开本身不是错误：正常结束时服务端也会关掉流。
    // 但如果没拿到终态就断了，说明中途出了问题，必须显式告诉用户，
    // 否则界面会一直停在"运行中"，看起来像卡死。
    case 'stream_closed':
      if (isTerminal(state.status)) return { ...state, streaming: false }
      return {
        ...state,
        streaming: false,
        status: 'error',
        error: state.error ?? '事件流意外中断，请检查后端服务是否仍在运行',
      }

    case 'stream_failed':
      if (isTerminal(state.status)) return { ...state, streaming: false }
      return {
        ...state,
        streaming: false,
        status: 'error',
        error: state.error ?? action.message,
      }

    case 'approval_decided':
      return {
        ...state,
        approvals: state.approvals.map((item) =>
          item.id === action.approvalId
            ? { ...item, state: action.approved ? 'approved' : 'denied' }
            : item,
        ),
      }

    case 'request_failed':
      return { ...state, error: action.message }

    case 'reset':
      return initialState

    case 'event':
      return applyEvent(state, action.event)

    default:
      return state
  }
}

function applyEvent(state: AgentState, event: AgentEvent): AgentState {
  switch (event.type) {
    case 'iteration_start':
      return {
        ...state,
        status: 'running',
        iterations: event.data.iteration,
        turns: [
          ...state.turns,
          { index: event.data.iteration, assistantText: '', tools: [] },
        ],
      }

    case 'assistant_message':
      return {
        ...state,
        turns: updateLastTurn(state.turns, (turn) => ({
          ...turn,
          assistantText: event.data.content,
        })),
      }

    case 'tool_start':
      return {
        ...state,
        turns: appendTool(state.turns, {
          id: `${event.data.name}#${countTools(state.turns)}`,
          name: event.data.name,
          args: event.data.arguments,
          status: 'running',
          content: '',
          truncated: false,
          startedAt: event.ts,
          finishedAt: null,
        }),
      }

    case 'tool_result':
      return {
        ...state,
        turns: resolveTool(state.turns, event.data.name, (tool) => ({
          ...tool,
          status: event.data.ok ? 'ok' : 'failed',
          content: event.data.content,
          truncated: event.data.truncated,
          finishedAt: event.ts,
        })),
      }

    case 'approval_required': {
      if (state.approvals.some((item) => item.id === event.data.approval_id)) return state
      return {
        ...state,
        approvals: [
          ...state.approvals,
          {
            id: event.data.approval_id,
            command: event.data.command,
            requestedAt: event.ts,
            state: 'pending',
          },
        ],
      }
    }

    case 'approval_timeout':
      return {
        ...state,
        approvals: state.approvals.map((item) =>
          item.id === event.data.approval_id ? { ...item, state: 'timed_out' } : item,
        ),
      }

    case 'interrupted':
      return {
        ...state,
        stopReason: event.data.reason,
        approvals: cancelPending(state.approvals),
      }

    case 'error':
      return { ...state, error: event.data.message ?? event.data.reason ?? '未知错误' }

    case 'done':
      return {
        ...state,
        status: isTerminal(event.data.reason) ? event.data.reason : 'error',
        finalText: event.data.text,
        stopReason: event.data.reason,
        iterations: event.data.iterations ?? state.iterations,
        usage: event.data.usage ?? state.usage,
        approvals: cancelPending(state.approvals),
        streaming: false,
      }

    default:
      return state
  }
}

// ---------- 不可变更新辅助 ----------

function countTools(turns: Turn[]): number {
  return turns.reduce((total, turn) => total + turn.tools.length, 0)
}

function emptyTurn(index = 1): Turn {
  return { index, assistantText: '', tools: [] }
}

function updateLastTurn(turns: Turn[], update: (turn: Turn) => Turn): Turn[] {
  if (turns.length === 0) return [update(emptyTurn())]
  const next = turns.slice()
  next[next.length - 1] = update(next[next.length - 1]!)
  return next
}

function appendTool(turns: Turn[], tool: ToolInvocation): Turn[] {
  return updateLastTurn(turns, (turn) => ({ ...turn, tools: [...turn.tools, tool] }))
}

/** 把结果落到最后一个同名且仍在运行的工具上；找不到就补一条，
 *  这样即使中间漏了 tool_start（比如中途才订阅），界面也不会丢内容。 */
function resolveTool(
  turns: Turn[],
  name: string,
  update: (tool: ToolInvocation) => ToolInvocation,
): Turn[] {
  for (let t = turns.length - 1; t >= 0; t -= 1) {
    const turn = turns[t]!
    for (let i = turn.tools.length - 1; i >= 0; i -= 1) {
      const tool = turn.tools[i]!
      if (tool.name === name && tool.status === 'running') {
        const tools = turn.tools.slice()
        tools[i] = update(tool)
        const next = turns.slice()
        next[t] = { ...turn, tools }
        return next
      }
    }
  }
  // 补一条"运行中"的占位再走同一套 update，否则结果内容会被丢掉
  return appendTool(
    turns,
    update({
      id: `${name}#${countTools(turns)}`,
      name,
      args: {},
      status: 'running',
      content: '',
      truncated: false,
      startedAt: 0,
      finishedAt: 0,
    }),
  )
}

function cancelPending(approvals: Approval[]): Approval[] {
  return approvals.map((item) => (item.state === 'pending' ? { ...item, state: 'cancelled' } : item))
}

// ---------- 派生选择器 ----------

export function pendingApproval(state: AgentState): Approval | null {
  return state.approvals.find((item) => item.state === 'pending') ?? null
}

export function isBusy(state: AgentState): boolean {
  return state.status === 'pending' || state.status === 'running'
}

export function toolCount(state: AgentState): number {
  return countTools(state.turns)
}
