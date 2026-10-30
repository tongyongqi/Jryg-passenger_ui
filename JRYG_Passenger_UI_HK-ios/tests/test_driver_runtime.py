"""司机全 UI 配置、单/双设备与账单参数的离线回归。

隔离环境变量及真实设备设置，验证WDA地址归一化、模式冲突、分阶段超时
和现金收款参数传递；所有设备/请求模拟，不调用司机业务登录接口。
"""

from unittest.mock import Mock

import pytest

from tools import JRYG_setup_driver as setup
from ui_framework import JRYG_driver_runtime as runtime
from tests.test_driver_readiness import OrderBase, order_module


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    """清除真实设备与金额环境变量，运行时测试只使用显式模拟配置。"""
    for name in ("HK_DRIVER_WDA_URL", "HK_DRIVER_DEVICE_MODE", "HK_ORDER_AMOUNT", "HK_OTHER_AMOUNT", "HK_DRIVER_PASSENGER_TAIL", "HK_DRIVER_CASH_COLLECTED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime, "settings_or_default", lambda settings=None: settings or {})


def test_missing_wda_defaults_to_passenger_for_sequential_device():
    """未配置司机WDA时共用乘客设备，且运行配置不依赖接口会话文件。"""
    result = runtime.resolve_runtime({"device": {"wda_url": "http://127.0.0.1:8100"}})
    assert result.shared_device
    assert result.wda_url == "http://127.0.0.1:8100"
    assert not hasattr(result, "session_file")


def test_explicit_wda_selects_dual_device(monkeypatch):
    """通过环境变量配置不同司机WDA时，auto模式应解析为双设备。

    :param monkeypatch: 临时设置环境变量，测试结束后自动恢复。
    """
    monkeypatch.setenv("HK_DRIVER_WDA_URL", "http://127.0.0.1:8200")
    assert runtime.resolve_runtime().device_mode == "dual"


def test_yaml_driver_configuration():
    """验证配置字典中的司机设备模式与WDA地址原样用于运行配置。"""
    result = runtime.resolve_runtime({"driver": {"device_mode": "dual", "wda_url": "http://127.0.0.1:8200"}})
    assert result.device_mode == "dual"
    assert result.wda_url == "http://127.0.0.1:8200"


def test_environment_overrides_yaml(monkeypatch):
    """环境变量优先于YAML，localhost及尾斜杠归一化后仍能识别共用设备。

    :param monkeypatch: 临时提供覆盖配置的设备地址与模式。
    """
    monkeypatch.setenv("HK_DRIVER_DEVICE_MODE", "shared")
    monkeypatch.setenv("HK_DRIVER_WDA_URL", "http://localhost:8100/")
    result = runtime.resolve_runtime({"driver": {"device_mode": "dual", "wda_url": "http://127.0.0.1:8200"}})
    assert result.shared_device


@pytest.mark.parametrize("mode,url", [("dual", "http://localhost:8100/"), ("shared", "http://127.0.0.1:8200"), ("unknown", "http://127.0.0.1:8100")])
def test_invalid_device_mode_is_not_silently_accepted(monkeypatch, mode, url):
    """未知模式、双设备共用地址或共享模式地址不同都必须拒绝，不能静默降级。

    :param monkeypatch: 临时设置设备运行环境。
    :param mode: 参数化的冲突或未知设备模式。
    :param url: 与该模式不匹配的司机WDA地址。
    """
    monkeypatch.setenv("HK_DRIVER_DEVICE_MODE", mode)
    monkeypatch.setenv("HK_DRIVER_WDA_URL", url)
    with pytest.raises(RuntimeError):
        runtime.resolve_runtime()


@pytest.mark.parametrize("url", ["ftp://localhost:8100", "http://user:secret@localhost:8100", "http://localhost:8100/source", "http://localhost:bad", "http://localhost:8100?x=1"])
def test_wda_configuration_rejects_invalid_service_roots(url):
    """拒绝非HTTP、携带凭据、业务路径、非法端口及查询参数的WDA地址。

    :param url: 仅用于验证格式的错误地址，不会发送请求。
    """
    with pytest.raises(RuntimeError):
        runtime.normalized_wda(url)


def test_setup_needs_no_token_or_session(monkeypatch, capsys):
    """配置检查不依赖token，即使提供无效接口凭据也能输出全UI设备说明。

    :param monkeypatch: 注入无效且不应被读取的测试token。
    :param capsys: 捕获输出以核验设备检查入口的说明。
    """
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", "invalid\nunused")
    assert setup.main([]) == 0
    assert "全 UI" in capsys.readouterr().out


def test_device_check_only_calls_wda(monkeypatch):
    """只读设备检查仅请求WDA状态，并使用5秒时限，不访问司机业务服务。

    :param monkeypatch: 替换HTTP请求，防止测试连接真实设备。
    """
    import requests
    reply = Mock()
    reply.json.return_value = {"value": {"ready": True}}
    get = Mock(return_value=reply)
    monkeypatch.setattr(requests, "get", get)
    assert setup.main(["--check-devices"]) == 0
    # 共享设备只探测一个地址，既不重复请求，也不获取接口会话。
    get.assert_called_once_with("http://127.0.0.1:8100/status", timeout=5)


@pytest.mark.parametrize("option", ["--check-api", "--save-session", "--from-har", "--session-file"])
def test_removed_session_setup_options_are_rejected(option):
    """旧API和会话参数应被命令行解析拒绝，不能恢复接口降级路径。

    :param option: 已移除的接口或会话选项。
    """
    with pytest.raises(SystemExit):
        setup.main([option])


def test_driver_ui_go_online_does_not_load_token(monkeypatch):
    """司机出车入口只调用UI状态机，即使存在无效token也不加载业务API。

    :param monkeypatch: 替换设备状态机及配置，避免真实出车。
    """
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", "invalid\nunused")
    monkeypatch.setattr(order_module, "SETTINGS", {})
    driver = Mock()
    monkeypatch.setattr(order_module, "DriverUIFlow", Mock(return_value=driver))
    instance = OrderBase()
    instance._driver_ui_go_online("test")
    driver.ensure_online.assert_called_once()
    assert "driver_api" not in vars(instance)


def test_order_ui_uses_configured_fare_and_tail(monkeypatch):
    """订单编排将车费、附加费、尾号和提交后停止阶段正确传给司机UI。

    :param monkeypatch: 提供测试配置并用模拟司机替代真机执行。
    """
    monkeypatch.setattr(order_module, "SETTINGS", {"driver": {"fare": "5", "surcharge": "0", "passenger_tail": "1234"}})
    driver = Mock(last_phase="unpaid")
    factory = Mock(return_value=driver)
    monkeypatch.setattr(order_module, "DriverUIFlow", factory)
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    instance._driver_ui_grab_and_flow("test")
    # 检查构造状态机时的解析结果，而非只判断模拟run是否被调用。
    args = factory.call_args.args[0]
    assert (args.fare, args.surcharge, args.tail, args.stop_after) == ("5", "0", "1234", "submitted")
    driver.run.assert_called_once()
    assert "driver_api" not in vars(instance)


def test_amount_environment_overrides_yaml(monkeypatch):
    """临时指定的车费和附加费应覆盖YAML默认账单金额。

    :param monkeypatch: 注入不同于默认值的金额及模拟司机状态机。
    """
    monkeypatch.setattr(order_module, "SETTINGS", {"driver": {"fare": "5", "surcharge": "0"}})
    monkeypatch.setenv("HK_ORDER_AMOUNT", "6")
    monkeypatch.setenv("HK_OTHER_AMOUNT", "1")
    driver = Mock(last_phase="unpaid")
    factory = Mock(return_value=driver)
    monkeypatch.setattr(order_module, "DriverUIFlow", factory)
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    instance._driver_ui_grab_and_flow("test")
    args = factory.call_args.args[0]
    assert (args.fare, args.surcharge) == ("6", "1")


def test_failed_ui_saves_scene_without_api_fallback(monkeypatch):
    """模拟司机UI执行失败，错误必须向上传递并保存现场，不能切换API继续。

    :param monkeypatch: 注入会抛错的模拟状态机，避免推进真实订单。
    """
    monkeypatch.setattr(order_module, "SETTINGS", {})
    driver = Mock(last_phase="bill")
    driver.run.side_effect = RuntimeError("UI failed")
    monkeypatch.setattr(order_module, "DriverUIFlow", Mock(return_value=driver))
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    with pytest.raises(RuntimeError, match="UI failed"):
        instance._driver_ui_grab_and_flow("test")
    # 取证不替代失败：异常仍需抛出，不能仅留截图后报告通过。
    driver.snapshot.assert_called_once_with("failed_order_flow")


def test_unsubmitted_bill_cannot_pass_order_ui_stage(monkeypatch):
    """司机仍停在账单编辑页时，不能把UI方法返回当成账单提交成功。

    :param monkeypatch: 模拟未提交账单的状态机，验证订单编排拒绝继续付款。
    """
    monkeypatch.setattr(order_module, "SETTINGS", {})
    monkeypatch.setattr(order_module, "DriverUIFlow", Mock(return_value=Mock(last_phase="bill")))
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    with pytest.raises(AssertionError, match="账单提交成功"):
        instance._driver_ui_grab_and_flow("test")


def test_accept_debug_parameter_is_forwarded_to_driver_ui(monkeypatch):
    """仅接单调试选项应传给司机UI，使流程停在接单后而非继续提交账单。

    :param monkeypatch: 注入停止阶段并模拟司机接单后的状态。
    """
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "accepted")
    monkeypatch.setattr(order_module, "SETTINGS", {})
    driver = Mock(last_phase="pickup")
    factory = Mock(return_value=driver)
    monkeypatch.setattr(order_module, "DriverUIFlow", factory)
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    instance._driver_ui_grab_and_flow("test")
    assert factory.call_args.args[0].stop_after == "accepted"
    driver.run.assert_called_once()


def test_order_forwards_per_stage_timeouts(monkeypatch):
    """订单配置的总流程、单步、派单和到账时限必须分别传给司机状态机。

    :param monkeypatch: 提供分阶段时限并替换真实状态机。
    """
    limits = {"total_timeout": 900, "state_timeout": 30, "dispatch_timeout": 90, "completion_timeout": 90}
    monkeypatch.setattr(order_module, "SETTINGS", {"order_validation": limits})
    factory = Mock(return_value=Mock(last_phase="unpaid"))
    monkeypatch.setattr(order_module, "DriverUIFlow", factory)
    instance = OrderBase()
    instance.PAYMENT = "epayment"
    instance.driver_runtime = runtime.resolve_runtime()
    instance._driver_ui_grab_and_flow("test")
    args = factory.call_args.args[0]
    assert (args.timeout, args.step_timeout, args.dispatch_timeout, args.payment_timeout) == (900, 30, 90, 90)
