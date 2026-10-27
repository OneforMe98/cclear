"""第一个 Agent 工具：扫描目录占用空间。

一个"工具"包含两样东西：
1. 给模型看的"使用说明书"（函数的 docstring 和参数说明）——模型靠它决定什么时候调用、传什么参数
2. 真正干活的 Python 代码——模型本身不能读你的硬盘，它只会"说"要调用，执行发生在这里

安全设计：只读（只统计大小，绝不动文件内容），且只允许扫描白名单目录。
"""

import os
import shutil
import time
from pathlib import Path

from langchain_core.tools import tool
from langgraph.types import interrupt
from send2trash import send2trash

# --- 删除安全限制：只允许删除这些根目录下的内容 ---
# 注意：这只约束"删除"。读取（扫描/查找）用更宽的范围，见 _is_read_allowed。
DELETE_ROOTS = [
    Path.home(),                          # C:\Users\<你的用户名>
    Path(os.environ.get("TEMP", r"C:\Windows\Temp")),  # 系统临时目录
]
# 向后兼容旧名字（测试与外部若引用 SAFE_ROOTS 仍可用）
SAFE_ROOTS = DELETE_ROOTS

MAX_DEPTH = 5         # 向下最多数几层目录
MAX_FILE_DEPTH = 8    # 找大文件时允许的更深层级（文件常藏在 AppData 深处）
TIMEOUT_SECONDS = 20  # 单次扫描总时长上限（防止大目录卡死）
TOP_N = 10            # 最多返回多少项


def _local_drives() -> list[str]:
    """列出本机所有固定磁盘分区（如 ['C:\\\\', 'D:\\\\']），用于全盘总览与读取范围判断。"""
    drives: list[str] = []
    # Python 3.12+ 有 os.listdrives；旧版本回退到逐字母探测
    if hasattr(os, "listdrives"):
        try:
            drives = list(os.listdrives())
        except OSError:
            drives = []
    if not drives:
        import string

        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
    return drives


def _is_read_allowed(path: Path) -> bool:
    """读取（扫描/查找）范围：任意本地磁盘上的真实路径都允许。

    为什么比删除宽松得多：读目录大小不会修改任何文件，把它限制在用户主目录
    会导致"C 盘用了 117G、只能看到 28G"这种反直觉体验。真正危险的是删除，
    删除仍由 _is_safe（白名单）严格约束。
    仅排除网络路径（UNC）——它们可能极慢且不属于本机，避免卡死。
    """
    raw = str(path)
    if raw.startswith("\\\\"):  # UNC 网络共享，拒绝
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.exists()



