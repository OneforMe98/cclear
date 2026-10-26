import { useEffect, useState } from 'react'
import { deleteProfileEntry, fetchProfile } from '../api'
import type { ProfileEntry } from '../api'

interface Props {
  /** 每次对话结束（或工具跑完）时递增，用来触发重新拉取画像 */
  refreshKey: number
}

/**
 * 侧栏里的"用户画像"卡片：展示 AI 跨会话记住的长期偏好。
 * 每条都可以手动删除——记忆必须可见、可撤回，否则就是不透明。
 */
export default function ProfilePanel({ refreshKey }: Props) {
  const [entries, setEntries] = useState<ProfileEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchProfile()
      .then((res) => {
        if (!cancelled) setEntries(res.entries)
      })
      .catch(() => {
        // 后端未启动时不打扰用户，保持空列表
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  const remove = async (key: string) => {
    setEntries((prev) => prev.filter((e) => e.key !== key))
    try {
      await deleteProfileEntry(key)
    } catch {
      // 删除失败就重新拉一次，保证界面与服务端一致
      fetchProfile()
        .then((res) => setEntries(res.entries))
        .catch(() => {})
    }
  }

  return (
    <div className="profile-block">
      <div className="profile-title">
        <span>AI 记住的偏好</span>
        <span className="profile-count">{entries.length}</span>
      </div>
      {entries.length === 0 ? (
        <p className="profile-empty">
          {loading ? '加载中…' : '还没有记住任何偏好。试试对它说"以后 500MB 以上的文件才问我"。'}
        </p>
      ) : (
        <ul className="profile-list">
          {entries.map((e) => (
            <li key={e.key} className="profile-item">
              <div className="profile-item-main">
                <span className="profile-key">{e.key}</span>
                <span className="profile-value">{e.value}</span>
              </div>
              <button
                className="profile-del"
                title="让 AI 忘记这条"
                onClick={() => remove(e.key)}
                aria-label={`删除偏好 ${e.key}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
