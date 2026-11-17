"""Android 独立业务基线加载，不依赖任何 Android 代码。"""

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import yaml

from .JRYG_config import BASE_DIR, SETTINGS as ANDROID_SETTINGS


def shared_settings():
    """返回 Android 独立业务配置，不合并 Android 配置。"""
    result = deepcopy(ANDROID_SETTINGS)
    result.setdefault("device", {})["udid"] = os.environ.get("HK_ANDROID_UDID") or result["device"].get("udid", "")
    result.setdefault("packages", {})
    result.setdefault("driver", {})
    result.setdefault("order_validation", {})
    result.setdefault("login", {})
    return result


def shared_scenarios():
    """返回 Android 默认场景顺序的订单子类列表。

    不执行运行器主入口或设备动作；场景文件缺失/子类不唯一立即失败，避免漏跑。
    """
    from .JRYG_scenarios import android_scenarios
    for cls in android_scenarios():
        yield cls
