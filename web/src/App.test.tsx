/**
 * 集成测试：用假的 fetch + 假的事件流把整条链路跑一遍。
 * 不碰网络、不起后端，但走的是真实的 client / 状态机 / 组件。
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const encoder = new TextEncoder()

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function envelope(type: string, data: unknown, ts = 1): string {
  return `event: ${type}\ndata: ${JSON.stringify({ type, ts, data })}\n\n`
}

/** 可手动推送的服务端事件流，用来模拟"停下来等用户确认"这类中间态。 */
function controllableSse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(inner) {
      controller = inner
    },
  })
  return {
    response: new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
    enqueue: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  }
}

type Sse = ReturnType<typeof controllableSse>

/**
 * 推送事件并等状态更新落定。
 * 必须包在 act 里：读取流、派发 action、React 重渲染是一条异步链，
 * 不包的话 React 会警告"更新未包裹在 act 中"，CI 输出会被噪声淹没。
 */
async function push(sse: Sse, ...frames: string[]): Promise<void> {
  await act(async () => {
    for (const frame of frames) sse.enqueue(frame)
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

interface Recorded {
  url: string
  body: Record<string, unknown> | undefined
}

function installFetch(router: (url: string) => Response) {
  const calls: Recorded[] = []
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input)
    let body: Record<string, unknown> | undefined
    if (typeof init?.body === 'string') {
      body = JSON.parse(init.body) as Record<string, unknown>
    }
    calls.push({ url, body })
    return router(url)
  })
  return calls
}

/** 一次常规任务的假后端：健康检查、建任务、事件流。 */
function standardRouter(sse: Sse) {
  return (url: string): Response => {
    if (url.endsWith('/health')) return jsonResponse(HEALTH)
    if (url.endsWith('/tasks')) return jsonResponse({ task_id: 't1', status: 'running' }, 202)
    if (url.includes('/stream')) return sse.response
    if (url.endsWith('/approve')) return jsonResponse({ ok: true })
    if (url.endsWith('/stop')) return jsonResponse({ ok: true, status: 'running' })
    throw new Error(`未预期的请求：${url}`)
  }
}

const HEALTH = { status: 'ok', model: 'glm-4.5-air', workspace: 'D:/ws', sessions: 0 }

afterEach(() => {
  vi.unstubAllGlobals()
})

async function submitTask(user: ReturnType<typeof userEvent.setup>, task = '跑测试并修好') {
  await user.type(screen.getByLabelText('任务描述'), task)
  await user.click(screen.getByRole('button', { name: '开始' }))
}

/** 提交任务并等到事件流真的建立，之后才能安全地推事件。 */
async function startAndConnect(user: ReturnType<typeof userEvent.setup>, calls: Recorded[]) {
  await submitTask(user)
  await waitFor(() => expect(calls.some((call) => call.url.includes('/stream'))).toBe(true))
}

