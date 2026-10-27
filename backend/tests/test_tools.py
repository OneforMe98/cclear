"""工具层单元测试——重点是"安全边界"。

这里测的是整个产品里唯一会"造成真实后果"的代码：
扫描工具的安全校验、删除工具的三重校验 / 数量上限 / 回收站行为。
删除路径全部用 tmp_path（自动清理的临时目录）+ monkeypatch 替换 send2trash，
绝不会删除你电脑上的真实文件。
"""

from pathlib import Path

import pytest

from app import tools
from app.tools import (
    MAX_DELETE_ITEMS,
    delete_to_recycle_bin,
    detect_junk_dirs,
    disk_overview,
    find_large_files,
    human_size,
    scan_directory_size,
)


# ---------- human_size：纯函数，输入输出一目了然 ----------

@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (int(1.2 * 1024**3), "1.2 GB"),
    ],
)
def test_human_size(size, expected):
    assert human_size(size) == expected


# ---------- 扫描工具：安全校验 ----------

def test_scan_rejects_outside_safe_roots():
    # 旧版：扫描范围和删除一样只限用户主目录/临时目录。
    # 新版（步骤 24）：读操作（扫描）范围放宽到任意本地磁盘，因为只读不会造成损害；
    # 删除仍严格限制在 DELETE_ROOTS。因此 C:\Windows 现在可以被扫描。
    text, artifact = scan_directory_size.func(r"C:\Windows")
    # 不再拒绝，而是真正扫描（可能因权限/超时只返回部分，但不能是"拒绝"）
    assert "只能扫描" not in text
    assert "拒绝" not in text


def test_scan_rejects_unc_network_path():
    # 网络共享路径（UNC）被拒绝——避免扫描慢速共享卡死
    text, artifact = scan_directory_size.func(r"\\server\share\folder")
    assert artifact is None
    assert "无法读取" in text or "拒绝" in text or "网络" in text


def test_scan_rejects_nonexistent():
    text, artifact = scan_directory_size.func(r"C:\this\path\should\not\exist_9x7")
    assert "不存在" in text
    assert artifact is None


def test_scan_empty_dir_returns_empty_artifact(tmp_path):
    # tmp_path 位于系统临时目录下，天然在白名单内
    text, artifact = scan_directory_size.func(str(tmp_path))
    assert artifact is not None
    assert artifact["kind"] == "dir_sizes"
    assert artifact["total_bytes"] == 0
    assert artifact["entries"] == []


def test_scan_reports_sizes_and_artifact(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 2000)
    (tmp_path / "b.bin").write_bytes(b"x" * 1000)

    text, artifact = scan_directory_size.func(str(tmp_path))

    assert artifact["kind"] == "dir_sizes"
    assert artifact["total_bytes"] == 3000
    names = [e["name"] for e in artifact["entries"]]
    assert names[0] == "a.bin"  # 按大小降序
    assert "b.bin" in names


# ---------- 删除工具：三重安全校验（不会真正执行删除） ----------

def test_delete_rejects_empty_list():
    assert "没有收到" in delete_to_recycle_bin.func([])


def test_delete_rejects_too_many_items():
    paths = [f"C:/fake/{i}.txt" for i in range(MAX_DELETE_ITEMS + 1)]
    assert "一次最多删除" in delete_to_recycle_bin.func(paths)


def test_delete_rejects_nonexistent():
    result = delete_to_recycle_bin.func([r"C:\no\such\file_abc123.txt"])
    assert "未通过安全校验" in result


def test_delete_rejects_forbidden_system_root():
    # C:\Windows 存在 → 过存在性检查；不在白名单 → 被 _is_safe 拒绝
    result = delete_to_recycle_bin.func([r"C:\Windows"])
    assert "未通过安全校验" in result


def test_delete_rejects_user_home_root_itself(monkeypatch):
    # 用户主目录本身在白名单内，但 _is_forbidden 禁止删除白名单"根"
    home = str(Path.home())
    result = delete_to_recycle_bin.func([home])
    assert "未通过安全校验" in result


def test_delete_user_approves_calls_send2trash(tmp_path, monkeypatch):
    target = tmp_path / "junk.txt"
    target.write_text("x")

    deleted: list[str] = []
    monkeypatch.setattr("app.tools.send2trash", lambda p: deleted.append(p))
    # interrupt 在真实图里才有效；单测里替换成"用户点了确认"
    monkeypatch.setattr("app.tools.interrupt", lambda payload: True)

    result = delete_to_recycle_bin.func([str(target)])
    assert deleted == [str(target)]
    assert "已删除到回收站 1 项" in result


