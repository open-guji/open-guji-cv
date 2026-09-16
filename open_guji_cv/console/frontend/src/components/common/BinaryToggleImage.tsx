import { useState } from 'react'
import { withWorkspace } from '../../api/client'
import './binaryToggle.css'

/**
 * 字块图 + 「二值 / 灰度」切换。
 *
 * **缺省显示二值**（用户 2026-09-16）：最后进字形库的一定是二值的，审阅时看到的
 * 就该是库里那个形，灰度会干扰判断。点一下切回灰度看扫描原样——同一个坐标两套图。
 *
 * 服务端 `?src=bin` 用 `char_index` 的 `bbox_page` 从整页二值副本上重裁
 * （`utils/binarized.py`）；副本没生成时**自动退回灰度**，不报错、不空图。
 *
 * ⚠️ `withWorkspace` 不能省：`<img src>` 发不出自定义请求头，工作区只能走查询串，
 * 不带的话服务端按默认工作区找不到这本书的 cache，直接 500。
 *
 * 复用点：Step7 定字裁决卡、异体组视图、夹注卡——凡是「给人看一个字块让他判」
 * 的地方都该用这个，别各写一份（各写一份的结果就是有的地方看二值、有的看灰度，
 * 人对不上号）。
 */
export function BinaryToggleImage({ src, alt, defaultBin = true, showToggle = true, extra }: {
  /** 字块图 URL，形如 `/api/cache/<book>/char_patch/<key>.png`（不带 query） */
  src: string
  alt?: string
  /** 缺省看二值还是灰度。只在「就是要看扫描原样」的场合传 false */
  defaultBin?: boolean
  /** 关掉切换按钮（缩略图列表等放不下按钮的地方） */
  showToggle?: boolean
  /** 按钮行里再塞几个别的按钮（如「看原图」） */
  extra?: React.ReactNode
}) {
  const [bin, setBin] = useState(defaultBin)
  const url = withWorkspace(src + (bin ? (src.includes('?') ? '&' : '?') + 'src=bin' : ''))
  return (
    <div className="bti">
      <img src={url} alt={alt ?? ''} loading="lazy" />
      {(showToggle || extra) && (
        <div className="bti-btns">
          {showToggle && (
            <button className="bti-btn" onClick={(e) => { e.stopPropagation(); setBin(!bin) }}
                    title="二值 = 进库那张（整页 Sauvola 二值副本）；灰度 = 扫描原样">
              {bin ? '看灰度' : '看二值'}
            </button>
          )}
          {extra}
        </div>
      )}
    </div>
  )
}
