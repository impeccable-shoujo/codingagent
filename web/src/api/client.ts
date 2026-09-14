/** 传输层客户端：上行走 REST，下行走 SSE。 */

import { SseParser, frameToEvent } from './sse'
import type { AgentEvent, HealthInfo, TaskCreated, TaskSnapshot } from './types'

const configured = (import.meta.env.VITE_API_BASE_URL ?? '').trim()
/** 默认走 /api，由 Vite 开发代理转发到后端，前后端同源。 */
export const API_BASE = (configured || '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function url(path: string): string {
  return `${API_BASE}${path}`
}

async function expectOk(response: Response, action: string): Promise<Response> {
  if (response.ok) return response
  let detail = ''
  try {
    const body = await response.json()
    detail = typeof body?.detail === 'string' ? body.detail : ''
  } catch {
    // 响应体不是 JSON，忽略，错误信息退回状态码
  }
  throw new ApiError(
    `${action}失败（HTTP ${response.status}）${detail ? `：${detail}` : ''}`,
    response.status,
  )
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export async function createTask(task: string): Promise<TaskCreated> {
  const response = await fetch(url('/tasks'), jsonInit({ task }))
  await expectOk(response, '提交任务')
  return (await response.json()) as TaskCreated
}

export async function stopTask(taskId: string): Promise<void> {
  const response = await fetch(url('/stop'), jsonInit({ task_id: taskId }))
  await expectOk(response, '中断任务')
}

export async function decideApproval(
  taskId: string,
  approvalId: string,
  approved: boolean,
): Promise<void> {
  const response = await fetch(
    url('/approve'),
    jsonInit({ task_id: taskId, approval_id: approvalId, approved }),
  )
  await expectOk(response, approved ? '批准命令' : '拒绝命令')
}

export async function fetchHealth(): Promise<HealthInfo> {
  const response = await fetch(url('/health'))
  await expectOk(response, '读取服务状态')
  return (await response.json()) as HealthInfo
}

export async function fetchSnapshot(taskId: string): Promise<TaskSnapshot> {
  const response = await fetch(url(`/tasks/${encodeURIComponent(taskId)}`))
  await expectOk(response, '读取任务快照')
  return (await response.json()) as TaskSnapshot
}

export interface StreamOptions {
  onEvent: (event: AgentEvent) => void
  cursor?: number
  signal?: AbortSignal
}

/**
 * 订阅事件流，直到服务端结束（收到 done 或连接断开）。
 *
 * 读取端可能是任意分块的，所以每一块都先喂给解析器，由解析器负责
 * 处理"半帧"和"多帧"两种情况。
 */
export async function streamEvents(taskId: string, options: StreamOptions): Promise<void> {
  const params = new URLSearchParams({
    task_id: taskId,
    cursor: String(options.cursor ?? 0),
  })
  const response = await fetch(url(`/stream?${params.toString()}`), {
    headers: { Accept: 'text/event-stream' },
    signal: options.signal,
  })
  await expectOk(response, '订阅事件流')

  if (!response.body) {
    throw new ApiError('当前环境不支持流式响应（response.body 为空）')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()

  const deliver = (frames: ReturnType<SseParser['push']>) => {
    for (const frame of frames) {
      const event = frameToEvent(frame)
      if (event) options.onEvent(event as AgentEvent)
    }
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      deliver(parser.push(decoder.decode(value, { stream: true })))
    }
    // 收尾：解码器可能还压着半个多字节字符，解析器可能还剩一帧没以空行结尾
    deliver(parser.push(decoder.decode()))
    deliver(parser.flush())
  } finally {
    reader.releaseLock()
  }
}
