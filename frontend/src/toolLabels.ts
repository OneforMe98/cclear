/** 工具名 → 中文短语。时间线和等待提示共用，避免两处各写一份。 */
export const TOOL_LABELS: Record<string, string> = {
  scan_directory_size: '扫描目录占用',
  find_large_files: '搜索大文件',
  detect_junk_dirs: '盘点垃圾目录',
  delete_to_recycle_bin: '执行删除',
  remember_preference: '记住偏好',
  forget_preference: '忘记偏好',
}

export const toolLabel = (name: string) => TOOL_LABELS[name] ?? name
