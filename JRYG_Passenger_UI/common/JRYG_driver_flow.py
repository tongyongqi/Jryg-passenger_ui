import time

from airtest.core.api import sleep

from JRYG_Passenger_UI.common.JRYG_logger import logger


class DriverFlowMixin:
    """订单用例和独立司机调试共用的页面识别、登录及出车操作。

    通过 Mixin 模式为测试用例提供司机端状态检测、登录（手机号+验证码）、
    出车请求、卡顿检测等通用能力，避免在多个测试文件中重复实现。
    """

    def _page_content(self, package=None):
        """遍历 Poco 控件树，返回当前页面所有文本集合和控件 name 集合。"""
        root = self.poco.agent.hierarchy.dump()
        texts, names = set(), set()
        pending = [root]
        while pending:
            node = pending.pop()
            payload = node.get("payload", {})
            matches_package = package is None or payload.get("package") == package
            if matches_package and payload.get("visible") is not False:
                for field in ("text", "desc"):
                    text = payload.get(field)
                    if isinstance(text, str) and text.strip():
                        texts.add(text.strip())
                name = payload.get("name") or node.get("name")
                if name:
                    names.add(name)
            pending.extend(node.get("children", []))
        return texts, names

    def _get_all_texts(self):
        """返回当前页面所有文本的排序列表，用于日志输出。"""
        return sorted(self._page_content()[0])

    def _get_top_activity_full(self):
        """获取当前顶层 Activity 完整名称。"""
        return self.adb.get_top_activity()

    def _click_first(self, texts=(), ids=(), package=None):
        """按优先级点击第一个匹配的控件：先按 ID 再按文本，返回是否点击成功。"""
        for resource_id in ids:
            button = self.poco(resource_id)
            if button.exists():
                button.click()
                return True
        for text in texts:
            selector = {"text": text}
            if package is not None:
                selector["package"] = package
            button = self.poco(**selector)
            if button.exists():
                button.click()
                return True
        return False

    def _driver_state(self, activity, texts, names):
        """根据 Activity 和页面文本识别司机端当前状态，返回状态字符串。

        状态包括：登录流程（tourist_home→login→verify_phone→verify_code）、
        出车流程（home→listening）、订单流程（accept_order→ready→at_pickup→
        wait_passenger→in_trip→bill→finished）及各种弹窗状态。
        """
        if self.driver_pkg not in activity:
            return None
        joined = " ".join(texts)
        if "reallogin" in activity or f"{self.driver_pkg}:id/vcv_verification_code" in names:
            return "driver_verify_code"
        if "请输入验证码" in joined or "验证码已经发送" in joined:
            return "driver_verify_code"
        if "login" in activity or "欢迎登录" in texts or (
            "请输入手机号码" in joined and "后两位" not in joined
        ):
            return "driver_login"
        if "touristhome" in activity or "登录/注册" in texts:
            return "driver_tourist_home"
        if "ygaloadingactivity" in activity:
            return "privacy_agreement" if "同意" in texts else "driver_other"
        if f"{self.driver_pkg}:id/iv_cancel" in names:
            return "driver_popup"
        if {"拒绝", "同意"} <= texts:
            return "driver_fee_abnormal"
        if "好的" in texts:
            return "driver_ok"
        if texts & {"我知道了", "知道了"}:
            return "driver_known"
        if texts & {"抢单", "接单"}:
            return "driver_accept_order"
        if "后两位" in joined or "验证身份" in texts:
            return "driver_verify_phone"
        for state, labels in (
            ("driver_bill", {"未确认账单", "发起收款"}),
            ("driver_in_trip", {"到达目的地"}),
            ("driver_wait_passenger", {"已接到乘客"}),
            ("driver_at_pickup", {"到达上车地点"}),
            ("driver_ready", {"准备出发", "出发"}),
        ):
            if texts & labels:
                return state
        if "送乘客" in joined:
            return "driver_in_trip"
        if "ygatraveldetailflutteractivity" in activity and "已完成" in texts and (
            texts & {"已支付", "返回首页"}
        ):
            return "driver_finished"
        if texts & {"点击出车", "出车"}:
            return "driver_home"
        if texts & {"听单中", "正在听单", "听单"}:
            return "driver_listening"
        if "服务中" in texts or "(出发去接乘客)" in joined or "出发去接乘客" in joined:
            return "driver_in_service"
        if "ygahomepageactivity" in activity and texts & {"今日营收", "听单检测"}:
            return "driver_home"
        return "driver_other"

    def _driver_login(self):
        """司机端手机号登录：输入手机号→勾选协议→下一步→同意弹窗。"""
        phone = self.poco(f"{self.driver_pkg}:id/et_phone_number")
        if not phone.exists():
            return False
        phone.click()
        phone.set_text(self.test_data["driver_phone"])
        sleep(1)
        # 勾选隐私协议复选框（多种选择器兼容）
        for selector in (
            {"name": f"{self.driver_pkg}:id/cb_agree"},
            {"type": "android.widget.CheckBox"},
            {"name": f"{self.driver_pkg}:id/text_agree_agreement"},
        ):
            checkbox = self.poco(**selector)
            if checkbox.exists():
                if not checkbox.attr("checked") and not checkbox.attr("selected"):
                    checkbox.click()
                    sleep(0.5)
                break
        else:
            raise RuntimeError("司机手机号页面未找到协议勾选框")
        if not self._click_first(texts=("下一步",), ids=(f"{self.driver_pkg}:id/bt_next",)):
            raise RuntimeError("司机手机号页面未找到下一步按钮")
        sleep(3)
        if self.poco(text="不同意").exists():
            self._click_first(texts=("同意",))
            sleep(2)
        return True

    def _input_driver_code(self):
        """司机端验证码输入：支持单框和六格独立输入框两种模式。

        六格模式需逐位 click + ADB input text，因为 Poco set_text
        只会写入第一个输入框。
        """
        code = "123456"
        container = self.poco(f"{self.driver_pkg}:id/vcv_verification_code")
        if container.exists():
            inputs = list(container.offspring(type="android.widget.EditText"))
        else:
            field = self.poco(f"{self.driver_pkg}:id/et_code")
            inputs = [field] if field.exists() else []
        if len(inputs) not in (1, len(code)):
            raise RuntimeError(f"司机验证码输入框数量异常: {len(inputs)}")
        if len(inputs) == 1:
            inputs[0].set_text(code)
        else:
            # 六格验证码逐位输入：click 激活 → ADB input text 写入单个字符
            for field, digit in zip(inputs, code):
                current = field.get_text()
                if current == digit:
                    continue
                if current:
                    field.set_text("")
                field.click()
                self.adb.run_cmd(["input", "text", digit])
                sleep(0.3)
        sleep(2)
        if "reallogin" in self._get_top_activity_full().lower():
            self._click_first(texts=("确认", "登录"))
        logger.info("司机验证码已填写，等待页面确认登录结果")
        sleep(3)

    def _request_drive_out(self):
        """请求出车：点击出车按钮并等待听单状态确认。"""
        clicked = self._click_first(texts=("点击出车", "出车"))
        if clicked:
            logger.info("已请求出车，等待听单状态确认")
            sleep(3)
        return clicked

    def _check_stall(self, state, timeout=60):
        """卡顿检测：当页面状态持续 timeout 秒未推进时抛出断言。"""
        now = time.monotonic()
        if getattr(self, "_last_state", None) != state:
            self._last_state = state
            self._state_since = now
        elapsed = now - self._state_since
        if elapsed >= timeout:
            raise AssertionError(
                f"页面状态 {state} 已持续 {elapsed:.0f} 秒未推进；"
                f"Activity: {self._get_top_activity_full()}；文本: {self._get_all_texts()}"
            )
