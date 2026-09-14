/**
 * SSE 帧解析（纯逻辑，无浏览器依赖，因此可以直接单测）。
 *
 * 为什么不用浏览器内置的 EventSource：
 * ① 它在连接正常结束后会自动重连。我们的 /stream 是"一次性事件流"，
 *    正常结束也是断开，EventSource 会当成错误去重连，于是历史被反复重放，
 *    界面上出现重复内容。
 * ② 它拿不到 HTTP 状态码，也带不了自定义请求头，出错时分不清是 404 还是网络问题。
 * 所以改用 fetch + ReadableStream，自己按 SSE 规范切帧。
 *
 * 分块边界是这里最容易被忽略的地方：一次 read() 可能只拿到半帧，
 * 也可能一次拿到好几帧，甚至把 "data:" 从中间切开。所以必须保留缓冲。
 */

export interface SseFrame {
  event: string
  data: string
}

export function parseSseBlock(block: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue // 空行与注释（心跳就是注释帧）
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      // 规范规定冒号后最多去掉一个空格，多余空格属于数据
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''))
    }
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

export class SseParser {
  private buffer = ''

  push(chunk: string): SseFrame[] {
    // 统一换行，后面只按 \n 处理
    this.buffer += chunk.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

    const frames: SseFrame[] = []
    let separator = this.buffer.indexOf('\n\n')
    while (separator !== -1) {
      const block = this.buffer.slice(0, separator)
      this.buffer = this.buffer.slice(separator + 2)
      const frame = parseSseBlock(block)
      if (frame) frames.push(frame)
      separator = this.buffer.indexOf('\n\n')
    }
    return frames
  }

  /** 流结束时调用：把没有以空行收尾的最后一帧也吐出来。 */
  flush(): SseFrame[] {
    const rest = this.buffer
    this.buffer = ''
    const frame = parseSseBlock(rest)
    return frame ? [frame] : []
  }
}

/** 把 SSE 帧还原成事件。解析失败返回 null 而不是抛错——
 *  单帧坏掉不该让整个界面的流中断。 */
export function frameToEvent(frame: SseFrame): { type: string; ts: number; data: unknown } | null {
  try {
    const envelope = JSON.parse(frame.data)
    if (typeof envelope?.type !== 'string') return null
    return envelope
  } catch {
    return null
  }
}
