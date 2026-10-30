"""iOS 司机全 UI 流程：打开 App、出车、接单、滑动状态及确认账单。

默认：打开已登录司机 App，点击出车后立即返回。
--inspect：只打开 App 并读取状态，不出车、不接单。
--stop-after bill：通过司机页面接单与滑动，停在账单页，不提交金额。
--stop-after submitted --fare 5：在司机页面提交账单后返回，便于切乘客 App 支付。
--stop-after complete --fare 5：通过 UI 提交账单并等待页面确认已支付（单设备请用双端用例付款）。
wait_completed：付款后核对本次订单，旧页未支付则返回首页并打开到账详情重新核验。
滑块首滑未生效时仅在原阶段且无弹窗重试一次，接单和账单不自动重提。
不调用司机业务 API、不创建 Socket、不加载 token 或会话文件。
现金收款另须显式传入 --payment cash --cash-collected。
默认可同设备顺序切换司机/乘客 App；双设备可配置独立 WDA，不并发争用同一设备。
"""

import argparse
from decimal import Decimal, InvalidOperation
import logging
import os
from pathlib import Path
import re
import sys
import time
import xml.etree.ElementTree as ET

import wda
from ui_framework.JRYG_logger import get_logger


BUNDLE_ID = "com.sunlightmobility.driver"
ACCEPT_LABELS = ("立即接單", "立即接单", "接單", "接单", "接受訂單")
ACTION_LABELS = {
    "offline": ("點擊出車",),
    "departure": ("已出發", "已出发"),
    "pickup": ("到達上車地點",),
    "onboard": ("已接載乘客",),
    "destination": ("到達目的地",),
    "bill": ("確認收款",),
}
PHASE_NAMES = {
    "login": "司机登录", "code": "验证码", "offline": "待出车",
    "online": "接单中", "offer": "新订单", "departure": "待确认出发", "pickup": "前往上车点",
    "onboard": "等待乘客上车", "tail": "乘客尾号验证", "destination": "送乘客",
    "bill": "确认账单", "unpaid": "已完成但未支付", "complete": "已完成且已支付",
    "cancelled": "订单已取消", "unknown": "未识别页面",
}
LOG = get_logger("JRYG_driver_ui")


def visible_nodes(root):
    """司机操作仅允许明确visible=true的节点，避免点到隐藏订单控件。"""
    return [node for node in root.iter() if node.get("visible") == "true"]


def node_text(node):
    """优先读取可访问label，缺失时使用name，空节点返回空字符串。"""
    return node.get("label") or node.get("name") or ""


def find_label(root, labels):
    """精确匹配可见且可用的候选文案，优先按钮，不做模糊坐标兜底。"""
    matches = [node for node in visible_nodes(root)
               if node.get("enabled") != "false" and node_text(node) in labels]
    matches.sort(key=lambda node: node.tag != "XCUIElementTypeButton")
    return matches[0] if matches else None


def read_order_no(root):
    """真实司机完成页显示独立的12位订单号；必须唯一，不使用示例订单号兜底。"""
    values = {node_text(n).strip() for n in visible_nodes(root)}
    orders = {value for value in values if re.fullmatch(r"[A-Z0-9]{12}", value)
              and any(c.isdigit() for c in value) and any(c.isalpha() for c in value)}
    if len(orders) != 1:
        raise RuntimeError("司机页面订单号缺失或不唯一，停止同订单核验")
    return orders.pop()


def detect_phase(root, accept_labels=ACCEPT_LABELS):
    """按登录、账单、真实滑块及订单终态识别阶段，未知页不猜测可执行动作。"""
    texts = {node_text(node) for node in visible_nodes(root)}
    if "歡迎登錄/註冊陽光司機版" in texts:
        return "login"
    if "請輸入驗證碼" in texts:
        return "code"
    if any("尾號" in text or "尾号" in text for text in texts):
        return "tail"
    if "確認賬單" in texts and "確認收款" in texts:
        return "bill"
    for phase in ("pickup", "onboard", "destination"):
        if find_label(root, ACTION_LABELS[phase]) is not None:
            return phase
    departure = find_label(root, ACTION_LABELS["departure"])
    # “已出發”也可能是历史状态文案；只有真实按钮或滑块才当作待确认出发。
    if departure is not None and (departure.tag == "XCUIElementTypeButton" or slider_points(root, departure) is not None):
        return "departure"
    if "已完成" in texts and texts.intersection({"已支付", "未支付"}):
        # 到账详情页没有“返回首頁”；同时出现冲突文案时不能确认已支付。
        return "unpaid" if "未支付" in texts else "complete"
    if "已取消" in texts and "返回首頁" in texts:
        return "cancelled"
    if "點擊出車" in texts:
        return "offline"
    if find_label(root, accept_labels) is not None:
        return "offer"
    if "接單中" in texts:
        return "online"
    return "unknown"


