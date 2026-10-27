# CCLEAR — 透明、可控的 C 盘清理 AI 助手

[![CI](https://github.com/OneforMe98/cclear/actions/workflows/ci.yml/badge.svg)](https://github.com/OneforMe98/cclear/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-18+-339933?logo=node.js&logoColor=white)
![Tests](https://img.shields.io/badge/tests-74%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

> 一个网页版 Agent：**先分析、后建议，删除前必须经你确认，文件进回收站随时可恢复**，绝不偷偷动你的文件。

用聊天的方式管理 C 盘，但把"会不会误删"这件事，从"相信 AI"变成"看得见、控得住"。

- 📐 [架构与设计文档](docs/项目设计文档.md)
- 📓 [开发进度与踩坑记录](docs/开发进度.md)
- 🗺️ [未来演进规划](docs/演进路线.md)
- 🧰 [Git 与 CI 使用指南](docs/git与CI使用指南.md)

<!-- 截图占位：把文件放进 docs/images/ 后即可显示 -->
<!-- ![主界面](docs/images/demo-main.png) -->
<!-- ![删除确认](docs/images/demo-confirm.png) -->

---

## 为什么它和"一键清理软件"不一样

市面上的清理工具让你**相信它**。CCLEAR 让你**看见它**：

| 常见清理软件 | CCLEAR |
| --- | --- |
| 二进制，看不到它删了什么 | 全流程对话可见，工具调用实时展示 |
| "一键清理"，删完才知道 | **先扫描分析 → 给出建议 → 你点确认才删** |
| 永久删除，删错没救 | **只移入回收站**，随时可恢复 |
| 不知道它怎么判断的 | 结论必须基于真实扫描数据，模型被禁止编造 |

---

## 它能做什么

- **"看看我用户目录下哪个文件夹最占空间"** → 扫描并给出占用排行（带图表）
- **"盘点一下有哪些垃圾可以清理"** → 检查临时文件、缓存、回收站、Windows.old 等，估算可释放空间
- **"把 xxx 删掉"** → **弹出确认卡片**，显示**总体积与文件数**；超过 5 GB 卡片变红二次警告；你点"确认"才移入回收站
- **"以后 500MB 以上的文件才提醒我"** → **记住这条长期偏好**，下次开新对话依然有效（侧栏可查看、可逐条删除）

---

## 架构一览

```
浏览器 (React 19 + Vite)
   │  SSE 流：delta / tool / tool_result / confirm / ping / [DONE]
   ▼
FastAPI (main.py)  ── HTTP 层：协议契约、会话、心跳、确认接口、画像接口
   │
   ▼
LangGraph 图 (agent.py)  ── Agent 大脑：模型思考 ↔ 工具执行的循环
   │                          │
   │                          ├─ checkpointer → SQLite（会话记忆 / 暂停恢复）
   │                          └─ compact.py   → 记忆压缩（只改发给模型的视图）
   ▼
工具集 (tools.py)  ── scan / find / detect_junk / delete(需确认) / remember / forget
   │
   ▼
Windows 文件系统 & 回收站（send2trash）
```

### 一次删除请求的完整链路（安全是设计出来的，不是承诺出来的）

```
模型想删 → ① 存在性校验 → ② 白名单（仅用户目录/临时目录）
        → ③ 黑名单（系统目录、白名单根本身）→ ④ 数量上限 50
        → ⑤ 统计体积与文件数 → ⑥ interrupt 暂停整个图，等用户确认
        → ⑦ 用户点确认 → send2trash（进回收站，可恢复）
        任何一步不通过，都不会删除任何东西
```

---

## 技术栈

| 层 | 技术 | 选择理由 |
| --- | --- | --- |
| 前端 | React 19 + TypeScript + Vite + recharts | 类型安全 + 秒级 HMR；图表库轻量 |
| 后端 | Python + FastAPI（SSE 流式） | 原生 async；SSE 比 WebSocket 更适合单向推送 |
| Agent | LangGraph + LangChain + DeepSeek | 图结构天然表达"思考↔工具"循环；DeepSeek 国内直连、便宜、支持 Function Calling |
| 记忆 | SQLite（checkpointer）+ SQLite 键值 | 零依赖、单文件、重启不丢；单机自用无需数据库服务 |
| 可观测 | LangSmith（可选，默认关闭） | 看清每步 token/耗时/输入输出；默认关，防止对话内容悄悄上云 |

---

## 工程化亮点

这个项目不只是"能跑"，而是按可交付的工程标准做的：

| 亮点 | 说明 |
| --- | --- |
| **74 个自动化测试 + CI** | 每次 push 自动跑 pytest（后端）+ tsc/oxlint（前端），全绿才放心 |
| **三层删除防线** | 白名单 → 黑名单 → `interrupt` 人工确认，每一层都有测试守护 |
| **删除体积可视化** | 按"项"计数会骗人（1 个目录可能装几万文件），所以递归统计体积+文件数并高亮大体积 |
| **两层记忆 + 压缩** | 会话记忆（按 thread）与长期画像（按 user）分离；压缩只改"发给模型的视图"，**存档始终完整** |
| **System Prompt 外置** | 话术放 `app/prompts/system.md`，改文案不碰代码；缺失立即报错而非静默退化 |
| **可观测性** | 接入 LangSmith，可在网页或终端（`learn/07_langsmith_trace.py`）查看每次运行的全过程 |
| **测试不碰真实文件** | 删除类测试全程用 `tmp_path` + monkeypatch，绝不误删你电脑上的东西 |

---

## 关键设计取舍（为什么这么做 / 为什么不那么做）

> 这一节记录"看起来可以做，但故意没做"的决定——好的工程不止是加功能，更是克制地不加。

| 决策 | 选择 | 为什么 |
| --- | --- | --- |
| **要不要 Docker 部署** | ❌ 不做 | 这工具要扫描**宿主的 `C:\`**、调用**宿主回收站**。容器是隔离的 Linux，看不到宿主机，`send2trash` 只会操作容器内的假回收站——容器化与产品目的**根本矛盾** |
| **要不要 MCP 化** | ❌ 已实验并回滚 | MCP 的价值是"多客户端复用"。本项目只有一个本地调用方（自己的前端），解耦零收益，净增进程管理与编码成本 |
| **用户画像用向量库吗** | ❌ 不用 | 画像是结构化键值对（阈值、禁区），键值能精确命中、可读、可人工改。向量库适合"语义模糊检索"，那是另一个问题——不为高级而高级 |
| **删除上限按"项"还是按"体积"** | ✅ 两个都要 | 按项计数会造成"删 1 个大目录比删 10 个小文件安全"的错觉。项数管"操作复杂度"，体积管"真实风险" |
| **压缩会破坏存档吗** | ❌ 不会 | 压缩只作用于"发给模型的视图"，checkpointer 里的完整历史一个字不改——可回溯、可时间旅行 |
| **记忆要不要暴露给用户** | ✅ 必须暴露 | 侧栏"AI 记住的偏好"可查看、可逐条删。**记忆不透明 = 不可控**，是不可接受的信任问题 |
| **CI 用 Windows 还是 Linux** | ✅ Windows | 产品只跑 Windows（回收站 API、`C:\` 路径、系统目录白名单）。用 Linux 跑测试测的是另一套代码路径，等于自欺欺人 |

---

## 安全设计（为什么可以放心用）

1. **只读优先**：扫描工具只统计大小，绝不修改文件
2. **三层删除校验**：存在性 → 白名单 → 黑名单（+ 体积/文件数展示）
3. **人工确认（human-in-the-loop）**：删除前整个 Agent 图 `interrupt` 暂停，你点"确认"才继续
4. **可恢复**：删除 = 移入回收站，不是永久删除
5. **测试守护**：以上每条规则都有对应测试，改动后一眼可验
6. **隐私开关默认关**：LangSmith 追踪默认关闭，开启需同时配置开关+密钥，且启动时大声提示

---

## 快速开始

### 前置要求

- Python 3.10+ · Node.js 18+ · 一个 [DeepSeek](https://platform.deepseek.com) API Key

### 方式一：一键启动（Windows，推荐）

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

自动完成：检查/创建 `.env` → 装依赖（首次）→ 起后端(8000) + 前端(5173) → 打开浏览器。

### 方式二：手动启动

```bash
# 1. 配置密钥：复制 backend/.env.example 为 backend/.env，填入 DEEPSEEK_API_KEY

# 2. 后端
cd backend
python -m venv .venv
.venv\Scripts\activate              # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. 前端（另开一个终端）
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
| `COMPACT_KEEP_TURNS` | | `4` | 完整保留最近几轮（更早的只留问题+结论） |
| `COMPACT_MAX_TOOL_CHARS` | | `1500` | 单条工具输出字符上限 |
| `HEARTBEAT_SECONDS` | | `10` | SSE 心跳间隔（秒） |
| `LANGSMITH_TRACING` | | `0` | 链路追踪开关（`1` 开启，会把对话上报云端，默认关） |
| `LANGSMITH_API_KEY` | | — | LangSmith 密钥（开启追踪时需要） |
| `LANGSMITH_PROJECT` | | `cclear` | LangSmith 项目名 |

> ⚠️ `.env` 含密钥，已被 `.gitignore` 排除，**切勿提交**。想清空对话与画像，停后端后删除 `backend/data/` 目录即可。

---

## 运行测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest        # 74 passed
```

覆盖工具安全边界、记忆压缩不破坏数据、画像增删改查、API 契约、配置默认值、Prompt 加载。删除类测试全程用临时目录 + monkeypatch，**不会动你的真实文件**。

CI 在每次 push/PR 时自动运行（后端 pytest + 前端 tsc/oxlint），见 `.github/workflows/ci.yml`。

---

## 目录结构

```
CCLEAR/
├─ .github/workflows/ci.yml   # CI 流水线
├─ backend/
│  ├─ app/
│  │  ├─ config.py            # 配置与密钥
│  │  ├─ agent.py             # LangGraph 图 + checkpointer
│  │  ├─ profile.py           # 用户画像（长期记忆）
│  │  ├─ compact.py           # 记忆压缩（只改视图）
│  │  ├─ tools.py             # 六个工具 + 安全校验 + 体积统计
│  │  ├─ main.py              # FastAPI + SSE
│  │  └─ prompts/system.md    # System Prompt 模板
│  ├─ tests/                  # 74 个 pytest 用例
│  ├─ learn/                  # 学习脚本（含 07_langsmith_trace.py）
│  └─ data/                   # 运行时生成：cclear.db / profile.db
├─ frontend/src/              # React 前端（components/ 下按职责拆分）
├─ docs/                      # 设计文档、开发进度、演进路线、Git 指南
└─ start.ps1                  # Windows 一键启动
```

---

## 关于"部署"的说明

这是一个**操作本机文件系统**的工具，部署形态和普通 Web 应用不同：

- **推荐**：在用户自己的 Windows 机器上本地运行——这是它能扫描你的 C 盘、把文件送进**你自己的回收站**的唯一方式。
- **不建议放进 Linux 容器**：容器看不到宿主的 `C:\`，`send2trash` 只会操作容器内的"回收站"，与产品目的相悖。
- **多用户方向**：后端服务化 + 每个客户端跑一个"本地文件操作代理"，而不是把扫描逻辑搬进服务器。已记入演进规划。

---

## 已知限制

- Agent 单次任务步数上限 12（防死循环 / 失控）
- 记忆与画像存本地 SQLite，单机自用；多用户并发需换服务端存储
- 用户画像由模型自行判断记什么（侧栏可见、可删），不记录变更历史（刻意不做，避免过度设计）
- 未接入 LangGraph Studio（图形化调试）；LangSmith 已接入（可选）

---

## License

MIT
