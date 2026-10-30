"""iOS 司机混合流程：仅打开 App、出车使用 UI，接单及状态流转使用接口。

默认：打开已登录司机 App，点击出车后立即返回，不使用 UI 接单或滑动订单。
--inspect：只打开 App 并读取状态，不出车、不接单。
--stop-after bill：复用 App 会话，接口接单并推进至账单阶段。
--stop-after complete --fare 5：接口提交测试账单并等待实际支付结果。
现金收款另须显式传入 --payment cash --cash-collected。
与乘客同时自动化时需要不同设备及 WDA 端口；不能争用同一台 iPhone。
"""

import argparse
from decimal import Decimal, InvalidOperation
import logging
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

import wda


BUNDLE_ID = "com.sunlightmobility.driver"
ACCEPT_LABELS = ("立即接單", "立即接单", "接單", "接单", "接受訂單")
ACTION_LABELS = {
    "offline": ("點擊出車",),
    "pickup": ("到達上車地點",),
    "onboard": ("已接載乘客",),
    "destination": ("到達目的地",),
    "bill": ("確認收款",),
}
PHASE_NAMES = {
    "login": "司机登录", "code": "验证码", "offline": "待出车",
    "online": "接单中", "offer": "新订单", "pickup": "前往上车点",
    "onboard": "等待乘客上车", "tail": "乘客尾号验证", "destination": "送乘客",
    "bill": "确认账单", "unpaid": "已完成但未支付", "complete": "已完成且已支付",
    "cancelled": "订单已取消", "unknown": "未识别页面",
}
LOG = logging.getLogger("JRYG_driver_ui")


def visible_nodes(root):
    return [node for node in root.iter() if node.get("visible") == "true"]


def node_text(node):
    return node.get("label") or node.get("name") or ""


def find_label(root, labels):
    matches = [node for node in visible_nodes(root)
               if node.get("enabled") != "false" and node_text(node) in labels]
    matches.sort(key=lambda node: node.tag != "XCUIElementTypeButton")
    return matches[0] if matches else None


def detect_phase(root, accept_labels=ACCEPT_LABELS):
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
        if any(label in texts for label in ACTION_LABELS[phase]):
            return phase
    if "已完成" in texts and "返回首頁" in texts:
        return "complete" if "已支付" in texts else "unpaid"
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
    return tuple(float(node.get(key, "0")) for key in ("x", "y", "width", "height"))


def center(node):
    x, y, width, height = rect(node)
    if width <= 0 or height <= 0:
        raise RuntimeError("目标控件坐标无效")
    return round(x + width / 2), round(y + height / 2)


def slider_points(root, target):
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
            _, _, thumb_width, _ = rect(thumb)
            start_x, start_y = center(thumb)
            end_x = round(x + width - thumb_width / 2 - 6)
            if width <= 120 or end_x - start_x <= 80 or height > 200:
                raise RuntimeError("滑块容器不明确，停止操作")
            return start_x, start_y, end_x, start_y
        container = parents.get(container)
    return None


