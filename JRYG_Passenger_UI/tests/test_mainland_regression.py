from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

import pytest

from JRYG_Passenger_UI import JRYG_run_main as runner
from JRYG_Passenger_UI.cases import JRYG_test_order as order_module
from JRYG_Passenger_UI.cases import JRYG_debug_driver_login as debug_module
from JRYG_Passenger_UI.common import JRYG_adb_tools as adb_module
from JRYG_Passenger_UI.common import JRYG_config as config
from JRYG_Passenger_UI.common import JRYG_device_config as device_config
from JRYG_Passenger_UI.common import JRYG_driver_flow as flow_module
from JRYG_Passenger_UI.common import JRYG_connect_device as device_module


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(flow_module, "sleep", Mock())
    obj = flow_module.DriverFlowMixin()
    obj.driver_pkg = "com.jryg.driver"
    obj.adb = Mock()
    obj.adb.get_top_activity.return_value = "com.jryg.driver/.YGAHomePageActivity"
    obj.poco = Mock()
    return obj


@pytest.mark.parametrize("texts, expected", [
    ({"今日营收", "发起收款"}, "driver_bill"),
    ({"听单检测", "接单"}, "driver_accept_order"),
    ({"今日营收", "听单中"}, "driver_listening"),
    ({"听单检测"}, "driver_home"),
    ({"点击出车", "听单检测"}, "driver_home"),
    ({"到达上车地点"}, "driver_at_pickup"),
    ({"已接到乘客"}, "driver_wait_passenger"),
    ({"到达目的地"}, "driver_in_trip"),
    ({"准备出发"}, "driver_ready"),
    ({"请输入手机号后两位"}, "driver_verify_phone"),
    ({"请输入手机号码后两位"}, "driver_verify_phone"),
    ({"验证码已经发送"}, "driver_verify_code"),
    ({"好的", "发起收款"}, "driver_ok"),
    ({"拒绝", "同意", "今日营收"}, "driver_fee_abnormal"),
    ({"我知道了", "点击出车"}, "driver_known"),
    (set(), "driver_other"),
])
def test_driver_state_priority(flow, texts, expected):
    assert flow._driver_state("com.jryg.driver/.ygahomepageactivity", texts, set()) == expected


def test_driver_state_package_and_popup(flow):
    assert flow._driver_state("com.jryg.client/.login", {"登录/注册"}, set()) is None
    assert flow._driver_state("com.jryg.driver/.ygahomepageactivity", {"今日营收"},
                              {"com.jryg.driver:id/iv_cancel"}) == "driver_popup"


def test_page_content_reads_one_tree(flow):
    flow.poco.agent.hierarchy.dump.return_value = {
        "name": "root", "payload": {}, "children": [
            {"name": "button", "payload": {"text": " 返回首页 "}},
            {"payload": {"name": "com.jryg.driver:id/iv_cancel", "text": ""}},
        ]
    }
    texts, names = flow._page_content()
    assert texts == {"返回首页"}
    assert "com.jryg.driver:id/iv_cancel" in names
    flow.poco.agent.hierarchy.dump.assert_called_once_with()


@pytest.mark.parametrize("marker", ["topResumedActivity", "mResumedActivity", "ResumedActivity"])
def test_adb_activity_variants(marker):
    adb = adb_module.JRYG_ADBTools("test-device")
    line = f"{marker}: ActivityRecord{{x com.jryg.driver/.Home t1}}"
    adb.run_cmd = Mock(return_value=line)
    assert adb.get_top_activity() == line


def test_adb_top_activity_priority():
    adb = adb_module.JRYG_ADBTools("test-device")
    adb.run_cmd = Mock(return_value="ResumedActivity: old\ntopResumedActivity: current")
    assert adb.get_top_activity() == "topResumedActivity: current"


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("adb", 15),
                                   subprocess.CalledProcessError(1, "adb")])
