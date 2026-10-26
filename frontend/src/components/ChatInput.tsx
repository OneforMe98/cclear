import { useRef, useState } from 'react'

interface Props {
  disabled: boolean
  onSend: (text: string) => void
}

export default function ChatInput({ disabled, onSend }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const resize = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  const submit = () => {
    if (disabled || !value.trim()) return
    onSend(value)
    setValue('')
    requestAnimationFrame(() => {
      const el = textareaRef.current
      if (el) {
        el.style.height = 'auto'
        el.focus()
      }
    })
  }

  return (
    <div className={`composer ${disabled ? 'composer-disabled' : ''}`}>
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        placeholder="例如：帮我看看 C 盘哪里最占空间…"
        onChange={(e) => {
          setValue(e.target.value)
          resize()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button
        className="send-btn"
        onClick={submit}
        disabled={disabled || !value.trim()}
        aria-label="发送"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19V5" />
          <path d="m5 12 7-7 7 7" />
        </svg>
      </button>
    </div>
  )
}