def test_delete_user_rejects_does_not_delete(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_text("x")

    deleted: list[str] = []
    monkeypatch.setattr("app.tools.send2trash", lambda p: deleted.append(p))
    monkeypatch.setattr("app.tools.interrupt", lambda payload: False)

    result = delete_to_recycle_bin.func([str(target)])

    assert deleted == []          # 什么都没删
    assert "拒绝" in result
    assert target.exists()        # 文件还在


def test_delete_partial_rejection(tmp_path, monkeypatch):
    """一批里混入危险路径：安全项照删，危险项被跳过并列明。"""
    good = tmp_path / "good.txt"
    good.write_text("x")

    deleted: list[str] = []
    monkeypatch.setattr("app.tools.send2trash", lambda p: deleted.append(p))
    monkeypatch.setattr("app.tools.interrupt", lambda payload: True)

    result = delete_to_recycle_bin.func([str(good), r"C:\Windows\notepad.exe"])

    assert deleted == [str(good)]
    assert "安全校验被跳过" in result


def test_delete_confirm_payload_reports_size_and_file_count(tmp_path, monkeypatch):
    """确认卡片必须带上体积和文件数——用户有权知道"删 1 项"背后是 200MB 还是 20GB。"""
    # 造一个目录，内含 3 个文件，合计约 3MB
    folder = tmp_path / "bigcache"
    folder.mkdir()
    for i in range(3):
        (folder / f"f{i}.bin").write_bytes(b"x" * (1024 * 1024))

    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return False  # 用户拒绝，避免真的删

    monkeypatch.setattr("app.tools.send2trash", lambda p: None)
    monkeypatch.setattr("app.tools.interrupt", fake_interrupt)

    delete_to_recycle_bin.func([str(folder)])

    # 体积：3 个 1MB 文件 → 约 3MB；按"项"只算 1 项，但体积/文件数必须是真实的
    assert captured["total_bytes"] >= 3 * 1024 * 1024
    assert captured["total_size"].endswith("MB")
    assert captured["file_count"] == 3


def test_delete_size_counts_nested_files(tmp_path, monkeypatch):
    """嵌套子目录里的文件也要算进体积和文件数（按项计数会严重低估）。"""
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"x" * 1024)
    (root / "sub" / "b.bin").write_bytes(b"x" * 2048)
    (root / "sub" / "c.bin").write_bytes(b"x" * 4096)

    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return False

    monkeypatch.setattr("app.tools.send2trash", lambda p: None)
    monkeypatch.setattr("app.tools.interrupt", fake_interrupt)

    delete_to_recycle_bin.func([str(root)])

    assert captured["file_count"] == 3
    assert captured["total_bytes"] == 1024 + 2048 + 4096


# ---------- 其他工具：基本可用性 ----------

def test_find_large_files_finds_big_file(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    (tmp_path / "small.bin").write_bytes(b"x" * 100)

    # 注意：find_large_files 还是单输出（纯文本），与双输出的另外两个工具不同
    text = find_large_files.func(str(tmp_path), min_size_mb=1)
    assert "big.bin" in text
    assert "small.bin" not in text


def test_detect_junk_dirs_smoke():
    """冒烟测试：不崩、返回文本，且结构（若有 artifact）自洽。"""
    text, artifact = detect_junk_dirs.func()
    assert isinstance(text, str)
    if artifact is not None:
        assert artifact["kind"] == "junk"
        assert isinstance(artifact["entries"], list)


def test_disk_overview_lists_drives():
    """磁盘总览：至少列出 C 盘，且每行含"总/已用/可用"。"""
    text = disk_overview.func()
    assert "磁盘空间总览" in text
    assert "C:" in text
    assert "总" in text and "可用" in text


def test_delete_reports_before_after_comparison(tmp_path, monkeypatch):
    """删除后必须给出"清理前后对比"（磁盘可用空间）。"""
    target = tmp_path / "junk.bin"
    target.write_bytes(b"x" * 1024)

    # 模拟磁盘可用空间：删除前 100、删除后 200（差值 +100）
    calls = {"n": 0}

    def fake_free(drive):
        calls["n"] += 1
        return 100 if calls["n"] == 1 else 200

    monkeypatch.setattr("app.tools._drive_free_bytes", fake_free)
    monkeypatch.setattr("app.tools.send2trash", lambda p: None)
    monkeypatch.setattr("app.tools.interrupt", lambda payload: True)

    result = delete_to_recycle_bin.func([str(target)])

    assert "清理前后对比" in result
    assert "清理前" in result and "清理后" in result
    # 必须提醒"回收站不立即释放空间"，否则用户会误以为没清理成功
    assert "回收站" in result and "释放" in result


def test_tools_registry():
    names = {t.name for t in tools.TOOLS}
    assert names == {
        "disk_overview",
        "scan_directory_size",
        "find_large_files",
        "detect_junk_dirs",
        "delete_to_recycle_bin",
        "remember_preference",
        "forget_preference",
    }