def test_adb_errors_propagate(monkeypatch, error):
    monkeypatch.setattr(adb_module.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(type(error)):
        adb_module.JRYG_ADBTools("test-device").run_cmd(["dumpsys", "activity"])


def test_stall_reports_page(flow, monkeypatch):
    clock = Mock(side_effect=[0, 59, 60])
    monkeypatch.setattr(flow_module, "time", SimpleNamespace(monotonic=clock))
    flow._get_all_texts = Mock(return_value=["发起收款"])
    flow._check_stall("driver_bill")
    flow._check_stall("driver_bill")
    with pytest.raises(AssertionError, match="driver_bill.*60 秒"):
        flow._check_stall("driver_bill")


def test_state_change_resets_stall(flow, monkeypatch):
    monkeypatch.setattr(flow_module, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 59, 60])))
    flow._check_stall("driver_in_trip")
    flow._check_stall("driver_bill")
    flow._check_stall("driver_bill")
    assert flow._state_since == 59


@pytest.mark.parametrize("count", [0, 2, 5, 7])
def test_otp_rejects_partial_layout(flow, count):
    container = Mock()
    container.exists.return_value = True
    container.offspring.return_value = [Mock() for _ in range(count)]
    flow.poco.return_value = container
    with pytest.raises(RuntimeError, match="数量异常"):
        flow._input_driver_code()


def test_otp_six_boxes_resume_without_duplicate_first_digit(flow):
    container = Mock()
    container.exists.return_value = True
    inputs = [Mock() for _ in range(6)]
    for index, field in enumerate(inputs):
        field.get_text.return_value = "1" if index == 0 else ""
    container.offspring.return_value = inputs
    flow.poco.return_value = container
    flow._input_driver_code()
    inputs[0].set_text.assert_not_called()
    assert [call.args[0] for call in flow.adb.run_cmd.call_args_list] == [
        ["input", "text", digit] for digit in "23456"
    ]
    for field in inputs[1:]:
        field.click.assert_called_once_with()


@pytest.mark.parametrize("checked", [True, False])
def test_driver_login_order(flow, checked):
    calls = []
    phone, checkbox, next_button, missing = (Mock() for _ in range(4))
    missing.exists.return_value = False
    checkbox.attr.side_effect = lambda key: checked if key == "checked" else False
    phone.set_text.side_effect = lambda value: calls.append("phone")
    checkbox.click.side_effect = lambda: calls.append("agreement")
    next_button.click.side_effect = lambda: calls.append("next")
    controls = {"com.jryg.driver:id/et_phone_number": phone,
                "com.jryg.driver:id/cb_agree": checkbox,
                "com.jryg.driver:id/bt_next": next_button}
    flow.poco.side_effect = lambda *args, **kw: controls.get(args[0] if args else kw.get("name"), missing)
    flow.test_data = {"driver_phone": "11070893898"}
    assert flow._driver_login()
    assert calls == (["phone", "next"] if checked else ["phone", "agreement", "next"])


def test_debug_click_is_not_success(monkeypatch):
    obj = debug_module.DebugDriverFlow.__new__(debug_module.DebugDriverFlow)
    obj.driver_phone, obj.verify_code = "test", "123456"
    obj.logged_in, obj.drived_out = False, False
    for name in ("_force_stop_passenger", "_force_stop_driver", "_launch_driver", "_check_stall"):
        setattr(obj, name, Mock())
    obj._detect_state = Mock(return_value="driver_home")
    obj._request_drive_out = Mock(return_value=True)
    monkeypatch.setattr(debug_module, "sleep", Mock())
    assert obj.run() is False
    obj._detect_state = Mock(return_value="driver_listening")
    assert obj.run() is True


@pytest.mark.parametrize("states, success", [
    (["calling", "driver_in_trip", "driver_bill", "driver_home"], True),
    (["driver_bill", "driver_home"], False),
    (["calling", "driver_home"], False),
])
def test_order_completion_guard(monkeypatch, states, success):
    obj = order_module.TestJRYGOrderRide()
    obj.test_data = dict(start_address="start", dest_address="dest", verify_tail="38")
    obj.passenger_pkg, obj.driver_pkg = "com.jryg.client", "com.jryg.driver"
    obj.adb = Mock()
    obj._launch_app = Mock()
    obj._switch_to_driver = Mock()
    obj._detect_state = Mock(side_effect=states + ["driver_home"] * 60)
    obj._check_stall = Mock()
    obj._slide_drag_view = Mock(return_value=True)
    obj._request_drive_out = Mock(return_value=False)
    obj._return_to_passenger_home = Mock()
    obj._get_all_texts = Mock(return_value=[])
    obj.poco = Mock()
    obj.poco.return_value.exists.return_value = False
    monkeypatch.setattr(order_module, "sleep", Mock())
    if success:
        obj.test_complete_ride_flow()
        obj._return_to_passenger_home.assert_called_once_with()
    else:
        with pytest.raises(AssertionError, match="司机端订单流程未结束"):
            obj.test_complete_ride_flow()
        obj._return_to_passenger_home.assert_not_called()


