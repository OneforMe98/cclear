import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import './App.css'
import ChatInput from './components/ChatInput'
import ConfirmCard from './components/ConfirmCard'
import MessageBubble from './components/MessageBubble'
import ProfilePanel from './components/ProfilePanel'
import ToolTimeline from './components/ToolTimeline'
import TypingIndicator from './components/TypingIndicator'
import Welcome from './components/Welcome'
import { confirmAction, fetchHistory, streamMessage } from './api'
import type { ConfirmPayload, DirSizesArtifact, JunkArtifact, StreamHandlers, ToolResultPayload } from './api'
import type { ChartItem } from './charts'
import type { ChatMessage } from './types'

// recharts 体积较大：图表组件懒加载，让首屏只加载聊天必需的代码。
// 图表只有在真正要画时才从服务器取这块 JS（Vite 会自动拆出独立 chunk）。
const DiskPieChart = lazy(() => import('./components/DiskPieChart'))
const DiskUsageChart = lazy(() => import('./components/DiskUsageChart'))

interface ToolActivity {
  name: string
  done: boolean
  chars?: number
}

/** 会改动画像的工具：跑完后要刷新侧栏的"AI 记住的偏好" */
const PROFILE_TOOL_NAMES = new Set(['remember_preference', 'forget_preference'])

interface ChartCard {
  /** 卡片来源：目录扫描 or 垃圾盘点。用于"同类结果替换旧卡片"而不是无限堆叠 */
  kind: 'dir_sizes' | 'junk'
  title: string
  totalBytes?: number
  items: ChartItem[]
}

/** 把工具的结构化结果转成图表卡片；实时流与历史恢复共用这一套映射 */
function artifactToCard(artifact: DirSizesArtifact | JunkArtifact): ChartCard | null {
  if (artifact.kind === 'dir_sizes' && artifact.entries.length > 0) {
    return {
      kind: 'dir_sizes',
      title: '目录占用排行',
      totalBytes: artifact.total_bytes,
      items: artifact.entries.map((e) => ({ name: e.name, bytes: e.bytes })),
    }
  }
  if (artifact.kind === 'junk' && artifact.entries.length > 0) {
    return {
      kind: 'junk',
      title: '垃圾目录盘点',
      totalBytes: artifact.total_bytes,
      items: artifact.entries.map((e) => ({ name: e.label, bytes: e.bytes })),
    }
  }
  return null
}

/**
 * 把新卡片并入已有列表：同 kind 的旧卡片被替换（保留位置），不同 kind 追加。
 *
 * 为什么不是简单 append：用户可能反复扫描同一个目录，append 会让右侧堆出一堆
 * 几乎相同的图；为什么也不是整体清空：右侧面板的定位是"扫描结果常驻"，
 * 问一句别的问题就把图清掉，等于让用户丢失刚看到的数据。
 */
function upsertCards(prev: ChartCard[], incoming: ChartCard[]): ChartCard[] {
  const next = [...prev]
  for (const card of incoming) {
    const idx = next.findIndex((c) => c.kind === card.kind)
    if (idx >= 0) next[idx] = card
    else next.push(card)
  }
  return next
}

const THREAD_KEY = 'cclear_thread_id'

