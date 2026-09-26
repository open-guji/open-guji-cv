import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 方案见 overview 仓 项目进展/图片初步数字化/进度/控制台重构v2/方案.md §一。
// 开发时 `npm run dev` 起独立端口，把 /api 代理到 FastAPI（8640）；
// `npm run build` 产物落 ../static/dist/，FastAPI 继续用一条命令托管，
// 产物入仓（用户 2026-09-11 定：工作台与 open-guji-cv 运行环境分离，
// 不能假设都装了 node/npm）。
// 挂在反向代理前缀下（如 `/collate`，网站把 `/collate/*` 转给 CV 服务器，
// overview 任务书「监听与本机开发」一节）：build 时传 `VITE_ROOT_PATH=/collate`，
// 资源 base 与 `client.ts` 的 `ROOT_PATH`（API/图片 URL 前缀、Router `basename`）
// 一起跟着换。缺省空串——本机单独跑控制台照旧挂在根路径。
const ROOT_PATH = (process.env.VITE_ROOT_PATH ?? '').replace(/\/$/, '')

export default defineConfig({
  plugins: [react()],
  base: `${ROOT_PATH}/static/dist/`,
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
