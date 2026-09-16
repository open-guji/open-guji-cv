import type { Book } from './types/registry'

// 面板可见性：**按这册书的版式声明**决定哪些裁决台 / 卡片 / 产物台出现。
//
// 2026-09-15 用户定：「每个裁决台、总览卡片、产物等等，在不同模式下要能够
// 方便地设置或隐藏」。在此之前是各页面自己写 `edition === 'modern' && …`，
// 散在四五个文件里，加一本新书（横排、简体、无界行刻本…）就得挨个去找。
//
// 三条规矩：
//
// 1. **按能力判，不按版式名判。** 写 `caps.hasFrame` 而不是
//    `edition === 'keben'`——真正决定「界行切分裁决台有没有意义」的是这本书
//    有没有版框界行（`frame: ruled`），不是它是刻本还是排印本。将来若有
//    「无界行的刻本」，它自然落到对的一侧，不必再改一次判断。
// 2. **能力从 Book 的版式字段推**（`frame` / `writing_mode` / `edition` /
//    `ocr_candidates`），那些字段本就是 book yaml 里声明的，是唯一真源。
// 3. **默认可见。** 新面板不写进这张表就一直显示——宁可多显示一个空面板，
//    也别让人以为功能丢了。要藏必须在这里显式声明理由。

export interface Caps {
  /** 有版框界行（`frame: ruled`）。界行/版框类的裁决与金标只对这类书有意义。 */
  hasFrame: boolean
  /** 走固定格数的格位切分（刻本链 `row_segment`）。现代排印本是墨段 DP
   *  切分（`row_segment_runs`），没有「格线穿字」「拖切线」这回事。 */
  hasGridCells: boolean
  /** 有抬头（每列首字上抬表敬语）。刻本版式特征，排印本不用这套。 */
  hasHeadRaise: boolean
  /** 有双行小注（夹注）。刻本常见；北行日錄的小注是单行小字，不走夹注切分。 */
  hasJiazhu: boolean
  /** 这一步有闸（现代链 Step3 是墨段 DP，没有闸3）。 */
  hasStep3Gate: boolean
  /** 启用了 Step5-c OCR 候选（book yaml 的 `ocr_candidates`）。 */
  hasOcrCandidates: boolean
  /** 登记了整理本（`references`），Step5-d 锚定才有意义。
   *
   *  ⚠️ 这一条**只在明确声明了 references 时才收紧**，没声明一律当有。
   *  实测（2026-09-15）：四庫工作区的 `books/vol01.yaml` 是一份 18 行的精简版，
   *  盖住了引擎仓那份 59 行的（工作区优先，见 core/book.py::_book_yaml_path），
   *  `references` 段就这么丢了——可它的 `align_ref` 产物明明是跑出来的。
   *  按「声明为准」去藏，会把一个在用的面板藏掉。宁可多显示。 */
  hasReference: boolean
}

/** 从册的版式声明推出能力。`book` 还没取到时给一份「全开」的，
 *  避免加载过程中面板先闪一下再消失。 */
export function capsOf(book: Book | null | undefined): Caps {
  if (!book) {
    return {
      hasFrame: true, hasGridCells: true, hasHeadRaise: true, hasJiazhu: true,
      hasStep3Gate: true, hasOcrCandidates: true, hasReference: true,
    }
  }
  const modern = book.edition === 'modern'
  const framed = (book.frame ?? 'ruled') === 'ruled'
  return {
    hasFrame: framed,
    // 格位切分与版框是两件事，但现在的两条链恰好一一对应：刻本 = 有框 + 格位，
    // 现代 = 无框 + 墨段。先按 edition 判，等真出现「无框刻本」再拆开。
    hasGridCells: !modern,
    hasHeadRaise: !modern,
    hasJiazhu: !modern,
    hasStep3Gate: !modern,
    hasOcrCandidates: book.ocr_candidates !== false,
    // `undefined` = 后端版本旧/字段没传 → 当有；只有明确回 0 才算没有。
    // 但即便回 0 也只是「没声明」，不代表没在用（见上面 vol01 的坑），
    // 所以这里暂时一律当有，等 book yaml 那边理清再收紧。
    hasReference: true,
  }
}
