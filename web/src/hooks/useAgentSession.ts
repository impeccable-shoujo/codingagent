/** 把 REST + SSE 接到状态机上。界面层只消费 state 和几个动作函数。 */

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import {
  ApiError,
  createTask,
  decideApproval,
  fetchHealth,
  stopTask,
  streamEvents,
} from '../api/client'
import type { HealthInfo } from '../api/types'
import { agentReducer, initialState, pendingApproval } from '../state/agentState'

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

export function useAgentSession() {
  const [state, dispatch] = useReducer(agentReducer, initialState)
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchHealth()
      .then((info) => {
        if (!cancelled) setHealth(info)
      })
      .catch(() => {
        // 状态栏拿不到服务信息不影响主流程，静默降级
        if (!cancelled) setHealth(null)
      })
    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
  }, [])

  const run = useCallback(async (task: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const created = await createTask(task)
      dispatch({ type: 'submitted', task, taskId: created.task_id })
      await streamEvents(created.task_id, {
        signal: controller.signal,
        onEvent: (event) => dispatch({ type: 'event', event }),
      })
      dispatch({ type: 'stream_closed' })
    } catch (error) {
      if (controller.signal.aborted) return
      dispatch({ type: 'stream_failed', message: describe(error) })
    }
  }, [])

  const stop = useCallback(async () => {
    if (!state.taskId) return
    try {
      await stopTask(state.taskId)
    } catch (error) {
      dispatch({ type: 'request_failed', message: describe(error) })
    }
  }, [state.taskId])

  const decide = useCallback(
    async (approved: boolean) => {
      const approval = pendingApproval(state)
      if (!approval || !state.taskId) return
      // 先本地标记，避免用户在请求往返期间重复点击
      dispatch({ type: 'approval_decided', approvalId: approval.id, approved })
      try {
        await decideApproval(state.taskId, approval.id, approved)
      } catch (error) {
        dispatch({ type: 'request_failed', message: describe(error) })
      }
    },
    [state],
  )

  const reset = useCallback(() => {
    abortRef.current?.abort()
    dispatch({ type: 'reset' })
  }, [])

  return { state, health, run, stop, decide, reset }
}
