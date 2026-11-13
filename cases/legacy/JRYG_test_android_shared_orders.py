# 编写时间：2026-09-20
# 本期功能：香港 Android 早期订单场景 — 继承默认订单场景仅覆盖手机平台操作
"""香港 Android 直接继承 Android 默认订单场景，仅覆盖手机平台操作。"""

from jryg_hk_android.JRYG_android_order import AndroidOrderMixin
from jryg_hk_android.JRYG_shared import shared_scenarios

# 动态继承同一订单模板和场景参数，AndroidMixin优先提供原生设备操作。
# __test__开启具体场景收集；不复制支付组合，未支持渠道仍由setup_class拒绝。
for _android_case in shared_scenarios():
    _name = _android_case.__name__ + "Android"
    globals()[_name] = type(_name, (AndroidOrderMixin, _android_case), {
        "__module__": __name__, "__test__": True, "pytestmark": [],
        "android_scenario_name": _android_case.__name__,
    })
del _android_case, _name
