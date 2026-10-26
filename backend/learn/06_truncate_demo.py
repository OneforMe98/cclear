"""⑥ 亲手验证"按行截断"—— 看它到底切在哪一行。

运行：
    .venv\\Scripts\\python.exe learn\\06_truncate_demo.py

对比三件事：
1. 按字符截断（旧做法）会切出半截路径
2. 按行截断（现在的做法）每一行都完整
3. 单行超长时的退化处理
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compact import _truncate_text


SAMPLE = """搜索目录：C:\\Users\\ASUS
超过 50 MB 的文件共 6 个，最大的 6 个：
- 939.0 MB  C:\\Users\\ASUS\\AppData\\Local\\Temp\\pip-unpack-agpyw4u8\\torch-2.11.0+cu128-cp313-cp313-win_amd64.whl
- 784.1 MB  C:\\Users\\ASUS\\AppData\\Local\\Packages\\B9ECED6F.ArmouryCrate_qmba6cd70vzyy\\LocalState\\ZIPFileTemp\\DRV_VGA_Intel_RPL_SZ_W11_64_V3101013678_20221130RL.zip
- 784.1 MB  C:\\Users\\ASUS\\AppData\\Local\\Packages\\B9ECED6F.ArmouryCrate_qmba6cd70vzyy\\LocalState\\SupportTemp\\DRV_VGA_Intel_RPL_SZ_W11_64_V3101013678_20221130RL.zip
- 660.4 MB  C:\\Users\\ASUS\\AppData\\Local\\Programs\\Ollama\\lib\\ollama\\cuda_v12\\cublasLt64_12.dll
- 385.4 MB  C:\\Users\\ASUS\\AppData\\Local\\overwolf\\CrashDumps\\OverwolfBrowser.exe.27188.dmp"""


def show(label: str, text: str) -> None:
    print(f"\n{'=' * 74}")
    print(f"【{label}】{len(text)} 字符")
    print("=" * 74)
    for line in text.split("\n"):
        print(f"  [{len(line):3d}] {line}")


def main() -> None:
    limit = 400
    print(f"原始内容：{len(SAMPLE)} 字符 / {SAMPLE.count(chr(10)) + 1} 行")
    print(f"截断上限：{limit} 字符")

    # ---- 旧做法：按字符切 ----
    naive = SAMPLE[:limit] + "\n…（已截断）"
    show("旧做法：按字符切（content[:limit]）", naive)
    print("\n  ⚠️ 看最后一行：路径被切成半截，模型会误判")

    # ---- 新做法：按行切 ----
    fixed = _truncate_text(SAMPLE, limit)
    show("新做法：按行切（_truncate_text）", fixed)
    print("\n  ✅ 每一行都完整，结尾明确告知「还有几行未显示」")

    # ---- 单行超长的退化 ----
    print(f"\n{'=' * 74}")
    print("【极端情况：一整行就超限（如压成一行的 JSON）】")
    print("=" * 74)
    huge_one_line = "x" * 3000
    out = _truncate_text(huge_one_line, 100)
    print(f"  原长度 {len(huge_one_line)}，截断后 {len(out)}")
    print(f"  结尾: {out[-40:]!r}")
    print("  → 无法按行切，只能退化按字符，但明确标注「单行过长」")

    print(
        "\n结论：\n"
        "  · 工具输出是「一行一个文件」的清单形式 → 必须按行切，否则路径残缺\n"
        "  · 按行切还会告诉模型「还剩 N 行」，它才知道数据不全\n"
        "  · 只有「单行本身超长」这种极端情况才退化成按字符切（并标注）\n"
    )


if __name__ == "__main__":
    main()