def rect(node):
    """读取页面树矩形为浮点数，缺失坐标为0，由操作前校验拒绝无效区域。"""
    return tuple(float(node.get(key, "0")) for key in ("x", "y", "width", "height"))


def center(node):
    """计算控件中心坐标；宽高无效立即停止，不能盲点页面原点。"""
    x, y, width, height = rect(node)
    if width <= 0 or height <= 0:
        raise RuntimeError("目标控件坐标无效")
    return round(x + width / 2), round(y + height / 2)


def slider_points(root, target):
    """最多向上查找三层滑块容器，终点为轨道右侧内缘；无滑块返回None。"""
    parents = {child: parent for parent in root.iter() for child in parent}
    target_y = center(target)[1]
    container = parents.get(target)
    for _ in range(3):
        if container is None:
            break
        thumbs = [node for node in visible_nodes(container)
                  if node.tag == "XCUIElementTypeImage"
                  and node.get("name", "").startswith("ca_icon_order_detail_hdjt")
                  and abs(center(node)[1] - target_y) < 40]
        if thumbs:
            thumb = thumbs[0]
            x, y, width, height = rect(container)
            start_x, start_y = center(thumb)
            # 拖动指针到轨道右侧内缘，让滑块达到最大位移；减去半个滑块会停在阈值之前。
            end_x = round(x + width - 6)
            if width <= 120 or end_x - start_x <= 80 or height > 200:
                raise RuntimeError("滑块容器不明确，停止操作")
            return start_x, start_y, end_x, start_y
        container = parents.get(container)
    return None