class DriverUIFlow:
    def __init__(self, args):
        self.args = args
        self.client = wda.Client(args.wda_url)
        self.accept_labels = tuple(args.accept_label or ACCEPT_LABELS)
        self.last_phase = None
        self.deadline = None

    def root(self):
        root = ET.fromstring(self.client.source(format="xml"))
        applications = [node for node in root.iter() if node.tag == "XCUIElementTypeApplication"]
        if not applications or applications[0].get("bundleId") != BUNDLE_ID:
            raise RuntimeError("司机 App 已不在前台，停止操作以免误触其他 App")
        return root

    def snapshot(self, name):
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
        deadline = min(self.deadline, time.monotonic() + (timeout or self.args.step_timeout))
        while time.monotonic() < deadline:
            root = self.root()
            phase = detect_phase(root, self.accept_labels)
            if phase in phases:
                return root, phase
            if phase == "cancelled":
                raise RuntimeError("订单已取消，停止流转")
            time.sleep(self.args.interval)
        raise TimeoutError(f"页面未进入预期状态：{' / '.join(PHASE_NAMES[p] for p in phases)}")

    def field(self, root, placeholder):
        fields = [node for node in visible_nodes(root)
                  if node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")
                  and node.get("placeholderValue") == placeholder]
        if len(fields) != 1:
            raise RuntimeError(f"输入框无法唯一定位：{placeholder}")
        return fields[0]

    def fill(self, root, placeholder, value):
        target = self.field(root, placeholder)
        fields = list(self.client(className=target.tag))
        x, y = center(target)
        for field in fields:
            bounds = field.bounds
            if abs(bounds.x + bounds.width / 2 - x) < 5 and abs(bounds.y + bounds.height / 2 - y) < 5:
                field.click()
                field.clear_text()
                self.client.send_keys(value)
                return
        raise RuntimeError(f"输入框无法匹配 WDA 元素：{placeholder}")

    def dismiss_keyboard(self):
        root = self.root()
        done = find_label(root, ("Done", "完成"))
        if done is not None:
            self.client.click(*center(done))

    def login(self, root):
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
        if not self.args.code:
            raise RuntimeError("请手工输入验证码，或通过 HK_DRIVER_UI_CODE 配置测试验证码")
        cells = [node for node in visible_nodes(root) if node.tag == "XCUIElementTypeCell"]
        if len(cells) != 6:
            raise RuntimeError("验证码输入区域未识别，停止操作")
        self.client.click(*center(cells[0]))
        self.client.send_keys(self.args.code)
        self.wait_for({"offline", "online", "pickup"})

    def enter_tail(self, root):
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
        if detect_phase(root, self.accept_labels) == "tail":
            self.act(root, ("確認", "确认", "驗證", "验证"))
        self.wait_for({"destination"})

    def submit_bill(self, root):
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
        if self.field(root, "請輸入車費").get("value") != self.args.fare:
            value = self.field(root, "請輸入車費").get("value", "")
            try:
                matches = Decimal(value) == Decimal(self.args.fare)
            except InvalidOperation:
                matches = False
            if not matches:
                raise RuntimeError("车费输入未确认，禁止提交账单")
        self.act(root, ACTION_LABELS["bill"])
        self.wait_for({"unpaid", "complete"})

    def ensure_online(self):
        self.client.app_activate(BUNDLE_ID)
        self.deadline = time.monotonic() + self.args.timeout
        root, phase = self.wait_for(set(PHASE_NAMES) - {"unknown"})
        if phase in ("login", "code"):
            raise RuntimeError("司机 App 尚未登录，请先登录；本流程只打开 App 和出车")
        if phase == "offline":
            self.act(root, ACTION_LABELS["offline"])
            root, phase = self.wait_for({"online", "offer"})
        if phase not in ("online", "offer"):
            raise RuntimeError("司机已有行程或页面不适合出车，停止操作")
        self.last_phase = phase
        LOG.info("司机 App 已出车；后续订单操作全部使用接口")

    def check_online(self):
        phase = detect_phase(self.root(), self.accept_labels)
        if phase not in ("online", "offer"):
            raise RuntimeError("司机 App 已离开听单状态，停止乘客下单")
        self.last_phase = phase

    def run(self):
        if self.args.inspect:
            self.client.app_activate(BUNDLE_ID)
            self.deadline = time.monotonic() + self.args.timeout
            _, phase = self.wait_for(set(PHASE_NAMES))
            LOG.info("司机 App 状态：%s；未出车、未接单、未收款", PHASE_NAMES[phase])
            return
        if self.args.stop_after == "online":
            self.ensure_online()
            return
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import HKDriverApiClient
        from jryg_hk_ios.JRYG_driver_order_api import DriverOrderAPI, load_app_session

        api = HKDriverApiClient()
        load_app_session(api, self.args.session_file)
        self.ensure_online()
        orders = DriverOrderAPI(api, LOG)
        orders.require_online()
        orders.require_idle()
        order_no = orders.poll(self.args.timeout, self.args.interval, self.args.order_no)
        orders.advance(order_no, stop_after=self.args.stop_after, fare=self.args.fare,
                       surcharge=self.args.surcharge or 0, payment=self.args.payment,
                       cash_collected=self.args.cash_collected)
        if self.args.stop_after == "complete":
            orders.wait_completed(order_no, self.args.timeout, self.args.interval)


def amount(value):
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2:
            raise InvalidOperation
    except InvalidOperation:
        raise argparse.ArgumentTypeError("金额必须为非负数，最多两位小数")
    return format(number, "f")


def positive(value):
    number = float(value)
    if number <= 0 or number != number or number == float("inf"):
        raise argparse.ArgumentTypeError("等待时间必须为正数")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--wda-url", default=os.environ.get("HK_DRIVER_WDA_URL", "http://127.0.0.1:8100"))
    result.add_argument("--inspect", action="store_true", help="只打开司机 App 并检查状态")
    result.add_argument("--mobile", default=os.environ.get("HK_DRIVER_MOBILE"), help="登录手机号，已有登录态时无需传入")
    result.add_argument("--code", default=os.environ.get("HK_DRIVER_UI_CODE"), help="测试验证码，不写入日志")
    result.add_argument("--tail", help="出现乘客尾号验证时使用的四位测试尾号")
    result.add_argument("--stop-after", choices=("online", "pickup", "onboard", "destination", "bill", "complete"),
                        default="online", help="默认仅UI出车；其他阶段均通过接口推进")
    result.add_argument("--session-file", default=os.environ.get("HK_DRIVER_SESSION_FILE"), help="当前司机 App 会话JSON，不会重新API登录")
    result.add_argument("--order-no", help="只接指定的派单；未指定时要求唯一派单")
    result.add_argument("--accept-label", action="append", help="新订单按钮的精确文案，仅用于页面状态识别")
    result.add_argument("--fare", type=amount, help="显式指定测试车费；默认不提交账单")
    result.add_argument("--surcharge", type=amount, help="显式指定附加费，默认不改动")
    result.add_argument("--payment", choices=("online", "cash"), default="online", help="测试订单支付方式，不会修改乘客选择")
    result.add_argument("--cash-collected", action="store_true", help="确认已实际收到测试现金款")
    result.add_argument("--timeout", type=positive, default=600, help="总运行超时，单位秒")
    result.add_argument("--step-timeout", type=positive, default=30, help="每次操作后的状态确认超时")
    result.add_argument("--interval", type=positive, default=2, help="页面轮询间隔")
    result.add_argument("--report-dir", default=str(Path(__file__).resolve().parent / "report/driver_ui"))
    return result


def main():
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.mobile and (not args.mobile.isdigit() or len(args.mobile) != 8):
        argument_parser.error("香港测试手机号必须为8位数字")
    if args.code and (not args.code.isdigit() or len(args.code) != 6):
        argument_parser.error("测试验证码必须为6位数字")
    if args.tail and (not args.tail.isdigit() or len(args.tail) != 4):
        argument_parser.error("乘客尾号必须为4位数字")
    if args.stop_after == "complete" and args.fare is None and not args.inspect:
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
