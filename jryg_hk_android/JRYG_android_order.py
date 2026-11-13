"""香港 Android 订单适配：组合公共模块，业务编排继续继承 iOS。

只覆盖原生设备、滑块及付款页同单校验，最终支付状态仍由共享司机流程核验。
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from decimal import Decimal

from .JRYG_android_base import AndroidUIBase, BASE_DIR
from .JRYG_android_ui import resolve_runtime
from .JRYG_android_passenger import AndroidPassengerMixin
from .JRYG_android_payment import AndroidPaymentMixin
from .JRYG_driver_ui import (
    ACTION_LABELS, LOG, DriverUIFlow, center, find_label, is_history_list, node_text,
    parser, read_fixed_fare, read_order_no, rect, visible_nodes,
)
from .JRYG_order_flow import TestOrderBase


def read_android_fixed_fare(root):
    """按原生账单区域合读金额与HKD；缺失、多值、异币或输入框均停止。"""
    nodes = visible_nodes(root)
    prefix = "com.sunlightmobility.driver:id/"
    resources = ("cl_fixed_price", "tv_fixed_price_title", "ll_fixed_price_amount",
                 "tv_fixed_price_amount", "tv_fixed_price_unit")
    if not any(node.get("resource-id") == prefix + resource for node in nodes for resource in resources):
        return read_fixed_fare(root)
    if not {"確認賬單", "確認收款"}.issubset({node_text(node) for node in nodes}):
        raise RuntimeError("Android包车固定价账单尚未就绪，禁止确认收款")
    if any(node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField") for node in nodes):
        raise RuntimeError("Android包车固定车费出现输入框，禁止提交")
    fields = {}
    for resource in resources:
        matches = [node for node in nodes if node.get("resource-id") == prefix + resource]
        if len(matches) != 1:
            raise RuntimeError(f"Android包车车费区域缺失或不唯一：{resource}")
        fields[resource] = matches[0]
    section = fields["cl_fixed_price"]
    row = fields["ll_fixed_price_amount"]
    if (fields["tv_fixed_price_title"] not in list(section.iter()) or row not in list(section.iter())
            or fields["tv_fixed_price_amount"] not in list(row.iter())
            or fields["tv_fixed_price_unit"] not in list(row.iter())):
        raise RuntimeError("Android金额与币种不属于同一固定车费区域，禁止提交")
    title, number, unit = (fields[key] for key in ("tv_fixed_price_title", "tv_fixed_price_amount", "tv_fixed_price_unit"))
    if any(node.tag != "XCUIElementTypeStaticText" for node in (title, number, unit)):
        raise RuntimeError("Android固定车费不是只读文本，禁止提交")
    if node_text(title).strip() != "車費" or node_text(unit).strip() != "HKD":
        raise RuntimeError("Android固定车费标题或币种不符，禁止确认收款")
    value = node_text(number).strip()
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", value) is None:
        raise RuntimeError("Android固定车费金额无效，禁止确认收款")
    return Decimal(value)


class AndroidDriverUIFlow(DriverUIFlow):
    """共享司机状态机的Android原生动作适配，不使用司机业务接口。

    不管执行到哪个阶段，如果设备熄屏，唤醒后继续执行，不中断测试。
    """

    def root(self, read_deadline=None):
        """读取页面前先检测 Android 设备熄屏并唤醒，不管执行到哪个阶段。"""
        udid = getattr(self.client, "_udid", None) or getattr(self.client, "udid", None)
        if udid:
            from .JRYG_android_device_guard import ensure_unlocked as _ensure_unlocked
            _ensure_unlocked(udid)
        return super().root(read_deadline)

    def detect_phase(self, root):
        """先用共享识别规则；未知页按真实Android滑块补识别出发阶段、登录页。"""
        phase = super().detect_phase(root)
        if phase != "unknown":
            return phase
        target = find_label(root, ("已出發", "已出发"))
        if target is not None and any(
            node.get("resource-id", "").split("/")[-1] in ("ll_drag_view", "drag_view", "sb_drag")
            and target in list(node.iter()) for node in visible_nodes(root)
        ):
            return "departure"
        texts = {node_text(node) for node in visible_nodes(root)}
        # Android 司机登录页文本与 iOS 不同，需要单独匹配
        if texts.intersection({
            "登錄/註冊", "登录/注册",
            "立即註冊，開始接單賺錢", "立即注册，开始接单赚钱",
            "歡迎登錄/註冊陽光車主", "欢迎登录/注册阳光车主",
            "同意並登錄", "同意并登录",
        }):
            return "login"
        if "請輸入驗證碼" in texts or "请输入验证码" in texts:
            return "code"
        return phase

    def back_from_paid_detail(self, root):
        """确认详情具有唯一订单号后返回；已支付前置由调用方核验。"""
        read_order_no(root)
        self.client.back()

    def wait_for_entry_page(self):
        """确认安卓历史列表后只返回一次；未知页面不盲目返回，不执行订单动作。"""
        deadline = min(self.deadline, time.monotonic() + self.args.step_timeout)
        returned = False
        prefix = "com.sunlightmobility.driver:id/"
        while time.monotonic() < deadline:
            root = self.root()
            phase = self.detect_phase(root)
            self._check_device_availability(phase)
            nodes = visible_nodes(root)
            titles = [node for node in nodes if node.get("resource-id") == prefix + "tv_bar_title"]
            native_history = False
            if any(node_text(node).strip() == "我的行程" for node in titles):
                if len(titles) != 1:
                    raise RuntimeError("Android行程列表标题不唯一，停止返回")
                lists = [node for node in nodes if node.get("resource-id") == prefix + "rl_order_list"]
                if len(lists) > 1:
                    raise RuntimeError("Android行程列表不唯一，停止返回")
                ids = {node.get("resource-id") for node in nodes}
                native_history = bool(lists) or {prefix + "tv_order_time", prefix + "tv_order_status"}.issubset(ids)
            if native_history or is_history_list(root):
                if not returned:
                    returned = True
                    try:
                        self.client.back()
                    except Exception as exc:
                        raise RuntimeError("Android历史列表返回响应未确认，禁止重复返回") from exc
                    LOG.info("Android已确认我的行程列表，单次原生返回听单首页；未出车、接单或收款")
            elif phase != "unknown":
                return root, phase
            time.sleep(self.args.interval)
        self.snapshot("driver_entry_navigation_timeout")
        raise TimeoutError("Android司机准备页恢复超时：原生历史列表返回未确认或仍为未知页；未重复返回或推进订单")

    def _open_bound_history_order(self):
        """按本次绑定号打开我的行程卡片，不点第一条收入通知或按金额/时间猜单。"""
        prefix = "com.sunlightmobility.driver:id/"
        pages = 0
        previous = None
        while time.monotonic() < self.deadline:
            root = self.root()
            nodes = visible_nodes(root)
            titles = [node for node in nodes if node.get("resource-id") == prefix + "tv_bar_title"]
            if not titles:
                self._check_device_availability(self.detect_phase(root))
                time.sleep(self.args.interval)
                continue
            if len(titles) != 1 or node_text(titles[0]).strip() != "我的行程":
                raise RuntimeError("Android当前不是司机行程列表，禁止点击其他订单")
            lists = [node for node in nodes if node.get("resource-id") == prefix + "rl_order_list"]
            if not lists:
                time.sleep(self.args.interval)
                continue
            if len(lists) != 1:
                raise RuntimeError("Android司机行程列表不唯一，停止同订单核验")
            identifiers = [node for node in visible_nodes(lists[0])
                           if node.get("resource-id") == prefix + "tv_order_id"]
            matches = [node for node in identifiers if node_text(node).strip() == self.order_no]
            if len(matches) > 1:
                raise RuntimeError("Android本次订单记录不唯一，禁止点击")
            if matches:
                selector = (f"//*[@resource-id='{prefix}rl_order_list']"
                            f"//*[@resource-id='{prefix}tv_order_id' and @text='{self.order_no}']"
                            "/ancestor::*[@clickable='true'][1]")
                cards = self.client.driver.find_elements("xpath", selector)
                if len(cards) != 1 or not cards[0].is_displayed() or not cards[0].is_enabled():
                    raise RuntimeError("Android本次订单卡片缺失或不唯一，停止核验")
                ids = cards[0].find_elements("xpath", f".//*[@resource-id='{prefix}tv_order_id']")
                if len(ids) != 1 or ids[0].text != self.order_no:
                    raise RuntimeError("Android订单卡片已改变，禁止打开其他订单")
                if time.monotonic() >= self.deadline:
                    raise TimeoutError("Android同订单核验总超时，未点击详情")
                cards[0].click()
                LOG.info("Android已按绑定订单号打开行程详情：%s", self.order_no)
                return
            signature = tuple(node_text(node).strip() for node in identifiers)
            if not signature or signature == previous or pages >= 10:
                time.sleep(self.args.interval)
                continue
            x, y, width, height = rect(lists[0])
            if width <= 0 or height <= 120:
                raise RuntimeError("Android行程列表范围无效，停止核验")
            self.client.swipe(round(x + width / 2), round(y + height * 0.8),
                              round(x + width / 2), round(y + height * 0.25), duration=0.5)
            previous = signature
            pages += 1
            time.sleep(self.args.interval)
        raise TimeoutError(f"Android行程列表未找到本次订单 {self.order_no}；不重付、不接其他订单")

    def bind_existing_history_order(self, order_no):
        """从司机首页按乘客唯一订单号绑定遗留订单，不点通知、金额相同单或列表首单。"""
        if (not isinstance(order_no, str) or re.fullmatch(r"[A-Z0-9]{12}", order_no) is None
                or not any(char.isdigit() for char in order_no) or not any(char.isalpha() for char in order_no)):
            raise ValueError("Android遗留订单号无效，禁止打开历史订单")
        if order_no in self.completed_before_run:
            raise RuntimeError("Android遗留订单已处理，禁止重复绑定或付款")
        self.deadline = time.monotonic() + self.args.payment_timeout
        self._activate_driver_app()
        root, phase = self.wait_for({"online", "offer", "offline", "unpaid", "complete"})
        self.order_no = order_no
        self.awaiting_new_order = False
        if phase in ("unpaid", "complete"):
            read_order_no(root, expected=order_no)
        else:
            if phase == "offline":
                self.act(root, ACTION_LABELS["offline"])
                root, phase = self.wait_for({"online", "offer"})
            self.act(root, ("我的行程",))
            self._open_bound_history_order()
            root, phase = self.wait_for({"unpaid", "complete"})
            read_order_no(root, expected=order_no)
        self.resume_phase = self.last_phase = phase
        LOG.info("Android司机已按乘客唯一订单号绑定遗留订单：%s，阶段=%s", order_no, phase)
        return phase

    def wait_completed(self):
        """静态未支付页返回后，按绑定订单号打开行程详情，最终仍须同单已完成且已支付。"""
        if (not isinstance(self.order_no, str) or re.fullmatch(r"[A-Z0-9]{12}", self.order_no) is None
                or not any(c.isdigit() for c in self.order_no) or not any(c.isalpha() for c in self.order_no)):
            raise RuntimeError("缺少本次绑定订单号，不能用任意已支付订单代替核验")
        if self.awaiting_new_order or self.order_no in self.completed_before_run:
            raise RuntimeError("本次订单未绑定或属于启动前旧订单，不能判定通过")
        LOG.info("Android开始同订单到账核验，绑定订单=%s", self.order_no)
        self.deadline = time.monotonic() + self.args.payment_timeout
        self._activate_driver_app()
        root, phase = self.wait_for({"unpaid", "complete"})
        read_order_no(root, excluded=self.completed_before_run, expected=self.order_no)
        if phase == "unpaid":
            if find_label(root, ("返回首頁",)) is not None:
                self.act(root, ("返回首頁",))
                self.wait_for({"online", "offer", "offline"})
                root = self.root()
                if self.detect_phase(root) not in ("online", "offer", "offline"):
                    raise RuntimeError("Android司机未回到首页，禁止点击历史详情或新订单")
                self.act(root, ("我的行程",))
                self._open_bound_history_order()
            while time.monotonic() < self.deadline:
                root = self.root()
                phase = self.detect_phase(root)
                if phase in ("unpaid", "complete"):
                    read_order_no(root, excluded=self.completed_before_run, expected=self.order_no)
                    if phase == "complete":
                        break
                else:
                    self._check_device_availability(phase)
                time.sleep(self.args.interval)
            else:
                raise TimeoutError("Android本次订单详情未确认已完成且已支付；不重付或重复提交账单")
        self.last_phase = "complete"
        self.snapshot("completed_paid")
        LOG.info("Android司机同订单详情已确认已完成且已支付：%s", self.order_no)

    def dismiss_keyboard(self):
        """委托Android客户端收键盘，不用司机按钮附近的坐标兜底。"""
        self.client.dismiss_keyboard()

    def submit_bill(self, root):
        """包车只读核对两次后单次滑动确认收款；打表仍委托原流程。"""
        if self.args.car_type != "charter":
            return super().submit_bill(root)
        fare = None
        for current in (root, None):
            current = self.root() if current is None else current
            texts = {node_text(node) for node in visible_nodes(current)}
            if texts.intersection({"現金", "現金支付", "现金", "现金支付"}) and self.args.payment != "cash":
                raise RuntimeError("页面显示现金支付，但未指定cash，停止账单提交")
            if self.args.payment == "cash" and not self.args.cash_collected:
                raise RuntimeError("现金收款需确认实际已收款，再传入--cash-collected")
            value = read_android_fixed_fare(current)
            if self.args.fare is not None and value != Decimal(self.args.fare):
                raise RuntimeError("包车固定车费与显式预期金额不符，禁止确认收款")
            if self.args.surcharge is not None and Decimal(self.args.surcharge) != 0:
                raise RuntimeError("包车固定价账单不能添加非零附加费或修改车费")
            if fare is not None and value != fare:
                raise RuntimeError("包车固定车费在提交前发生变化，禁止确认收款")
            fare = value
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("Android确认收款前已超时，未滑动或提交")
        self.bill_total = fare
        LOG.info("Android包车固定车费已核对：%s HKD；单次滑动确认收款，不修改金额", fare)
        try:
            self.act(current, ACTION_LABELS["bill"])
        except Exception as exc:
            raise RuntimeError("Android确认收款滑动响应未确认，禁止重复提交账单") from exc
        self.wait_for({"unpaid", "complete"})

    def fill(self, root, placeholder, value):
        target = self.field(root, placeholder)
        resource = target.get("resource-id")
        if not resource:
            raise RuntimeError("Android司机输入框缺少原生资源标识，停止输入")
        field = self.client(resourceId=resource).unique()
        deadline = time.monotonic() + self.args.step_timeout
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        if time.monotonic() >= deadline:
            raise TimeoutError("Android司机输入已超时，未提交")
        field.set_text(str(value))
        while time.monotonic() < deadline:
            current = self.client(resourceId=resource).unique()
            if current.native.id != field.native.id:
                raise RuntimeError("Android司机输入框已变化，禁止提交")
            if current.native.text == str(value):
                return
            time.sleep(0.2)
        raise TimeoutError("Android司机输入回读未确认，禁止提交")

    def enter_tail(self, root):
        if not re.fullmatch(r"\d{4}", self.args.tail or ""):
            raise RuntimeError("Android乘客尾号必须显式配置四位数字")
        fields = [node for node in visible_nodes(root)
                  if node.tag == "XCUIElementTypeTextField" and node.get("enabled") != "false"]
        if len(fields) != 1 or not fields[0].get("resource-id"):
            raise RuntimeError("Android乘客尾号输入框缺失或不唯一")
        field = self.client(resourceId=fields[0].get("resource-id")).unique()
        field.set_text(self.args.tail)
        if field.native.text != self.args.tail:
            raise RuntimeError("Android乘客尾号回读不一致，禁止验证")
        self.dismiss_keyboard()
        root = self.root()
        if self.detect_phase(root) == "tail":
            self.act(root, ("確認", "确认", "驗證", "验证"))
        self.wait_for({"destination"})

    def login(self, root):
        """Android司机端登录：处理协议弹窗→输入手机号→勾选协议→点击下一步→等验证码。"""
        if not self.args.mobile:
            raise RuntimeError("Android司机未登录，请传入 --mobile 或先手工登录")
        from .JRYG_driver_ui import find_label, center, visible_nodes, node_text

        # 1. 先处理可能出现的协议弹窗（「同意並登錄」按钮）
        agreement_btn = find_label(root, ("同意並登錄", "同意并登录"))
        if agreement_btn is not None:
            LOG.info("检测到协议弹窗，点击「同意並登錄」")
            self.client.click(*center(agreement_btn))
            time.sleep(2)
            root = self.root()

        # 2. 首页可能显示「登錄/註冊」按钮，需要先点击进入登录输入页
        login_btn = find_label(root, ("登錄/註冊", "登录/注册", "立即註冊，開始接單賺錢", "立即注册，开始接单赚钱", "登錄", "登录"))
        if login_btn is not None:
            LOG.info("点击登录按钮进入登录输入页")
            self.client.click(*center(login_btn))
            time.sleep(2)
            root = self.root()

        # 3. 输入手机号（使用 WDA TextField，与 iOS 一致）
        phone_fields = [node for node in visible_nodes(root)
                        if node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")
                        and node.get("enabled") != "false"]
        if not phone_fields:
            raise RuntimeError("Android司机登录页未找到输入框")
        phone_field = phone_fields[0]
        current_value = phone_field.get("value", "")
        if current_value != str(self.args.mobile):
            LOG.info("输入手机号")
            placeholder = phone_field.get("placeholderValue", "請輸入手機號碼")
            self.fill(root, placeholder, self.args.mobile)
            root = self.root()
        else:
            LOG.info("手机号已输入，跳过")

        # 4. 勾选协议复选框（如果有）
        try:
            checkboxes = [node for node in visible_nodes(root)
                          if node.get("resource-id", "").endswith("cb_agreement")]
            for cb in checkboxes:
                self.client.click(*center(cb))
                LOG.info("已勾选协议复选框")
                break
        except Exception:
            pass

        # 5. 点击下一步
        root = self.root()
        btn = find_label(root, ("下一步", "登錄", "登录", "獲取驗證碼", "获取验证码"))
        if btn is not None:
            LOG.info("点击下一步")
            self.client.click(*center(btn))
        else:
            raise RuntimeError("Android司机登录页未找到下一步按钮")

        root, phase = self.wait_for({"code", "offline", "online", "pickup"})
        if phase == "code":
            self.enter_code(root)

    def enter_code(self, root):
        if not re.fullmatch(r"\d{6}", self.args.code or ""):
            raise RuntimeError("Android司机UI验证码必须显式配置六位数字")
        fields = self.client(className="android.widget.EditText").find_elements()
        if len(fields) == 1:
            fields[0].set_text(self.args.code)
        elif len(fields) == 6:
            fields.sort(key=lambda field: (field.bounds.y, field.bounds.x))
            for field, digit in zip(fields, self.args.code):
                field.set_text(digit)
        elif not fields:
            region = self.client(resourceId="com.sunlightmobility.driver:id/verify_code")
            region.click()
            for digit in self.args.code:
                self.client.driver.press_keycode(7 + int(digit))
        else:
            raise RuntimeError("Android司机验证码输入区域不唯一，禁止输入")
        self.wait_for({"offline", "online", "pickup"})

    def act(self, root, labels):
        """识别唯一真实滑块轨道及滑块后滑动；无轨道只允许明确按钮点击。"""
        target = find_label(root, labels)
        if target is None:
            raise RuntimeError(f"Android 找不到司机操作：{labels}")
        tracks = [node for node in visible_nodes(root)
                  if node.get("resource-id", "").split("/")[-1] in ("ll_drag_view", "drag_view", "sb_drag")
                  and target in list(node.iter())]
        if not tracks:
            from .JRYG_driver_ui import ACTION_LABELS
            if labels in tuple(ACTION_LABELS[phase] for phase in ("departure", "pickup", "onboard", "destination", "bill")) and target.tag not in ("XCUIElementTypeButton", "android.widget.Button", "android.widget.TextView"):
                raise RuntimeError("Android 司机滑块未定位，禁止盲点动作文字")
            self.client.click(*center(target))
            return
        if len(tracks) != 1:
            raise RuntimeError("Android 司机滑块不唯一，停止操作")
        track = tracks[0]
        x, y, width, height = rect(track)
        thumbs = [node for node in visible_nodes(track) if node.tag in ("XCUIElementTypeImage", "android.widget.ImageView")
                  and 0 < rect(node)[2] < width / 3 and center(node)[0] < x + width / 3]
        screen_width, screen_height = self.client.window_size()
        if len(thumbs) != 1 or width < screen_width * 0.4 or height > screen_height * 0.25:
            # 页面可能在读取后发生过渡变化（动画、布局调整），重新读取一次再判断
            import time as _time
            _time.sleep(0.5)
            root = self.root()
            target = find_label(root, labels)
            if target is None:
                raise RuntimeError(f"Android 重读页面后找不到司机操作：{labels}")
            tracks = [node for node in visible_nodes(root)
                      if node.get("resource-id", "").split("/")[-1] in ("ll_drag_view", "drag_view", "sb_drag")
                      and target in list(node.iter())]
            if not tracks or len(tracks) != 1:
                raise RuntimeError("Android 真实滑块/轨道无法明确识别，停止滑动")
            track = tracks[0]
            x, y, width, height = rect(track)
            thumbs = [node for node in visible_nodes(track) if node.tag in ("XCUIElementTypeImage", "android.widget.ImageView")
                      and 0 < rect(node)[2] < width / 3 and center(node)[0] < x + width / 3]
            if len(thumbs) != 1 or width < screen_width * 0.4 or height > screen_height * 0.25:
                raise RuntimeError("Android 真实滑块/轨道无法明确识别，停止滑动")
        sx, sy = center(thumbs[0])
        self.client.driver.execute_script("mobile: dragGesture", {
            "startX": sx, "startY": sy, "endX": round(x + width - 6), "endY": sy,
            "speed": max(1, round((x + width - 6 - sx) / 0.8)),
        })


class AndroidOrderMixin(AndroidPassengerMixin, AndroidPaymentMixin, AndroidUIBase):
    """组合乘客、支付及设备实现，供动态生成的共享订单用例继承。"""

    DRIVER_REQUIRED = True

    @classmethod
    def setup_class(cls):
        """在设备连接前拒绝未支持渠道，随后执行公共设备生命周期。"""
        if cls.PAYMENT not in ("cash", "epayment", "bankcard", "alipay"):
            raise ValueError("当前香港 iOS 默认场景不支持该支付方式，禁止连接设备及下单")
        super().setup_class()

    def _resolve_driver_runtime(self):
        """用本用例合并后的Android配置解析司机设备和单/双设备模式。"""
        return resolve_runtime(self.order_settings)

    def _driver_parser(self):
        """复用参数解析器并将司机报告输出定位到Android项目根。"""
        result = parser(wda_url=self._resolve_driver_runtime().wda_url)
        result.set_defaults(report_dir=str(BASE_DIR / "report/driver_ui"))
        return result

    def _create_driver_flow(self, args):
        """复用已建司机设备客户端，避免同一设备重复创建Appium会话。"""
        return AndroidDriverUIFlow(args, client=self.clients[self.driver_runtime.udid])

    @staticmethod
    def _normalized_driver_identity(value):
        """统一司机手机号和乘客页车牌字段，仅保留大写字母与数字。"""
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    def _expected_driver_assignment(self):
        """校验当前司机登录配置与乘客页身份映射，禁止配置不一致时下单。"""
        validation = self.order_settings.get("order_validation") or {}
        driver = self.order_settings.get("driver") or {}
        expected_phone = self._normalized_driver_identity(validation.get("expected_driver_phone"))
        active_phone = self._normalized_driver_identity(
            os.environ.get("HK_DRIVER_UI_MOBILE") or driver.get("mobile") or "11000005")
        expected_car = self._normalized_driver_identity(validation.get("expected_driver_car_number"))
        if not expected_phone or not expected_car:
            raise RuntimeError("未配置目标司机手机号与乘客页车牌映射，禁止下单")
        if active_phone != expected_phone:
            raise RuntimeError(
                f"当前司机登录手机号{active_phone or '空'}与目标司机{expected_phone}不一致，禁止下单")
        return expected_phone, expected_car

    def _driver_assignment_attempt_limit(self):
        """Android错配订单最多处理配置次数，防止无限预付或无限下单。"""
        self._expected_driver_assignment()
        maximum = (self.order_settings.get("order_validation") or {}).get("max_attempts", 5)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
            raise ValueError("目标司机下单次数上限必须为正整数")
        return maximum

    def _passenger_assigned_driver(self):
        """仅用乘客原生页面唯一状态和车牌控件读取已接单司机身份。"""
        self._assert_passenger_foreground()
        root = ET.fromstring(self.client.source())
        nodes = visible_nodes(root)
        statuses = {
            node_text(node).strip() for node in nodes
            if node.get("resource-id", "").split("/")[-1] == "tv_status_name"
            and node_text(node).strip()
        }
        cars = {
            node_text(node).strip() for node in nodes
            if node.get("resource-id", "").split("/")[-1] == "tv_car_number"
            and node_text(node).strip()
        }
        if len(statuses) != 1 or len(cars) != 1:
            return None
        return {"status": next(iter(statuses)), "car_number": next(iter(cars))}

    def _assigned_driver_matches(self, tag):
        """等待乘客端显示唯一接单车辆，并核对其属于当前登录的目标司机。"""
        expected_phone, expected_car = self._expected_driver_assignment()
        timeout = (self.order_settings.get("order_validation") or {}).get("state_timeout", 30)
        identity = self._wait(
            self._passenger_assigned_driver,
            "Android乘客订单页未出现唯一司机状态和车牌，禁止切换司机端",
            timeout=timeout,
        )
        self.assigned_driver_identity = identity
        actual_car = self._normalized_driver_identity(identity["car_number"])
        matched = actual_car == expected_car
        LOG.info(
            "【%s】乘客端接单司机核验：目标手机号=%s，目标车牌字段=%s，实际车牌字段=%s，匹配=%s",
            tag, expected_phone, expected_car, actual_car, matched,
        )
        return matched

    def _cancel_mismatched_driver_order(self, tag, attempt, maximum):
        """乘客端取消非目标司机订单；必须确认回首页后才允许再次下单。"""
        identity = getattr(self, "assigned_driver_identity", {})
        LOG.warning(
            "【%s】第%s/%s次订单由非目标司机接单，乘客页车牌=%s；正在通过乘客UI取消",
            tag, attempt, maximum, identity.get("car_number", "未知"),
        )
        self._ios_screenshot(
            f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_wrong_driver_{attempt}.png")
        self._clear_waiting_order(tag)
        LOG.info("【%s】非目标司机订单已确认取消并回到乘客首页", tag)

    def _ios_handle_unfinished_order_popup(self, tag):
        if not self._ios_click_dialog_button(["去完成", "去處理", "去处理"], wait_after=2):
            raise RuntimeError("Android 未定位遗留订单入口，停止，不假装已清理")
        self._clear_waiting_order(tag)

    def _clear_waiting_order(self, tag):
        def state():
            self._assert_passenger_foreground()
            texts = self._ios_get_all_texts(self.client)
            if any(keyword in text for text in texts for keyword in ("確認支付", "费用明细", "費用明細", "行程結束")):
                raise RuntimeError("遗留订单需要付款，缺少本次同单账单凭据，禁止自动付款")
            if any(keyword in text for text in texts for keyword in ("取消訂單", "取消订单")):
                return "waiting"
            if self.client(resourceId="com.sunlightmobility.client:id/tv_start_address").exists:
                return "home"
            return None
        if self._wait(state, "Android 遗留订单页面未确认") == "home":
            return
        self._click_text(["取消訂單", "取消订单"], exact=True)
        self._ios_click_dialog_button(self.CANCEL_CONFIRM_KEYWORDS, wait_after=1)

        def cleared():
            self._assert_passenger_foreground()
            texts = self._ios_get_all_texts(self.client)
            if any("未完成" in text or "取消訂單" in text or "取消订单" in text for text in texts):
                return False
            return self.client(resourceId="com.sunlightmobility.client:id/tv_start_address").exists
        self._wait(cleared, "Android 遗留订单未确认取消并回首页，停止后续下单")

    def _ui_cleanup_ongoing_order(self, tag):
        if not self.ensure_passenger_login(tag):
            raise RuntimeError("安卓乘客登录未核验，未处理遗留订单")
        texts = self._ios_get_all_texts(self.client)
        if any("未完成" in text and ("訂單" in text or "订单" in text) for text in texts):
            self._ios_handle_unfinished_order_popup(tag)
        else:
            self._clear_waiting_order(tag)

    def _ios_wait_current_payment(self, tag):
        """共享金额等待后核验付款页订单号唯一且与司机相同，尚不表示已付款。"""
        super()._ios_wait_current_payment(tag)
        texts = self._ios_get_all_texts(self.client)
        orders = {match for text in texts for match in re.findall(r"\b[A-Z0-9]{12}\b", text)
                  if any(char.isdigit() for char in match) and any(char.isalpha() for char in match)}
        if not self.driver_ui.order_no or orders != {self.driver_ui.order_no}:
            raise RuntimeError("Android 乘客付款页订单号缺失、非唯一或与司机不一致，禁止付款")
        LOG.info("【%s】Android乘客付款页与司机绑定同单：%s；尚未提交渠道付款", tag, self.driver_ui.order_no)


class AndroidOrderBase(AndroidOrderMixin, TestOrderBase):
    """安卓独立场景公共编排，必须完成行程并核验同订单已支付。"""

    __test__ = False
    pytestmark = []

    def _run_order_flow(self):
        if os.environ.get("HK_DRIVER_UI_STOP_AFTER", "submitted") != "submitted":
            raise RuntimeError("安卓完整场景不允许仅接单模式，未执行下单或支付")
        super().test_order_flow()
        driver = self.driver_ui
        if (not self.completed_order_no or driver.last_phase != "complete"
                or self.completed_order_no != driver.order_no or driver.awaiting_new_order
                or driver.order_no in driver.completed_before_run):
            raise AssertionError("安卓当前场景未通过同订单已完成且已支付核验")