class DriverUIFlow:
    """司机全UI状态机：单步操作后必须确认状态，账单和付款不可自动重提。

    独立负责司机前台保护、输入、滑块、账单和同订单核验；与乘客基类共享的是
    调用顺序而非点击实现，避免把WebView付款与原生司机控件混为一类。
    """

    def __init__(self, args, client=None):
        """创建平台UI客户端和截止时间状态，不在构造时登录或推进订单。"""
        self.args = args
        if client is None:
            wda.HTTP_TIMEOUT = min(20, args.step_timeout)
            client = wda.Client(args.wda_url)
        self.client = client
        self.accept_labels = tuple(args.accept_label or ACCEPT_LABELS)
        self.last_phase = None
        self.deadline = None
        self.order_no = None

    def detect_phase(self, root):
        return detect_phase(root, self.accept_labels)

    def back_from_paid_detail(self, root):
        read_order_no(root)
        width, height = self.client.window_size()
        self.client.click(round(width * 0.055), round(height * 0.071))
        LOG.info("已支付详情左上返回箭头（截图验证位置）")

    def root(self):
        """读取司机页面树并强制验证司机App在前台，切到乘客或其他App时停止。"""
        root = ET.fromstring(self.client.source(format="xml"))
        applications = [node for node in root.iter() if node.tag == "XCUIElementTypeApplication"]
        if not applications or applications[0].get("bundleId") != BUNDLE_ID:
            raise RuntimeError("司机 App 已不在前台，停止操作以免误触其他 App")
        return root

    def snapshot(self, name):
        """保存带时间戳的XML与截图供核验；取证失败不重做订单业务动作。"""
        directory = Path(self.args.report_dir)
        directory.mkdir(parents=True, exist_ok=True)
        prefix = directory / f"{time.time_ns()}_{name}"
        try:
            prefix.with_suffix(".xml").write_text(self.client.source(format="xml"), encoding="utf-8")
            self.client.screenshot(str(prefix.with_suffix(".png")))
            LOG.info("已保存页面现场：%s", prefix)
        except Exception as exc:
            LOG.warning("保存页面现场失败：%s", type(exc).__name__)

    def act(self, root, labels):
        """精确定位后执行一次滑动或点击；是否重试由状态编排决定，不在此重提。"""
        target = find_label(root, labels)
        if target is None:
            raise RuntimeError(f"找不到操作控件：{' / '.join(labels)}")
        points = slider_points(root, target)
        if points is not None:
            self.client.swipe(*points, duration=0.8)
            LOG.info("滑动操作：%s", node_text(target))
        else:
            self.client.click(*center(target))
            LOG.info("点击操作：%s", node_text(target))

    def wait_for(self, phases, timeout=None):
        """有界轮询目标阶段，单步时限不能超过总截止时间，已取消立即失败。"""
        deadline = min(self.deadline, time.monotonic() + (timeout or self.args.step_timeout))
        while time.monotonic() < deadline:
            root = self.root()
            phase = self.detect_phase(root)
            if phase in phases:
                return root, phase
            if phase == "cancelled":
                raise RuntimeError("订单已取消，停止流转")
            time.sleep(self.args.interval)
        raise TimeoutError(f"页面未进入预期状态：{' / '.join(PHASE_NAMES[p] for p in phases)}")

    def field(self, root, placeholder):
        """按placeholder唯一定位可见输入框，缺失或重复时拒绝输入。"""
        fields = [node for node in visible_nodes(root)
                  if node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")
                  and node.get("placeholderValue") == placeholder]
        if len(fields) != 1:
            raise RuntimeError(f"输入框无法唯一定位：{placeholder}")
        return fields[0]

    def fill(self, root, placeholder, value):
        """有限枚举WDA控件并匹配坐标，依次聚焦、清空、输入；每步检查截止时间。"""
        target = self.field(root, placeholder)
        deadline = time.monotonic() + self.args.step_timeout
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)

        def step(name, action):
            """在输入动作前后核对时限，日志只记录阶段而不记录输入内容。"""
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{placeholder}：输入超时，停在{name}")
            LOG.info("输入步骤：%s — %s", placeholder, name)
            started = time.monotonic()
            result = action()
            LOG.info("输入步骤完成：%s — %s（%.2f秒）", placeholder, name,
                     time.monotonic() - started)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{placeholder}：{name}耗时过长，停止后续操作")
            return result

        selector = self.client(className=target.tag)
        fields = step("查找输入框", selector.find_elements)
        x, y = center(target)
        for field in fields:
            bounds = step("读取输入框坐标", lambda: field.bounds)
            if abs(bounds.x + bounds.width / 2 - x) < 5 and abs(bounds.y + bounds.height / 2 - y) < 5:
                step("聚焦输入框", lambda: self.client.click(x, y))
                step("清空旧内容", field.clear_text)
                step("输入内容", lambda: self.client.send_keys(value))
                LOG.info("输入内容已发送：%s", placeholder)
                return
        raise RuntimeError(f"输入框无法匹配 WDA 元素：{placeholder}")

    def dismiss_keyboard(self):
        """仅在真实Done/完成按钮存在时收键盘，不用盲点影响订单按钮。"""
        root = self.root()
        done = find_label(root, ("Done", "完成"))
        if done is not None:
            self.client.click(*center(done))

    def login(self, root):
        """仅使用显式测试手机号完成UI登录并确认结果，不获取业务接口会话。"""
        if not self.args.mobile:
            raise RuntimeError("司机尚未登录，请传入 --mobile 或先手工登录")
        self.fill(root, "請輸入手機號碼", self.args.mobile)
        root = self.root()
        unchecked = find_label(root, ("ca icon dl wxz",))
        if unchecked is not None:
            self.client.click(*center(unchecked))
        self.dismiss_keyboard()
        self.act(self.root(), ("下一步",))
        root, phase = self.wait_for({"code", "offline", "online", "pickup"})
        if phase == "code":
            self.enter_code(root)

    def enter_code(self, root):
        """只向已识别的六格验证码区域输入显式测试验证码，缺配置停止。"""
        if not self.args.code:
            raise RuntimeError("请手工输入验证码，或通过 HK_DRIVER_UI_CODE 配置测试验证码")
        cells = [node for node in visible_nodes(root) if node.tag == "XCUIElementTypeCell"]
        if len(cells) != 6:
            raise RuntimeError("验证码输入区域未识别，停止操作")
        self.client.click(*center(cells[0]))
        self.client.send_keys(self.args.code)
        self.wait_for({"offline", "online", "pickup"})

    def enter_tail(self, root):
        """使用显式乘客尾号验证，唯一输入框确认后才推进到送乘客阶段。"""
        if not self.args.tail:
            raise RuntimeError("出现乘客尾号校验，请传入 --tail；不从手机号猜测")
        fields = [node for node in visible_nodes(root) if node.tag == "XCUIElementTypeTextField"]
        if len(fields) != 1:
            raise RuntimeError("尾号输入区域未识别，请手工完成校验")
        placeholder = fields[0].get("placeholderValue")
        if not placeholder:
            raise RuntimeError("尾号输入框缺少定位标识，请手工完成校验")
        self.fill(root, placeholder, self.args.tail)
        self.dismiss_keyboard()
        root = self.root()
        if self.detect_phase(root) == "tail":
            self.act(root, ("確認", "确认", "驗證", "验证"))
        self.wait_for({"destination"})

    def submit_bill(self, root):
        """输入车费和附加费并回读核对后仅提交一次；现金必须显式确认已收款。"""
        if self.args.fare is None:
            raise RuntimeError("账单提交需显式传入 --fare，不自动填写或改动金额")
        texts = {node_text(node) for node in visible_nodes(root)}
        if texts.intersection({"現金", "現金支付", "现金", "现金支付"}) and self.args.payment != "cash":
            raise RuntimeError("页面显示现金支付，但 --payment 未指定 cash，停止账单提交")
        if self.args.payment == "cash" and not self.args.cash_collected:
            raise RuntimeError("现金收款需确认实际已收款，再传入 --cash-collected")
        self.fill(root, "請輸入車費", self.args.fare)
        if self.args.surcharge is not None:
            self.fill(self.root(), "請輸入附加費", self.args.surcharge)
        self.dismiss_keyboard()
        root = self.root()
        # 提交前核对两个输入框，避免键盘遮挡或输入失败导致金额错误。
        for placeholder, expected in (("請輸入車費", self.args.fare), ("請輸入附加費", self.args.surcharge)):
            if expected is None:
                continue
            value = self.field(root, placeholder).get("value", "")
            try:
                matches = Decimal(value) == Decimal(expected)
            except InvalidOperation:
                matches = False
            if not matches:
                raise RuntimeError(f"{placeholder}输入未确认，禁止提交账单")
        self.act(root, ACTION_LABELS["bill"])
        self.wait_for({"unpaid", "complete"})

    def ensure_online(self):
        """打开已登录司机App并出车；仅可返回旧已付详情，不自动清理进行中订单。"""
        self.client.app_activate(BUNDLE_ID)
        self.deadline = time.monotonic() + self.args.timeout
        root, phase = self.wait_for(set(PHASE_NAMES) - {"unknown"})
        if phase in ("login", "code"):
            raise RuntimeError("司机 App 尚未登录，请先登录；本流程只打开 App 和出车")
        if phase == "complete":
            # 上一次已支付详情可以安全返回首页；未支付或进行中订单不得自动清理。
            labels = ("返回首頁", "返回", "ca_icon_back_black", "ca icon back black")
            if find_label(root, labels) is not None:
                self.act(root, labels)
            else:
                self.back_from_paid_detail(root)
            root, phase = self.wait_for({"offline", "online", "offer"})
        if phase == "offline":
            self.act(root, ACTION_LABELS["offline"])
            root, phase = self.wait_for({"online", "offer"})
        if phase not in ("online", "offer"):
            raise RuntimeError("司机已有行程或页面不适合出车，停止操作")
        self.last_phase = phase
        LOG.info("司机 App 已出车；接单及后续状态全部在司机页面操作")

    def check_online(self):
        """乘客下单前只读确认司机仍在听单，不重新出车或接受未知订单。"""
        phase = self.detect_phase(self.root())
        if phase not in ("online", "offer"):
            raise RuntimeError("司机 App 已离开听单状态，停止乘客下单")
        self.last_phase = phase

    def run(self):
        """按目标阶段流转司机UI；无派单停止，仅同阶段无弹窗允许一次重滑。

        accepted停在接单后，submitted提交账单后等待乘客付款；订单号切换、
        未知页面或取消均不可继续。此方法不调用乘客支付或司机业务接口。
        """
        if self.args.inspect:
            self.client.app_activate(BUNDLE_ID)
            self.deadline = time.monotonic() + self.args.timeout
            _, phase = self.wait_for(set(PHASE_NAMES))
            LOG.info("司机 App 状态：%s；未出车、未接单、未收款", PHASE_NAMES[phase])
            return
        if self.args.stop_after == "online":
            self.ensure_online()
            return
        self.client.app_activate(BUNDLE_ID)
        self.deadline = time.monotonic() + self.args.timeout
        root, phase = self.wait_for(set(PHASE_NAMES) - {"unknown"})
        while time.monotonic() < self.deadline:
            self.last_phase = phase
            if phase in ("unpaid", "complete"):
                current_order = read_order_no(root)
                if self.order_no is not None and current_order != self.order_no:
                    raise RuntimeError("司机页面已切换到其他订单，停止操作")
                self.order_no = current_order
            LOG.info("司机 UI 阶段：%s", PHASE_NAMES[phase])
            if phase == self.args.stop_after:
                return
            if self.args.stop_after == "accepted":
                if phase in ("departure", "pickup"):
                    return
                if phase in ("onboard", "tail", "destination", "bill", "unpaid", "complete"):
                    raise RuntimeError("当前订单已超出接单阶段，停止接单调试")
            if phase == "complete":
                return
            if phase in ("unpaid", "complete") and self.args.stop_after == "submitted":
                # 账单已提交，立即交还乘客 App 支付，单设备也不会互相等待。
                return
            if phase == "login":
                self.login(root)
            elif phase == "code":
                self.enter_code(root)
            elif phase == "offline":
                self.act(root, ACTION_LABELS["offline"])
                root, phase = self.wait_for({"online", "offer", "departure", "pickup"})
                continue
            elif phase == "online":
                # 新订单只能从司机 App 的派单卡片取得，不查询 polling/grab 接口。
                root, phase = self.wait_for({"offer", "departure", "pickup"}, timeout=self.args.dispatch_timeout)
                continue
            elif phase == "offer":
                self.act(root, self.accept_labels)
                root, phase = self.wait_for({"departure", "pickup"})
                continue
            elif phase in ("departure", "pickup", "onboard", "destination"):
                # 到达上车点、接载乘客、到达目的地均使用页面滑块/按钮，不模拟位置轨迹。
                transitions = {"departure": {"pickup"}, "pickup": {"onboard"},
                               "onboard": {"tail", "destination"}, "destination": {"bill", "unpaid", "complete"}}
                self.act(root, ACTION_LABELS[phase])
                try:
                    root, phase = self.wait_for(transitions[phase])
                except TimeoutError:
                    # 只在仍为同阶段且无弹窗时最多重试一次；接单和账单提交不自动重试。
                    root = self.root()
                    if self.detect_phase(root) != phase or any(n.tag == "XCUIElementTypeAlert" for n in visible_nodes(root)):
                        raise
                    LOG.warning("%s首滑未生效，当前仍为同阶段；仅重试一次，不模拟定位", PHASE_NAMES[phase])
                    self.act(root, ACTION_LABELS[phase])
                    root, phase = self.wait_for(transitions[phase])
                continue
            elif phase == "tail":
                self.enter_tail(root)
            elif phase == "bill":
                self.submit_bill(root)
            elif phase == "unpaid":
                # 在线支付必须等待真实页面“已支付”，不能将“已完成但未支付”当成功。
                root, phase = self.wait_for({"complete"}, timeout=self.args.timeout)
                continue
            elif phase == "cancelled":
                raise RuntimeError("订单已取消，停止流转")
            else:
                raise RuntimeError("司机页面未识别，停止误操作；不会回退调用业务接口")
            root, phase = self.wait_for(set(PHASE_NAMES) - {"unknown"})
        raise TimeoutError("司机 UI 流转超时；未取消订单、未收车")

    def wait_completed(self):
        """按真机走通顺序：旧完成页 → 返回首页 → 收入到账详情 → 同订单已支付。"""
        if not self.order_no:
            raise RuntimeError("缺少本次账单订单号，不能用任意已支付订单代替核验")
        self.client.app_activate(BUNDLE_ID)
        self.deadline = time.monotonic() + self.args.payment_timeout
        root, phase = self.wait_for({"unpaid", "complete"})
        if read_order_no(root) != self.order_no:
            raise RuntimeError("司机完成页不是本次订单，停止支付核验")
        if phase == "unpaid":
            # 静态完成页不会自动刷新，禁止因此重付或重复确认账单。
            self.act(root, ("返回首頁",))
            self.wait_for({"online", "offer", "offline"})
            while time.monotonic() < self.deadline:
                root = self.root()
                texts = {node_text(n).strip() for n in visible_nodes(root)}
                if "收入到賬" in texts and "查看詳情" in texts:
                    # App 控件实际带尾空格，用真实完整 label 定位。
                    labels = tuple(node_text(n) for n in visible_nodes(root) if node_text(n).strip() == "查看詳情")
                    self.act(root, labels)
                    break
                time.sleep(self.args.interval)
            else:
                raise TimeoutError("司机首页未收到到账通知；不重复支付或提交账单")
            # 详情加载短暂空白；就算页面出现已支付，也必须核对本次订单号。
            while time.monotonic() < self.deadline:
                root = self.root()
                phase = self.detect_phase(root)
                if phase in ("unpaid", "complete"):
                    if read_order_no(root) != self.order_no:
                        raise RuntimeError("到账详情属于其他订单，停止支付核验")
                    if phase == "complete":
                        break
                time.sleep(self.args.interval)
            else:
                raise TimeoutError("本次订单详情未确认已完成且已支付")
        self.last_phase = "complete"
        self.snapshot("completed_paid")
        LOG.info("司机同订单详情已确认完成且已支付：%s", self.order_no)


