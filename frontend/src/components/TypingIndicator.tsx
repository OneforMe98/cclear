import { useEffect, useState } from 'react'
import { toolLabel } from '../toolLabels'

interface Props {
  /** 本轮请求开始的时间戳（毫秒）。用来算"已经等了多久"。 */
  startedAt: number
  /** 当前正在执行的工具名；为空表示模型正在思考/生成。 */
  runningTool?: string
}

const TICK_MS = 200

/** 根据已等待时长给一句更具体的说明，避免用户以为卡死 */
function statusText(seconds: number, runningTool?: string): string {
  if (runningTool) {
    const label = toolLabel(runningTool)
    if (seconds >= 8) return `${label}中，大目录会比较慢…`
    return `${label}中…`
  }
  if (seconds >= 15) return '正在整理结果…'
  if (seconds >= 6) return '正在分析…'
  return '思考中'
}

export default function TypingIndicator({ startedAt, runningTool }: Props) {
  // 只存"现在几点"，已等待时长在渲染时算出来——避免在 effect 里 setState 触发额外渲染
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))

  return (
    <div className="msg-row msg-row-assistant">
      <div className="msg-avatar">C</div>
      <div className="msg-bubble msg-bubble-assistant typing">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
        <span className="typing-status">
          {statusText(seconds, runningTool)}
          {seconds >= 3 && <span className="typing-elapsed"> {seconds}s</span>}
        </span>
      </div>
    </div>
  )
}
