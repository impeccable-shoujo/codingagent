import { describe, expect, it } from 'vitest'

import { SseParser, frameToEvent, parseSseBlock } from './sse'

const frame = (type: string, data: string) => `event: ${type}\ndata: ${data}\n\n`

describe('SseParser', () => {
  it('单个完整帧', () => {
    const parser = new SseParser()
    expect(parser.push(frame('done', '{"reason":"completed"}'))).toEqual([
      { event: 'done', data: '{"reason":"completed"}' },
    ])
  })

  it('一次拿到多帧', () => {
    const parser = new SseParser()
    const frames = parser.push(frame('a', '{}') + frame('b', '{}') + frame('c', '{}'))
    expect(frames.map((item) => item.event)).toEqual(['a', 'b', 'c'])
  })

  it('半帧留在缓冲里，等后半截到了再吐出来', () => {
    const whole = frame('tool_start', '{"name":"bash"}')

    // 切在任意位置都不能丢帧，这是最容易出错的地方
    for (let cut = 1; cut < whole.length; cut += 1) {
      const fresh = new SseParser()
      const first = fresh.push(whole.slice(0, cut))
      const second = fresh.push(whole.slice(cut))
      const all = [...first, ...second]
      expect(all, `在第 ${cut} 个字符处切开时丢帧了`).toEqual([
        { event: 'tool_start', data: '{"name":"bash"}' },
      ])
    }
  })

  it('data: 被从中间切开也不受影响', () => {
    const parser = new SseParser()
    expect(parser.push('event: x\ndata: {"a"')).toEqual([])
    expect(parser.push(':1}\n\n')).toEqual([{ event: 'x', data: '{"a":1}' }])
  })

  it('忽略注释帧（心跳）', () => {
    const parser = new SseParser()
    expect(parser.push(': ping\n\n')).toEqual([])
    expect(parser.push(': ping\n\nevent: done\ndata: {}\n\n')).toEqual([{ event: 'done', data: '{}' }])
  })

  it('兼容 CRLF 换行', () => {
    const parser = new SseParser()
    expect(parser.push('event: done\r\ndata: {"a":1}\r\n\r\n')).toEqual([
      { event: 'done', data: '{"a":1}' },
    ])
  })

  it('flush 吐出没有以空行收尾的最后一帧', () => {
    const parser = new SseParser()
    expect(parser.push('event: done\ndata: {"reason":"completed"}')).toEqual([])
    expect(parser.flush()).toEqual([{ event: 'done', data: '{"reason":"completed"}' }])
  })

  it('flush 之后不会重复吐出同一帧', () => {
    const parser = new SseParser()
    parser.push('event: done\ndata: {}')
    expect(parser.flush()).toHaveLength(1)
    expect(parser.flush()).toHaveLength(0)
  })

  it('多行 data 用换行拼接', () => {
    const parser = new SseParser()
    const frames = parser.push('event: x\ndata: line1\ndata: line2\n\n')
    expect(frames[0]?.data).toBe('line1\nline2')
  })

  it('没有 data 的块被丢弃', () => {
    expect(parseSseBlock('event: orphan')).toBeNull()
    expect(parseSseBlock('')).toBeNull()
  })

  it('缺省 event 时按 message 处理（SSE 规范）', () => {
    expect(parseSseBlock('data: hello')).toEqual({ event: 'message', data: 'hello' })
  })

  it('data 值只去掉一个前导空格，多余空格属于数据', () => {
    expect(parseSseBlock('data:  两个空格')?.data).toBe(' 两个空格')
  })
})

describe('frameToEvent', () => {
  it('还原成事件信封', () => {
    const event = frameToEvent({ event: 'done', data: '{"type":"done","ts":1.5,"data":{}}' })
    expect(event).toMatchObject({ type: 'done', ts: 1.5 })
  })

  it('坏 JSON 返回 null 而不是抛错——单帧坏掉不该中断整条流', () => {
    expect(frameToEvent({ event: 'x', data: '{不是 JSON' })).toBeNull()
  })

  it('缺少 type 字段返回 null', () => {
    expect(frameToEvent({ event: 'x', data: '{"ts":1}' })).toBeNull()
    expect(frameToEvent({ event: 'x', data: 'null' })).toBeNull()
  })
})
