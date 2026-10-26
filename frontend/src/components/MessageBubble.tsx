import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../types'

interface Props {
  message: ChatMessage
}

/** 把 ISO 时间转成本地"HH:MM"；时间无效就返回空串（不显示） */
function formatTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user'
  const time = formatTime(message.ts)

  return (
    <div className={`msg-row ${isUser ? 'msg-row-user' : 'msg-row-assistant'}`}>
      {!isUser && <div className="msg-avatar">C</div>}
      <div className="msg-stack">
        <div className={`msg-bubble ${isUser ? 'msg-bubble-user' : 'msg-bubble-assistant'}`}>
          {isUser ? (
            <p className="msg-plain">{message.content}</p>
          ) : (
            <div className="msg-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>
        {time && <span className={`msg-time ${isUser ? 'msg-time-user' : ''}`}>{time}</span>}
      </div>
    </div>
  )
}
