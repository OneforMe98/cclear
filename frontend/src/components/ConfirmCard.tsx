import type { ConfirmPayload } from '../api'

interface Props {
  payload: ConfirmPayload
  disabled: boolean
  onDecide: (approved: boolean) => void
}

/** 超过这个体积就在确认卡片上高亮警告（5 GB） */
const BIG_DELETE_BYTES = 5 * 1024 ** 3

export default function ConfirmCard({ payload, disabled, onDecide }: Props) {
  const paths = payload.paths ?? []
  const rejected = payload.rejected ?? []
  const hasSize = payload.total_bytes != null && payload.total_bytes > 0
  const isBig = hasSize && payload.total_bytes! >= BIG_DELETE_BYTES

  return (
    <div className={`confirm-card${isBig ? ' confirm-card-warn' : ''}`}>
      <div className="confirm-header">
        <span className="confirm-title">需要你确认：删除以下 {paths.length} 项</span>
        <span className="confirm-sub">删除后会进入回收站，可随时恢复</span>
      </div>

      {/* 体积和文件数：让"删 3 项"背后到底是 200MB 还是 20GB 一目了然 */}
      {hasSize && (
        <div className={`confirm-size${isBig ? ' big' : ''}`}>
          合计约 <strong>{payload.total_size}</strong>
          {payload.file_count ? ` · ${payload.file_count.toLocaleString()} 个文件` : ''}
          {isBig && <span className="confirm-size-warn">　⚠ 体积较大，请再确认一遍</span>}
        </div>
      )}

      <ul className="confirm-list">
        {paths.map((p) => (
          <li key={p} title={p}>
            {p}
          </li>
        ))}
      </ul>
      {rejected.length > 0 && (
        <p className="confirm-rejected">另有 {rejected.length} 项未通过安全校验，已自动跳过</p>
      )}
      <div className="confirm-actions">
        <button className="confirm-btn danger" disabled={disabled} onClick={() => onDecide(true)}>
          确认删除（移到回收站）
        </button>
        <button className="confirm-btn" disabled={disabled} onClick={() => onDecide(false)}>
          取消
        </button>
      </div>
    </div>
  )
}
