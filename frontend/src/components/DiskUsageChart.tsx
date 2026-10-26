import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CHART_COLORS, humanSize } from '../charts'
import type { ChartItem } from '../charts'

interface Props {
  title: string
  totalBytes?: number
  items: ChartItem[]
}

/** 磁盘占用条形图：数据来自后端工具的结构化结果（artifact） */
export default function DiskUsageChart({ title, totalBytes, items }: Props) {
  const data = items.slice(0, 10)
  if (data.length === 0) return null

  const height = data.length * 34 + 24

  return (
    <div className="chart-card">
      <div className="chart-header">
        <span className="chart-title">{title}</span>
        {totalBytes != null && totalBytes > 0 && (
          <span className="chart-sub">总计 {humanSize(totalBytes)}</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 64, bottom: 4, left: 8 }}
          barSize={16}
        >
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={120}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
            formatter={(value) => humanSize(Number(value))}
            contentStyle={{
              background: '#0f172a',
              border: '1px solid rgba(148, 163, 184, 0.25)',
              borderRadius: 10,
              color: '#e2e8f0',
              fontSize: 12.5,
            }}
          />
          <Bar dataKey="bytes" radius={[6, 6, 6, 6]}>
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
            <LabelList
              dataKey="bytes"
              position="right"
              formatter={(value: unknown) => humanSize(Number(value))}
              style={{ fill: '#94a3b8', fontSize: 11 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
