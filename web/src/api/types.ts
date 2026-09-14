/**
 * 前后端事件契约。
 *
 * 对应后端 `agent/types.py` 的 AgentEvent 与 `agent/loop.py` 里各 _emit 调用。
 * 后端字段一旦调整，这里必须同步——目前是手写维护，
 * v0.5 可以考虑用 FastAPI 的 OpenAPI schema 自动生成，避免两边漂移。
 */

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

/** 每种事件各自的负载形状。 */
export interface EventPayloads {
  iteration_start: { iteration: number }
  assistant_message: { content: string; tool_calls: string[] }
  tool_start: { name: string; arguments: Record<string, unknown> }
  tool_result: { name: string; ok: boolean; truncated: boolean; content: string }
  approval_required: { approval_id: string; command: string }
  approval_timeout: { approval_id: string; command: string }
  interrupted: { reason: string }
  error: { message?: string; reason?: string }
  done: {
    reason: string
    text: string
    iterations: number
    usage: TokenUsage
  }
}

export type AgentEventType = keyof EventPayloads

/** 信封：type 决定 data 的形状，消费方可以据此做穷尽判断。 */
export type AgentEvent = {
  [K in AgentEventType]: { type: K; ts: number; data: EventPayloads[K] }
}[AgentEventType]

export const TERMINAL_STATUSES = [
  'completed',
  'max_iterations',
  'consecutive_failures',
  'provider_error',
  'stopped',
  'error',
] as const

export type TerminalStatus = (typeof TERMINAL_STATUSES)[number]
export type TaskStatus = 'pending' | 'running' | TerminalStatus

export function isTerminal(status: string): status is TerminalStatus {
  return (TERMINAL_STATUSES as readonly string[]).includes(status)
}

export interface TaskCreated {
  task_id: string
  status: TaskStatus
}

export interface TaskSnapshot {
  task_id: string
  task: string
  status: TaskStatus
  events: number
  pending_approvals: string[]
  iterations: number | null
  tokens: number | null
  text: string | null
  created_at: number
  finished_at: number | null
}

export interface HealthInfo {
  status: string
  model: string
  workspace: string
  sessions: number
}
