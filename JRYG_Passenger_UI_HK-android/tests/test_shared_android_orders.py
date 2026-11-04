"""香港 Android 离线适配回归，不连接设备或业务服务。"""

import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, call
import xml.etree.ElementTree as ET

import pytest
import yaml

from jryg_hk_android import JRYG_android_order as android
from jryg_hk_android import JRYG_android_base as base
from jryg_hk_android import JRYG_android_ui as ui
from jryg_hk_android.JRYG_shared_ios import IOS_DIR, ios_scenarios, shared_settings
from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_driver_ui import ACTION_LABELS, DriverUIFlow, detect_phase, read_order_no
from ui_framework.JRYG_order_flow import TestOrderBase as OrderBase

BASE_DIR = Path(__file__).resolve().parents[1]
IOS_CASES = list(ios_scenarios())


def android_case(ios_case):
    """组合 Android 适配层与指定 iOS 场景，生成不参与收集的离线测试类。"""
    return type(ios_case.__name__ + "Offline", (android.AndroidOrderMixin, ios_case), {"__test__": False})


def native_node(text="", class_name="android.widget.TextView", **attributes):
    """创建带默认边界和可用状态的 Android 原生节点，并允许覆盖属性。"""
    return ET.Element(class_name, {"class": class_name, "text": text,
                                  "bounds": "[10,10][400,100]", "enabled": "true", **attributes})


def tree(*nodes, package="com.sunlightmobility.driver"):
    """将原生节点封装为层级树，并归一化为共享流程使用的界面结构。"""
    native = ET.Element("hierarchy")
    native.extend(nodes)
    return ui.normalized_tree(ET.tostring(native, encoding="unicode"), package)


def flow(client=None):
    """使用指定客户端或模拟客户端构建 Android 司机界面流程。"""
    args = SimpleNamespace(step_timeout=30, accept_label=None, report_dir=str(BASE_DIR / "report"))
    return android.AndroidDriverUIFlow(args, client=client or Mock())


@pytest.mark.parametrize("ios_case", IOS_CASES, ids=lambda case: case.__name__)
def test_android_inherits_same_business_and_payment_flow(ios_case):
    """验证 Android 场景沿用共享订单、司机及支付流程，并保留原场景参数。"""
    case = android_case(ios_case)
    assert case.test_order_flow is OrderBase.test_order_flow
    assert case._driver_ui_go_online is OrderBase._driver_ui_go_online
    assert case._driver_ui_grab_and_flow is OrderBase._driver_ui_grab_and_flow
    assert case._ios_pay is ios_case._ios_pay
    assert (case.CAR_TYPE, case.PAYMENT, case.FINAL_PAYMENT) == (
        ios_case.CAR_TYPE, ios_case.PAYMENT, ios_case.FINAL_PAYMENT)
    assert android.AndroidDriverUIFlow.run is DriverUIFlow.run
    assert android.AndroidDriverUIFlow.submit_bill is not DriverUIFlow.submit_bill
    assert android.AndroidDriverUIFlow.submit_bill.__module__ == android.__name__
    assert android.AndroidDriverUIFlow.wait_completed is not DriverUIFlow.wait_completed
    assert android.AndroidDriverUIFlow.wait_completed.__module__ == android.__name__


def test_android_settings_only_replace_device(monkeypatch):
    """验证适配配置保留订单校验与费用、替换设备设置，且返回独立配置副本。"""
    monkeypatch.delenv("HK_ANDROID_UDID", raising=False)
    with (IOS_DIR / "config/JRYG_settings.yaml").open() as stream:
        original = yaml.safe_load(stream)
    settings = shared_settings()
    assert {key: settings["order_validation"][key] for key in original["order_validation"] if key != "end_names"} == {
        key: value for key, value in original["order_validation"].items() if key != "end_names"}
    assert settings["order_validation"]["end_names"] == original["order_validation"]["end_names"] + ["香港大学"]
    assert settings["order_validation"]["end_details"] == ["香港特別行政區中西區薄扶林道", "香港特别行政区中西区薄扶林道"]
    assert settings["driver"]["fare"] == original["driver"]["fare"]
    assert settings["driver"]["surcharge"] == original["driver"]["surcharge"]
    assert settings["device"]["platform_name"] == "Android"
    assert "wda_url" not in settings["driver"]
    settings["driver"]["fare"] = "999"
    assert shared_settings()["driver"]["fare"] == original["driver"]["fare"]


