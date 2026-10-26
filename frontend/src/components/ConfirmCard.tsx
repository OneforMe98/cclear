import type { ConfirmPayload } from '../api'

interface Props {
  payload: ConfirmPayload
  disabled: boolean
  onDecide: (approved: boolean) => void
}

export default function ConfirmCard({ payload, disabled, onDecide }: Props) {
  const paths = payload.paths ?? []
  const rejected = payload.rejected ?? []

  return (
    <div className="confirm-card">
      <div className="confirm-header">
        <span className="confirm-title">需要你确认：删除以下 {paths.length} 项</span>
        <span className="confirm-sub">删除后会进入回收站，可随时恢复</span>
      </div>
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
