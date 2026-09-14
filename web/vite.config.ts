import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// 从 vitest/config 引入 defineConfig，这样 test 段也有类型提示。
export default defineConfig(({ mode }) => {
  // 第三个参数传空串，表示不限定前缀，VITE_ 之外的变量也能读到
  const env = loadEnv(mode, '.', '')
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: Number(env.VITE_DEV_PORT || 5173),
      proxy: {
        // 开发期把 /api 转发到后端，前后端同源，省掉 CORS 配置。
        // SSE 也走这条链路，所以不能开压缩缓冲。
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }
})