def test_explicit_android_device_override(monkeypatch):
    """验证环境变量能够明确覆盖 Android 乘客设备标识。"""
    monkeypatch.setenv("HK_ANDROID_UDID", "test-device")
    assert shared_settings()["device"]["udid"] == "test-device"


@pytest.mark.parametrize("driver,mode,expected", [
    ("", "auto", "shared"), ("passenger", "shared", "shared"),
    ("driver", "auto", "dual"), ("driver", "dual", "dual"),
])
def test_android_runtime(driver, mode, expected, monkeypatch):
    """验证单设备共享与双设备模式解析，以及 Android 司机连接地址。"""
    monkeypatch.delenv("HK_DRIVER_DEVICE_MODE", raising=False)
    monkeypatch.delenv("HK_DRIVER_ANDROID_UDID", raising=False)
    runtime = ui.resolve_runtime({"device": {"udid": "passenger"}, "driver": {"udid": driver, "device_mode": mode}})
    assert runtime.device_mode == expected
    assert runtime.shared_device == (expected == "shared")
    assert runtime.wda_url == "android://" + (driver or "passenger")


@pytest.mark.parametrize("driver,mode", [("", "dual"), ("driver", "shared"), ("", "invalid")])
def test_invalid_runtime_stops(driver, mode, monkeypatch):
    """验证设备标识与运行模式不匹配或模式无效时立即报错。"""
    monkeypatch.delenv("HK_DRIVER_DEVICE_MODE", raising=False)
    monkeypatch.delenv("HK_DRIVER_ANDROID_UDID", raising=False)
    with pytest.raises(RuntimeError):
        ui.resolve_runtime({"device": {"udid": "passenger"}, "driver": {"udid": driver, "device_mode": mode}})


@pytest.mark.parametrize("status", ["", "target\tunauthorized\n", "other\tdevice\n", "target\toffline\n"])
def test_missing_device_never_falls_back(status, monkeypatch):
    """验证目标设备缺失、未授权或离线时停止，不回退到其他设备。"""
    monkeypatch.setattr(ui.shutil, "which", lambda name: "/test/adb")
    run = Mock(return_value=SimpleNamespace(stdout="List of devices attached\n" + status))
    monkeypatch.setattr(ui.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="未连接或未授权"):
        ui.ensure_device("target", ("com.sunlightmobility.client",))
    assert run.call_count == 1


def test_missing_app_stops_before_ui_connection(monkeypatch):
    """验证目标设备未安装乘客应用时，设备预检查直接报错。"""
    monkeypatch.setattr(ui.shutil, "which", lambda name: "/test/adb")
    run = Mock(side_effect=[SimpleNamespace(stdout="List of devices attached\ntarget\tdevice\n"),
                            SimpleNamespace(stdout="")])
    monkeypatch.setattr(ui.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="未安装"):
        ui.ensure_device("target", ("com.sunlightmobility.client",))


@pytest.mark.parametrize("texts,phase", [
    (["點擊出車"], "offline"), (["接單中"], "online"), (["立即接單"], "offer"),
    (["到達上車地點"], "pickup"), (["已接載乘客"], "onboard"), (["到達目的地"], "destination"),
    (["確認賬單", "確認收款"], "bill"), (["已完成", "未支付"], "unpaid"),
    (["已完成", "已支付"], "complete"), (["已完成", "已支付", "未支付"], "unpaid"),
    (["已取消", "返回首頁"], "cancelled"), (["今日營收"], "unknown"),
])
def test_native_android_tree_uses_same_strict_phase_rules(texts, phase):
    """验证原生 Android 界面文本归一化后遵循共享阶段识别与冲突优先级。"""
    assert detect_phase(tree(*(native_node(text) for text in texts))) == phase


def test_driver_input_hint_survives_filled_value():
    """验证车费输入框已有内容时仍可通过提示语定位，并保留填写值。"""
    root = tree(native_node("5", "android.widget.EditText", **{"resource-id": "com.sunlightmobility.driver:id/et_input_fee"}))
    field = flow().field(root, "請輸入車費")
    assert field.get("value") == "5"


def test_hidden_offer_not_actionable():
    """验证隐藏的接单控件不会被识别为可操作的派单阶段。"""
    assert detect_phase(tree(native_node("立即接單", displayed="false"))) == "unknown"


