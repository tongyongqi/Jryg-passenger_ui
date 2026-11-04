"""香港 Android 直接继承 iOS 默认订单场景，仅覆盖手机平台操作。"""

from jryg_hk_android.JRYG_android_order import AndroidOrderMixin
from jryg_hk_android.JRYG_shared_ios import ios_scenarios

# 动态继承同一订单模板和场景参数，AndroidMixin优先提供原生设备操作。
# __test__开启具体场景收集；不复制支付组合，未支持渠道仍由setup_class拒绝。
for _ios_case in ios_scenarios():
    _name = _ios_case.__name__ + "Android"
    globals()[_name] = type(_name, (AndroidOrderMixin, _ios_case), {
        "__module__": __name__, "__test__": True, "pytestmark": [],
        "ios_scenario_name": _ios_case.__name__,
    })
del _ios_case, _name
