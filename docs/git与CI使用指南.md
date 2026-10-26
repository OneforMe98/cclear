# Git 与 CI 使用指南

> 这份文档是给"知道有 git 但没怎么用过"的人看的。看完你会知道：**每次改完代码该做什么、改坏了怎么退回去、代码怎么传到 GitHub、CI 报红了怎么办。**

---

## 1. git 到底是什么（一句话）

**git = 你项目的"存档点"系统。**

打游戏时你会存档，打 boss 前存一个，死了就读取回来。git 就是给代码存档：

```
改代码 → 存档（commit）→ 再改 → 再存档 → ...
                                        │
                              改坏了？读回任意一个存档
```

**它解决的核心问题**：`我要删掉 3 个文件，结果删错了，怎么回到 5 分钟前？`

---

## 2. 三个"区"，理解了这个就懂 git 了

```
① 工作区            ② 暂存区            ③ 仓库
（你正在编辑的文件）  （准备提交的清单）   （已存好的历史）
      │                   │                  │
      │  git add          │   git commit     │
      └──────────────────►└─────────────────►│
                                              │
                                          git push
                                              │
                                              ▼
                                        GitHub（云端备份）
```

| 区 | 是什么 | 类比 |
| --- | --- | --- |
| **工作区** | 硬盘上你能看到的文件 | 你正在写的草稿 |
| **暂存区** | 你挑出来"这次要存档"的改动 | 装进信封的稿纸 |
| **仓库** | 已经存好的历史版本 | 档案柜 |

**为什么要"暂存区"这一层？** 因为一次改动可能包含无关的东西（比如你顺手改了个错别字）。暂存区让你**只挑想提交的**，保持每次提交干净。

---

## 3. 现在的状态（本项目已配置好）

```
D:\AIAGENT_STUDY\Cclear\
├── .git/                      ← 仓库本体（不要手动改里面的东西）
├── .gitignore                 ← 哪些文件"不入库"
├── .gitattributes             ← 统一换行符（Windows 上很重要）
├── .github/workflows/ci.yml   ← CI 配置（推上去自动跑测试）
├── backend/  frontend/  docs/
└── README.md
```

已提交 2 次：

```
5ffb6fd docs: 添加 CI 状态徽章
e17d7c5 feat: CCLEAR 磁盘清理 Agent 初始版本
```

**`.gitignore` 保护了什么**（这些永远不进 git）：

| 排除项 | 为什么 |
| --- | --- |
| `.env` | 里面是你的 DeepSeek API Key，泄露=别人能花你的钱 |
| `backend/data/*.db` | 你的真实对话记录，不该公开 |
| `.venv/` `node_modules/` | 几万个依赖文件，能随时重装，没必要存 |
| `__pycache__/` `dist/` | 编译产物，自动生成 |

---

## 4. 日常只需要 5 条命令

### ① 看现在什么状态（最常用）

```powershell
git status
```

输出会告诉你：哪些文件改了、哪些还没暂存、当前在哪个分支。

```
Changes not staged for commit:
        modified:   backend/app/compact.py     ← 改了但还没 add

Untracked files:
        docs/新文档.md                          ← 新文件，git 还没管它
```

### ② 看具体改了什么

```powershell
git diff                    # 工作区 vs 暂存区（还没 add 的改动）
git diff --staged           # 暂存区 vs 上次提交（准备提交的改动）
```

### ③ 暂存 + 提交（存档）

```powershell
git add backend/app/compact.py    # 只加这一个文件
git add -A                        # 加所有改动（省事但要看清楚）
git commit -m "fix: 截断时不再切断路径"
```

**提交信息怎么写**（业界通用格式）：

```
<类型>: <做了什么>

类型：
  feat      新功能
  fix       修 bug
  docs      只改文档
  refactor  重构（不改行为）
  test      只改测试
  chore     杂活（依赖升级、配置）
```

例子：

