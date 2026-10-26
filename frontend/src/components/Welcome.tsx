interface Props {
  onPick: (text: string) => void
}

const SUGGESTIONS = [
  { title: 'C 盘哪里最占空间？', desc: '让 Agent 分析目录占用排行' },
  { title: '常见的系统垃圾在哪？', desc: '临时文件、缓存、回收站等位置盘点' },
  { title: '能释放多少空间？', desc: '生成只读的清理建议报告' },
]

export default function Welcome({ onPick }: Props) {
  return (
    <div className="welcome">
      <div className="welcome-mark">C</div>
      <h1 className="welcome-title">CCLEAR</h1>
      <p className="welcome-sub">
        透明、可控的 C 盘清理助手。先分析，后建议，绝不偷偷动你的文件。
      </p>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s.title} className="suggestion-card" onClick={() => onPick(s.title)}>
            <span className="suggestion-title">{s.title}</span>
            <span className="suggestion-desc">{s.desc}</span>
          </button>
        ))}
      </div>
      <p className="welcome-note">当前为 Phase 2：已接入 DeepSeek 真实对话，磁盘扫描能力将在后续阶段接入</p>
    </div>
  )
}
