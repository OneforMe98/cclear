import { toolLabel } from '../toolLabels'

interface ToolActivity {
  name: string
  done: boolean
  chars?: number
}

interface Props {
  items: ToolActivity[]
}

/** 工具调用时间线：把 Agent 的每一步"动作"展示给用户，让过程透明可见 */
export default function ToolTimeline({ items }: Props) {
  if (items.length === 0) return null

  return (
    <div className="tool-timeline">
      {items.map((item, i) => (
        <span key={i} className={`tool-chip ${item.done ? 'done' : 'running'}`}>
          <span className="tool-dot" />
          {toolLabel(item.name)}
          {item.done ? (
            item.chars != null ? ` · 完成（${item.chars} 字符）` : ' · 完成'
          ) : (
            ' 进行中…'
          )}
        </span>
      ))}
    </div>
  )
}