```
feat: 扫描进度显示计时器
fix: 工具输出按行截断，不再切断路径
docs: 补 Git 与 CI 指南
```

### ④ 看历史

```powershell
git log --oneline            # 一行一个提交，看最近的
git log --oneline -10        # 最近 10 条
```

### ⑤ 推送到 GitHub

```powershell
git push
```

---

## 5. 改坏了怎么退回去（这是 git 最大的价值）

### 场景 A：改了但还没提交，想全部丢弃

```powershell
git restore backend/app/compact.py     # 丢弃单个文件的改动
git restore .                          # 丢弃全部改动（危险，不可恢复）
```

### 场景 B：已经提交了，想回到上一个存档

```powershell
git log --oneline                      # 先看历史，找到目标提交号
git revert <提交号>                     # 推荐：生成一个"反向提交"，历史保留
```

**为什么推荐 `revert` 而不是 `reset`？**

| | 效果 | 风险 |
| --- | --- | --- |
| `git revert` | 新增一个"撤销"提交，历史完整 | ✅ 安全，已推送的也能用 |
| `git reset --hard` | 直接把历史抹掉 | ⚠️ 已推送的会出问题，慎用 |

### 场景 C：想看某个文件以前长什么样

```powershell
git show e17d7c5:backend/app/compact.py    # 看那次提交时的完整内容
```

---

## 6. 推到 GitHub（本项目已改用 SSH）

### ⚠️ 这个网络环境有问题

实测结果：

```
https://github.com      → 超时（被阻断）
https://api.github.com  → 正常
github.com:22 (SSH)     → 通
```

**所以本项目最终改用 SSH**，不再依赖代理，也不用管 HTTPS 证书问题。

### 当前配置

```
origin  git@github.com:OneforMe98/cclear.git
```

密钥位置：

```
C:\Users\ASUS\.ssh\id_ed25519        私钥（绝不外传）
C:\Users\ASUS\.ssh\id_ed25519.pub    公钥（已加到 GitHub）
```

**以后推送就是一条命令，不需要代理、不需要密码：**

```powershell
git push
```

### 验证连通性

```powershell
ssh -T git@github.com
# 期望输出：Hi OneforMe98! You've successfully authenticated...
# （后面那句 "does not provide shell access" 是正常的，GitHub 不给 shell）
```

### 如果哪天换了电脑，重新配 SSH

```powershell
# 1. 生成密钥（-N '""' 表示不设密码短语，全程免交互）
ssh-keygen -t ed25519 -C "你的邮箱" -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'

# 2. 复制公钥
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"

# 3. 粘到 https://github.com/settings/keys → New SSH key

# 4. 验证
ssh -T git@github.com
```

> **踩坑提醒**：跑 `ssh-keygen` 时它会依次问"保存路径"和"密码短语"，
> **如果这时候粘贴了别的命令进去，密钥不会被创建**（它会把命令当成密码，
> 且两次不一致直接退出）。想全程不被打断，就用上面的 `-N '""'` 一次性指定。

### 备选：HTTPS + 代理

如果哪天 SSH 也不通了：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"    # 换成你代理软件的端口
$env:HTTPS_PROXY="http://127.0.0.1:7897"
git remote set-url origin https://github.com/OneforMe98/cclear.git
git push
```

---

## 7. CI 是什么，怎么看

### 一句话

**CI = 每次你推送代码，GitHub 自动在云端跑一遍测试，红了就告诉你"你改坏了"。**

```
你 git push
     │
     ▼
GitHub Actions 启动一台云端 Windows 机器
     │
     ├── 装 Python 依赖 → 跑 63 个 pytest
     └── 装 npm 依赖 → 跑 tsc 类型检查 + oxlint
     │
     ▼