/** 会话 ID 持久化在 localStorage：刷新页面还是同一个对话（记忆在服务端） */
function loadThreadId(): string {
  const saved = localStorage.getItem(THREAD_KEY)
  if (saved) return saved
  const id = crypto.randomUUID()
  localStorage.setItem(THREAD_KEY, id)
  return id
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  // 本轮请求的开始时间（毫秒）。等待提示用它算"已经等了多久"。
  const [startedAt, setStartedAt] = useState(0)
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmPayload | null>(null)
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([])
  const [chartCards, setChartCards] = useState<ChartCard[]>([])
  // 画像版本号：每次"记住/忘记偏好"后 +1，用来触发侧栏重新拉取
  const [profileVersion, setProfileVersion] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  // 会话 ID：存在 localStorage，刷新后继续同一个对话
  const threadIdRef = useRef<string>(loadThreadId())
  // 当前正在跑的工具（最后一个未完成的）。等待提示据此显示"正在扫描目录占用中…"
  const runningTool = toolActivity.findLast((t) => !t.done)?.name
  // 本轮是否已经有可见文字：决定"等待提示"是占用占位气泡，还是另起一行
  const lastMsg = messages[messages.length - 1]
  const hasVisibleAnswer = lastMsg?.role === 'assistant' && lastMsg.content.trim() !== ''

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loading, pendingConfirm, toolActivity, chartCards])

  // 打开页面时从服务端恢复这个会话的历史与图表（对话记忆）
  useEffect(() => {
    let cancelled = false
    fetchHistory(threadIdRef.current)
      .then((history) => {
        if (cancelled) return
        if (history.messages.length > 0) setMessages(history.messages)
        // 恢复图表卡片：历史里可能有多批扫描结果，同 kind 只保留最新一份
        const cards = (history.artifacts ?? [])
          .map((a) => artifactToCard(a))
          .filter((c): c is ChartCard => c !== null)
        if (cards.length > 0) setChartCards((prev) => upsertCards(prev, cards))
        // 刷新时如果正停在"等待删除确认"，把确认卡片也恢复出来
        if (history.pending_confirm) setPendingConfirm(history.pending_confirm)
      })
      .catch(() => {
        // 历史恢复失败不影响正常使用（比如后端还没启动）
      })
    return () => {
      cancelled = true
    }
  }, [])

  const appendToLast = (chunk: string) => {
    setMessages((prev) => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      copy[copy.length - 1] = { ...last, content: last.content + chunk }
      return copy
    })
  }

  const showError = (err: unknown) => {
    const base = err instanceof Error ? err.message : '未知错误'
    const offlineHint = navigator.onLine ? '' : '（检测到当前设备已离线，请恢复网络后重新发送。）'
    const detail = `${base}${offlineHint}`
    setMessages((prev) => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      const prefix = last && last.content ? '\n\n' : ''
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = {
          ...last,
          content: `${last.content}${prefix}请求失败：${detail}\n\n（若提示连接失败，请确认后端已启动：进入 \`backend\` 目录运行 \`uvicorn app.main:app --reload\`。）`,
        }
      } else {
        copy.push({
          role: 'assistant',
          content: `请求失败：${detail}\n\n（若提示连接失败，请确认后端已启动。）`,
        })
      }
      return copy
    })
  }

  const handlers: StreamHandlers = {
    onDelta: appendToLast,
    onConfirm: (payload) => setPendingConfirm(payload),
    onTool: (name) => setToolActivity((prev) => [...prev, { name, done: false }]),
    onToolResult: (result: ToolResultPayload) => {
      // 时间线：把最近一个同名且"进行中"的条目标记为完成
      setToolActivity((prev) => {
        const copy = [...prev]
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].name === result.name && !copy[i].done) {
            copy[i] = { ...copy[i], done: true, chars: result.chars }
            break
          }
        }
        return copy
      })

      // 画像变了（记住/忘记偏好）→ 让侧栏重新拉取，让用户立刻看到 AI 记住了什么
      if (PROFILE_TOOL_NAMES.has(result.name)) {
        setProfileVersion((v) => v + 1)
      }

      // 图表卡片：工具带了结构化结果（artifact）时，渲染成图表
      const artifact = result.artifact
      if (artifact) {
        const card = artifactToCard(artifact)
        if (card) setChartCards((prev) => upsertCards(prev, [card]))
      }
    },
  }

  const handleSend = async (text: string) => {
    const content = text.trim()
    if (!content || loading || pendingConfirm) return

    const now = new Date().toISOString()
    const userMsg: ChatMessage = { role: 'user', content, ts: now }

    // 新一轮对话：只清空"本轮工具时间线"。
    // 图表卡片不清空——右侧面板定位是"扫描结果常驻"，问一句别的问题不该让图消失。
    setToolActivity([])
    // 本地先显示用户消息 + 空助手占位；历史记忆由服务端负责，只发这一句新消息
    setMessages((prev) => [...prev, userMsg, { role: 'assistant', content: '', ts: now }])
    setStartedAt(Date.now())
    setLoading(true)

    try {
      await streamMessage(threadIdRef.current, content, handlers)
    } catch (err) {
      showError(err)
    } finally {
      setLoading(false)
    }
  }

  const startNewChat = () => {
    if (loading || pendingConfirm) return
    const id = crypto.randomUUID()
    localStorage.setItem(THREAD_KEY, id)
    threadIdRef.current = id
    setMessages([])
    setToolActivity([])
    setChartCards([])
    setPendingConfirm(null)
  }

  const respondConfirm = async (approved: boolean) => {
    if (!pendingConfirm || loading) return
    setPendingConfirm(null)

    // 恢复后的 Agent 会继续生成回答，同样先放空占位消息接流
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', ts: new Date().toISOString() },
    ])
    setStartedAt(Date.now())
    setLoading(true)

    try {
      await confirmAction(threadIdRef.current, approved, handlers)
    } catch (err) {
      showError(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">C</div>
          <div className="brand-text">
            <span className="brand-name">CCLEAR</span>
            <span className="brand-slogan">让 C 盘干净透明的 AI 助手</span>
          </div>
        </div>
        <div className="header-actions">
          <button className="new-chat-btn" onClick={startNewChat} disabled={loading || !!pendingConfirm}>
            新对话
          </button>
        </div>
      </header>

      <div className="workspace">
        <main className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 ? (
            <Welcome onPick={handleSend} />
          ) : (
            <div className="chat-list">
              {messages.map((m, i) => {
                // 注意用 trim：后端在"调用工具"时会先推两个换行，content 变成 "\n\n"，
                // 若用 === '' 判断，等待提示会在最需要它的扫描阶段消失。
                const isWaitingFirstChunk =
                  loading &&
                  i === messages.length - 1 &&
                  m.role === 'assistant' &&
                  m.content.trim() === ''
                return isWaitingFirstChunk ? (
                  <TypingIndicator
                    key={i}
                    startedAt={startedAt}
                    runningTool={runningTool}
                  />
                ) : (
                  <MessageBubble key={i} message={m} />
                )
              })}
              {/* 工具正在跑（如扫描大目录）：模型可能已经说了"我先扫一下…"，
                  此时占位气泡已被正文替换，需要额外一行提示显示进度与计时。
                  若占位气泡已在显示（本轮还没有任何文字），就不再重复。 */}
              {loading && runningTool && hasVisibleAnswer && (
                <TypingIndicator startedAt={startedAt} runningTool={runningTool} />
              )}
              {pendingConfirm && (
                <ConfirmCard payload={pendingConfirm} disabled={loading} onDecide={respondConfirm} />
              )}
            </div>
          )}
        </main>

        <aside className="insight-panel">
          <div className="insight-header">
            <span className="insight-title">磁盘洞察</span>
            <span className="insight-hint">扫描结果在此常驻</span>
          </div>
          <ToolTimeline items={toolActivity} />
          <ProfilePanel refreshKey={profileVersion} />
          <div className="insight-body">
            {chartCards.length === 0 ? (
              <div className="insight-empty">
                <div className="insight-empty-mark">📊</div>
                <p>还没有扫描数据</p>
                <p className="insight-empty-sub">让它"看看哪里最占空间"或"盘点垃圾目录"，图表会显示在这里</p>
              </div>
            ) : (
              chartCards.map((card) => (
                <div className="insight-group" key={card.kind}>
                  <Suspense fallback={<div className="chart-loading">图表加载中…</div>}>
                    <DiskPieChart items={card.items} />
                    <DiskUsageChart title={card.title} totalBytes={card.totalBytes} items={card.items} />
                  </Suspense>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>

      <footer className="composer-area">
        <ChatInput disabled={loading || !!pendingConfirm} onSend={handleSend} />
        <p className="composer-hint">
          Enter 发送 · Shift + Enter 换行 · 本地运行，数据不出本机
        </p>
      </footer>
    </div>
  )
}