describe('App', () => {
  it('初始状态给出引导，而不是空白页面', () => {
    installFetch((url) => {
      if (url.endsWith('/health')) return jsonResponse(HEALTH)
      throw new Error(`未预期的请求：${url}`)
    })

    render(<App />)

    expect(screen.getByText(/还没有任务/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '停止' })).not.toBeInTheDocument()
  })

  it('状态栏展示后端上报的模型与工作区', async () => {
    installFetch((url) => {
      if (url.endsWith('/health')) return jsonResponse(HEALTH)
      throw new Error(`未预期的请求：${url}`)
    })

    render(<App />)

    expect(await screen.findByText('glm-4.5-air')).toBeInTheDocument()
    expect(screen.getByText(/D:\/ws/)).toBeInTheDocument()
  })

  it('跑完一个任务：工具卡片、最终回复、用量都出现在界面上', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(
      sse,
      envelope('iteration_start', { iteration: 1 }, 1),
      envelope('assistant_message', { content: '先跑一遍测试', tool_calls: ['bash'] }, 1.1),
      envelope('tool_start', { name: 'bash', arguments: { command: 'pytest -q' } }, 1.2),
      envelope('tool_result', { name: 'bash', ok: true, truncated: false, content: '1 passed' }, 1.9),
      envelope(
        'done',
        {
          reason: 'completed',
          text: '测试已经通过',
          iterations: 1,
          usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
        },
        2,
      ),
    )
    await act(async () => {
      sse.close()
    })

    expect(await screen.findByText('先跑一遍测试')).toBeInTheDocument()
    expect(screen.getByText('bash')).toBeInTheDocument()
    expect(screen.getByText('pytest -q')).toBeInTheDocument()
    expect(await screen.findByText('测试已经通过')).toBeInTheDocument()
    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
  })

  it('工具输出默认收起，展开后可见', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(
      sse,
      envelope('tool_start', { name: 'bash', arguments: { command: 'ls' } }, 1),
      envelope('tool_result', { name: 'bash', ok: true, truncated: false, content: 'a.txt' }, 2),
    )

    const card = await screen.findByRole('button', { name: /bash/ })
    expect(screen.queryByTestId('tool-output')).not.toBeInTheDocument()

    await user.click(card)

    expect(screen.getByTestId('tool-output')).toHaveTextContent('a.txt')
    await act(async () => {
      sse.close()
    })
  })

  it('危险命令弹出确认框，批准后调用审批接口', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(sse, envelope('approval_required', { approval_id: 'ap1', command: 'rm -f o.log' }, 1.5))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('rm -f o.log')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '批准执行' }))

    await waitFor(() => {
      const approve = calls.find((call) => call.url.endsWith('/approve'))
      expect(approve?.body).toMatchObject({ task_id: 't1', approval_id: 'ap1', approved: true })
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await act(async () => {
      sse.close()
    })
  })

  it('拒绝危险命令同样会通知后端', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(sse, envelope('approval_required', { approval_id: 'ap1', command: 'rm -f x' }, 1))
    await user.click(await screen.findByRole('button', { name: '拒绝' }))

    await waitFor(() => {
      const approve = calls.find((call) => call.url.endsWith('/approve'))
      expect(approve?.body).toMatchObject({ approved: false })
    })
    await act(async () => {
      sse.close()
    })
  })

  it('运行中提供停止按钮，点击后调用中断接口', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(sse, envelope('iteration_start', { iteration: 1 }, 1))
    await user.click(await screen.findByRole('button', { name: '停止' }))

    await waitFor(() => expect(calls.some((call) => call.url.endsWith('/stop'))).toBe(true))
    await act(async () => {
      sse.close()
    })
  })

  it('事件流中途断开时明确报错，不让界面停在运行中', async () => {
    const user = userEvent.setup()
    const sse = controllableSse()
    const calls = installFetch(standardRouter(sse))

    render(<App />)
    await startAndConnect(user, calls)

    await push(sse, envelope('iteration_start', { iteration: 1 }, 1))
    expect(await screen.findByText('运行中')).toBeInTheDocument()

    await act(async () => {
      sse.close()
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('意外中断')
    expect(screen.getByText('出错')).toBeInTheDocument()
  })

  it('后端返回错误时展示服务端给出的原因', async () => {
    const user = userEvent.setup()
    installFetch((url) => {
      if (url.endsWith('/health')) return jsonResponse(HEALTH)
      if (url.endsWith('/tasks')) return jsonResponse({ detail: '模型未配置' }, 500)
      throw new Error(`未预期的请求：${url}`)
    })

    render(<App />)
    await submitTask(user)

    expect(await screen.findByRole('alert')).toHaveTextContent('模型未配置')
  })

  it('网络不通时给出可见错误，而不是一直转圈', async () => {
    const user = userEvent.setup()
    installFetch((url) => {
      if (url.endsWith('/health')) return jsonResponse(HEALTH)
      throw new Error('connect ECONNREFUSED 127.0.0.1:8000')
    })

    render(<App />)
    await submitTask(user)

    expect(await screen.findByRole('alert')).toHaveTextContent('ECONNREFUSED')
  })
})
