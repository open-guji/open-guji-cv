// Step7「切分裁决」卡片：默认选中项与落定时的 verdict / 来源口径（overview#188）。
//
// 纯函数、不依赖 React，`tests/test_cutline_default.py` 用 node 直接跑它。
//
// 口径（C 道定）：
// - 默认选中：后端下发的 `default_idx`（书级开关 `params.review.cutline_default`，
//   缺省 unet：有 `unet_seam` 候选就指它，否则同 `chosen`）。老后端没下发时前端自己算同一件事。
// - verdict：`moved` = 用户动手改了——**跟卡片默认选中项比，不跟引擎 chosen 比**。
//   直接确认默认项记 `ok`；改选别的候选、自己画线记 `moved`。
// - picked_source：最后落定的线出自谁。`engine`（就是引擎 chosen，引擎恰好也选了
//   U-Net 时也算 engine）/ `unet`（U-Net 候选，且不是 chosen）/ `alt`（别的算法候选，
//   具体 kind 见 `cand`）/ `hand`（自己画的）。下游要「引擎错没错」看
//   `picked_source !== 'engine'`，不再看 `moved`。
// - default_pick：这张卡当时默认选中的是 `unet` 还是 `chosen`。

export const UNET_KIND = 'unet_seam'

export interface PickCase {
  candidates?: Array<{ kind: string }> | null
  chosen: number | null
  default_idx?: number | null
  default_pick?: 'unet' | 'chosen'
}

export type PickedSource = 'engine' | 'unet' | 'alt' | 'hand'

export function defaultPick(c: PickCase): { idx: number | null; from: 'unet' | 'chosen' } {
  if (c.default_idx !== undefined && c.default_pick) {
    return { idx: c.default_idx ?? null, from: c.default_pick }
  }
  const unet = (c.candidates || []).findIndex((x) => x.kind === UNET_KIND)
  return unet >= 0 ? { idx: unet, from: 'unet' } : { idx: c.chosen ?? null, from: 'chosen' }
}

export function pickedSource(c: PickCase, pick: number | null, drawn: boolean): PickedSource | undefined {
  if (drawn) return 'hand'
  if (pick == null) return undefined
  if (pick === c.chosen) return 'engine'
  if (c.candidates?.[pick]?.kind === UNET_KIND) return 'unet'
  return 'alt'
}

// `idk` 不带来源字段：没落定任何一条线。
export function decideFields(c: PickCase, pick: number | null, drawn: boolean, verdict: 'confirmed' | 'idk') {
  const d = defaultPick(c)
  if (verdict === 'idk') return { verdict: 'idk', default_pick: d.from }
  return {
    verdict: drawn ? 'moved' : (pick === d.idx ? 'ok' : 'moved'),
    picked_source: pickedSource(c, pick, drawn),
    default_pick: d.from,
  }
}