def amount(value):
    """校验有限非负金额和两位小数精度，返回无科学计数法的输入文本。"""
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2:
            raise InvalidOperation
    except InvalidOperation:
        raise argparse.ArgumentTypeError("金额必须为非负数，最多两位小数")
    return format(number, "f")


def positive(value):
    """将等待时间解析为有限正数，拒绝零、负数及非有限值。"""
    number = float(value)
    if number <= 0 or number != number or number == float("inf"):
        raise argparse.ArgumentTypeError("等待时间必须为正数")
    return number


def parser(wda_url=None):
    """构建司机UI命令参数，复用运行配置与金额/超时校验，不启动设备动作。"""
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from ui_framework.JRYG_driver_runtime import resolve_runtime

    result.add_argument("--wda-url", default=resolve_runtime().wda_url if wda_url is None else wda_url)
    result.add_argument("--inspect", action="store_true", help="只打开司机 App 并检查状态")
    result.add_argument("--mobile", default=os.environ.get("HK_DRIVER_MOBILE"), help="登录手机号，已有登录态时无需传入")
    result.add_argument("--code", default=os.environ.get("HK_DRIVER_UI_CODE"), help="测试验证码，不写入日志")
    result.add_argument("--tail", default=os.environ.get("HK_DRIVER_PASSENGER_TAIL"), help="出现乘客尾号验证时使用的四位测试尾号")
    result.add_argument("--stop-after", choices=("online", "accepted", "pickup", "onboard", "destination", "bill", "submitted", "complete"),
                        default="online", help="accepted 仅接单后停止；submitted 提交账单后暂停等待乘客支付")
    result.add_argument("--accept-label", action="append", help="司机接单按钮的精确文案，可重复配置")
    result.add_argument("--fare", type=amount, help="显式指定测试车费；默认不提交账单")
    result.add_argument("--surcharge", type=amount, help="显式指定附加费，默认不改动")
    result.add_argument("--payment", choices=("online", "cash"), default="online", help="测试订单支付方式，不会修改乘客选择")
    result.add_argument("--cash-collected", action="store_true", help="确认已实际收到测试现金款")
    result.add_argument("--timeout", type=positive, default=600, help="总运行超时，单位秒")
    result.add_argument("--step-timeout", type=positive, default=30, help="每次操作后的状态确认超时")
    result.add_argument("--dispatch-timeout", type=positive, default=90, help="等待司机页面实际派单超时")
    result.add_argument("--payment-timeout", type=positive, default=90, help="支付后等待司机到账及同订单详情超时")
    result.add_argument("--interval", type=positive, default=2, help="页面轮询间隔")
    result.add_argument("--report-dir", default=str(Path(__file__).resolve().parents[1] / "report/driver_ui"))
    return result


def main():
    """校验测试参数并执行状态机；失败留现场，退出码0/1/130表示成功/失败/中断。"""
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.mobile and (not args.mobile.isdigit() or len(args.mobile) != 8):
        argument_parser.error("香港测试手机号必须为8位数字")
    if args.code and (not args.code.isdigit() or len(args.code) != 6):
        argument_parser.error("测试验证码必须为6位数字")
    if args.tail and (not args.tail.isdigit() or len(args.tail) != 4):
        argument_parser.error("乘客尾号必须为4位数字")
    if args.stop_after in ("submitted", "complete") and args.fare is None and not args.inspect:
        argument_parser.error("完整账单流程必须显式传入 --fare")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    wda.HTTP_TIMEOUT = 20
    flow = DriverUIFlow(args)
    try:
        flow.run()
        return 0
    except KeyboardInterrupt:
        LOG.warning("运行已停止；未取消订单、未收车，请检查司机 App 当前状态")
        return 130
    except Exception as exc:
        LOG.error("司机端流程失败：%s", exc)
        flow.snapshot("failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
