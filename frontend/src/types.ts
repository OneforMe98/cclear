export type Role = 'user' | 'assistant'

export interface ChatMessage {
  role: Role
  content: string
  /** 消息时间（ISO 8601）。历史消息由后端提供，实时消息由前端生成 */
  ts?: string
}
