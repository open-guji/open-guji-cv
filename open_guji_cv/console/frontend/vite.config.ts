import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 方案见 overview 仓 项目进展/图片初步数字化/进度/控制台重构v2/方案.md §一。
// 开发时 `npm run dev` 起独立端口，把 /api 代理到 FastAPI（8640）；
// `npm run build` 产物落 ../static/dist/，FastAPI 继续用一条命令托管，
// 产物入仓（用户 2026-09-11 定：工作台与 open-guji-cv 运行环境分离，
// 不能假设都装了 node/npm）。
export default defineConfig({
  plugins: [react()],
  base: '/static/dist/',
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8640',
    },
  },
})
