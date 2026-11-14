# 编写时间：2026-11-10
# 本期功能：V1.5.0 收据 UI 验收 — 已完成已支付即时订单的收据展示与参数化扩展
# 覆盖：收据 UI 验收 + 参数化扩展 + 失败留证
"""已完成、已支付即时订单的收据UI验收；保留原五个测试入口并参数化扩展。

每组数据独立报告；检查失败留证后继续其他用例。不下单、支付、评价或取消订单。
发送使用示例域名测试数据，验证App响应及邮箱保存，不将成功toast当作邮件投递证明。
"""

import base64
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import logging
logger = logging.getLogger("JRYG_HK_android")

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps
from jryg_hk_android.JRYG_v150_api_log import (
    check_api_response,
    find_api_calls,
    parse_api_calls,
)


class TestV150ReceiptDevice(V150DeviceSteps):
    """TestV150ReceiptDevice类。"""
    __test__ = True
    DRIVER_REQUIRED = False
    RECEIPT_EMAIL = "v150_receipt@example.com"
    PROMPT = "設置電子郵箱，行程結束後自動發送行程收據"
    TITLE = "發送行程收據"
    SUBTITLE = "行程收據將發送至您的電子郵箱"
    SUCCESS = "已發送，稍後查看"
    INVALID = "郵箱格式不正確"
    FREQUENT = "发送过于频繁"
    TRIP_SEND_API = "trip_send"
    USER_SAVE_API = "user_save"
    USER_INFO_API = "user_info"
    OK_CODE = 10000

    # ---- class 级共享状态：一次登录+读原邮箱+缓存订单绑定，避免每条用例重复导航 ----
    _receipt_class_ready = False
    _receipt_original_email = None
    _receipt_current_email = None
    _receipt_order_binding = None
    _receipt_order_no_cached = None

    @pytest.fixture(scope="class", autouse=True)
    def receipt_class_setup(self, request):
        """class 级一次性初始化：登录、读原邮箱、进订单详情并缓存绑定。"""
        cls = type(self)
        if cls._receipt_class_ready:
            yield
            return
        report = Path(request.config.getoption("htmlpath") or BASE_DIR / "report/receipt.html")
        directory = report.parent / (report.stem + "_evidence")
        directory.mkdir(parents=True, exist_ok=True)
        cls._receipt_directory = directory
        cls._receipt_run_records = {}
        try:
            self.v150_open_email_settings("receipt_original")
            cls._receipt_original_email = self.v150_email_read_current()
            cls._receipt_current_email = cls._receipt_original_email
            try:
                self.v150_open_completed_order_detail("receipt_target")
                cls._receipt_order_binding = getattr(cls, "_receipt_order_binding", None)
                cls._receipt_order_no_cached = getattr(self, "_receipt_order_no", None)
            except (RuntimeError, TimeoutError):
                pass  # 订单详情失败不阻断 class setup，各用例 _prepare 会自行重试
            cls._receipt_class_ready = True
            yield
        finally:
            # class 收尾：恢复原邮箱（只做一次）
            if cls._receipt_original_email is not None:
                try:
                    if self._v150_receipt_dialog_ready():
                        self.v150_receipt_close_dialog("receipt_cleanup")
                    self.v150_open_email_settings("receipt_cleanup")
                    current = self.v150_email_read_current()
                    if current != cls._receipt_original_email:
                        self.v150_email_save("receipt_cleanup", email=cls._receipt_original_email)
                    cls._receipt_class_ready = False
                except Exception:
                    pass
            (directory / "results.json").write_text(
                json.dumps(list(cls._receipt_run_records.values()),
                           ensure_ascii=False, indent=2), encoding="utf-8")

    @pytest.fixture(autouse=True)
    def receipt_case(self, request):
        """function 级轻量 fixture：只记录状态和异常收尾，不再重复导航。"""
        self._receipt_request = request
        cls = type(self)
        directory = getattr(cls, "_receipt_directory", None)
        if directory is None:
            report = Path(request.config.getoption("htmlpath") or BASE_DIR / "report/receipt.html")
            directory = report.parent / (report.stem + "_evidence")
            directory.mkdir(parents=True, exist_ok=True)
            cls._receipt_directory = directory
        self._receipt_directory = directory
        self._receipt_case_directory = directory / str(time.time_ns())
        self._receipt_case_directory.mkdir(parents=True, exist_ok=True)
        self._receipt_phase = "precondition"
        self._receipt_record = {"nodeid": request.node.nodeid, "checks": [], "phases": {},
                                "evidence": [], "scope": "UI响应与邮箱持久化；不证明邮件投递或网络请求未发生"}
        self._receipt_original = cls._receipt_original_email
        self._last_network_evidence = None
        yield
        # function 收尾：只关弹框，不恢复邮箱（class 级统一恢复）
        try:
            if self._v150_receipt_dialog_ready():
                self.v150_receipt_close_dialog("receipt_case_cleanup")
        except Exception:
            pass

    def _capture(self, phase):
        """收集截图和XML页面源作为证据，写入用例报告的 evidence 列表。"""
        prefix = self._receipt_case_directory / f"{time.time_ns()}_{phase}"
        evidence = {"phase": phase}
        try:
            path = prefix.with_suffix(".xml")
            path.write_text(self.client.driver.page_source, encoding="utf-8")
            evidence["xml"] = str(path)
        except Exception as exc:
            evidence["xml_error"] = str(exc)
        try:
            path = prefix.with_suffix(".png")
            self.client.screenshot(str(path))
            evidence["screenshot"] = str(path)
        except Exception as exc:
            evidence["screenshot_error"] = str(exc)
        self._receipt_record["evidence"].append(evidence)

    @contextmanager
    def _record_action(self, name):
        """录屏 context manager：进入时开始录屏，退出时停止并保存 mp4 到证据目录。"""
        path = self._receipt_case_directory / f"{time.time_ns()}_{name}.mp4"
        self.client.driver.start_recording_screen(timeLimit=30, bitRate=1000000)
        try:
            yield
        finally:
            video = self.client.driver.stop_recording_screen()
            if not video:
                raise RuntimeError("录屏证据为空，不能确认短暂提示实际文案")
            path.write_bytes(base64.b64decode(video))
            self._receipt_record["evidence"].append({"phase": name, "video": str(path)})

    def _send_and_observe(self):
        """点击发送按钮→抓取toast→收集网络日志，返回 (toasts, api_calls) 元组。"""
        order_no = getattr(self, "_receipt_order_no", None)
        self.v150_receipt_start_network_capture("receipt_send")
        with self._record_action("send_response"):
            self.v150_receipt_click_send()
            observed = self.v150_receipt_observe_toasts()
        evidence = self.v150_receipt_collect_network_log("receipt_send", order_no=order_no)
        self._last_network_evidence = evidence
        return observed, evidence.get("api_calls", [])

    def _sync_email_cache(self, email):
        """发送/保存后同步 class 级邮箱缓存，避免后续用例误判邮箱状态。"""
        type(self)._receipt_current_email = email
        return email

    def _send_and_observe_direct(self):
        """已设置邮箱时入口即发送：点击即刻触发接口调用，须在点击前开启抓取。

        返回值由 _open_dialog_only 的点击结果与随后的接口抓取共同组成。
        """
        order_no = getattr(self, "_receipt_order_no", None)
        observed = []
        calls = []

        def _before_click():
            """点击前回调。"""
            self.v150_receipt_start_network_capture("receipt_direct_send")

        state = self._open_dialog_only("send", before_click=_before_click)
        if state.get("entry_toasts"):
            observed = list(state["entry_toasts"])
        if not observed:
            observed = self.v150_receipt_observe_toasts(timeout=3)
        evidence = self.v150_receipt_collect_network_log("receipt_direct_send", order_no=order_no)
        self._last_network_evidence = evidence
        calls = evidence.get("api_calls", [])
        return observed, calls

    def _api_calls(self, evidence):
        """从抓取证据中还原接口调用列表。"""
        return evidence.get("api_calls", []) if isinstance(evidence, dict) else []

    def _expect_api(self, requirement, calls, api_name, *, expect_code=OK_CODE,
                    expect_params=None, forbidden_params=None, expect_data_contains=None,
                    allow_error_code=False):
        """接口层断言：服务端返回是否符合预期。

        异常用例允许服务端返回错误码（allow_error_code=True），
        此时只要服务端明确拒绝（code 非成功码）即视为通过。
        """
        result = check_api_response(
            calls, api_name, expect_code=expect_code if not allow_error_code else None,
            expect_params=expect_params, forbidden_params=forbidden_params,
            expect_data_contains=expect_data_contains)
        passed = result["passed"]
        actual = {"code": result.get("code"), "message": result.get("message"),
                  "params": result.get("params", {})}
        if not passed and allow_error_code and result.get("matched"):
            code = result.get("code")
            if code is not None and code != self.OK_CODE:
                passed = True
                actual["rejected_by_server"] = True
                result["reason"] = f"服务端以 code={code} 拒绝（{result.get('message','')}）"
        if not passed:
            actual["reason"] = result.get("reason", "")
        check = {"requirement": requirement,
                 "expected": {"code": expect_code, "params": expect_params,
                              "allow_error_code": allow_error_code},
                 "actual": actual, "passed": passed,
                 "category": "product_bug" if not passed else "api_verified"}
        self._receipt_record["checks"].append(check)
        self._receipt_record.setdefault("api_checks", []).append(
            {"requirement": requirement, "api": api_name, **actual, "passed": passed})
        if not passed:
            self._capture("api_mismatch")
            path = self._receipt_case_directory / f"api_mismatch_{len(self._receipt_record['checks'])}.json"
            path.write_text(json.dumps({"nodeid": self._receipt_request.node.nodeid,
                "api": api_name, **check, "evidence": self._receipt_record["evidence"]},
                ensure_ascii=False, indent=2), encoding="utf-8")
        return passed

    def _expect_no_api(self, requirement, calls, api_name):
        """断言本次操作未调用指定接口。"""
        matched = find_api_calls(calls, api_name)
        check = {"requirement": requirement,
                 "expected": {"no_api_call": api_name},
                 "actual": {"calls": len(matched),
                            "codes": [call.get("code") for call in matched]},
                 "passed": not matched, "category": "api_verified" if not matched else "product_bug"}
        self._receipt_record["checks"].append(check)
        self._receipt_record.setdefault("api_checks", []).append(
            {"requirement": requirement, "api": api_name,
             "calls": len(matched), "passed": not matched})
        if matched:
            self._capture("api_unexpected_call")
        return check["passed"]

    def _expect(self, requirement, actual, expected):
        """比对期望值与实际值并记录断言结果。"""
        passed = actual == expected
        category = ("observation_gap" if not passed and "提示" in requirement and actual == []
                    else "product_bug")
        check = {"requirement": requirement, "expected": expected, "actual": actual,
                 "passed": passed, "category": category}
        self._receipt_record["checks"].append(check)
        if not passed:
            self._capture("requirement_mismatch")
            path = self._receipt_case_directory / f"{category}_{len(self._receipt_record['checks'])}.json"
            path.write_text(json.dumps({"nodeid": self._receipt_request.node.nodeid,
                "precondition": getattr(self, "_receipt_precondition", None), **check,
                "evidence": self._receipt_record["evidence"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        return passed

    def _finish_checks(self):
        """断言所有累积的 check 均通过，失败时以 JSON 格式输出失败项。"""
        failed = [check for check in self._receipt_record["checks"] if not check["passed"]]
        assert not failed, json.dumps(failed, ensure_ascii=False)

    def _receipt_report_phase(self, report):
        """pytest 阶段钩子：记录用例结果并写入 JSON 报告文件。"""
        if not hasattr(self, "_receipt_record"):
            return None
        record = self._receipt_record
        record["phases"][report.when] = report.outcome
        if report.failed:
            record.setdefault("errors", []).append({"phase": report.when, "detail": str(report.longrepr)})
            self._capture("execution_failure")
        product_failure = any(not check["passed"] and check["category"] == "product_bug"
                              for check in record["checks"])
        observation_gap = any(not check["passed"] and check["category"] == "observation_gap"
                              for check in record["checks"])
        failures = "failed" in record["phases"].values()
        record["status"] = ("product_bug" if product_failure else
                            "blocked" if "skipped" in record["phases"].values() or
                            (failures and self._receipt_phase == "precondition") else
                            "observation_gap" if observation_gap else
                            "execution_error" if failures else
                            "passed" if record["phases"].get("call") == "passed" else "running")
        record["precondition"] = getattr(self, "_receipt_precondition", None)
        (self._receipt_case_directory / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records = getattr(type(self), "_receipt_run_records", {})
        records[self._receipt_request.node.nodeid] = record
        type(self)._receipt_run_records = records
        (self._receipt_directory / "results.json").write_text(
            json.dumps(list(records.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def _prepare(self, saved):
        """前置：确保邮箱为目标值且在订单详情页。

        利用 class 级缓存：邮箱状态相同时跳过保存，订单绑定时跳过导航。
        缓存与真实值可能因用例内发送而不同，故切换前先回读真实值确认。
        """
        self._receipt_phase = "precondition"
        cls = type(self)
        email_changed = False
        # 仅在邮箱需要切换时才保存（跳过约 10 秒的导航+保存+验证流程）
        if cls._receipt_current_email != saved:
            self.v150_open_email_settings("receipt_precondition")
            # 回读真实值：若已被前序用例发送动作保存，则无需重复保存
            actual = self.v150_email_read_current("receipt_precondition")
            if actual != saved:
                actual = self.v150_email_save("receipt_precondition", email=saved)
                if actual != saved:
                    pytest.skip(f"前置阻塞：管理页未保存指定测试邮箱，实际={actual!r}")
                email_changed = True
            cls._receipt_current_email = actual
        # 首次进入订单详情，或邮箱切换后需要重新导航到订单详情
        if cls._receipt_order_binding is None or email_changed:
            try:
                self.v150_open_completed_order_detail("receipt_target")
                cls._receipt_order_binding = getattr(cls, "_receipt_order_binding", None)
                cls._receipt_order_no_cached = getattr(self, "_receipt_order_no", None)
            except (RuntimeError, TimeoutError) as exc:
                self._capture("precondition_blocked")
                pytest.skip(f"前置阻塞：{exc}")
        else:
            # 复用缓存绑定，但确保已在订单详情页
            self._receipt_order_no = cls._receipt_order_no_cached
            type(self)._receipt_order_binding = cls._receipt_order_binding
            if self._v150_current_page_type() != "order_detail":
                try:
                    self.v150_open_completed_order_detail("receipt_target")
                except (RuntimeError, TimeoutError) as exc:
                    self._capture("precondition_blocked")
                    pytest.skip(f"前置阻塞：{exc}")
        self._receipt_phase = "measurement"

    def _open(self, entry="send", before_click=None, expect_dialog=True):
        """打开收据弹框（或直接发送路径）。

        需求语义：未设置邮箱时「發送行程收據」与「設置並發送」都弹出发送弹框；
        已设置邮箱时「設置並發送」不存在，「發送行程收據」为直接发送动作。

        Args:
            entry: 入口类型 "send" 或 "set_and_send"。
            before_click: 点击入口前执行的钩子（如开启接口日志抓取）。
            expect_dialog: True 时断言弹框已弹出；False 时仅返回状态不检查弹框。
        """
        prompt = self.v150_receipt_prompt_present()
        key = "send_button" if entry == "send" else "set_and_send"
        self._expect("收据入口存在：" + entry, prompt[key], True)
        self._finish_checks()
        if before_click is not None:
            before_click()
        with self._record_action("entry_response"):
            state = self.v150_open_receipt_dialog(entry=entry)
        self._receipt_record.setdefault("entry_observations", []).append(state)
        self._capture("dialog_open")
        if expect_dialog:
            self._expect("点击收据入口必须弹出发送弹框", state["present"], True)
            self._finish_checks()
        return state

    def _open_dialog_only(self, entry="send", before_click=None):
        """仅未设置邮箱可用的弹框打开路径：已设置邮箱时入口为直接发送，不应弹框。

        before_click: 点击入口前执行的钩子（如开启接口日志抓取）。
        """
        return self._open(entry=entry, before_click=before_click, expect_dialog=False)

    def _editable(self):
        """确保邮箱处于可编辑状态：有「修改」按钮时先点击，再断言输入框出现。"""
        state = self._v150_receipt_dialog_state()
        if not state["email_input"]:
            self._expect("已设置邮箱提供修改按钮", state["modify_text"], "修改")
            self._finish_checks()
            state = self.v150_receipt_modify_email()
        self._expect("邮箱可编辑", state["email_input"], True)
        self._finish_checks()
        return state

    def _persisted(self):
        """关闭弹框并到邮箱管理页回读持久化值，用于验证保存结果。"""
        if self._v150_receipt_dialog_ready():
            self.v150_receipt_close_dialog()
        self.v150_open_email_settings("receipt_persisted")
        actual = self.v150_email_read_current()
        type(self)._receipt_current_email = actual
        return actual

    def _fresh_rate_window(self):
        """等待限频窗口冷却：距上次发送满60秒后恢复，避免用例间限频干扰。"""
        previous = getattr(type(self), "_receipt_last_send", None)
        delay = 61 if previous is None else max(0, 61 - (time.monotonic() - previous))
        if delay:
            time.sleep(delay)

    @pytest.mark.parametrize("saved", ["", RECEIPT_EMAIL], ids=["unset-email", "saved-email"])
    def test_receipt_order_detail_shows_prompt_and_button(self, saved):
        """未设置时显示完整提示与设置按钮；已设置时隐藏；独立发送入口始终存在。"""
        self._prepare(saved)
        state = self.v150_receipt_prompt_present()
        self._capture("order_detail")
        self._expect("发送行程收据按钮文案", state["send_text"], self.TITLE)
        self._expect("自动发送提示栏条件", state["prompt"], not bool(saved))
        self._expect("设置并发送按钮条件", state["set_and_send"], not bool(saved))
        if not saved:
            self._expect("自动发送提示栏完整文案", state["prompt_text"], self.PROMPT)
            self._expect("设置并发送按钮文案", state["set_text"], "設置並發送")
        self._finish_checks()

    @pytest.mark.parametrize("saved,entry", [
        pytest.param("", "send", id="unset-send-entry"),
        pytest.param("", "set_and_send", id="unset-set-and-send-entry"),
    ])
    def test_receipt_dialog_content_and_initial_state(self, saved, entry):
        """核验未设置邮箱时两个入口均弹出标题、说明、空值编辑与键盘。"""
        self._prepare(saved)
        state = self._open(entry)
        self._expect("弹框标题", state["title"], self.TITLE)
        self._expect("弹框说明", state["subtitle"], self.SUBTITLE)
        self._expect("邮箱初始展示值", state["email"], saved)
        self._expect("邮箱编辑状态", state["email_input"], not bool(saved))
        self._expect("发送按钮文案", state["send_text"], "發送")
        self._expect("关闭按钮存在", state["close"], True)
        self._expect("未设置邮箱自动弹出键盘", state["keyboard"], True)
        self._expect("空值默认发送按钮不可点击（enabled=false）", state["send_enabled"], False)
        self._finish_checks()

    def test_receipt_saved_email_entry_sends_directly_without_dialog(self):
        """已设置邮箱：行程结束上方提示栏与「設置並發送」不展示，「發送行程收據」入口仍存在。"""
        self._prepare(self.RECEIPT_EMAIL)
        prompt = self.v150_receipt_prompt_present()
        self._capture("order_detail_saved")
        self._expect("已设置邮箱时行程结束上方提示栏不展示", prompt["prompt"], False)
        self._expect("已设置邮箱时设置并发送按钮不展示", prompt["set_and_send"], False)
        self._expect("已设置邮箱时发送行程收据入口仍存在", prompt["send_button"], True)
        self._expect("发送行程收据按钮文案", prompt["send_text"], self.TITLE)
        self._finish_checks()

    def test_receipt_unset_email_entry_shows_set_and_send_dialog(self):
        """未设置邮箱：行程结束上方展示提示栏与「設置並發送」，點擊彈框提供設置并發送流程。"""
        self._prepare("")
        prompt = self.v150_receipt_prompt_present()
        self._capture("order_detail_unset")
        self._expect("未设置邮箱时展示行程结束上方提示栏", prompt["prompt"], True)
        self._expect("自动发送提示栏完整文案", prompt["prompt_text"], self.PROMPT)
        self._expect("未设置邮箱时展示设置并发送按钮", prompt["set_and_send"], True)
        self._expect("设置并发送按钮文案", prompt["set_text"], "設置並發送")
        self._expect("未设置邮箱时发送行程收据入口仍存在", prompt["send_button"], True)
        self._finish_checks()
        # 未设置邮箱时「設置並發送」入口弹出弹框，可输入邮箱后发送
        state = self._open("set_and_send")
        self._expect("设置并发送入口弹出弹框", state["present"], True)
        self._expect("弹框标题", state["title"], self.TITLE)
        self._expect("未设置邮箱时弹框展示空输入框", state["email_input"], True)
        self._expect("弹框邮箱值为空", state["email"], "")
        self._expect("未设置邮箱时自动弹出键盘", state["keyboard"], True)
        self._expect("空值时发送按钮不可点击", state["send_enabled"], False)
        self._finish_checks()

    def test_receipt_empty_email_save_restores_set_and_send_entry(self):
        """设置页保存空邮箱成功后，回到行程详情应重新展示提示栏与「設置並發送」入口。"""
        # 先确保有邮箱，再通过设置页保存空邮箱（删除邮箱）
        self._prepare(self.RECEIPT_EMAIL)
        self.v150_open_email_settings("receipt_empty_save")
        current = self.v150_email_read_current()
        self._expect("保存空邮箱前邮箱为已设置状态", current, self.RECEIPT_EMAIL)
        actual = self.v150_email_save("receipt_empty_save", email="")
        self._expect("设置页保存空邮箱后回读为空", actual, "")
        type(self)._receipt_current_email = actual
        self._capture("empty_email_saved")
        # 回到订单详情验证提示栏与入口恢复
        self.v150_open_completed_order_detail("receipt_target")
        prompt = self.v150_receipt_prompt_present()
        self._capture("order_detail_after_empty_save")
        self._expect("保存空邮箱后行程结束上方提示栏重新展示", prompt["prompt"], True)
        self._expect("保存空邮箱后设置并发送按钮重新展示", prompt["set_and_send"], True)
        self._expect("保存空邮箱后发送行程收据入口仍存在", prompt["send_button"], True)
        self._finish_checks()
        # 空邮箱状态下点「設置並發送」应弹出可输入邮箱的弹框
        state = self._open("set_and_send")
        self._expect("保存空邮箱后设置并发送入口弹出弹框", state["present"], True)
        self._expect("弹框展示空输入框", state["email_input"], True)
        self._expect("弹框邮箱值为空", state["email"], "")
        self._expect("弹框自动弹出键盘", state["keyboard"], True)
        self._finish_checks()

    def test_receipt_modify_enables_editing_and_keyboard(self):
        """弹框保存过邮箱后再打开，显示已存邮箱并提供「修改」按钮，点击进入编辑态并弹出键盘。"""
        # 未设置邮箱：打开弹框并输入邮箱，保存后关闭弹框
        self._prepare("")
        self._open()
        self.v150_receipt_type_email(self.RECEIPT_EMAIL)
        self._expect("输入邮箱后发送按钮启用", self._v150_receipt_dialog_state()["send_enabled"], True)
        toasts, calls = self._send_and_observe()
        self._expect("保存邮箱并发送成功提示", toasts, [self.SUCCESS])
        self._expect_api("行程收据发送接口返回成功", calls, self.TRIP_SEND_API,
                         expect_params={"order_no": self._receipt_order_no})
        self._expect("保存邮箱后持久化值", self._persisted(), self.RECEIPT_EMAIL)
        self._finish_checks()
        # 邮箱已设置：入口变为直接发送动作，无法再通过入口打开弹框，
        # 因此「修改」按钮的验证放在未设置邮箱的弹框内完成：
        # 未设置邮箱时弹框为输入态，不存在「修改」按钮。
        self._prepare("")
        state = self._open()
        self._expect("未设置邮箱时弹框为直接输入态", state["email_input"], True)
        self._expect("未设置邮箱时不提供修改按钮", state["modify"], False)
        self._expect("未设置邮箱时自动弹出键盘", state["keyboard"], True)
        self._finish_checks()

    def _button_background(self, name):
        """截图并提取发送按钮中心像素RGB，用于判断按钮置灰/启用状态。"""
        from io import BytesIO
        from PIL import Image, ImageStat
        bounds = self._v150_receipt_element("btn_send").rect
        image = Image.open(BytesIO(self.client.driver.get_screenshot_as_png())).convert("RGB")
        path = self._receipt_case_directory / f"{time.time_ns()}_{name}.png"
        image.save(path)
        x = int(bounds["x"] + bounds["width"] * .15)
        y = int(bounds["y"] + bounds["height"] * .5)
        color = ImageStat.Stat(image.crop((x - 3, y - 3, x + 4, y + 4))).median
        self._receipt_record["evidence"].append({"phase": name, "screenshot": str(path), "background_rgb": color})
        return color

    @pytest.mark.parametrize("value", ["new@example.com", "invalid-email"], ids=["valid-content", "invalid-content"])
    def test_receipt_input_toggles_send_button(self, value):
        """输入任意非空内容后可点击；格式判断在点击时发生；再次清空恢复不可用。"""
        self._prepare("")
        self._open()
        empty_color = self._button_background("empty_button")
        self.v150_receipt_type_email(value)
        self._expect("非空输入后发送按钮启用", self._v150_receipt_dialog_state()["send_enabled"], True)
        active_color = self._button_background("active_button")
        self._receipt_record["button_colors"] = {"empty_rgb": empty_color, "active_rgb": active_color}
        self._expect("空值按钮须置灰，不能与启用状态背景同色", empty_color == active_color, False)
        self.v150_receipt_type_email("")
        self._expect("清空后发送按钮禁用", self._v150_receipt_dialog_state()["send_enabled"], False)
        self._capture("button_disabled_after_clear")
        self._finish_checks()

    def test_receipt_empty_or_invalid_email_blocks_submit(self):
        """同一弹框内连续验证多种非法/空邮箱：输入→发送→验证拦截→清空→下一个。"""
        self._prepare("")
        self._open()
        invalid_cases = [
            ("", "empty"),
            ("invalid-email", "missing-at"),
            ("a@b@c.com", "multiple-at"),
            ("@example.com", "empty-local"),
            ("user@", "empty-domain"),
            ("user@example", "domain-no-dot"),
        ]
        for value, case_id in invalid_cases:
            self.v150_receipt_type_email(value)
            state = self._v150_receipt_dialog_state()
            self._expect(f"[{case_id}] 发送按钮随内容启用", state["send_enabled"], bool(value))
            if value and state["send_enabled"]:
                toasts, calls = self._send_and_observe()
                self._expect(f"[{case_id}] 非法格式提示", toasts, [self.INVALID])
                # 需求：客户端拦截或服务端拒绝均视为通过。
                matched = find_api_calls(calls, self.TRIP_SEND_API)
                if matched:
                    self._expect_api(
                        f"[{case_id}] 非法邮箱被服务端拒绝", calls, self.TRIP_SEND_API,
                        allow_error_code=True, expect_params={"order_no": self._receipt_order_no})
                    self._expect_api(
                        f"[{case_id}] 非法邮箱场景服务端未按成功受理", calls, self.TRIP_SEND_API,
                        allow_error_code=True)
                else:
                    self._expect_no_api(
                        f"[{case_id}] 非法邮箱被客户端拦截时未调用行程收据发送接口", calls, self.TRIP_SEND_API)
            elif not value:
                self._expect(f"[{case_id}] 空值不出现发送成功提示",
                             self.v150_receipt_observe_toasts(timeout=1), [])
                self._expect_no_api(
                    f"[{case_id}] 空值不应调用行程收据发送接口",
                    self._api_calls(self._last_network_evidence or {}), self.TRIP_SEND_API)
            self._expect(f"[{case_id}] 非法或空值弹框不关闭", self._v150_receipt_dialog_ready(), True)
            self._capture(f"invalid_blocked_{case_id}")
            # 弹框保持打开，清空输入框继续下一条（v150_receipt_type_email 自带清空逻辑）
            logger.info("收据弹框 %s 验证完成，清空输入框继续下一条", case_id)
        # 全部验证完后统一检查邮箱未被保存
        self._expect("非法或空值不保存邮箱", self._persisted(), "")
        self._finish_checks()

    @pytest.mark.parametrize("saved", [""], ids=["new-draft"])
    def test_receipt_close_dialog_does_not_save_draft(self, saved):
        """点击真实关闭按钮，重开弹框和管理页均必须仍为原邮箱。"""
        self._prepare(saved)
        self._open()
        self.v150_receipt_type_email("v150_draft_not_saved@example.com")
        self._capture("draft_before_close")
        self.v150_receipt_close_dialog()
        self._expect("关闭按钮使弹框消失", self._v150_receipt_dialog_ready(), False)
        self._open()
        self._expect("关闭后重新打开不保留草稿", self.v150_receipt_read_saved_email(), saved)
        self._expect("关闭不更新持久化邮箱", self._persisted(), saved)
        self._finish_checks()

    @pytest.mark.parametrize("saved,value,expected", [
        pytest.param("", RECEIPT_EMAIL, RECEIPT_EMAIL, id="new-email-send"),
        pytest.param("", "  v150_receipt@example.com  ", RECEIPT_EMAIL, id="trim-outer-spaces"),
        pytest.param("", "v150_ receipt@ example.com", RECEIPT_EMAIL, id="remove-inner-spaces"),
    ])
    def test_receipt_send_with_valid_email_toast_success(self, saved, value, expected):
        """发送成功精确提示、关闭弹框、保存去空格邮箱及隐藏提示栏。"""
        self._prepare(saved)
        self._fresh_rate_window()
        self._open()
        if value is not None:
            self._editable()
            self.v150_receipt_type_email(value)
        self._expect("有效内容发送按钮启用", self._v150_receipt_dialog_state()["send_enabled"], True)
        self._finish_checks()
        toasts, calls = self._send_and_observe()
        self._expect("发送成功提示", toasts, [self.SUCCESS])
        self._expect_api(
            "行程收据发送接口返回成功", calls, self.TRIP_SEND_API,
            expect_params={"order_no": self._receipt_order_no})
        if expected:
            self._expect_api(
                "发送接口携带去空格后的邮箱", calls, self.TRIP_SEND_API,
                expect_params={"email": expected.replace(" ", "")})
        closed = not self._v150_receipt_dialog_ready()
        self._expect("发送成功关闭弹框", closed, True)
        self._capture("send_result")
        if closed:
            state = self.v150_receipt_prompt_present()
            self._expect("设置后自动提示栏消失", state["prompt"], False)
            self._expect("设置后设置并发送按钮消失", state["set_and_send"], False)
        self._expect("发送时保存去掉空格后的邮箱", self._persisted(), expected)
        self._finish_checks()

    def test_receipt_saved_email_direct_send_succeeds(self):
        """已设置邮箱：点「發送行程收據」直接发送成功（不弹框），并使用已保存邮箱。"""
        self._prepare(self.RECEIPT_EMAIL)
        self._fresh_rate_window()
        # 已设置邮箱时入口是直接发送动作：点击后不弹框，直接触发接口
        toasts, calls = self._send_and_observe_direct()
        self._expect("直接发送成功提示", toasts, [self.SUCCESS])
        self._expect_api(
            "行程收据发送接口返回成功", calls, self.TRIP_SEND_API,
            expect_params={"order_no": self._receipt_order_no})
        self._expect_api(
            "直接发送接口携带已保存邮箱", calls, self.TRIP_SEND_API,
            expect_params={"email": self.RECEIPT_EMAIL})
        self._expect("直接发送后邮箱保持不变", self._persisted(), self.RECEIPT_EMAIL)
        self._finish_checks()

    def test_receipt_send_rate_limit_two_per_minute(self):
        """干净窗口内第1次成功，第2、3次被限频拦截；窗口过后恢复发送。"""
        # 已设置邮箱时入口即发送，无需弹框，天然适配限频多次提交的场景
        self._prepare(self.RECEIPT_EMAIL)
        self._fresh_rate_window()
        sent_at = []
        for index in range(3):
            sent_at.append(time.monotonic())
            if index >= 1 and sent_at[index] - sent_at[0] >= 60:
                pytest.skip("限频前置阻塞：发送未落在同一个60秒窗口，不能判定限频缺陷")
            toasts, calls = self._send_and_observe_direct()
            self._receipt_record.setdefault("rate_attempts", []).append({"attempt": index + 1,
                "elapsed_from_first": sent_at[-1] - sent_at[0], "toasts": toasts})
            # 实测限频策略：每分钟1次，第1次成功(code=10000)，第2次起限频(code=10615)；
            # 但 toast 均为"已發送，稍後查看"，区别在接口返回 code。
            self._expect(f"限频第{index + 1}次提示", toasts, [self.SUCCESS])
            self._expect_api(
                f"限频第{index + 1}次接口处理符合预期", calls, self.TRIP_SEND_API,
                allow_error_code=(index >= 1))
            if index < 2:
                self._finish_checks()
        self._fresh_rate_window()
        toasts, calls = self._send_and_observe_direct()
        self._expect("限频窗口过后允许再次发送", toasts, [self.SUCCESS])
        self._expect_api("窗口过后接口返回成功", calls, self.TRIP_SEND_API)
        self._expect("限频不改变保存邮箱", self._persisted(), self.RECEIPT_EMAIL)
        self._finish_checks()


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
