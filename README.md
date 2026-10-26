# CCLEAR — 透明、可控的 C 盘清理 AI 助手

[![CI](https://github.com/OneforMe98/cclear/actions/workflows/ci.yml/badge.svg)](https://github.com/OneforMe98/cclear/actions/workflows/ci.yml)

一个网页版 Agent：**先分析、后建议，删除前必须经你确认，文件进回收站随时可恢复**，绝不偷偷动你的文件。

- 详细设计：[docs/项目设计文档.md](docs/项目设计文档.md)
- 开发进度与踩坑记录：[docs/开发进度.md](docs/开发进度.md)
- 未来演进规划：[docs/演进路线.md](docs/演进路线.md)

---

## 它能做什么

用聊天的方式管理 C 盘空间：

- "看看我用户目录下哪个文件夹最占空间" → 扫描并给出占用排行（带图表）
- "盘点一下有哪些垃圾可以清理" → 检查临时文件、缓存、回收站、Windows.old 等
- "把 xxx 删掉" → **弹出确认卡片**，你点"确认"才真正删除，且是**移入回收站**（可恢复）
- "以后 500MB 以上的文件才提醒我" → **记住这条长期偏好**，下次开新对话依然有效（侧栏可查看、可删除）

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 19 + TypeScript + Vite + recharts（图表） |
| 后端 | Python + FastAPI（SSE 流式） |
| Agent | LangGraph（模型↔工具循环）+ LangChain + DeepSeek |
| 记忆 | **两层**：① 对话记忆（checkpointer + SQLite，按 `thread_id`，换会话看不见）；② 用户画像（SQLite 键值 + 内存缓存，按 `user_id`，跨会话注入 System Prompt） |
| 上下文管理 | 记忆压缩：旧轮次剪枝（只留问题+结论）+ 工具输出限长；**只压缩"发给模型的视图"，存档始终完整** |
| 安全 | 工具白名单/黑名单、数量上限、`interrupt` 人工确认（human-in-the-loop） |

---

## 架构一览

```
浏览器 (React)
   │  SSE 流：delta / tool / tool_result / confirm / ping / [DONE]
   ▼
FastAPI (main.py)  ── HTTP 层：协议契约、会话、心跳、确认接口
   │
   ▼
LangGraph 图 (agent.py)  ── Agent 大脑：模型思考 ↔ 工具执行的循环
   │                          │
   │                          └─ checkpointer → SQLite（记忆/暂停恢复）
   ▼
工具集 (tools.py)  ── scan / find / detect_junk / delete(需确认)
```

---

## 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- 一个 [DeepSeek](https://platform.deepseek.com) API Key

### 方式一：一键启动（Windows，推荐）

在项目根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

脚本会自动：检查/创建 `.env` → 装依赖（首次）→ 起后端(8000) 和前端(5173) → 打开浏览器。

### 方式二：手动启动

**1. 配置后端环境变量**

```bash
# 把 backend/.env.example 复制为 backend/.env，填入你的 DeepSeek API Key
```

**2. 启动后端**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**3. 启动前端**

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。

---

## 环境变量（backend/.env）

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | ✅ | — | DeepSeek 密钥。缺失时服务能起，但聊天接口会提示"未配置" |
| `DEEPSEEK_BASE_URL` | | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `MODEL_NAME` | | `deepseek-chat` | 模型名（可换 `deepseek-reasoner`） |
| `MODEL_TEMPERATURE` | | `0.3` | 采样温度（0~1，越低越稳定保守） |
| `AGENT_MAX_STEPS` | | `12` | Agent 单次任务最大步数（防失控） |
| `CHECKPOINT_DB` | | `backend/data/cclear.db` | 对话记忆数据库路径 |
| `PROFILE_DB` | | `backend/data/profile.db` | 用户画像数据库路径 |
| `PROFILE_USER_ID` | | `local` | 当前用户标识（单机自用固定 local；多用户时从认证信息取） |
| `COMPACT_KEEP_TURNS` | | `4` | 上下文压缩：完整保留最近几轮（更早的只留问题+结论） |
| `COMPACT_MAX_TOOL_CHARS` | | `1500` | 单条工具输出字符上限（超过截断） |
| `COMPACT_ENABLED` | | `1` | 压缩开关（设 0 可对比关闭后的行为） |
| `HEARTBEAT_SECONDS` | | `10` | SSE 心跳间隔（秒） |

> ⚠️ `.env` 含密钥，已被 `.gitignore` 排除，**切勿提交**。想清空所有对话历史，停后端后删除 `backend/data/` 目录即可（会同时清空用户画像）。

---

## 运行测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest
```

覆盖工具安全校验（白名单/黑名单/数量上限/确认与否的删除行为）与 API 契约。删除类测试全程使用临时目录 + monkeypatch，**不会动你的真实文件**。

---

## 目录结构

```
CCLEAR/
├─ backend/
│  ├─ app/
│  │  ├─ config.py     # 配置与密钥加载
│  │  ├─ agent.py      # LangGraph 图 + checkpointer + System Prompt（含画像注入）
│  │  ├─ profile.py    # 用户画像：跨会话长期偏好（SQLite + 内存缓存）
│  │  ├─ compact.py    # 记忆压缩：旧轮次剪枝 + 工具输出限长
│  │  ├─ tools.py      # 六个工具 + 安全校验
│  │  └─ main.py       # FastAPI + SSE + 确认接口 / 画像接口
│  ├─ tests/           # pytest 测试
│  └─ data/            # 运行时生成：cclear.db（对话记忆）、profile.db（用户画像）
├─ frontend/
│  └─ src/             # React 前端
├─ docs/               # 设计文档 + 开发进度
└─ start.ps1           # Windows 一键启动
```

---

## 关于"部署"的说明

这是一个**操作本机文件系统**的工具（扫描 C 盘、调用 Windows 回收站），因此它的"部署"形态和普通 Web 应用不同：

- **推荐形态**：在用户自己的 Windows 机器上本地运行（如上"快速开始"）。这是它能真正扫描你 C 盘、把文件送进**你自己的回收站**的唯一方式。
- **不建议放进 Linux 容器**：Docker 容器是隔离的 Linux 环境，看不到宿主的 `C:\`，`send2trash` 也只会操作容器内的"回收站"，与产品目的相悖。
- 若将来要多人使用，正确方向是：后端服务化 + 每个客户端运行一个"本地文件操作代理"，而不是把扫描逻辑搬进服务器。这一点已记入演进规划。

---

## 安全设计（为什么可以放心用）

1. **只读分析**：扫描工具只统计大小，绝不修改文件
2. **三层删除校验**：存在性 → 白名单（仅用户主目录/临时目录）→ 黑名单（系统目录、白名单根本身）+ 数量上限
3. **人工确认**：删除前 Agent 暂停，你在卡片上点"确认"才执行
4. **可恢复**：删除 = 移入回收站，不是永久删除
5. **自动化测试守护**：以上规则都有测试覆盖，改动后一眼可验

---

## 已知限制

- Agent 单次任务步数上限 12（防止死循环 / 失控）
- 对话记忆与用户画像都存本地 SQLite，单机自用；多用户并发需换服务端存储
- 用户画像由模型自行判断该记什么（侧栏可见、可手动删除），暂不记录变更历史
- 未接入 LangSmith（云端链路追踪）与 LangGraph Studio（图形化调试）
