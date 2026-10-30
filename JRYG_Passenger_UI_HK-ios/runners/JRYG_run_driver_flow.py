"""司机UI运行入口：仅解析命令并委托公共状态机，不复制司机操作代码。

从项目根执行 python runners/JRYG_run_driver_flow.py --help 查看选项。
默认出车；仅接单、提交账单等副作用由显式停止阶段和金额参数控制。
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ui_framework.JRYG_driver_ui import main


if __name__ == "__main__":
    sys.exit(main())
