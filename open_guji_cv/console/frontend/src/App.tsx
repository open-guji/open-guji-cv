import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout'
import { HomePage } from './pages/HomePage'
import { BookOverviewPage } from './pages/BookOverviewPage'
import { StepPage } from './pages/StepPage'
import { Step0Page } from './pages/Step0Page'
import { Step1Page } from './pages/Step1Page'
import { Step2Page } from './pages/Step2Page'
import { Step3Page } from './pages/Step3Page'
import { Step4Page } from './pages/Step4Page'
import { Step5Page } from './pages/Step5Page'
import { Step6Page } from './pages/Step6Page'
import { Step7Page } from './pages/Step7Page'
import { Step8Page } from './pages/Step8Page'
import { Step9Page } from './pages/Step9Page'
import { RunsPage } from './pages/RunsPage'
import { EvalsPage } from './pages/EvalsPage'
import { GlyphLibraryPage } from './pages/GlyphLibraryPage'
import { VariantLibraryPage } from './pages/VariantLibraryPage'

// 路由表见方案 §二。Step9（结果整理）2026-09-11 落地第一件事：坐标转字符位。
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/glyphlib/" element={<GlyphLibraryPage />} />
        <Route path="/variantlib/" element={<VariantLibraryPage />} />
        <Route path="/:book/" element={<BookOverviewPage />} />
        <Route path="/:book/step/step0/" element={<Step0Page />} />
        <Route path="/:book/step/step1/" element={<Step1Page />} />
        <Route path="/:book/step/step2/" element={<Step2Page />} />
        <Route path="/:book/step/step3/" element={<Step3Page />} />
        <Route path="/:book/step/step4/" element={<Step4Page />} />
        <Route path="/:book/step/step5/" element={<Step5Page />} />
        <Route path="/:book/step/step5/:sub/" element={<Step5Page />} />
        <Route path="/:book/step/step6/" element={<Step6Page />} />
        <Route path="/:book/step/step7/" element={<Step7Page />} />
        <Route path="/:book/step/step8/" element={<Step8Page />} />
        <Route path="/:book/step/step9/" element={<Step9Page />} />
        <Route path="/:book/step/:step/" element={<StepPage />} />
        <Route path="/:book/runs/" element={<RunsPage />} />
        <Route path="/:book/evals/" element={<EvalsPage />} />
      </Route>
    </Routes>
  )
}