def test_native_alert_blocks_shared_retry_rule():
    """验证原生弹窗归一化为共享告警节点，供流程阻止重复操作。"""
    root = tree(native_node("", "android.widget.LinearLayout", **{"resource-id": "android:id/parentPanel"}))
    assert any(node.tag == "XCUIElementTypeAlert" for node in root.iter())


def test_wrong_foreground_app_stops():
    """验证司机流程读取到乘客应用界面时拒绝继续操作。"""
    client = Mock()
    client.source.return_value = ET.tostring(tree(native_node("接單中"), package="com.sunlightmobility.client"), encoding="unicode")
    with pytest.raises(RuntimeError, match="不在前台"):
        flow(client).root()


def test_order_number_must_be_unique():
    """验证界面包含多个不同订单号时拒绝选择，避免关联错误订单。"""
    root = tree(native_node("26A6P22WECNY"), native_node("26A6P22WECNX"))
    with pytest.raises(RuntimeError, match="不唯一"):
        read_order_no(root)


def slider_root(thumb=True, displayed="true"):
    """构造带真实轨道边界的滑块界面，并按参数添加或隐藏滑块图标。"""
    track = native_node("", "android.widget.LinearLayout", **{
        "resource-id": "com.sunlightmobility.driver:id/ll_drag_view", "bounds": "[100,1800][1000,1920]"})
    track.append(native_node("到達上車地點", bounds="[350,1820][800,1900]"))
    if thumb:
        track.append(native_node("", "android.widget.ImageView", bounds="[110,1810][210,1910]", displayed=displayed))
    return tree(track)


def test_android_slider_ends_at_real_track_inner_edge():
    """验证滑动从原生滑块中心到真实轨道右侧内缘，且不点击替代控件。"""
    client = Mock()
    client.window_size.return_value = (1080, 2400)
    flow(client).act(slider_root(), ACTION_LABELS["pickup"])
    client.driver.execute_script.assert_called_once_with("mobile: dragGesture", {
        "startX": 160, "startY": 1860, "endX": 994, "endY": 1860, "speed": 1042})
    client.swipe.assert_not_called()
    client.click.assert_not_called()


@pytest.mark.parametrize("root", [slider_root(False), slider_root(True, "false"), tree(native_node("到達上車地點"))])
def test_missing_real_slider_does_not_guess(root):
    """验证真实滑块缺失或隐藏时直接报错，不猜测滑动坐标或改用点击。"""
    client = Mock()
    client.window_size.return_value = (1080, 2400)
    with pytest.raises(RuntimeError, match="滑块"):
        flow(client).act(root, ACTION_LABELS["pickup"])
    client.swipe.assert_not_called()
    client.click.assert_not_called()


def test_offer_click_is_not_repeated_or_swiped():
    """验证立即接单控件只点击一次，不重复提交或改为滑动。"""
    client = Mock()
    flow(client).act(tree(native_node("立即接單")), ("立即接單",))
    client.click.assert_called_once()
    client.swipe.assert_not_called()


def test_native_field_cleared_before_typing():
    """验证原生输入框按点击、清空、输入的顺序填写内容。"""
    native = Mock()
    ui.AndroidElement(Mock(), native).set_text("123456")
    assert native.mock_calls == [call.click(), call.clear(), call.send_keys("123456")]


def test_ambiguous_native_selector_never_clicks():
    """验证原生选择器匹配多个控件时拒绝点击，防止误触支付操作。"""
    driver = Mock()
    first = Mock(text="確認支付", id="first-payment")
    second = Mock(text="確認支付", id="second-payment")
    driver.find_elements.return_value = [first, second]
    with pytest.raises(RuntimeError, match="不唯一"):
        ui.AndroidClient(driver)(text="確認支付").click()
    first.click.assert_not_called()
    second.click.assert_not_called()


@pytest.mark.parametrize("texts", [["UNSUCCESSFUL"], ["SUCCESS", "支付失敗"], ["Incorrect OTP"], ["Authentication Failed"]])
def test_payment_failure_wins_over_success(texts):
    """验证支付失败或认证失败提示优先于成功文本，且不会继续点击。"""
    order = android_case(IOS_CASES[1])()
    page = ET.Element("hierarchy")
    page.extend(native_node(text) for text in texts)
    order._android_payment_guard = Mock(return_value=page)
    order.client = Mock()
    order._wait = lambda predicate, *args, **kwargs: predicate()
    order._click_text = Mock()
    with pytest.raises(RuntimeError, match="支付失败"):
        order._wait_payment_exit(["OTP"], require_success=False)
    order._click_text.assert_not_called()


