"""UI 时间线：只记录动作名称和时间，不记录函数参数、输入值或异常正文。"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import json
from pathlib import Path
import time
import uuid

import pytest

_ACTIVE = ContextVar("hk_ui_trace", default=None)
_CASE = ContextVar("hk_ui_trace_case", default="")
_PARENT = ContextVar("hk_ui_trace_parent", default=None)


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class UIRecorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.run_id = uuid.uuid4().hex
        self.steps = []
        self.warnings = []
        self._written = False
        self.started_at = now()
        self.finished_at = None

    def emit(self, row):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "ui_steps.jsonl").open("a" if self._written else "w", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._written = True
        except OSError:
            if "UI 时间线写入失败" not in self.warnings:
                self.warnings.append("UI 时间线写入失败")

    @contextmanager
    def activate(self, case=""):
        active = _ACTIVE.set(self)
        selected_case = _CASE.set(case)
        parent = _PARENT.set(None)
        try:
            yield
        finally:
            _PARENT.reset(parent)
            _CASE.reset(selected_case)
            _ACTIVE.reset(active)

    @contextmanager
    def step(self, name, role):
        row = {"run_id": self.run_id, "step_id": uuid.uuid4().hex,
               "parent_id": _PARENT.get(), "case": _CASE.get(), "name": name,
               "role": role, "started_at": now(), "status": "running"}
        self.steps.append(row)
        self.emit(dict(row, event="start"))
        parent = _PARENT.set(row["step_id"])
        started = time.monotonic()
        try:
            yield
        except BaseException as exc:
            row["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            row["error_type"] = type(exc).__name__
            raise
        else:
            if row["status"] == "running":
                row["status"] = "passed"
        finally:
            row["finished_at"] = now()
            row["duration_seconds"] = round(time.monotonic() - started, 3)
            self.emit(dict(row, event="end"))
            _PARENT.reset(parent)


@contextmanager
def ui_step(name, role):
    recorder = _ACTIVE.get()
    if recorder is None:
        yield
    else:
        with recorder.step(name, role):
            yield


PASSENGER_STEPS = {
    "_ios_prepare_passenger_app": "打开乘客 App",
    "_ios_ensure_logged_in": "核验乘客登录状态",
    "_ios_ui_login": "乘客登录",
    "_ui_cleanup_ongoing_order": "处理乘客遗留订单",
    "_ios_handle_unfinished_order_popup": "处理未完成订单提示",
    "_ios_configure_addresses": "设置起终点",
    "_ios_search_address": "搜索地址",
    "_ios_select_car_type": "选择车型与询价",
    "_ios_select_payment": "选择支付方式",
    "_click_call_and_check_login_then_retry": "下单并等待结果",
    "_charter_click_call_and_select_payment": "包车预付下单并等待结果",
    "_ios_click_confirm_call": "确认呼叫",
    "_ios_click_refreshed_estimate_call": "更新报价后确认呼叫",
    "_ios_click_confirm_pay": "确认支付并呼叫",
    "_ios_wait_order_result": "等待下单结果",
    "_ios_wait_current_payment": "等待订单费用页",
    "_ios_complete_payment": "完成乘客支付",
    "_ios_pay": "渠道支付",
    "_ios_fill_bank_card_form": "填写银行卡表单",
    "_ios_handle_otp_page": "完成支付验证",
    "_ios_complete_alipay_payment": "完成 Alipay HK 支付",
    "_ios_back_to_home": "乘客返回首页",
}
DRIVER_STEPS = {
    "_activate_driver_app": "打开司机 App",
    "login": "司机登录",
    "enter_code": "司机输入验证码",
    "enter_tail": "司机验证乘客尾号",
    "submit_bill": "司机填写与确认账单",
    "ensure_online": "司机登录与出车",
    "run": "司机接单与订单流转",
    "act": "司机点击或滑动",
    "fill": "填写司机输入框",
    "wait_for": "等待司机订单状态",
    "wait_completed": "核验订单完成与到账",
}
DRIVER_ACTIONS = {
    "點擊出車": "司机出车", "立即接單": "司机接单", "立即接单": "司机接单",
    "接單": "司机接单", "接单": "司机接单", "接受訂單": "司机接单",
    "出發接乘客": "司机出发接乘客", "出发接乘客": "司机出发接乘客",
    "已出發": "司机确认出发", "已出发": "司机确认出发",
    "到達上車地點": "司机到达上车点", "已接載乘客": "司机接载乘客",
    "到達目的地": "司机到达目的地", "確認收款": "司机确认账单或收款",
    "取得驗證碼": "司机获取验证码",
}


class UITracePlugin:
    def __init__(self, directory):
        self.recorder = UIRecorder(directory)
        self.clues = {"passenger": set(), "driver": set()}
        self._patches = []

    def _patch(self, cls, method, name, role):
        original = getattr(cls, method, None)
        if original is None or not callable(original):
            return
        owned = method in cls.__dict__

        @wraps(original)
        def wrapped(instance, *args, **kwargs):
            title = name
            if role == "driver" and method == "act":
                labels = kwargs.get("labels", args[1] if len(args) > 1 else ())
                title = next((DRIVER_ACTIONS[label] for label in labels if label in DRIVER_ACTIONS), name)
            with ui_step(title, role):
                return original(instance, *args, **kwargs)

        setattr(cls, method, wrapped)
        self._patches.append((cls, method, original, owned))

    def pytest_sessionstart(self, session):
        from ui_framework.JRYG_order_flow import TestOrderBase
        from ui_framework.JRYG_driver_ui import DriverUIFlow
        for method, name in PASSENGER_STEPS.items():
            self._patch(TestOrderBase, method, name, "passenger")
        for method, name in DRIVER_STEPS.items():
            self._patch(DriverUIFlow, method, name, "driver")
        self._patch(TestOrderBase, "_driver_ui_go_online", "司机登录与出车", "driver")
        self._patch(TestOrderBase, "_driver_ui_grab_and_flow", "司机接单与订单流转", "driver")

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        from ui_framework.JRYG_config import SETTINGS
        import os
        instance = item.instance
        passenger = os.environ.get("HK_PASSENGER_MOBILE") or getattr(instance, "LOGIN_PHONE", "")
        driver = os.environ.get("HK_DRIVER_MOBILE") or (SETTINGS.get("driver") or {}).get("mobile", "")
        for role, clue in (("passenger", passenger), ("driver", driver)):
            if clue:
                self.clues[role].add(str(clue))
        with self.recorder.activate(item.nodeid):
            with ui_step("用例准备、执行与清理", "session"):
                yield
                flow = getattr(instance, "driver_ui", None)
                order_no = getattr(flow, "order_no", None) or getattr(instance, "completed_order_no", None)
                if order_no:
                    for role in self.clues:
                        self.clues[role].add(str(order_no))
                args = getattr(flow, "args", None)
                mobile = getattr(args, "mobile", None)
                if mobile:
                    self.clues["driver"].add(str(mobile))

    def pytest_runtest_logreport(self, report):
        if report.failed:
            for row in reversed(self.recorder.steps):
                if row["role"] == "session" and row["case"] == report.nodeid:
                    row["status"] = "failed"
                    break

    def pytest_sessionfinish(self, session, exitstatus):
        self.recorder.finished_at = now()

    def pytest_unconfigure(self, config):
        for cls, method, original, owned in reversed(self._patches):
            if owned:
                setattr(cls, method, original)
            else:
                delattr(cls, method)
        self._patches.clear()
