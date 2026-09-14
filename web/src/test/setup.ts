import '@testing-library/jest-dom/vitest'

// jsdom 没有实现 ReadableStream，而测试里要构造假的流式响应喂给解析器。
// 这里补一个最小的实现，只覆盖 client.ts 用到的 getReader/read/releaseLock。
if (typeof globalThis.ReadableStream === 'undefined') {
  class FakeReadableStream {
    private chunks: Uint8Array[]

    constructor(chunks: Uint8Array[] = []) {
      this.chunks = chunks
    }

    getReader() {
      return {
        read: async () => {
          if (this.chunks.length === 0) return { value: undefined, done: true }
          return { value: this.chunks.shift(), done: false }
        },
        releaseLock: () => undefined,
      }
    }
  }
  ;(globalThis as unknown as { ReadableStream: unknown }).ReadableStream = FakeReadableStream
}