def human_size(n: float) -> str:
    """把字节数变成人能看的格式，如 1.2 GB。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _dir_size(path: Path, started: float) -> int:
    """递归统计目录下所有文件的总大小（带超时和深度限制）。"""
    total = 0
    stack: list[tuple[Path, int]] = [(path, 0)]
    while stack:
        if time.monotonic() - started > TIMEOUT_SECONDS:
            break
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False) and depth + 1 <= MAX_DEPTH:
                            stack.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue  # 个别没权限的文件跳过，不中断整体扫描
        except OSError:
            continue
    return total


def _drive_free_bytes(drive: str) -> int:
    """返回该盘符的可用空间（字节）。失败时返回 0。"""
    try:
        return int(shutil.disk_usage(drive + "\\").free)
    except (OSError, ValueError):
        return 0


def _is_safe(path: Path) -> bool:
    """删除范围：目标必须落在删除白名单内（含白名单目录本身）。"""
    resolved = path.resolve()
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in DELETE_ROOTS)


@tool
def disk_overview() -> str:
    """查看本机各磁盘分区的总容量、已用空间、剩余空间（只读）。

    回答"C 盘容量多大""还剩多少空间""哪个盘快满了"这类问题。
    不需要任何参数，会自动列出所有本地磁盘。
    """
    drives = _local_drives()
    if not drives:
        return "没有检测到任何磁盘分区。"

    lines = ["本机磁盘空间总览："]
    for root in drives:
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        total = usage.total
        used = usage.used
        free = usage.free
        percent = (used / total * 100) if total else 0
        lines.append(
            f"- {root}  总 {human_size(total)} · 已用 {human_size(used)}（{percent:.0f}%）· 可用 {human_size(free)}"
        )
    return "\n".join(lines)


@tool(response_format="content_and_artifact")
def scan_directory_size(path: str = "") -> tuple[str, dict | None]:
    """统计指定目录下各项内容的占用空间（只读，不删除、不修改任何文件）。

    返回该目录下第一层子目录和文件各自的总大小，按从大到小排序（最多 10 项）。
    用于回答"C 盘哪个文件夹最占空间""这个目录为什么这么大"这类问题。
    想了解整块磁盘的容量与剩余，请用 disk_overview；想看整盘各顶级目录的占用，
    可以传 path="C:\\\\"。

    Args:
        path: 要扫描的目录绝对路径（可以是 C 盘任意目录，如 C:\\ 或 C:\\Windows）。
              留空（推荐）则扫描当前用户主目录。
    """
    started = time.monotonic()
    target = Path(path).expanduser() if path.strip() else Path.home()

    if str(target).startswith("\\\\"):
        return "无法读取网络共享路径（\\\\server\\...），请只扫描本地磁盘。", None
    if not target.exists():
        return f"目录不存在：{path}。留空 path 即扫描用户主目录 {Path.home()}", None
    if not target.is_dir():
        return f"不是目录：{path}", None
    if not _is_read_allowed(target):
        return f"无法读取该目录（可能是网络路径或无权限）：{path}", None

    rows: list[tuple[str, int]] = []
    timeout_hit = False
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    full = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        size = _dir_size(full, started)
                        rows.append((full.name + "/", size))
                    elif entry.is_file(follow_symlinks=False):
                        rows.append((full.name, entry.stat(follow_symlinks=False).st_size))
                except OSError:
                    continue
                if time.monotonic() - started > TIMEOUT_SECONDS:
                    timeout_hit = True
                    break
    except OSError as exc:
        return f"无法读取目录 {path}：{exc}", None

    if not rows:
        return f"{path} 是空目录。", {"kind": "dir_sizes", "total_bytes": 0, "entries": []}

    rows.sort(key=lambda r: r[1], reverse=True)
    total = sum(size for _, size in rows)
    lines = [
        f"扫描目录：{target}",
        f"第一层内容总计：{human_size(total)}（按大小排序，最多 {TOP_N} 项）：",
    ]
    for name, size in rows[:TOP_N]:
        lines.append(f"- {name}  {human_size(size)}")
    if timeout_hit:
        lines.append(f"（注意：扫描超过 {TIMEOUT_SECONDS} 秒已截断，结果可能不完整）")

    # artifact：同一次扫描的"机器可读版"——前端拿它画图表，模型只看上面的文本
    artifact = {
        "kind": "dir_sizes",
        "path": str(target),
        "total_bytes": total,
        "entries": [
            {"name": name.rstrip("/"), "bytes": size, "is_dir": name.endswith("/")}
            for name, size in rows[:TOP_N]
        ],
    }
    return "\n".join(lines), artifact


def _walk_files(root: Path, started: float, min_bytes: int) -> tuple[list[tuple[Path, int]], bool]:
    """递归找出目录下所有大于 min_bytes 的文件。返回 (文件列表, 是否超时)。"""
    found: list[tuple[Path, int]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    timed_out = False
    while stack:
        if time.monotonic() - started > TIMEOUT_SECONDS:
            timed_out = True
            break
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            if size >= min_bytes:
                                found.append((Path(entry.path), size))
                        elif entry.is_dir(follow_symlinks=False) and depth < MAX_FILE_DEPTH:
                            stack.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue
        except OSError:
            continue
    return found, timed_out


@tool
def find_large_files(directory: str = "", min_size_mb: int = 100, limit: int = 20) -> str:
    """递归查找指定目录下体积最大的文件（只读，不删除、不修改任何文件）。

    找出所有超过 min_size_mb 的文件并按大小降序返回，最多 limit 个。
    适合回答"哪些文件最占地方""找出最大的安装包/压缩包/视频"这类问题。
    注意：如果要看"哪个文件夹总共多大"，请改用 scan_directory_size。

    Args:
        directory: 要搜索的目录绝对路径（可以是 C 盘任意目录，如 C:\\）。留空则搜索当前用户主目录。
        min_size_mb: 最小文件大小（单位 MB），默认 100。
        limit: 最多返回多少个文件，默认 20。
    """
    started = time.monotonic()
    target = Path(directory).expanduser() if directory.strip() else Path.home()

    if str(target).startswith("\\\\"):
        return "无法搜索网络共享路径（\\\\server\\...），请只搜索本地磁盘。"
    if not target.exists():
        return f"目录不存在：{directory}。留空 directory 即搜索用户主目录 {Path.home()}"
    if not target.is_dir():
        return f"不是目录：{directory}"
    if not _is_read_allowed(target):
        return f"无法搜索该目录（可能是网络路径或无权限）：{directory}"

    min_bytes = max(0, min_size_mb) * 1024 * 1024
    found, timed_out = _walk_files(target, started, min_bytes)

    if not found:
        return f"在 {target} 下没有找到超过 {min_size_mb} MB 的文件。"

    found.sort(key=lambda item: item[1], reverse=True)
    lines = [
        f"搜索目录：{target}",
        f"超过 {min_size_mb} MB 的文件共 {len(found)} 个，最大的 {min(limit, len(found))} 个：",
    ]
    for path, size in found[:limit]:
        lines.append(f"- {human_size(size)}  {path}")
    if timed_out:
        lines.append(f"（注意：搜索超过 {TIMEOUT_SECONDS} 秒已截断，结果可能不完整）")
    return "\n".join(lines)


# 常见"垃圾目录"清单：(展示名, 路径, 风险等级)
# 说明：这些路径是写死的"已知垃圾位置"，与 scan_directory_size 的"任意路径白名单校验"不同，
# 工具本身不接受任何外部输入，因此不存在被诱导扫描危险目录的可能。
JUNK_LOCATIONS: list[tuple[str, str, str]] = [
    ("用户临时目录 (TEMP)", os.environ.get("TEMP", ""), "安全"),
    ("Windows 临时目录", r"C:\Windows\Temp", "安全"),
    ("Windows 更新缓存", r"C:\Windows\SoftwareDistribution\Download", "安全"),
    ("回收站", r"C:\$Recycle.Bin", "安全（清空回收站即可）"),
    ("pip 包管理器缓存", os.path.join(os.environ.get("LOCALAPPDATA", ""), "pip", "Cache"), "安全"),
    ("npm 包管理器缓存", os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache"), "安全"),
    ("Chrome 浏览器缓存", os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data", "Default", "Cache"), "安全"),
    ("Edge 浏览器缓存", os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data", "Default", "Cache"), "安全"),
    ("Windows.old 旧系统备份", r"C:\Windows.old", "谨慎（删除前务必确认）"),
]


@tool(response_format="content_and_artifact")
def detect_junk_dirs() -> tuple[str, dict | None]:
    """盘点 Windows 常见的系统垃圾目录，并统计各自占用的空间（只统计，不删除任何东西）。

    检查临时文件、Windows 更新缓存、回收站、包管理器缓存、浏览器缓存、
    Windows.old 等常见可清理位置，返回各自大小、风险等级和合计可释放空间。
    适合回答"有哪些垃圾可以清理""大概能释放多少空间"这类问题。
    """
    started = time.monotonic()
    rows: list[tuple[str, str, int, str]] = []  # (名称, 路径, 大小, 风险)
    skipped: list[str] = []

    for label, raw_path, risk in JUNK_LOCATIONS:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        if time.monotonic() - started > TIMEOUT_SECONDS:
            skipped.append(label)
            continue
        try:
            size = _dir_size(path, started)
        except OSError:
            continue
        rows.append((label, raw_path, size, risk))

    if not rows:
        return "没有发现常见垃圾目录，或它们都是空的。", None

    rows.sort(key=lambda r: r[2], reverse=True)
    total = sum(r[2] for r in rows)
    lines = [
        "常见垃圾目录盘点（只统计，未删除任何文件）：",
    ]
    for label, raw_path, size, risk in rows:
        lines.append(f"- {human_size(size)}  {label}（风险：{risk}）\n  路径：{raw_path}")
    lines.append(f"合计可释放空间约：{human_size(total)}")
    if skipped:
        lines.append(f"（注意：{'、'.join(skipped)} 因超时未统计）")

    artifact = {
        "kind": "junk",
        "total_bytes": total,
        "entries": [
            {"label": label, "path": raw_path, "bytes": size, "risk": risk}
            for label, raw_path, size, _risk in rows
        ],
    }
    return "\n".join(lines), artifact


# 永远不允许删除的位置（即使用户点名也不行——防误删的最后一层保险）
FORBIDDEN_ROOTS = [
    Path(r"C:\Windows"),
    Path(r"C:\Program Files"),
    Path(r"C:\Program Files (x86)"),
    Path(r"C:\ProgramData"),
]
MAX_DELETE_ITEMS = 50  # 一次删除请求最多多少项


def _measure_targets(paths: list[Path], started: float) -> tuple[int, int]:
    """统计这批待删路径的总体积和总文件数。

    为什么必须算体积：上限是"50 项"，但一个目录可能装着几万个文件——
    按"项"计数会让"删 1 个大目录"看起来比"删 10 个小文件"更安全，
    这是危险的错觉。体积和文件数才是用户真正在意的量。
    返回 (总字节数, 文件数)；超时则提前返回已统计到的部分。
    """
    total_bytes = 0
    file_count = 0
    for p in paths:
        if time.monotonic() - started > TIMEOUT_SECONDS:
            break
        if p.is_file():
            try:
                total_bytes += p.stat().st_size
                file_count += 1
            except OSError:
                continue
        elif p.is_dir():
            size, count = _walk_stats(p, started)
            total_bytes += size
            file_count += count
    return total_bytes, file_count


def _walk_stats(root: Path, started: float) -> tuple[int, int]:
    """递归统计一个目录的体积与文件数（超时即停，不做深度限制——这里要的是真实大小）。"""
    size = 0
    count = 0
    stack = [root]
    while stack:
        if time.monotonic() - started > TIMEOUT_SECONDS:
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                            count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return size, count


def _is_forbidden(path: Path) -> bool:
    """系统关键位置、或白名单根目录本身，一律禁止删除。"""
    resolved = path.resolve()
    if resolved in {root.resolve() for root in SAFE_ROOTS}:
        return True  # 主目录/临时目录"根"本身不能删
    return any(
        resolved == root.resolve() or root.resolve() in resolved.parents
        for root in FORBIDDEN_ROOTS
    )


@tool
def delete_to_recycle_bin(paths: list[str]) -> str:
    """把指定文件/目录删除到 Windows 回收站（可从回收站恢复，不是永久删除）。

    调用后系统会先向用户展示待删除清单并暂停，等待用户点"确认"。
    用户拒绝则不会删除任何东西。使用要求：
    - 只传入用户明确要求清理、且你已经扫描分析确认无风险的路径
    - 一次最多 50 项；系统关键目录（Windows、Program Files 等）会被安全校验拒绝
    - 想获得"可清理什么"的完整清单，请先调用 detect_junk_dirs 分析

    Args:
        paths: 要删除的绝对路径列表（文件或目录均可）。
    """
    if not paths:
        return "没有收到要删除的路径。"
    if len(paths) > MAX_DELETE_ITEMS:
        return f"一次最多删除 {MAX_DELETE_ITEMS} 项，本次收到 {len(paths)} 项，请精选后重试。"

    checked: list[Path] = []
    rejected: list[str] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            rejected.append(f"{raw}（不存在）")
        elif not _is_safe(p):
            rejected.append(f"{raw}（不在允许的扫描范围内）")
        elif _is_forbidden(p):
            rejected.append(f"{raw}（系统关键位置，禁止删除）")
        else:
            checked.append(p)

    if not checked:
        return "全部路径都未通过安全校验，未删除任何东西：\n" + "\n".join(rejected)

    # ---- human-in-the-loop 关键一步：暂停整个 Agent 图，等用户确认 ----
    # 先算清楚这批到底多大、多少个文件：用户有权知道"删 3 项"背后是 200MB 还是 20GB
    # 也先记录磁盘状态，以便删除后给用户一份"清理前后对比"
    measured_started = time.monotonic()
    total_bytes, file_count = _measure_targets(checked, measured_started)

    # 涉及的磁盘：每条待删路径所在的盘符，去重
    drives_involved: list[str] = []
    for p in checked:
        drive = (p.drive or "").upper()
        if drive and drive not in drives_involved:
            drives_involved.append(drive)
    before_free: dict[str, int] = {d: _drive_free_bytes(d) for d in drives_involved}

    decision = interrupt(
        {
            "type": "delete_confirm",
            "paths": [str(p) for p in checked],
            "rejected": rejected,
            "total_bytes": total_bytes,
            "total_size": human_size(total_bytes),
            "file_count": file_count,
            "drives_before": {d: human_size(v) for d, v in before_free.items()},
        }
    )
    if not decision:
        return "用户拒绝了本次删除，未删除任何文件。"

    done: list[str] = []
    failed: list[str] = []
    for p in checked:
        try:
            send2trash(str(p))
            done.append(str(p))
        except Exception as exc:  # noqa: BLE001 —— 单项失败不影响其余项
            failed.append(f"{p}（{exc}）")

    # 删除后再次记录磁盘状态，形成"清理前后对比"
    after_free: dict[str, int] = {d: _drive_free_bytes(d) for d in drives_involved}

    lines = [f"已删除到回收站 {len(done)} 项、约 {human_size(total_bytes)}（可从回收站恢复）："]
    lines += [f"- {item}" for item in done]
    if failed:
        lines.append("以下项目删除失败：")
        lines += [f"- {item}" for item in failed]
    if rejected:
        lines.append("以下项目未通过安全校验被跳过：")
        lines += [f"- {item}" for item in rejected]

    lines.append("")
    lines.append("【清理前后对比】（磁盘可用空间）")
    for d in drives_involved:
        b = before_free.get(d, 0)
        a = after_free.get(d, 0)
        delta = a - b
        if delta == 0:
            lines.append(f"- {d}：清理前 {human_size(b)} → 清理后 {human_size(a)}（暂无变化）")
        else:
            lines.append(f"- {d}：清理前 {human_size(b)} → 清理后 {human_size(a)}（+{human_size(delta)}）")
    lines.append(
        "注意：移入回收站不会立即释放磁盘空间——文件仍占着原来那块空间，"
        "清空回收站后才会真正释放。上面的 '暂无变化' 是正常现象，不是 bug。"
    )
    return "\n".join(lines)


@tool
def remember_preference(key: str, value: str) -> str:
    """记住用户的一条**长期偏好**，跨会话有效（下次开新对话也记得）。

    什么时候用：用户表达了"以后都按这个来"的偏好，而不是这一轮的临时要求。
    - ✅ 该记："以后 500MB 以上的文件才需要问我""永远别删我的下载文件夹""我的电脑是 256G 小硬盘"
    - ❌ 不该记："这次帮我扫一下桌面"（临时要求，不是偏好）
    不要记与清理任务无关的隐私信息（真实姓名、住址、账号密码等）。

    Args:
        key: 偏好的简短标签，如「大文件阈值」「禁止删除的目录」「硬盘容量」。同一标签会覆盖旧值。
        value: 偏好内容，一句话说清，如「500MB 以上才提醒我」。
    """
    from .profile import set_preference

    return set_preference(key, value)


@tool
def forget_preference(key: str) -> str:
    """删除一条已经记住的长期偏好。

    当用户说"不用记这个了""忘掉之前的偏好"时调用。看不清有哪些偏好时，
    先不需要猜——错误信息里会列出当前已有的全部 key。

    Args:
        key: 要删除的偏好标签（必须与当初记住时的标签一致）。
    """
    from .profile import forget_preference as _forget

    return _forget(key)


# 所有可用的工具都放在这个列表里，Agent 构建时统一挂载
TOOLS = [
    disk_overview,
    scan_directory_size,
    find_large_files,
    detect_junk_dirs,
    delete_to_recycle_bin,
    remember_preference,
    forget_preference,
]
