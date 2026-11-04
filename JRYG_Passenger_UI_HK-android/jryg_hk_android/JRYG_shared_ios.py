"""从安卓项目内的已验证副本加载业务基线，不依赖外部iOS目录。"""

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import yaml

from .JRYG_config import BASE_DIR, SETTINGS as ANDROID_SETTINGS

IOS_DIR = Path(BASE_DIR) / "_ios_verified_snapshot"
if not (IOS_DIR / "ui_framework/JRYG_order_flow.py").is_file():
    raise RuntimeError("缺少安卓项目内的已验证业务基线 _ios_verified_snapshot")
if str(IOS_DIR) not in sys.path:
    sys.path.insert(0, str(IOS_DIR))


def shared_settings():
    """深拷贝iOS业务配置，覆盖Android设备/包名/司机信息，不改原配置对象。"""
    with (IOS_DIR / "config/JRYG_settings.yaml").open(encoding="utf-8") as stream:
        settings = yaml.safe_load(stream)
    result = deepcopy(settings)
    result["device"] = deepcopy(ANDROID_SETTINGS["device"])
    result["device"]["udid"] = os.environ.get("HK_ANDROID_UDID") or result["device"]["udid"]
    result["packages"].update(ANDROID_SETTINGS.get("packages") or {})
    result["driver"].pop("wda_url", None)
    driver_device = ANDROID_SETTINGS.get("driver") or {}
    result["driver"].update(deepcopy(driver_device))
    result["driver"].pop("wda_url", None)
    result["order_validation"].update(deepcopy(ANDROID_SETTINGS.get("order_validation") or {}))
    result["login"] = deepcopy(ANDROID_SETTINGS.get("login") or {})
    return result


def ios_scenarios():
    """静态解析iOS默认场景顺序，逐模块加载唯一订单子类并依序生成。

    不执行运行器主入口或设备动作；场景文件缺失/子类不唯一立即失败，避免漏跑。
    """
    path = IOS_DIR / "runners/JRYG_run_main_ios.py"
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    files = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ios_test_files" for target in node.targets
        ):
            for entry in node.value.elts:
                name = entry.args[-1].value
                files.append(IOS_DIR / "cases" / name)
    if not files or any(not path.is_file() for path in files):
        raise RuntimeError("iOS 默认订单场景缺失，停止收集而非静默漏跑")
    from ui_framework.JRYG_order_flow import TestOrderBase
    for path in files:
        spec = importlib.util.spec_from_file_location("hk_shared_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classes = [value for value in vars(module).values() if isinstance(value, type)
                   and value is not TestOrderBase and issubclass(value, TestOrderBase)
                   and value.__module__ == module.__name__]
        if len(classes) != 1:
            raise RuntimeError(f"iOS 场景必须唯一：{path.name}")
        yield classes[0]
