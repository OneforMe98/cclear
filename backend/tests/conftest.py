"""pytest 共享配置：fixture 集中放这里。

测试用的策略：
- 删除类测试绝不碰真实文件：用 tmp_path（pytest 自带临时目录），并在目录里放文件
- 用 monkeypatch 把 delete_to_recycle_bin 依赖的 send2trash 替换掉，
  避免测试真的往回收站里丢东西；改成"记录被调用的路径"，好断言"确实删了"
  并避免对用户环境产生副作用
"""

import sys
from pathlib import Path

# 把 backend/ 加到 import 路径，pytest 才能 import app.*
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
