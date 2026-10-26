/** 图表共享工具：颜色盘、字节格式化、数据项类型 */

export interface ChartItem {
  name: string
  bytes: number
}

export const CHART_COLORS = [
  '#38bdf8',
  '#22d3ee',
  '#34d399',
  '#a3e635',
  '#facc15',
  '#fb923c',
  '#f87171',
  '#f472b6',
  '#a78bfa',
  '#818cf8',
]

export function humanSize(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  for (const unit of units) {
    if (value < 1024) {
      return unit === 'B' ? `${Math.round(value)} B` : `${value.toFixed(1)} ${unit}`
    }
    value /= 1024
  }
  return `${value.toFixed(1)} PB`
}
