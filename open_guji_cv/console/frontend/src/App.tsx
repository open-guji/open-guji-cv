import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout'
import { HomePage } from './pages/HomePage'
import { BookOverviewPage } from './pages/BookOverviewPage'
import { StepPage } from './pages/StepPage'
import { Step0Page } from './pages/Step0Page'
import { Step3Page } from './pages/Step3Page'
import { Step5Page } from './pages/Step5Page'
import { Step7Page } from './pages/Step7Page'
import { Step8Page } from './pages/Step8Page'
import { RunsPage } from './pages/RunsPage'
import { EvalsPage } from './pages/EvalsPage'
import { GlyphLibraryPage } from './pages/GlyphLibraryPage'
import { VariantLibraryPage } from './pages/VariantLibraryPage'

// 路由表见方案 §二。Step9（结果整理）路由已加（用户 2026-09-11 改口），页面暂时空。
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/glyphlib/" element={<GlyphLibraryPage />} />
        <Route path="/variantlib/" element={<VariantLibraryPage />} />
        <Route path="/:book/" element={<BookOverviewPage />} />
        <Route path="/:book/step/step0/" element={<Step0Page />} />
        <Route path="/:book/step/step3/" element={<Step3Page />} />
        <Route path="/:book/step/step5/" element={<Step5Page />} />
        <Route path="/:book/step/step5/:sub/" element={<Step5Page />} />
        <Route path="/:book/step/step7/" element={<Step7Page />} />
        <Route path="/:book/step/step8/" element={<Step8Page />} />
        <Route path="/:book/step/:step/" element={<StepPage />} />
        <Route path="/:book/runs/" element={<RunsPage />} />
        <Route path="/:book/evals/" element={<EvalsPage />} />
      </Route>
    </Routes>
  )
}