全绿 ✅  → README 徽章变绿
有红 ❌  → 邮件通知你，点进去看哪一行炸了
```

### 为什么值得有

| 没有 CI | 有 CI |
| --- | --- |
| 改完靠自己记得跑 `pytest` | 忘了也会被自动检查 |
| 改 A 功能，悄悄弄坏 B 功能 | 立刻发现 |
| 面试时说"我写了测试" | 说"我有 CI，每次提交自动验证 63 个测试" |

### 怎么看结果

1. 打开 `https://github.com/OneforMe98/cclear/actions`
2. 点最新那次运行
3. 左边 `backend` / `frontend` 是两个任务，点进去看日志
4. 红色 ❌ 的那一步会显示具体报错

### 为什么 CI 用 `windows-latest` 而不是 `ubuntu`

```yaml
runs-on: windows-latest
```

因为本项目**只能在 Windows 上跑**：删除文件用的是 Windows 回收站（`send2trash`），路径是 `C:\Users\...`，安全白名单也是按 Windows 目录写的。在 Linux 上跑测试**测不到真实行为**，等于自欺欺人。

代价是 Windows 机器启动慢一点（约 1 分钟），但值得。

---

## 8. 五个常见坑

### 坑 1：`.env` 被提交了

```powershell
git rm --cached backend/.env      # 从 git 里移除（文件还在硬盘上）
```

**但如果已经推到 GitHub，Key 就泄露了**——必须立刻去 DeepSeek 后台**吊销并重建 Key**。改 `.gitignore` 只防未来，不防过去。

### 坑 2：在错误的目录 `git init`

本项目的真实事故：第一次在 `backend/` 里建了仓库，导致 `frontend/` 和 `docs/` 完全不在版本控制里。

```powershell
git rev-parse --show-toplevel      # 检查当前仓库的根在哪
```

### 坑 3：CRLF / LF 换行符打架

Windows 用 `\r\n`，Linux 用 `\n`。不统一会导致"我明明没改，git 却说整个文件都变了"。

本项目已用 `.gitattributes` 解决：

```
* text=auto eol=lf        # 代码统一存 LF
*.ps1 text eol=crlf       # PowerShell 脚本保留 CRLF
```

### 坑 4：`git add -A` 加进了不该加的东西

```powershell
git status                # add 之前一定先看这个
git reset                 # 后悔了：把暂存区清空（改动还在）
```

### 坑 5：`node_modules` 进了仓库

会让仓库从 2MB 暴涨到 500MB。本项目 `.gitignore` 已排除，别手动改。

---

## 9. 速查表

| 我想…… | 命令 |
| --- | --- |
| 看改了什么 | `git status` / `git diff` |
| 存档 | `git add -A` + `git commit -m "..."` |
| 看历史 | `git log --oneline` |
| 丢弃未提交的改动 | `git restore <文件>` |
| 撤销某次提交 | `git revert <提交号>` |
| 推到 GitHub | `git push`（已配 SSH，不需要代理） |
| 验证 SSH 通不通 | `ssh -T git@github.com` |
| 看 CI 结果 | 网页 `github.com/OneforMe98/cclear/actions` |
| 仓库根在哪 | `git rev-parse --show-toplevel` |
| 从 git 移除但保留文件 | `git rm --cached <文件>` |
| 只跑某个测试 | `pytest tests/test_tools.py::test_xxx` |
| 只跑名字含某词的测试 | `pytest -k delete` |

---

## 10. 一次完整的工作流（照着做就行）

```powershell
# 1. 改完代码，先看状态
git status

# 2. 跑一遍测试，确认没改坏
cd backend; .venv\Scripts\python.exe -m pytest -q; cd ..

# 3. 看具体改动，确认没有不该提交的东西
git diff

# 4. 暂存 + 提交
git add -A
git commit -m "feat: 扫描进度显示计时器"

# 5. 推送（SSH，不需要代理）
git push

# 6. 去 GitHub Actions 看 CI 是否全绿
```

**习惯一旦养成，最爽的时刻是**：改了一堆东西发现不对劲，一条 `git diff` 就看清楚到底动了哪些行，不用凭记忆。
