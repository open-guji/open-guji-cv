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
import { WorkspacePickerPage } from './pages/WorkspacePickerPage'

// 路由表见方案 §二。Step9（结果整理）2026-09-11 落地第一件事：坐标转字符位。
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* 工作区 id 是 URL 第一段（用户 2026-09-15：「这个 id 应该直接反映在
            url 上，而不是隐藏在浏览器 tab 里。这样更直观」）。
            `/` 不带工作区：落到 WorkspacePickerPage，让人先选一个。
            字形库/异体字库跟着工作区走（库在工作区里），所以也在 /:ws 下。 */}
        <Route path="/" element={<WorkspacePickerPage />} />
        <Route path="/:ws/" element={<HomePage />} />
        <Route path="/:ws/glyphlib/" element={<GlyphLibraryPage />} />
        <Route path="/:ws/variantlib/" element={<VariantLibraryPage />} />
        <Route path="/:ws/:book/" element={<BookOverviewPage />} />
        <Route path="/:ws/:book/step/step0/" element={<Step0Page />} />
        <Route path="/:ws/:book/step/step1/" element={<Step1Page />} />
        <Route path="/:ws/:book/step/step2/" element={<Step2Page />} />
        <Route path="/:ws/:book/step/step3/" element={<Step3Page />} />
        <Route path="/:ws/:book/step/step4/" element={<Step4Page />} />
        <Route path="/:ws/:book/step/step5/" element={<Step5Page />} />
        <Route path="/:ws/:book/step/step5/:sub/" element={<Step5Page />} />
        <Route path="/:ws/:book/step/step6/" element={<Step6Page />} />
        <Route path="/:ws/:book/step/step7/" element={<Step7Page />} />
        <Route path="/:ws/:book/step/step8/" element={<Step8Page />} />
        <Route path="/:ws/:book/step/step9/" element={<Step9Page />} />
        <Route path="/:ws/:book/step/:step/" element={<StepPage />} />
        <Route path="/:ws/:book/runs/" element={<RunsPage />} />
        <Route path="/:ws/:book/evals/" element={<EvalsPage />} />
      </Route>
    </Routes>
  )
}