def test_empty_payment_page_not_success():
    """验证空白支付页面不能视作成功退出，等待结果应保持超时失败。"""
    order = android_case(IOS_CASES[1])()
    order._android_payment_guard = Mock(return_value=ET.Element("hierarchy"))
    order.client = Mock()
    def wait(predicate, *args, **kwargs):
        """确认退出条件尚未满足，再模拟空白页面等待超时。"""
        assert predicate() is False
        raise TimeoutError("empty page")
    order._wait = wait
    with pytest.raises(TimeoutError):
        order._wait_payment_exit(["OTP"], require_success=False)


def test_bank_fields_and_otp_keep_verified_order():
    """验证银行卡字段、确认支付、验证码和认证提交遵循已验证的填写顺序。"""
    order = android_case(IOS_CASES[1])()
    actions = []
    order._wait = Mock(return_value=True)
    order._fill_payment_field = lambda placeholders, value: actions.append(placeholders[0])
    order._click_text = lambda labels: actions.append(labels[0])
    order._ios_handle_otp_page = lambda tag: actions.append("verified_otp")
    assert order._ios_fill_bank_card_form("offline")
    assert actions == ["卡號", "月 / 年", "CVV", "持卡人姓名", "請支付", "verified_otp"]


@pytest.mark.parametrize("dual,connections", [(False, 1), (True, 2)])
def test_single_device_session_reused_for_both_apps(dual, connections, monkeypatch):
    """验证单设备复用会话、双设备分别连接应用，并在清理时各退出一次。"""
    monkeypatch.delenv("HK_DRIVER_DEVICE_MODE", raising=False)
    monkeypatch.delenv("HK_DRIVER_ANDROID_UDID", raising=False)
    settings = shared_settings()
    settings["device"]["udid"] = "passenger"
    settings["driver"]["udid"] = "driver" if dual else ""
    monkeypatch.setattr(base, "shared_settings", lambda: settings)
    connect = Mock(side_effect=lambda *args, **kwargs: Mock())
    monkeypatch.setattr(ui.AndroidClient, "connect", connect)
    case = android_case(IOS_CASES[1])
    case.setup_class()
    assert connect.call_count == connections
    if dual:
        assert connect.call_args_list[0].args[2] != connect.call_args_list[1].args[2]
        assert connect.call_args_list[0].kwargs["packages"] == ("com.sunlightmobility.client",)
        assert connect.call_args_list[1].kwargs["packages"] == ("com.sunlightmobility.driver",)
    else:
        assert connect.call_args.kwargs["packages"] == ("com.sunlightmobility.client", "com.sunlightmobility.driver")
    clients = list(case.clients.values())
    case.teardown_class()
    for client in clients:
        client.quit.assert_called_once()
        client.app_activate.assert_not_called()


def test_unsupported_payment_stops_before_connect(monkeypatch):
    """验证不支持的支付方式在建立设备连接前即被拒绝。"""
    case = android_case(IOS_CASES[1])
    case.PAYMENT = "unsupported"
    connect = Mock()
    monkeypatch.setattr(ui.AndroidClient, "connect", connect)
    with pytest.raises(ValueError, match="不支持"):
        case.setup_class()
    connect.assert_not_called()


def test_collection_has_original_scenarios_and_android_target_case():
    """保留六个原订单场景，加一个安卓目标场景，不混入快照或旧用例。"""
    import sys
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", str(BASE_DIR / "pytest.ini"),
                             str(BASE_DIR / "cases"), "--collect-only", "-q"],
                            cwd=BASE_DIR, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    collected = [line for line in result.stdout.splitlines() if "::test_order_flow" in line]
    target = [line for line in collected if "::TestMeterEpaymentTargetOrderAndroid::" in line]
    assert len(target) == 1
    assert "JRYG_test_android_meter_epayment_target_order.py" in target[0]
    assert len(collected) - len(target) == len(IOS_CASES) == 6
    assert all("::IOS_SCENARIO::" not in line for line in collected)
    assert all("Android::test_order_flow" in line for line in collected)
    assert len({line.split("::")[0] for line in collected}) == 7
    assert not any("legacy/" in line or "_ios_verified_snapshot/" in line for line in collected)


