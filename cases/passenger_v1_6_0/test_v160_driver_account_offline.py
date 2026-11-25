"""司机账号来源工程回归：两个阶段读取同一配置，不连接设备、不登录。

来源：2026-11-23 用户更换测试司机包并提供司机测试账号。
使用合成账号；不在测试代码中固化真实手机号或验证码。
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from passenger_android_core.main_flow.order_flow import TestOrderBase as OrderFlow


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    import subprocess
    import socket
    import pymysql
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("账号离线验证禁止登录、设备、网络和数据库操作")

    monkeypatch.delenv("HK_DRIVER_UI_MOBILE", raising=False)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(pymysql, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture
def case(monkeypatch):
    settings = {"driver": {"mobile": "fixture-mobile"}}
    monkeypatch.setattr(OrderFlow, "order_settings", property(lambda self: settings))
    value = object.__new__(OrderFlow)
    value.CAR_TYPE, value.PAYMENT = "charter", "alipay"
    value._resolve_driver_runtime = Mock(return_value=SimpleNamespace(wda_url="fixture-driver"))
    parser = Mock()

    def parse(args):
        return SimpleNamespace(mobile=args[args.index("--mobile") + 1])

    parser.parse_args.side_effect = parse
    value._driver_parser = Mock(return_value=parser)
    value.driver_ui = Mock(last_phase="unpaid")
    value.driver_ui.ensure_online.return_value = False
    value._create_driver_flow = Mock(return_value=value.driver_ui)
    return value


@pytest.mark.parametrize("source", ["configuration", "environment"])
def test_both_stages_use_same_mobile_source(case, monkeypatch, source):
    if source == "environment":
        monkeypatch.setenv("HK_DRIVER_UI_MOBILE", "fixture-override")
    expected = "fixture-override" if source == "environment" else "fixture-mobile"
    case._driver_ui_go_online("fixture")
    initial = case._create_driver_flow.call_args.args[0]
    assert initial.mobile == expected
    case.driver_ui.ensure_online.assert_called_once_with(resume_existing=False)
    case._driver_ui_grab_and_flow("fixture")
    assert case.driver_ui.args.mobile == expected
    case.driver_ui.run.assert_called_once()
    calls = case._driver_parser.return_value.parse_args.call_args_list
    assert len(calls) == 2
    assert all(call.args[0][call.args[0].index("--mobile") + 1] == expected for call in calls)


@pytest.mark.parametrize("value", [None, "", " ", " fixture", "fixture ", 123])
def test_invalid_config_stops_before_device_preparation(case, value):
    case.order_settings["driver"]["mobile"] = value
    with pytest.raises(ValueError, match="driver.mobile"):
        case._driver_ui_go_online("fixture")
    case._resolve_driver_runtime.assert_not_called()
    case._create_driver_flow.assert_not_called()
    case.driver_ui.ensure_online.assert_not_called()


def test_missing_mobile_has_no_historical_default(case):
    case.order_settings["driver"].pop("mobile")
    with pytest.raises(ValueError, match="driver.mobile"):
        case._driver_login_mobile()


@pytest.mark.parametrize("override", ["", " ", " fixture"])
def test_invalid_explicit_override_cannot_fall_back(case, monkeypatch, override):
    monkeypatch.setenv("HK_DRIVER_UI_MOBILE", override)
    with pytest.raises(ValueError, match="HK_DRIVER_UI_MOBILE"):
        case._driver_ui_go_online("fixture")
    case.driver_ui.ensure_online.assert_not_called()


def test_invalid_grab_account_cannot_advance_orders(case):
    case.driver_runtime = SimpleNamespace(wda_url="fixture-driver")
    case.order_settings["driver"].pop("mobile")
    with pytest.raises(ValueError, match="driver.mobile"):
        case._driver_ui_grab_and_flow("fixture")
    case.driver_ui.run.assert_not_called()
    case._driver_parser.assert_not_called()
