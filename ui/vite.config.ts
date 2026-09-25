import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 后端地址与前端端口都可由 ui/.env 或 shell 环境变量覆盖，方便与本机其他服务共存
  const env = loadEnv(mode, process.cwd(), '')
  const uiPort = Number(env.UI_PORT || 5199)
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8100'
  const wsTarget = apiTarget.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    server: {
      port: uiPort,
      // 端口被占用时直接报错，避免 Vite 静默换端口后与后端 CORS 白名单不一致
      strictPort: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          timeout: 10000,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
          }
        },
        '/ws': {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
          secure: false,
          timeout: 10000
        }
      }
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      minify: true,
      target: 'es2015',
      chunkSizeWarningLimit: 2000,
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom'],
            router: ['react-router-dom']
          }
        }
      }
    }
  }
})
