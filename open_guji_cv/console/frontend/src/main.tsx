import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { ROOT_PATH } from './api/client'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* 挂在反向代理前缀下时（`--root-path`/`VITE_ROOT_PATH`），地址栏本身就带着
        前缀——Router 的内部路径要先把它减掉，否则每条 <Route path> 都得手写前缀。 */}
    <BrowserRouter basename={ROOT_PATH || undefined}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