def test_explicit_dual_android_parser_does_not_read_ios_wda(monkeypatch):
    """验证显式双设备配置生成 Android 司机地址，而不使用 iOS 驱动地址。"""
    monkeypatch.setenv("HK_DRIVER_DEVICE_MODE", "dual")
    monkeypatch.setenv("HK_DRIVER_ANDROID_UDID", "driver-device")
    order = android_case(IOS_CASES[1])()
    order.android_settings = shared_settings()
    args = order._driver_parser().parse_args([])
    assert args.wda_url == "android://driver-device"


def test_android_departure_slider_uses_native_resource_ids():
    """验证 Android 专用阶段检测通过原生资源标识识别已出发滑块。"""
    root = slider_root()
    target = next(node for node in root.iter() if node.get("label") == "到達上車地點")
    target.set("label", "已出發")
    assert detect_phase(root) == "unknown"
    assert flow().detect_phase(root) == "departure"


def test_paid_android_detail_returns_without_ios_coordinates():
    """验证已支付详情页通过 Android 返回操作退出，不沿用 iOS 点击坐标。"""
    client = Mock()
    flow(client).back_from_paid_detail(tree(native_node("26A6P22WECNY")))
    client.back.assert_called_once()
    client.click.assert_not_called()


@pytest.mark.parametrize("orders,allowed", [
    (["26A6P22WECNY"], True), (["26A6P22WECNX"], False),
    ([], False), (["26A6P22WECNY", "26A6P22WECNX"], False),
])
def test_android_payment_matches_current_driver_order(monkeypatch, orders, allowed):
    """验证付款界面的唯一订单号与当前司机订单一致，否则禁止付款。"""
    monkeypatch.setattr(OrderBase, "_ios_wait_current_payment", lambda self, tag: None)
    order = android_case(IOS_CASES[1])()
    order.driver_ui = Mock(order_no="26A6P22WECNY")
    order.client = Mock()
    order._ios_get_all_texts = Mock(return_value=["確認支付5HKD", *orders])
    if allowed:
        order._ios_wait_current_payment("offline")
    else:
        with pytest.raises(RuntimeError, match="禁止付款"):
            order._ios_wait_current_payment("offline")


def passenger_tree(*nodes):
    return tree(*nodes, package="com.sunlightmobility.client")


def quote_tree(price="包車價 50 HKD", start="北角(地鐵站) A1", end="香港大學", extra=()):
    car = native_node("", "android.widget.LinearLayout")
    car.extend([native_node("包車價的士"), native_node(price)])
    return passenger_tree(
        native_node(start, **{"resource-id": "com.sunlightmobility.client:id/tv_start_address"}),
        native_node(end, **{"resource-id": "com.sunlightmobility.client:id/tv_destination"}),
        car, native_node("確認呼叫", clickable="true"), *extra)


def address_row(district=E.NORTH_POINT_DISTRICT, exit_label=E.NORTH_POINT_EXIT):
    row = native_node("", "android.widget.LinearLayout")
    row.extend([native_node("北角(地鐵站)", **{"resource-id": "com.sunlightmobility.client:id/tv_title"}),
                native_node(district), native_node(exit_label, "android.widget.Button")])
    return row


@pytest.mark.parametrize("district,exit_label,allowed", [
    (E.NORTH_POINT_DISTRICT, E.NORTH_POINT_EXIT, True),
    ("西區", E.NORTH_POINT_EXIT, False), (E.NORTH_POINT_DISTRICT, "A2出入口", False),
])
def test_north_point_requires_same_station_district_and_exit(district, exit_label, allowed):
    from jryg_hk_android.JRYG_android_passenger import AndroidPassengerMixin
    root = passenger_tree(address_row(district, exit_label))
    result = AndroidPassengerMixin._native_address_result(root, ["北角(地鐵站)"], True)
    assert (result is not None) == allowed
    if allowed:
        assert result.get("label") == E.NORTH_POINT_EXIT


def test_north_point_duplicate_never_selects_first_result():
    from jryg_hk_android.JRYG_android_passenger import AndroidPassengerMixin
    with pytest.raises(AssertionError, match="不唯一"):
        AndroidPassengerMixin._native_address_result(
            passenger_tree(address_row(), address_row()), ["北角(地鐵站)"], True)


