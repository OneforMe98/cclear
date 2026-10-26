"""集中管理配置：所有"环境和密钥"相关的值都从这里读。

敏感信息（比如 API Key）写在 backend/.env 文件里，不进代码、不进 git。
.env 文件不存在或没填时，程序也能启动，只是会给出"未配置"的提示。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 固定放在 backend/ 目录下（本文件是 backend/app/config.py，向上两级）
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_FILE)

# DeepSeek 的 API Key，去 https://platform.deepseek.com 创建
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# DeepSeek 提供 OpenAI 兼容接口，所以 base_url 填它的地址即可
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# 模型名：deepseek-chat（日常对话）；想体验"推理模型"可以改成 deepseek-reasoner
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")

# 采样温度：越低越稳定保守，越高越发散。清理建议类任务适合偏低。
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.3"))

# Agent 单次任务的最大步数（模型思考 + 调工具都算一步），防止失控死循环
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "12"))

# 对话记忆（checkpointer 存档）的 SQLite 数据库文件。
# 存在 backend/ 目录下的 data/ 里，重启后端历史不丢。
# 想重置所有对话：停掉后端，删除这个文件即可。
CHECKPOINT_DB = Path(
    os.getenv("CHECKPOINT_DB", str(Path(__file__).resolve().parents[1] / "data" / "cclear.db"))
)

# 用户长期画像（跨会话偏好）的存储位置。与对话存档分开存：
# 一个是"这次聊了什么"（按会话），一个是"这个人什么样"（按用户），生命周期不同。
PROFILE_DB = Path(
    os.getenv("PROFILE_DB", str(Path(__file__).resolve().parents[1] / "data" / "profile.db"))
)

# 当前用户 ID。单机自用固定为 local；将来做多用户时从认证信息里取。
PROFILE_USER_ID = os.getenv("PROFILE_USER_ID", "local")

# ---- 上下文压缩（记忆压缩）----
# 每次"模型思考"时，只把最近 N 轮完整历史发给模型；更早的轮次被压缩成一行摘要。
# 数字越大越"记得清楚"，但 token 越贵。4 轮对清理类任务足够（通常 1-3 轮就问完）。
COMPACT_KEEP_TURNS = int(os.getenv("COMPACT_KEEP_TURNS", "4"))

# 单条工具输出的字符上限。超过就截断并注释说明——防止一次 find_large_files
# 把 100 条长路径（实测 1 万字符）直接灌进上下文。
COMPACT_MAX_TOOL_CHARS = int(os.getenv("COMPACT_MAX_TOOL_CHARS", "1500"))

# 压缩开关：设为 0 可关闭（用于对比"压缩前/后"的行为差异）
COMPACT_ENABLED = os.getenv("COMPACT_ENABLED", "1").strip() not in ("0", "false", "False")

# ---- LangSmith 链路追踪（可选，默认关闭）----
# 打开后，每次 Agent 运行的全过程（每步 LLM 调用、工具执行、token 数、耗时）
# 会上传到 https://smith.langchain.com 供可视化查看。
#
# ⚠️ 隐私提醒：上报内容包含完整的对话文本与工具输出——也就是"你问了什么"
# 和"扫描到的文件路径"。这是把本机信息发到云端，必须由你明确同意才开启。
#
# 三个都配齐才生效：开关 + API Key + 项目名。
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "0").strip().lower() in ("1", "true")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "").strip()
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "cclear").strip()

# 只有在"开关打开 + Key 已填"时才真正启用，避免只填一半导致运行时报错。
LANGSMITH_ENABLED = LANGSMITH_TRACING and bool(LANGSMITH_API_KEY)

if LANGSMITH_ENABLED:
    # LangChain / LangGraph 通过环境变量识别追踪配置（在 import 时就读取），
    # 所以这里必须写回 os.environ，光有 Python 变量不够。
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # 旧版变量名，兼容旧版 SDK
    os.environ["LANGSMITH_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = LANGSMITH_PROJECT
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
else:
    # 显式关掉：避免"上次开过、这次忘了关"导致悄悄上报
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