def test_order_detection_uses_one_activity_and_tree(monkeypatch):
    obj = order_module.TestJRYGOrderRide()
    obj.driver_pkg, obj.passenger_pkg = "com.jryg.driver", "com.jryg.client"
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.YGAImmediateOrderProcessActivity")
    obj._page_content = Mock(return_value=({"行程结束", "返回首页"}, set()))
    assert obj._detect_state() == "trip_finished"
    obj._get_top_activity_full.assert_called_once_with()
    obj._page_content.assert_called_once_with(obj.passenger_pkg)


def test_runner_preserves_exit_code_and_excludes_debug(monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    fake_pytest = SimpleNamespace(main=Mock(return_value=1))
    monkeypatch.setattr(runner, "pytest", fake_pytest)
    assert runner.run_tests(["--collect-only"]) == 1
    args = fake_pytest.main.call_args.args[0]
    assert "python_files=JRYG_test_*.py" in args
    assert args[-1] == "--collect-only"


def test_device_config_uses_yaml():
    assert device_config.DEVICE_UDID == config.SETTINGS["device"]["udid"]
    assert device_config.APP_ACTIVITY == config.SETTINGS["packages"]["passenger_activity"]
    assert device_config.SYSTEM_PORT == config.SETTINGS["device"]["system_port"]


def test_appium_cleanup_is_scoped(monkeypatch):
    command = Mock()
    monkeypatch.setattr(device_module.subprocess, "run", command)
    device_module.AndroidDevice(system_port=9999)._clean_uiautomator2()
    commands = [call.args[0] for call in command.call_args_list]
    assert all("--remove-all" not in args and "pkill" not in args for args in commands)
    assert commands[-1][-2:] == ["--remove", "tcp:9999"]


def test_disconnect_clears_session():
    device = device_module.AndroidDevice()
    driver = Mock()
    device.driver = driver
    device.disconnect()
    device.disconnect()
    assert device.driver is None
    driver.quit.assert_called_once_with()


@pytest.mark.parametrize("initial", ["finish", "home", "ad", "monitor", "wrong_package"])
def test_return_to_passenger_home(monkeypatch, initial):
    obj = order_module.TestJRYGOrderRide()
    obj.udid, obj.passenger_pkg = "test-device", "com.jryg.client"
    page = [initial]
    ticks = iter(range(1000))
    monkeypatch.setattr(order_module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(order_module, "sleep", Mock())
    monkeypatch.setattr(order_module.subprocess, "run", Mock())
    monkeypatch.setattr(order_module, "keyevent", lambda key: page.__setitem__(0, "finish"))
    def activity():
        if page[0] == "monitor":
            return "com.jryg.client/blockcanary.DisplayActivity"
        if page[0] == "wrong_package":
            return "com.jryg.driver/.YGAHomeActivity"
        return "com.jryg.client/" + (".YGAHomeActivity" if page[0] == "home" else ".OrderActivity")
    def select(*args, **kw):
        rid = args[0] if args else ""
        button = Mock()
        button.exists.return_value = (
            (page[0] == "finish" and kw.get("text") == "返回首页")
            or (page[0] == "ad" and rid.endswith(":id/iv_cancel"))
            or (page[0] in ("home", "wrong_package") and rid.endswith(":id/ll_start"))
        )
        button.click.side_effect = lambda: page.__setitem__(0, "finish" if page[0] == "ad" else "home")
        return button
    obj.poco = select
    obj._get_top_activity_full = activity
    obj._get_all_texts = Mock(return_value=[])
    if initial == "wrong_package":
        with pytest.raises(pytest.fail.Exception, match="未返回首页"):
            obj._return_to_passenger_home()
    else:
        obj._return_to_passenger_home()
        assert page[0] == "home"
    assert "force-stop" not in order_module.subprocess.run.call_args.args[0]


def test_cancelled_order_is_not_calling():
    obj = order_module.TestJRYGOrderRide()
    obj.passenger_pkg, obj.driver_pkg = "com.jryg.client", "com.jryg.driver"
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.YGAImmediateOrderProcessActivity")
    obj._page_content = Mock(return_value=({"呼叫超时，已自动取消订单", "重新下单"}, set()))
    assert obj._detect_state() == "order_failed"


@pytest.fixture(autouse=True)
def isolate_regression_logs(monkeypatch):
    for module in (order_module, debug_module, flow_module, adb_module):
        monkeypatch.setattr(module, "logger", Mock())


@pytest.mark.parametrize("activity", ["YGAHomeActivity", "YGAImmediateOrderProcessActivity"])
@pytest.mark.parametrize("names", [set(), {"com.jryg.client:id/cashier_title", "com.jryg.client:id/btn_confirm"}])
def test_cashier_tip_is_not_trip_finished(activity, names):
    obj = order_module.TestJRYGOrderRide()
    obj.passenger_pkg, obj.driver_pkg = "com.jryg.client", "com.jryg.driver"
    obj._get_top_activity_full = Mock(return_value=f"com.jryg.client/.{activity}")
    texts = {"先付后乘", "微信支付", "确认支付并呼叫", "预付车费，行程结束按实际费用结算"}
    obj._page_content = Mock(return_value=(texts, names))
    assert obj._detect_state() == "cashier"


def test_settlement_tip_alone_does_not_mean_finished():
    obj = order_module.TestJRYGOrderRide()
    obj.passenger_pkg, obj.driver_pkg = "com.jryg.client", "com.jryg.driver"
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.YGAHomeActivity")
    obj._page_content = Mock(return_value=({"预付车费，行程结束按实际费用结算"}, set()))
    assert obj._detect_state() == "home"


@pytest.fixture
def cashier(monkeypatch):
    obj = order_module.TestJRYGOrderRide()
    obj.passenger_pkg = "com.jryg.client"
    monkeypatch.setattr(order_module, "sleep", Mock())
    obj._detect_state = Mock(side_effect=["cashier", "calling"])
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.YGAHomeActivity")
    obj._get_all_texts = Mock(return_value=["确认支付并呼叫"])
    obj._click_first = Mock(return_value=False)
    checkbox, title, row, button, missing = (Mock() for _ in range(5))
    for node in (checkbox, title, row, button):
        node.exists.return_value = True
    missing.exists.return_value = False
    checked = [False]
    events = []
    checkbox.attr.side_effect = lambda attr: checked[0] if attr == "checked" else True
    row.attr.return_value = "com.jryg.client:id/pay_root"
    row.offspring.return_value = checkbox
    title.parent.return_value.parent.return_value = row
    def select_wechat():
        events.append("select_wechat")
        checked[0] = True
    row.parent.return_value.click.side_effect = select_wechat
    button.attr.return_value = True
    button.click.side_effect = lambda: events.append("submit")
    def select(*args, **kw):
        if args == ("com.jryg.client:id/pay_title",) and kw.get("text") == "微信支付":
            return title
        if args == ("com.jryg.client:id/btn_confirm",) and kw.get("text") == "确认支付并呼叫":
            return button
        return missing
    obj.poco = Mock(side_effect=select)
    return SimpleNamespace(obj=obj, checkbox=checkbox, title=title, row=row, button=button,
                           checked=checked, events=events)


@pytest.mark.parametrize("already_checked", [False, True])
def test_cashier_selects_wechat_before_submit(cashier, already_checked):
    cashier.checked[0] = already_checked
    assert cashier.obj._handle_cashier() is True
    assert cashier.events == (["submit"] if already_checked else ["select_wechat", "submit"])
    cashier.button.click.assert_called_once_with()
    cashier.row.offspring.assert_called_with("com.jryg.client:id/pay_cb")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_called_once_with()


def test_cashier_missing_wechat_prevents_submit(cashier):
    cashier.title.exists.return_value = False
    with pytest.raises(RuntimeError, match="未找到微信支付"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_not_called()


def test_cashier_unchecked_prevents_submit(cashier):
    cashier.row.parent.return_value.click.side_effect = None
    with pytest.raises(RuntimeError, match="仍未勾选"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_not_called()


@pytest.mark.parametrize("problem", ["row", "checkbox", "button", "disabled"])
def test_cashier_invalid_controls_prevent_submit(cashier, problem):
    if problem == "row":
        cashier.row.attr.return_value = "other_row"
    elif problem == "checkbox":
        cashier.checkbox.exists.return_value = False
    elif problem == "button":
        cashier.button.exists.return_value = False
    else:
        cashier.button.attr.return_value = False
    with pytest.raises(RuntimeError):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_not_called()


def test_cashier_submission_timeout_is_not_retried(cashier):
    cashier.obj._detect_state.side_effect = None
    cashier.obj._detect_state.return_value = "cashier"
    with pytest.raises(RuntimeError, match="15秒内未进入呼叫页面"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_called_once_with()
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_called_once_with()


def test_cashier_external_wechat_is_not_payment_success(cashier):
    cashier.obj._detect_state.side_effect = ["cashier", "unknown"]
    cashier.obj._get_top_activity_full.return_value = "com.tencent.mm/.WalletActivity"
    with pytest.raises(RuntimeError, match="尚未完成外部支付"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_called_once_with()


def test_cashier_failed_call_is_not_success(cashier):
    cashier.obj._detect_state.side_effect = ["cashier", "order_failed"]
    with pytest.raises(RuntimeError, match="呼叫失败"):
        cashier.obj._handle_cashier()


def test_cashier_wrong_page_prevents_actions(cashier):
    cashier.obj._detect_state.side_effect = ["home"]
    with pytest.raises(RuntimeError, match="当前不是乘客收银台"):
        cashier.obj._handle_cashier()
    cashier.obj.poco.assert_not_called()


def test_cashier_click_error_is_not_retried(cashier):
    cashier.button.click.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError, match="connection lost"):
        cashier.obj._handle_cashier()
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        cashier.obj._handle_cashier()
    cashier.button.click.assert_called_once_with()


@pytest.mark.parametrize("pending_reads", [0, 2])
def test_cashier_requeries_snapshot_after_select(cashier, pending_reads):
    original_select = cashier.obj.poco.side_effect
    snapshots = []
    remaining = [pending_reads]
    def select(*args, **kw):
        if args == ("com.jryg.client:id/pay_title",) and kw.get("text") == "微信支付":
            title, row, checkbox = Mock(), Mock(), Mock()
            title.exists.return_value = True
            title.parent.return_value.parent.return_value = row
            row.attr.return_value = "com.jryg.client:id/pay_root"
            row.parent.return_value = cashier.row.parent.return_value
            row.offspring.return_value = checkbox
            checkbox.exists.return_value = True
            value = cashier.checked[0]
            if value and remaining[0]:
                remaining[0] -= 1
                value = False
            checkbox.attr.return_value = value
            snapshots.append(checkbox)
            return title
        return original_select(*args, **kw)
    cashier.obj.poco.side_effect = select
    assert cashier.obj._handle_cashier() is True
    assert snapshots[1].attr("checked") is False
    assert snapshots[-1].attr("checked") is True
    assert len(snapshots) == pending_reads + 3
    assert cashier.events == ["select_wechat", "submit"]
    cashier.row.parent.return_value.click.assert_called_once_with()
    cashier.button.click.assert_called_once_with()


def test_cashier_log_records_pre_submit_failure(cashier, monkeypatch):
    obj = cashier.obj
    obj.test_data = {"start_address": "start", "dest_address": "dest", "verify_tail": "38"}
    obj._launch_app = Mock()
    obj._check_stall = Mock()
    obj._detect_state = Mock(return_value="cashier")
    obj._handle_cashier = Mock(side_effect=RuntimeError("selection failed"))
    with pytest.raises(RuntimeError, match="selection failed"):
        obj.test_complete_ride_flow()
    order_module.logger.exception.assert_called_once_with("【收银台失败】已尝试提交=%s", False)


def test_flutter_desc_is_read_as_visible_text(flow):
    flow.poco.agent.hierarchy.dump.return_value = {"payload": {}, "children": [
        {"payload": {"desc": "已完成", "visible": True}},
        {"payload": {"desc": "已支付", "visible": True}},
        {"payload": {"desc": "返回首页", "visible": True}},
        {"payload": {"text": "已取消", "desc": "旧页面", "visible": False}},
    ]}
    assert flow._get_all_texts() == sorted(["已完成", "已支付", "返回首页"])


@pytest.mark.parametrize("activity,texts,expected", [
    ("ygatraveldetailflutteractivity", {"已完成", "已支付", "返回首页"}, "driver_finished"),
    ("ygatraveldetailflutteractivity", {"已完成", "返回首页"}, "driver_finished"),
    ("ygatraveldetailflutteractivity", {"返回首页", "元"}, "driver_other"),
    ("ygatraveldetailflutteractivity", {"已支付"}, "driver_other"),
    ("ygahomepageactivity", {"已完成", "返回首页"}, "driver_other"),
    ("ygatraveldetailflutteractivity", {"未确认账单", "已完成", "返回首页"}, "driver_bill"),
])
def test_driver_completed_page_requires_evidence(flow, activity, texts, expected):
    assert flow._driver_state(f"com.jryg.driver/.{activity}", texts, set()) == expected


@pytest.mark.parametrize("foreground", ["com.jryg.driver/.YGALoadingActivity",
                                         "com.android.permissioncontroller/.GrantPermissionsActivity"])
def test_switch_driver_preserves_passenger(monkeypatch, foreground):
    obj = order_module.TestJRYGOrderRide()
    obj.driver_pkg = "com.jryg.driver"
    obj.adb = Mock()
    obj._get_top_activity_full = Mock(side_effect=["com.jryg.client/.OrderActivity", foreground])
    monkeypatch.setattr(order_module, "sleep", Mock())
    obj._switch_to_driver()
    obj.adb.start_app.assert_called_once_with(obj.driver_pkg, config.SETTINGS["packages"]["driver_activity"])
    obj.adb.force_stop.assert_not_called()


def test_switch_driver_times_out_without_restarting(monkeypatch):
    obj = order_module.TestJRYGOrderRide()
    obj.driver_pkg = "com.jryg.driver"
    obj.adb = Mock()
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.OrderActivity")
    monkeypatch.setattr(order_module, "sleep", Mock())
    with pytest.raises(RuntimeError, match="切换司机端失败"):
        obj._switch_to_driver()
    obj.adb.start_app.assert_called_once()
    obj.adb.force_stop.assert_not_called()


@pytest.mark.parametrize("entry_state", ["calling", "cashier"])
def test_calling_continues_driver_slides_and_returns_home(monkeypatch, entry_state):
    obj = order_module.TestJRYGOrderRide()
    obj.test_data = {"start_address": "start", "dest_address": "dest", "verify_tail": "38"}
    obj.passenger_pkg, obj.driver_pkg = "com.jryg.client", "com.jryg.driver"
    obj._launch_app = Mock()
    obj._check_stall = Mock()
    events = []
    obj._switch_to_driver = Mock(side_effect=lambda: events.append("driver"))
    obj._handle_cashier = Mock(side_effect=lambda: events.append("payment"))
    obj._detect_state = Mock(side_effect=[entry_state, "driver_accept_order", "driver_ready",
                                         "driver_at_pickup", "driver_wait_passenger",
                                         "driver_in_trip", "driver_bill", "driver_finished"])
    def select(*args, **kwargs):
        node = Mock()
        label = kwargs.get("text")
        node.exists.return_value = label in ("抢单", "准备出发")
        node.click.side_effect = lambda: events.append(label)
        return node
    obj.poco = select
    obj._slide_drag_view = Mock(side_effect=lambda: events.append("slide") or True)
    obj._return_to_passenger_home = Mock(side_effect=lambda: events.append("passenger_home"))
    monkeypatch.setattr(order_module, "sleep", Mock())
    obj.test_complete_ride_flow()
    expected = (["payment"] if entry_state == "cashier" else []) + ["driver", "抢单", "准备出发"]
    assert events == expected + ["slide"] * 4 + ["passenger_home"]
    obj._switch_to_driver.assert_called_once_with()


def test_completed_page_alone_cannot_finish_new_order(monkeypatch):
    obj = order_module.TestJRYGOrderRide()
    obj.test_data = {"start_address": "start", "dest_address": "dest", "verify_tail": "38"}
    obj._detect_state = Mock(return_value="driver_finished")
    obj._check_stall = Mock()
    obj._get_top_activity_full = Mock(return_value="com.jryg.driver/.YGATravelDetailFlutterActivity")
    obj._get_all_texts = Mock(return_value=["已完成"])
    obj._return_to_passenger_home = Mock()
    monkeypatch.setattr(order_module, "sleep", Mock())
    with pytest.raises(AssertionError, match="司机端订单流程未结束"):
        obj._run_ride_flow()
    obj._return_to_passenger_home.assert_not_called()


def test_passenger_state_ignores_driver_floating_home_button():
    obj = order_module.TestJRYGOrderRide()
    obj.driver_pkg, obj.passenger_pkg = "com.jryg.driver", "com.jryg.client"
    obj._get_top_activity_full = Mock(return_value="com.jryg.client/.YGAHomeActivity")
    obj.poco = Mock()
    obj.poco.agent.hierarchy.dump.return_value = {"payload": {}, "children": [
        {"payload": {"package": "com.jryg.client", "name": "com.jryg.client:id/ll_start", "text": "从"}},
        {"payload": {"package": "com.jryg.driver", "name": "com.jryg.driver:id/iv_bottom", "text": "点击回首页"}},
        {"payload": {"package": "com.android.systemui", "desc": "订单已取消"}},
    ]}
    assert obj._detect_state() == "home"
    texts, names = obj._page_content(obj.passenger_pkg)
    assert texts == {"从"}
    assert names == {"com.jryg.client:id/ll_start"}


@pytest.mark.parametrize("page", ["home", "finished"])
def test_return_home_never_clicks_driver_floating_window(monkeypatch, page):
    obj = order_module.TestJRYGOrderRide()
    obj.udid, obj.passenger_pkg = "test-device", "com.jryg.client"
    current = [page]
    floating_button = Mock()
    floating_button.exists.return_value = True
    floating_button.click.side_effect = AssertionError("clicked driver floating window")
    def select(*args, **kwargs):
        if (kwargs.get("text") or kwargs.get("desc")) in ("点击回首页", "返回首页", "回到首页"):
            if kwargs.get("package") != obj.passenger_pkg:
                return floating_button
        node = Mock()
        node.exists.return_value = (
            current[0] == "finished" and kwargs.get("text") == "返回首页"
        ) or (current[0] == "home" and args == ("com.jryg.client:id/ll_start",))
        node.click.side_effect = lambda: current.__setitem__(0, "home")
        return node
    obj.poco = select
    obj._get_top_activity_full = lambda: "com.jryg.client/" + (
        ".YGAHomeActivity" if current[0] == "home" else ".YGAImmediateOrderProcessActivity"
    )
    ticks = iter(range(100))
    monkeypatch.setattr(order_module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(order_module, "sleep", Mock())
    monkeypatch.setattr(order_module.subprocess, "run", Mock())
    obj._return_to_passenger_home()
    assert current[0] == "home"
    floating_button.click.assert_not_called()


def test_click_first_supports_package_filter(flow):
    flow.poco.return_value.exists.return_value = True
    assert flow._click_first(texts=("返回首页",), package="com.jryg.client")
    flow.poco.assert_called_once_with(text="返回首页", package="com.jryg.client")


def test_return_home_reactivates_passenger_after_monitor_back(monkeypatch):
    obj = order_module.TestJRYGOrderRide()
    obj.udid, obj.passenger_pkg = "test-device", "com.jryg.client"
    obj._get_top_activity_full = Mock(side_effect=[
        "com.jryg.client/blockcanary.DisplayActivity", "com.jryg.driver/.DetailActivity",
        "com.jryg.client/.YGAHomeActivity"
    ])
    def select(*args, **kwargs):
        node = Mock()
        node.exists.return_value = args == ("com.jryg.client:id/ll_start",)
        return node
    obj.poco = select
    ticks = iter(range(100))
    monkeypatch.setattr(order_module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(order_module, "sleep", Mock())
    back = Mock()
    monkeypatch.setattr(order_module, "keyevent", back)
    launch = Mock()
    monkeypatch.setattr(order_module.subprocess, "run", launch)
    obj._return_to_passenger_home()
    back.assert_called_once_with("BACK")
    assert launch.call_count == 2
    assert all("force-stop" not in call.args[0] for call in launch.call_args_list)