@pytest.mark.parametrize("value", ["香港大學", "北角舊搜索", ""])
def test_wrong_search_readback_stops(value):
    from jryg_hk_android.JRYG_android_passenger import AndroidPassengerMixin
    root = passenger_tree(native_node(value, "android.widget.EditText", **{
        "resource-id": "com.sunlightmobility.client:id/et_search"}))
    with pytest.raises(AssertionError, match="回读"):
        AndroidPassengerMixin._check_address_query(root, "北角")


@pytest.mark.parametrize("price,expected", [("包車價 50.00 HKD", "50"), ("包車價 0 HKD", None), ("加载中", None)])
def test_native_quote_requires_positive_same_car_price(price, expected):
    order = android_case(IOS_CASES[4])()
    quote = order._ios_estimate_quote(quote_tree(price), "charter")
    assert quote == ((("北角(地鐵站) A1", "香港大學"), expected) if expected is not None else None)


@pytest.mark.parametrize("blocked", ["預估資訊已更新，請重新選擇", "確認支付並呼叫", "支付失敗"])
def test_native_quote_not_ready_when_order_or_cashier_blocks(blocked):
    order = android_case(IOS_CASES[4])()
    assert order._ios_estimate_quote(quote_tree(extra=[native_node(blocked)]), "charter") is None


def test_refreshed_quote_uses_shared_stable_readback_and_one_call(monkeypatch):
    from ui_framework import JRYG_ios_ui_base as ios_base
    monkeypatch.setattr(ios_base.time, "sleep", lambda seconds: None)
    order = android_case(IOS_CASES[4])()
    root = quote_tree()
    order.client = Mock()
    order.client.source.return_value = ET.tostring(root, encoding="unicode")
    order._ios_call_route_key = order._ios_estimate_route_identity(root)
    order._ios_click_estimate_car = Mock()
    order._ios_click_estimate_call = Mock()
    assert order._ios_reselect_refreshed_estimate("offline", "charter") == "ready"
    order._ios_click_estimate_car.assert_called_once_with("charter")
    order._ios_click_refreshed_estimate_call("offline", "charter")
    order._ios_click_estimate_call.assert_called_once()
    with pytest.raises(AssertionError, match="不重复提交"):
        order._ios_click_refreshed_estimate_call("offline", "charter")
    order._ios_click_estimate_call.assert_called_once()


def test_changed_route_stops_estimate_retry(monkeypatch):
    order = android_case(IOS_CASES[4])()
    order.client = Mock()
    order.client.source.return_value = ET.tostring(quote_tree(end="銅鑼灣"), encoding="unicode")
    order._ios_call_route_key = ("北角(地鐵站) A1", "香港大學")
    order._ios_click_estimate_car = Mock()
    with pytest.raises(AssertionError, match="起终点已变化"):
        order._ios_reselect_refreshed_estimate("offline", "charter")
    order._ios_click_estimate_car.assert_not_called()


@pytest.mark.parametrize("texts,expected", [
    (["預估資訊已更新，請重新選擇"], "estimate_updated"),
    (["確認支付並呼叫"], "cashier"),
    (["支付失敗", "確認支付並呼叫"], "fail"),
    (["您还有未完成订单"], "ongoing_order"),
])
def test_order_result_is_identical_to_latest_ios(texts, expected, monkeypatch):
    from ui_framework import JRYG_ios_ui_base as ios_base
    monkeypatch.setattr(ios_base.time, "sleep", lambda seconds: None)
    order = android_case(IOS_CASES[4])()
    order.client = Mock()
    order._ios_get_all_texts = Mock(return_value=texts)
    assert order._ios_wait_order_result.__func__ is ios_base.iOSBase._ios_wait_order_result
    assert order._ios_wait_order_result("offline", max_checks=1) == expected


def test_alipay_wait_and_submission_are_shared_with_ios():
    from ui_framework.JRYG_ios_payment import HKIOSPaymentMixin
    order = android_case(IOS_CASES[4])()
    assert order._ios_complete_alipay_payment.__func__ is HKIOSPaymentMixin._ios_complete_alipay_payment
    assert order._ios_wait_and_click_alipay_pay_now.__func__ is HKIOSPaymentMixin._ios_wait_and_click_alipay_pay_now


