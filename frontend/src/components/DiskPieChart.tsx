import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { CHART_COLORS, humanSize } from '../charts'
import type { ChartItem } from '../charts'

interface Props {
  items: ChartItem[]
}

/** 磁盘占用饼状图：只看占比最高的前 8 项，其余合并为"其他" */
export default function DiskPieChart({ items }: Props) {
  if (items.length === 0) return null

  const top = items.slice(0, 8)
  const restSum = items.slice(8).reduce((sum, it) => sum + it.bytes, 0)
  const data = restSum > 0 ? [...top, { name: '其他', bytes: restSum }] : top
  const total = data.reduce((sum, it) => sum + it.bytes, 0)

  return (
    <div className="chart-card pie-card">
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={data}
            dataKey="bytes"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={46}
            outerRadius={78}
            paddingAngle={2}
            stroke="none"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, name) => [
              `${humanSize(Number(value))}${total ? `（${((Number(value) / total) * 100).toFixed(1)}%）` : ''}`,
              String(name),
            ]}
            contentStyle={{
              background: '#0f172a',
              border: '1px solid rgba(148, 163, 184, 0.25)',
              borderRadius: 10,
              color: '#e2e8f0',
              fontSize: 12.5,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <ul className="pie-legend">
        {data.map((it, i) => (
          <li key={i}>
            <span className="pie-dot" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
            <span className="pie-name" title={it.name}>{it.name}</span>
            <span className="pie-value">{humanSize(it.bytes)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