def test_alipay_uncertain_tap_is_never_repeated():
    order = android_case(IOS_CASES[4])()
    order.client = Mock()
    element = Mock()
    element.click.side_effect = RuntimeError("response lost")
    order.client.source.return_value = "<XCUIElementTypeApplication/>"
    order.client.return_value.find_elements.return_value = [element]
    order._ios_wait_and_close_safari_alert = Mock()
    order._ios_wait_and_click_alipay_pay_now("offline")
    element.click.assert_called_once()


@pytest.mark.parametrize("alert,allowed", [(True, False), (False, True)])
def test_native_alipay_alert_blocks_payment(alert, allowed):
    order = android_case(IOS_CASES[4])()
    order.client = Mock()
    order.client.source.return_value = "<XCUIElementTypeAlert/>" if alert else "<XCUIElementTypeApplication/>"
    element = Mock()
    order.client.return_value.find_elements.return_value = [element]
    assert order._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False) == allowed
    assert element.click.call_count == int(allowed)
    order.client.click.assert_not_called()


def test_android_config_can_override_fare_without_mutating_verified_baseline(monkeypatch):
    from jryg_hk_android import JRYG_shared_ios as shared
    baseline = (shared.IOS_DIR / "config/JRYG_settings.yaml").read_bytes()
    monkeypatch.setitem(shared.ANDROID_SETTINGS["driver"], "fare", "999")
    assert shared.shared_settings()["driver"]["fare"] == "999"
    assert (shared.IOS_DIR / "config/JRYG_settings.yaml").read_bytes() == baseline


def test_missing_unfinished_entry_stops_without_payment():
    order = android_case(IOS_CASES[1])()
    order._ios_click_dialog_button = Mock(return_value=False)
    order._ios_complete_payment = Mock()
    with pytest.raises(RuntimeError, match="未定位遗留订单"):
        order._ios_handle_unfinished_order_popup("offline")
    order._ios_complete_payment.assert_not_called()


def test_unrelated_unpaid_order_is_not_automatically_paid():
    order = android_case(IOS_CASES[1])()
    order.client = Mock()
    order._assert_passenger_foreground = Mock()
    order._ios_get_all_texts = Mock(return_value=["費用明細", "確認支付5HKD"])
    order._wait = lambda predicate, *args, **kwargs: predicate()
    order._ios_complete_payment = Mock()
    with pytest.raises(RuntimeError, match="禁止自动付款"):
        order._clear_waiting_order("offline")
    order._ios_complete_payment.assert_not_called()


def test_android_runner_batch_order_and_gate_are_shared():
    import JRYG_run_main as runner
    from runners import JRYG_run_main_ios as ios_runner
    assert runner.run_batch is ios_runner.run_batch
    assert runner.CompletedOrderGate is ios_runner.CompletedOrderGate
    assert runner.batch_order is ios_runner.batch_order
    nodes = runner.scenario_nodes()
    assert len(nodes) == len(IOS_CASES) == 6
    ordered = runner.batch_order(nodes)
    assert "Charter" in ordered[0] and "Charter" in ordered[1]
    assert all("Meter" in node for node in ordered[2:])


@pytest.mark.parametrize("second_order,second_exit,expected,executed", [
    ("26A6P22WECNX", 0, 0, 3), ("26A6P22WECNY", 0, 1, 2), ("26A6P22WECNX", 1, 1, 2),
])
def test_shared_batch_stops_on_failed_or_duplicate_order(tmp_path, monkeypatch, second_order, second_exit, expected, executed):
    import json
    from runners import JRYG_run_main_ios as runner
    monkeypatch.delenv("HK_DRIVER_UI_STOP_AFTER", raising=False)
    sleeps = Mock()
    monkeypatch.setattr(runner.time, "sleep", sleeps)
    calls = []
    def run_case(case, args):
        calls.append(case)
        index = len(calls)
        order = "26A6P22WECNY" if index == 1 else second_order if index == 2 else "26A6P22WEAAA"
        code = second_exit if index == 2 else 0
        result_file = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result="))
        Path(result_file).write_text(json.dumps({"exit_code": code, "completed_orders": [{"order_no": order}]}))
        return code
    code = runner.run_batch(["first.py", "second.py", "third.py"], [],
                            run_case=run_case, report_dir=tmp_path, platform="android")
    assert code == expected
    assert len(calls) == executed
    assert all(item == call(10) for item in sleeps.call_args_list)
    result = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())
    assert result["exit_code"] == expected
    if expected:
        assert result["cases"][-1]["status"] == "not_run"
