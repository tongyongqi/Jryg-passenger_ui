"""V1.5.0 新功能真机调试步骤：预约用车、安全中心、邮箱收据、收银台。

继承 AndroidPassengerBase，复用既有登录、设备生命周期和 UI 操作工具。
每个步骤方法均遵循既有模式：
- 主动操作前检测熄屏；第二轮预约呼叫后仅只读等待，禁止唤醒或交互
- 使用规范化或原生页面树定位控件
- 支持繁体/简体文案

预约场景按两轮执行：首轮下单后取消并返回首页，第二轮等待系统超时。
不操作司机、不采集业务接口、不支付、不清理已有订单。

真机 UI 结构已通过 uiautomator dump 验证：
- 预约入口：首页 id=tv_home_reservation「預約用車」
- 时间选择器弹窗：id=time_wheels，含 rv_date/rv_hour/rv_minute，确认 id=btn_confirm
- 预约页面：id=reservation_title「歡迎使用預約服務」，出发时间 id=reservation_departure_time
- 安全中心入口：首页 id=tv_safe「安全中心」
"""

import json
import os
import re
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .JRYG_android_passenger import AndroidPassengerBase
from .JRYG_driver_ui import center, rect, visible_nodes
from . import JRYG_ios_ui_elements as E
from .JRYG_logger import logger
from .JRYG_v150_contract import (
    BOOKING_TIMEOUT_MINUTES,
    ceil_five_minutes,
    CONTACT_LIMIT,
    CONTACT_NAME_LIMIT,
    PAYMENT_ORDER,
    SAFETY_ENTRY_PAGES,
    effective_min_booking_interval,
    format_use_time,
    validate_booking_time,
    validate_contact_input,
    normalize_email,
    save_email,
    receipt_auto_eligible,
    receipt_controls,
    receipt_event_source,
    receipt_failure_state,
    receipt_rate_allowed,
    receipt_request,
    receipt_success_state,
)
from .JRYG_v150_api_log import check_api_response, parse_api_calls, summarize_calls


class V150DeviceSteps(AndroidPassengerBase):
    """V1.5.0 新功能真机调试步骤基类，不被 pytest 直接收集。

    每个步骤方法返回页面核验结果或抛出 RuntimeError/TimeoutError。
    调用方负责异常处理和截图留存。
    """

    __test__ = False

    # ==================== 预约用车 ====================

    def v150_open_booking_entry(self, tag="v150_booking"):
        """从首页点击「預約用車」入口，等待时间选择器弹窗出现。

        真机 UI 结构：
        - 首页入口 id=tv_home_reservation，文案「預約用車」
        - 点击后弹出时间选择器弹窗（非新页面），id=time_wheels，
          含 rv_date/rv_hour/rv_minute 三个 RecyclerView 滚轮
        - 弹窗标题 id=tv_title「選擇出發時間」，确认按钮 id=btn_confirm「確認」

        返回页面类型标识字符串。
        """
        if getattr(self, "_v150_active_booking", None) is not None:
            raise RuntimeError("本次预约尚未处理完成，不允许重新打开预约入口")
        self._ensure_devices_awake()
        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        # 预约入口匹配：优先 resource-id，其次文案
        entry = [n for n in nodes if n.get("resource-id", "").split("/")[-1] == "tv_home_reservation"
                 and n.get("enabled") != "false"]
        if not entry:
            booking_labels = ("預約用車", "预约用车")
            entry = [n for n in nodes if (n.get("label") or "").strip() in booking_labels
                     and n.get("enabled") != "false"]
        if not entry:
            raise RuntimeError("V1.5.0 预约用车入口不可见，可能未在 services 配置中开启")
        if len(entry) > 1:
            raise RuntimeError("V1.5.0 预约用车入口不唯一，禁止点击")
        self.client.click(* center(entry[0]))
        logger.info("【%s】已点击预约用车入口", tag)
        # 等待时间选择器弹窗出现
        self._wait(
            lambda: self._v150_time_picker_open(),
            "V1.5.0 预约时间选择器弹窗未出现",
            timeout=15,
        )
        page = self._v150_current_page_type()
        logger.info("【%s】预约时间选择器已就绪，页面类型=%s", tag, page)
        return page

    def _v150_time_picker_open(self):
        """检测时间选择器弹窗是否已打开。

        真机特征：id=time_wheels 或 id=tv_title（「選擇出發時間」）或 id=btn_confirm。
        """
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        ids = {n.get("resource-id", "").split("/")[-1] for n in nodes}
        texts = {(n.get("label") or "").strip() for n in nodes}
        return ("time_wheels" in ids or "btn_confirm" in ids or
                texts.intersection({"選擇出發時間", "选择出发时间"}))

    def _v150_booking_root(self):
        """只读原生页面，保留滚轮 selected；不唤醒、不激活应用。"""
        self._assert_passenger_foreground()
        return ET.fromstring(self.client.driver.page_source)

    @staticmethod
    def _v150_booking_now():
        return datetime.now(ZoneInfo("Asia/Hong_Kong")).replace(tzinfo=None)

    def _v150_booking_click(self, *, ids=(), texts=()):
        if getattr(self, "_v150_passive_wait", False):
            raise RuntimeError("预约超时等待期间禁止操作")
        root = self._v150_booking_root()
        node = self._login_find(root, ids=ids, texts=texts)
        self._login_native(root, node).click()

    def v150_select_booking_time(self, tag="v150_booking", *, minutes_ahead=35, exact=False):
        """原始间隔先校验；exact模式不把精确边界改成其他五分钟刻度。"""
        now = self._v150_booking_now()
        target = now + timedelta(minutes=minutes_ahead)
        ok, message = validate_booking_time(now, target)
        if not ok:
            raise ValueError(f"预约原始时间不在29分钟至72小时闭区间内：{message}")
        rounded = ceil_five_minutes(target)
        if rounded != target and (exact or minutes_ahead in (29, 72 * 60)):
            raise RuntimeError("精确预约边界不在界面五分钟刻度上；未取整改写边界，未操作时间选择器")
        ok, message = validate_booking_time(now, rounded)
        if not ok:
            raise RuntimeError(f"V1.5.0 预约时间取整后越界：{message}")
        self._ensure_devices_awake()
        if not self._v150_time_picker_open():
            raise RuntimeError("V1.5.0 时间选择器未打开，无法选择时间")
        for recycler_id, value in (("rv_date", rounded.strftime("%Y-%m-%d")),
                                   ("rv_hour", str(rounded.hour)),
                                   ("rv_minute", str(rounded.minute))):
            self._v150_scroll_recycler_to(recycler_id, target_str=value)
        self._v150_confirm_booking_time(rounded)
        self._wait(lambda: not self._v150_time_picker_open(), "时间选择器未关闭", timeout=10)
        expected = rounded.strftime("%Y/%m/%d %H:%M")
        self._wait(lambda: self._v150_booking_value("reservation_departure_time") == expected,
                   f"预约时间回读不一致，预期 {expected}，未继续选址", timeout=10)
        self._v150_use_time = rounded
        logger.info("【%s】预约时间已回读确认：%s", tag, expected)
        return format_use_time(rounded)

    def _v150_booking_value(self, resource_id):
        nodes = [n for n in self._login_visible(self._v150_booking_root())
                 if n.get("resource-id", "").split("/")[-1] == resource_id]
        if len(nodes) > 1:
            raise RuntimeError(f"预约控件不唯一：{resource_id}")
        return (nodes[0].get("text") or "").strip() if nodes else ""

    def _v150_wait_time_picker_stable(self, *, timeout=10):
        """只读等待滚轮归位及确认按钮可用，连续稳定至少0.5秒后返回同一快照。"""
        deadline = time.monotonic() + timeout
        previous = None
        stable_since = None
        last_reason = "尚未读取时间选择器"
        wheel_ids = ("rv_date", "rv_hour", "rv_minute")
        prefix = self.order_settings["packages"]["passenger_hk"] + ":id/"
        while time.monotonic() < deadline:
            root = self._v150_booking_root()
            nodes = self._login_visible(root)
            controls = {}
            selected = {}
            reasons = []
            for name in ("time_wheels", *wheel_ids, "btn_confirm"):
                matches = [n for n in nodes if n.get("resource-id") == prefix + name]
                if len(matches) > 1:
                    raise RuntimeError(f"预约时间控件 {name} 不唯一：可见数量={len(matches)}，未操作")
                if not matches:
                    reasons.append(f"{name} 暂不可见")
                else:
                    controls[name] = matches[0]
            if not reasons:
                for name in wheel_ids:
                    wheel = controls[name]
                    if wheel not in list(controls["time_wheels"].iter()):
                        raise RuntimeError(f"{name} 不属于当前时间选择器，未操作")
                    choices = [n for n in self._login_visible(wheel)
                               if n.get("selected") == "true" and (n.get("text") or "").strip()]
                    if len(choices) > 1:
                        raise RuntimeError(f"滚轮 {name} 无唯一选中值，未操作")
                    if not choices:
                        reasons.append(f"{name} 暂无选中值")
                    else:
                        selected[name] = choices[0]
                        if abs(center(choices[0])[1] - center(wheel)[1]) > 2:
                            reasons.append(f"{name} 选中项仍在移动或未归位")
                button = controls["btn_confirm"]
                if button.get("enabled") != "true":
                    reasons.append("btn_confirm 存在但 enabled=false，等待滚轮停止")
                if button.get("clickable") != "true":
                    reasons.append("btn_confirm 暂不可点击")
            if reasons:
                last_reason = "；".join(reasons)
                previous = stable_since = None
            else:
                fingerprint = tuple((selected[name].get("text"), selected[name].get("bounds"))
                                    for name in wheel_ids) + (controls["btn_confirm"].get("bounds"),)
                now = time.monotonic()
                if fingerprint != previous:
                    previous, stable_since = fingerprint, now
                elif now - stable_since >= 0.5:
                    return root, controls, selected
                last_reason = "滚轮及确认按钮尚未连续稳定0.5秒"
            time.sleep(min(0.3, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"预约时间选择器未稳定：{last_reason}；未点击确认")

    def _v150_confirm_booking_time(self, expected):
        if getattr(self, "_v150_passive_wait", False):
            raise RuntimeError("预约超时等待期间禁止操作")
        root, controls, selected = self._v150_wait_time_picker_stable()
        actual = (selected["rv_date"].get("text").strip(),
                  int(selected["rv_hour"].get("text")), int(selected["rv_minute"].get("text")))
        target = (expected.strftime("%Y-%m-%d"), expected.hour, expected.minute)
        if actual != target:
            raise RuntimeError(f"预约确认前时间已变化：实际={actual}，预期={target}；未点击确认")
        self._login_native(root, controls["btn_confirm"]).click()

    def _v150_scroll_recycler_to(self, recycler_id, *, target_str):
        """等滚轮停止后读取选中值；优先点击可见目标项，避免滑动惯性越过目标。"""
        if getattr(self, "_v150_passive_wait", False):
            raise RuntimeError("预约超时等待期间禁止操作")
        target = int(target_str.replace("-", ""))
        previous = None
        stalled = 0
        for _ in range(60):
            root, controls, selected = self._v150_wait_time_picker_stable()
            wheel = controls[recycler_id]
            text = selected[recycler_id].get("text").strip()
            current = int(text.replace("-", ""))
            if current == target:
                return
            stalled = stalled + 1 if current == previous else 0
            if stalled >= 3:
                raise RuntimeError(f"滚轮 {recycler_id} 停滞于 {text}，目标 {target_str}")
            previous = current
            matches = [n for n in self._login_visible(wheel)
                       if re.fullmatch(r"\d{1,2}|\d{4}-\d{2}-\d{2}", n.get("text", "").strip())
                       and int(n.get("text").strip().replace("-", "")) == target]
            if len(matches) > 1:
                raise RuntimeError(f"滚轮 {recycler_id} 目标值 {target_str} 不唯一，未操作")
            if matches and matches[0].get("clickable") == "true" and matches[0].get("enabled") == "true":
                self._login_native(root, matches[0]).click()
            else:
                x, y = center(wheel)
                step = rect(selected[recycler_id])[3]
                direction = -1 if target > current else 1
                self.client.swipe(x, y, x, y + direction * step, 0.4)
        raise TimeoutError(f"滚轮 {recycler_id} 未到目标 {target_str}，未确认时间")

    def v150_verify_booking_page(self, tag="v150_booking"):
        """验证预约用车页面（时间选择确认后）是否正确显示。

        真机 UI 结构（时间选择确认后进入预约页面）：
        - id=reservation_title「歡迎使用預約服務」
        - id=reservation_subtitle「提前預約車輛 出行有保障」
        - id=reservation_departure_time 显示选中的预约时间
        - id=reservation_origin 起点地址
        - id=reservation_destination 终点地址
        - id=reservation_confirm「確認」确认按钮
        - id=reservation_back 返回按钮
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        ids = {n.get("resource-id", "").split("/")[-1] for n in nodes}
        # 预约页面特征
        has_title = "reservation_title" in ids
        has_departure_time = "reservation_departure_time" in ids
        has_origin = "reservation_origin" in ids
        has_destination = "reservation_destination" in ids
        has_confirm = "reservation_confirm" in ids
        has_back = "reservation_back" in ids
        if not has_title:
            raise RuntimeError("V1.5.0 预约页面未出现标题控件 reservation_title")
        if not has_departure_time:
            raise RuntimeError("V1.5.0 预约页面未显示出发时间 reservation_departure_time")
        if not has_confirm:
            raise RuntimeError("V1.5.0 预约页面未出现确认按钮 reservation_confirm")
        # 读取预约时间
        time_node = [n for n in nodes if n.get("resource-id", "").split("/")[-1] == "reservation_departure_time"]
        departure_time = (time_node[0].get("label") or "").strip() if time_node else ""
        logger.info("【%s】预约页面已确认：出发时间=%s, 确认=%s, 返回=%s",
                     tag, departure_time, has_confirm, has_back)
        return {
            "title": has_title,
            "departure_time": departure_time,
            "origin": has_origin,
            "destination": has_destination,
            "confirm": has_confirm,
            "back": has_back,
        }

    def v150_verify_booking_cancel_flow(self, tag="v150_booking"):
        """验证预约页面点击返回后回到首页。

        不实际提交预约订单，仅在预约页面点击返回按钮，验证回到首页。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        # 点击 reservation_back 返回按钮
        back = [n for n in nodes if n.get("resource-id", "").split("/")[-1] == "reservation_back"
                and n.get("enabled") != "false"]
        if back:
            self.client.click(* center(back[0]))
            logger.info("【%s】已点击预约返回按钮", tag)
        else:
            self.client.driver.back()
            logger.info("【%s】使用系统返回键", tag)
        time.sleep(1)
        # 验证返回到的页面
        page = self._v150_current_page_type()
        logger.info("【%s】预约取消后页面类型=%s", tag, page)
        return page

    def _v150_booking_texts(self, root):
        return {(n.get("text") or n.get("content-desc") or "").strip()
                for n in self._login_visible(root)}

    def _v150_assert_booking_route(self, start, end):
        names = self.order_settings["order_validation"]
        compact = lambda value: re.sub(r"\s+", "", value)
        starts = {compact(name + suffix) for name in names["start_names"]
                  for suffix in ("", E.NORTH_POINT_EXIT)}
        ends = {compact(name) for name in names["end_names"]}
        if compact(start) not in starts or compact(end) not in ends:
            raise AssertionError(f"预约路线回读不一致：{start} → {end}，未呼叫")

    def _v150_confirm_booking_origin(self):
        """A1回填表单即完成起点选择；仅出现专用确认页时点击一次。"""
        confirm_texts = ("確認起點", "确认起点", "確認上車點", "确认上车点", "確認出發點", "确认出发点")
        clicked = False
        def ready():
            nonlocal clicked
            root = self._v150_booking_root()
            nodes = self._login_visible(root)
            ids = {n.get("resource-id", "").split("/")[-1] for n in nodes}
            if "et_search" in ids:
                return False
            if self._v150_booking_texts(root).intersection(confirm_texts):
                if not clicked:
                    self._v150_booking_click(texts=confirm_texts)
                    clicked = True
                return False
            if {"reservation_origin", "reservation_destination", "reservation_confirm"}.issubset(ids):
                origins = [n for n in nodes if n.get("resource-id", "").endswith("/reservation_origin")]
                if len(origins) != 1:
                    raise RuntimeError("预约起点不唯一，未选择终点")
                self._v150_assert_booking_route(origins[0].get("text", "").strip(), E.DEFAULT_END_ADDRESS)
                return True
            return False
        self._wait(ready, "起点确认后未回填正确预约表单，未选择终点", timeout=15)

    def v150_prepare_booking_route(self, tag="v150_booking"):
        """选择北角站并确认起点，再选择港大；仅提交预约表单进入询价。"""
        self.v150_verify_booking_page(tag)
        limits = self.order_settings["order_validation"]
        self._search_address(["reservation_origin"], [], E.DEFAULT_START_ADDRESS, limits["start_names"])
        self._v150_confirm_booking_origin()
        logger.info("【%s】已确认起点：北角地铁站", tag)
        self._search_address(["reservation_destination"], [], E.DEFAULT_END_ADDRESS, limits["end_names"])
        self._wait(lambda: bool(self._v150_booking_value("reservation_destination")),
                   "选择香港大学后未返回预约表单", timeout=15)
        start = self._v150_booking_value("reservation_origin")
        end = self._v150_booking_value("reservation_destination")
        self._v150_assert_booking_route(start, end)
        expected = self._v150_use_time.strftime("%Y/%m/%d %H:%M")
        if self._v150_booking_value("reservation_departure_time") != expected:
            raise AssertionError("选址后预约时间发生变化，未进入询价")
        self._v150_booking_click(ids=("reservation_confirm",))
        self._wait(lambda: bool(self._v150_booking_quote()), "预约询价页未就绪，未呼叫", timeout=45)
        logger.info("【%s】已进入预约询价页：%s → %s", tag, start, end)

    def _v150_booking_quote(self):
        root = self._passenger_root()
        times = [(n.get("label") or "").strip() for n in visible_nodes(root)
                 if n.get("resource-id", "").endswith("/tv_reservation_time")]
        if not times:
            return None
        if times != [self._v150_use_time.strftime("%Y/%m/%d %H:%M")]:
            raise RuntimeError("询价页预约时间不一致，未呼叫")
        for car_type in ("charter", "meter"):
            quote = self._ios_estimate_quote(root, car_type)
            if quote is not None:
                self._v150_assert_booking_route(*quote[0])
                return quote
        return None

    def _v150_booking_status(self):
        """只读当前页面，区分主动取消、系统超时、呼叫中和已接单。"""
        root = self._v150_booking_root()
        texts = self._v150_booking_texts(root)
        contains = lambda words: any(word in text for word in words for text in texts)
        order_numbers = {match.group(1) for text in texts for match in
                         [re.fullmatch(r"(?:訂單編號|订单编号|訂單號|订单号)?\s*[:：]?\s*([A-Z0-9]{12})", text)]
                         if match and re.search(r"[A-Z]", match.group(1)) and re.search(r"\d", match.group(1))}
        if len(order_numbers) > 1:
            raise RuntimeError("预约页面出现多个订单号，停止操作")
        order_no = next(iter(order_numbers), None)
        active = getattr(self, "_v150_active_booking", None)
        if active is not None and order_no:
            if active.get("order_no") not in (None, order_no):
                raise RuntimeError("预约页面订单号发生变化，停止操作")
            active["order_no"] = order_no
        status = {
            "root": root,
            "order_no": order_no,
            "calling": contains(("正在為您預約", "正在为您预约", "正在為您呼叫", "正在为您呼叫")),
            "cancelled": contains(("訂單已取消", "订单已取消", "已自動取消訂單", "已自动取消订单")),
            "timeout": contains(("暫無司機接單", "暂无司机接单", "訂單已超時", "订单已超时",
                                 "呼叫超時", "呼叫超时")),
            "accepted": contains(("司機正在趕來", "司机正在赶来", "司機已接單", "司机已接单", "行程中")),
        }
        fingerprint = tuple(status[key] for key in ("calling", "cancelled", "timeout", "accepted"))
        if active is not None and active.get("last_status") != fingerprint:
            active["last_status"] = fingerprint
            logger.info("预约状态变化：阶段=%s，呼叫中=%s，已取消=%s，超时=%s，已接单=%s",
                        active["phase"], *fingerprint)
        return status

    def _v150_append_bug(self, bug_path, summary):
        """记录 Bug 路径到汇总列表，最终在用例结束时输出。"""
        if not hasattr(self, "_v150_bug_paths"):
            self._v150_bug_paths = []
        self._v150_bug_paths.append({"path": bug_path, "summary": summary})
        logger.error("【Bug 汇总】%s → %s", summary, bug_path)

    def v150_bug_summary(self):
        """返回本轮所有已记录 Bug 的路径和摘要，供测试用例断言或输出。"""
        return getattr(self, "_v150_bug_paths", [])

    def _v150_record_bug(self, *, category, title, expected, actual, phase, order_no=None,
                         root=None, tag="v150_booking"):
        """提取并记录 Bug 证据到 report/v150_bugs/ 目录，方便后续提交。

        保存内容：
        - JSON 结构化记录（时间线、预期、实际、页面文本快照）
        - 页面 XML 快照（如有 root）
        - 截图（如设备会话可用）

        返回 Bug 记录文件路径，不抛异常，不操作订单。
        """
        bug_dir = Path("report/v150_bugs")
        bug_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        bug_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{category}"
        texts = []
        if root is not None:
            texts = [n.get("text", "") for n in self._login_visible(root) if n.get("text")]
        record = {
            "bug_id": bug_id,
            "timestamp": now.isoformat(),
            "category": category,
            "title": title,
            "phase": phase,
            "tag": tag,
            "order_no": order_no,
            "expected": expected,
            "actual": actual,
            "page_texts": texts,
            "status_fingerprint": getattr(self, "_v150_active_booking", {}).get("last_status"),
        }
        json_path = bug_dir / f"{bug_id}.json"
        json_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if root is not None:
            xml_path = bug_dir / f"{bug_id}.xml"
            try:
                xml_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
            except Exception as exc:
                logger.warning("Bug XML 快照保存失败：%s", exc)
        try:
            png_path = bug_dir / f"{bug_id}.png"
            self.client.screenshot(str(png_path))
        except Exception as exc:
            logger.warning("Bug 截图保存失败（设备会话可能已释放）：%s", exc)
        logger.error("【%s】已记录 Bug：%s → %s", tag, title, json_path)
        return str(json_path)

    def v150_submit_booking(self, tag="v150_booking"):
        """本轮只点击一次确认呼叫；响应不确定时保留状态，禁止重复提交。"""
        if getattr(self, "_v150_active_booking", None) is not None:
            raise RuntimeError("已有本次预约提交记录，禁止重复呼叫")
        ok, message = validate_booking_time(self._v150_booking_now(), self._v150_use_time)
        if not ok:
            raise RuntimeError(f"下单前预约时间已失效：{message}")
        if self._v150_booking_quote() is None:
            raise RuntimeError("预约报价未就绪，未呼叫")
        ok, message = validate_booking_time(self._v150_booking_now(), self._v150_use_time)
        if not ok:
            raise RuntimeError(f"报价核验后预约时间已失效：{message}；未呼叫")
        self._v150_active_booking = {"phase": "submitting", "started": time.monotonic(), "order_no": None}
        self._v150_booking_click(texts=("確認呼叫", "确认呼叫"))
        def calling():
            status = self._v150_booking_status()
            if status["accepted"] or status["cancelled"]:
                raise RuntimeError("订单未停留预约呼叫中，未继续取消或重下单")
            return status["calling"]
        self._wait(calling, "未确认进入预约呼叫中；禁止重复呼叫", timeout=30)
        self._v150_active_booking["phase"] = "calling"
        logger.info("【%s】已进入预约呼叫中，本轮仅提交一次", tag)

    def v150_cancel_booking_and_return_home(self, tag="v150_booking"):
        """仅取消本轮新建且仍待接单的预约，然后单次点左上角返回。

        检测到 Bug（取消后显示超时文案或取消期间被接单）时：
        - 记录 Bug 证据（JSON+XML+截图+时间线）
        - 尝试返回首页，不阻塞后续用例
        - 将 Bug 路径存入 _v150_bug_paths，最终汇总到测试结果
        """
        active = getattr(self, "_v150_active_booking", None)
        if not active or active["phase"] != "calling" or getattr(self, "_v150_passive_wait", False):
            raise RuntimeError("没有可取消的本轮预约，或已进入禁止操作的超时等待")
        status = self._v150_booking_status()
        if not status["calling"] or status["accepted"] or status["cancelled"]:
            raise RuntimeError("本轮预约已不在待接单状态，未取消")
        active["phase"] = "cancelling"
        cancel_clicked_at = datetime.now().isoformat()
        logger.info("【%s】已核对本轮仍在呼叫中，单次点击取消订单，时点=%s", tag, cancel_clicked_at)
        self._v150_booking_click(texts=("取消訂單", "取消订单"))
        confirmed = False
        confirm_texts = ("不用車了", "不用车了", "確認取消", "确认取消")
        bug_recorded = False
        def cancelled():
            nonlocal confirmed, bug_recorded
            current = self._v150_booking_status()
            if current["accepted"]:
                bug_path = self._v150_record_bug(
                    category="cancel_accepted",
                    title="取消期间司机已接单",
                    expected="取消订单后订单应被取消",
                    actual="取消期间司机已接单，订单未被取消",
                    phase="cancelling",
                    order_no=current.get("order_no"),
                    root=current["root"],
                    tag=tag)
                record = json.loads(Path(bug_path).read_text(encoding="utf-8"))
                record["timeline"] = {
                    "cancel_clicked_at": cancel_clicked_at,
                    "accepted_detected_at": datetime.now().isoformat(),
                }
                Path(bug_path).write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                self._v150_append_bug(bug_path, "取消期间司机已接单")
                bug_recorded = True
                return True
            if current["cancelled"]:
                if current["timeout"]:
                    bug_path = self._v150_record_bug(
                        category="cancel_shows_timeout",
                        title="主动取消后页面显示呼叫超时/自动取消文案",
                        expected="点击取消订单后页面应显示'訂單已取消'等主动取消文案",
                        actual="点击取消订单后页面显示'呼叫超時，已自動取消訂單'等系统超时文案",
                        phase="cancelling",
                        order_no=current.get("order_no"),
                        root=current["root"],
                        tag=tag)
                    record = json.loads(Path(bug_path).read_text(encoding="utf-8"))
                    record["timeline"] = {
                        "cancel_clicked_at": cancel_clicked_at,
                        "timeout_detected_at": datetime.now().isoformat(),
                    }
                    Path(bug_path).write_text(
                        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                    self._v150_append_bug(bug_path, "主动取消后页面显示呼叫超时/自动取消文案")
                    bug_recorded = True
                return True
            if not confirmed and self._v150_booking_texts(current["root"]).intersection(confirm_texts):
                confirmed = True
                self._v150_booking_click(texts=confirm_texts)
            return False
        self._wait(cancelled, "预约取消未确认；不重复取消，不返回或重下单", timeout=30)
        active["phase"] = "cancelled"
        logger.info("【%s】取消流程结束，bug_recorded=%s，尝试返回首页", tag, bug_recorded)
        root = self._v150_booking_root()
        back = self._login_find(root, ids=("iv_arrow_back", "reservation_back"))
        x, y = center(back)
        width, height = self.client.window_size()
        if x > width / 3 or y > height / 3:
            raise RuntimeError("返回按钮不是左上角控件，停止操作")
        self._login_native(root, back).click()
        def home():
            ids = {n.get("resource-id", "").split("/")[-1]
                   for n in self._login_visible(self._v150_booking_root())}
            return {"tv_home_reservation", "tv_start_address"}.issubset(ids) and "time_wheels" not in ids
        self._wait(home, "取消后点击左上角返回未到首页，不开始第二轮", timeout=15)
        self._v150_active_booking = None
        logger.info("【%s】本轮预约已取消，左上角返回首页已核验", tag)

    def v150_wait_booking_timeout(self, tag="v150_booking", *, grace_seconds=120, poll_seconds=5):
        """第二轮只读等待系统自然超时；不唤醒、点击、截图、返回或自动取消。"""
        active = getattr(self, "_v150_active_booking", None)
        if not active or active["phase"] != "calling":
            raise RuntimeError("本轮尚未确认进入预约呼叫中，不能等待超时")
        if grace_seconds < 0 or poll_seconds <= 0:
            raise ValueError("预约等待参数无效")
        self._v150_passive_wait = True
        active["phase"] = "passive_wait"
        deadline = active["started"] + BOOKING_TIMEOUT_MINUTES * 60 + grace_seconds
        next_log = 0
        while time.monotonic() < deadline:
            status = self._v150_booking_status()
            elapsed = time.monotonic() - active["started"]
            if status["accepted"]:
                raise RuntimeError("第二轮已被司机接单，未取得超时结果；未执行任何干预")
            if status["cancelled"]:
                if not status["timeout"]:
                    raise AssertionError("订单已取消但缺少系统超时文案，不能判定超时通过")
                active["phase"] = "timed_out"
                logger.info("【%s】已只读确认系统超时取消，耗时 %.1f 秒", tag, elapsed)
                return {"timed_out": True, "elapsed": elapsed, "order_no": status["order_no"]}
            if elapsed >= next_log:
                logger.info("【%s】只读等待自然超时，已等待 %.0f 秒；不执行任何界面操作", tag, elapsed)
                next_log = elapsed + 60
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
        raise TimeoutError("等待预算已到，但未观察到系统超时取消；保留当前订单，未自动取消")

    # ==================== 安全中心 ====================

    def v150_open_safety_center(self, tag="v150_safety"):
        """从首页进入安全中心。

        真机 UI 结构：
        - 首页安全中心入口 id=tv_safe「安全中心」，位于 id=safe_center 布局中
        - 点击后进入安全中心页面（H5或原生）

        优先用返回键回首页，不重启 App（避免启动页分类超时）。
        """
        self._ensure_devices_awake()
        # 先尝试返回首页（增加返回次数以兼容H5页面），不重启 App
        home_ok = self._v150_return_home(tag, attempts=8)
        if not home_ok:
            # H5 页面可能返回键无法回到首页，force-stop 后重新启动
            logger.info("【%s】返回键未能回到首页，强制重启 App", tag)
            package = self.order_settings["packages"]["passenger_hk"]
            self._v150_adb("shell", "am", "force-stop", package)
            time.sleep(2)
            self._v150_adb("shell", "monkey", "-p", package, "-c",
                           "android.intent.category.LAUNCHER", "1")
            # 等待首页 Activity 出现
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    out = self._v150_adb("shell", "dumpsys", "activity", "activities")
                    if "YGAHomeActivity" in out:
                        break
                except Exception:
                    pass
                time.sleep(2)
            time.sleep(2)
        self.ensure_passenger_login(tag)
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        # 安全中心入口匹配：优先 resource-id
        entry = [n for n in nodes if n.get("resource-id", "").split("/")[-1] == "tv_safe"
                 and n.get("enabled") != "false"]
        if not entry:
            # 文案兜底
            safety_labels = ("安全中心", "安全中心")
            entry = [n for n in nodes if (n.get("label") or "").strip() in safety_labels
                     and n.get("enabled") != "false"]
        if not entry:
            raise RuntimeError("V1.5.0 安全中心入口不可见")
        if len(entry) > 1:
            raise RuntimeError("V1.5.0 安全中心入口不唯一，禁止点击")
        self.client.click(* center(entry[0]))
        logger.info("【%s】已点击安全中心入口", tag)
        # 等待安全中心页面加载
        self._wait(
            lambda: self._v150_safety_page_ready(),
            "V1.5.0 安全中心页面未就绪",
            timeout=15,
        )
        page = self._v150_current_page_type()
        logger.info("【%s】安全中心页面已就绪，页面类型=%s", tag, page)
        return page

    def _v150_safety_page_ready(self):
        """检测安全中心页面是否已加载。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        texts = {(n.get("label") or "").strip() for n in nodes}
        safety_keywords = ("緊急聯絡人", "紧急联系人", "行程分享", "999", "報警", "报警",
                           "安全中心", "聯絡人", "联络人")
        return any(keyword in text for text in texts for keyword in safety_keywords)

    def v150_safety_verify_contacts(self, tag="v150_safety"):
        """验证安全中心紧急联系人列表页面。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        contact_names = []
        contact_phones = []
        for n in nodes:
            rid = n.get("resource-id", "").split("/")[-1]
            label = (n.get("label") or "").strip()
            if rid in ("tv_contact_name", "tv_name") and label:
                contact_names.append(label)
            elif rid in ("tv_contact_phone", "tv_phone") and label:
                contact_phones.append(label)
        count = len(contact_names)
        logger.info("【%s】安全中心联系人数量=%d", tag, count)
        if count > CONTACT_LIMIT:
            raise RuntimeError(f"V1.5.0 联系人数量{count}超过上限{CONTACT_LIMIT}")
        for phone in contact_phones:
            if not re.fullmatch(r"[*•]{0,4}\d{4}", phone.replace(" ", "")):
                logger.warning("【%s】联系人手机号掩码格式异常：%s", tag, phone)
        return {"count": count, "names": contact_names, "phones": contact_phones}

    def v150_safety_ensure_contacts_ready(self, tag="v150_safety", timeout=30):
        """确保紧急联系人列表接口加载成功（loadPhase=ready）。

        接口失败时页面进入 error 态，此时「新增緊急聯絡人」弹框无法打开，
        必须重新触发加载直到 ready，否则新增操作只会来回切换页面。

        返回最后的 Vuex store 快照。
        """
        deadline = time.monotonic() + timeout
        store = None
        attempt = 0
        reentered = False
        while time.monotonic() < deadline:
            attempt += 1
            store = self.v150_safety_read_vuex_store(tag)
            phase = store.get("loadPhase")
            if phase == "ready":
                if attempt > 1:
                    logger.info("【%s】联系人列表已恢复（第 %d 次尝试）", tag, attempt)
                return store
            logger.warning("【%s】联系人列表未就绪（loadPhase=%s errorKind=%s），"
                           "第 %d 次重新加载", tag, phase, store.get("errorKind"), attempt)
            self.v150_safety_vuex_trigger_reload(tag)
            time.sleep(2)
            # 连续失败时重新进入页面，强制组件重新挂载并重新拉取接口
            if attempt >= 3 and not reentered:
                reentered = True
                logger.warning("【%s】接口多次失败，重新进入紧急联系人页面重置", tag)
                try:
                    self.v150_safety_return_center(tag)
                    self.v150_safety_enter_contacts(tag)
                except Exception as exc:
                    logger.warning("【%s】重新进入页面失败：%s", tag, exc)
                time.sleep(2)
        raise RuntimeError(
            f"V1.5.0 联系人列表加载持续失败：loadPhase={store.get('loadPhase')} "
            f"errorKind={store.get('errorKind')}")

    def v150_safety_add_contact(self, tag="v150_safety", *, name="測試聯絡人", phone="61234567"):
        """在安全中心添加紧急联系人。

        H5 弹框（.contact-popup）内的 input/button 不出现在 uiautomator 控件树中，
        因此弹框的填写与确认统一走 CDP 在页面内操作：
        - 姓名：input[placeholder='請輸入聯絡人姓名']
        - 电话：input[placeholder='請輸入聯絡人電話']（maxlength=15）
        - 确认：button.safety-action__button
        """
        own_phone = self._v150_get_own_phone()
        validated_name = validate_contact_input(name, phone, own_phone, 0)
        logger.info("【%s】联系人输入已通过离线契约校验：name=%s, phone=%s",
                     tag, validated_name, phone)
        self._ensure_devices_awake()
        # 接口未就绪时页面处于 error 态，弹框打不开，先确保列表加载成功
        self.v150_safety_ensure_contacts_ready(tag)
        # H5 页面按钮真实文案为「新增緊急聯絡人」，且同名 StaticText 说明文案与
        # Button 同时存在，必须按节点类型过滤后点击，否则唯一性校验失败。
        add_labels = ("新增緊急聯絡人", "新增紧急联系人", "新增聯絡人", "新增联络人",
                      "添加緊急聯絡人", "添加聯絡人", "添加联系人")
        clicked = False
        # 弹框打开失败时重试（页面可能仍在加载或按钮位置未刷新）
        for attempt in range(3):
            clicked = self._v150_click_node_by_text(
                add_labels, node_tags=("XCUIElementTypeButton",), required=False, tag=tag)
            if not clicked:
                # 兜底：不限定节点类型
                clicked = self._v150_click_node_by_text(add_labels, required=False, tag=tag)
            if not clicked:
                prefix = E.PASSENGER_BUNDLE_ID + ":id/"
                for name_id in ("btn_add_contact", "iv_add_contact", "tv_add_contact"):
                    entry = self.client(resourceId=prefix + name_id)
                    if entry.exists:
                        entry.click()
                        clicked = True
                        break
            if clicked:
                try:
                    self._wait(
                        lambda: self._v150_contact_form_ready(),
                        "V1.5.0 联系人添加表单未就绪",
                        timeout=6,
                    )
                    break
                except Exception as exc:
                    logger.warning("【%s】第 %d 次点击新增后弹框未弹出：%s",
                                   tag, attempt + 1, exc)
                    clicked = False
            else:
                logger.warning("【%s】第 %d 次未找到新增联系人按钮", tag, attempt + 1)
            time.sleep(1.5)
            # 重试前重新进入页面，确保按钮处于可点击状态
            self.v150_safety_ensure_contacts_ready(tag)
        if not clicked:
            raise RuntimeError("V1.5.0 添加联系人按钮未找到")
        logger.info("【%s】已点击添加联系人按钮", tag)
        # 弹框内输入框不在控件树中，用 CDP 填写并确认
        self._v150_fill_contact_dialog(tag, validated_name, phone)
        # 等待接口回写并刷新列表
        time.sleep(2)
        self.v150_safety_vuex_trigger_reload(tag)
        time.sleep(1)
        logger.info("【%s】联系人已添加：%s / %s", tag, validated_name, phone)
        return {"name": validated_name, "phone": phone}

    def _v150_fill_contact_dialog(self, tag, name, phone):
        """通过 CDP 在新增联系人弹框内填写姓名与电话并点击确认。"""
        js = r"""
        (function(name, phone) {
          function setValue(el, value) {
            if (!el) return false;
            el.focus();
            var proto = el instanceof HTMLTextAreaElement
              ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            var setter = Object.getOwnPropertyDescriptor(proto, 'value');
            if (setter && setter.set) { setter.set.call(el, value); }
            else { el.value = value; }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
          }
          var popup = document.querySelector('.contact-popup')
                   || document.querySelector('.contact-editor');
          if (!popup) return JSON.stringify({ok: false, reason: 'no_popup'});
          var nameInput = popup.querySelector("input[placeholder*='聯絡人姓名'], input[placeholder*='联系人姓名']")
                       || popup.querySelector("input[type='text']");
          var telInput = popup.querySelector("input[placeholder*='聯絡人電話'], input[placeholder*='联系人电话']")
                      || popup.querySelector("input[type='tel']");
          var okName = setValue(nameInput, name);
          var okTel = setValue(telInput, phone);
          var btn = popup.querySelector("button.safety-action__button")
                 || Array.prototype.slice.call(popup.querySelectorAll('button'))
                       .filter(function(b){ return (b.textContent||'').trim() === '確認'; })[0];
          return JSON.stringify({
            ok: okName && okTel,
            hasName: !!nameInput, hasTel: !!telInput, hasBtn: !!btn,
            nameValue: nameInput ? nameInput.value : null,
            telValue: telInput ? telInput.value : null
          });
        })(%s, %s)
        """ % (json.dumps(name), json.dumps(phone))
        fill = self._v150_cdp_eval(js)
        if not fill.get("success"):
            raise RuntimeError(f"V1.5.0 联系人弹框填写失败：{fill.get('error')}")
        state = json.loads(fill["value"])
        if not state.get("hasName") or not state.get("hasTel"):
            raise RuntimeError(f"V1.5.0 联系人弹框输入框未找到：{state}")
        logger.info("【%s】弹框填写状态：%s", tag, state)

        # 点击「確認」
        click_js = r"""
        (function() {
          var popup = document.querySelector('.contact-popup')
                   || document.querySelector('.contact-editor');
          if (!popup) return JSON.stringify({ok: false, reason: 'no_popup'});
          var btn = popup.querySelector("button.safety-action__button")
                 || Array.prototype.slice.call(popup.querySelectorAll('button'))
                       .filter(function(b){ return (b.textContent||'').trim() === '確認'; })[0];
          if (!btn) return JSON.stringify({ok: false, reason: 'no_button'});
          btn.click();
          return JSON.stringify({ok: true});
        })()
        """
        clicked = self._v150_cdp_eval(click_js)
        if not clicked.get("success"):
            raise RuntimeError(f"V1.5.0 联系人弹框确认失败：{clicked.get('error')}")
        result = json.loads(clicked["value"])
        if not result.get("ok"):
            raise RuntimeError(f"V1.5.0 联系人弹框确认按钮未找到：{result}")
        logger.info("【%s】已点击弹框「確認」", tag)

    def _v150_open_contact_dialog(self, tag="v150_safety"):
        """点击「新增緊急聯絡人」按钮打开新增联系人弹框。"""
        self._ensure_devices_awake()
        # 接口未就绪时页面处于 error 态，按钮点击无效，先确保列表加载成功
        try:
            self.v150_safety_ensure_contacts_ready(tag)
        except RuntimeError as exc:
            logger.warning("【%s】联系人列表未就绪，仍尝试打开弹框：%s", tag, exc)
        add_labels = ("新增緊急聯絡人", "新增紧急联系人", "新增聯絡人", "新增联络人",
                      "添加緊急聯絡人", "添加聯絡人", "添加联系人")
        clicked = self._v150_click_node_by_text(
            add_labels, node_tags=("XCUIElementTypeButton",), required=False, tag=tag)
        if not clicked:
            clicked = self._v150_click_node_by_text(add_labels, required=False, tag=tag)
        if not clicked:
            raise RuntimeError("V1.5.0 添加联系人按钮未找到")
        self._wait(
            lambda: self._v150_contact_form_ready(),
            "V1.5.0 联系人添加弹框未弹出",
            timeout=10,
        )
        logger.info("【%s】新增联系人弹框已弹出", tag)
        return True

    def _v150_read_contact_dialog(self, tag="v150_safety"):
        """读取新增联系人弹框内的输入框与按钮状态。"""
        js = r"""
        (function() {
          var popup = document.querySelector('.contact-popup')
                   || document.querySelector('.contact-editor');
          if (!popup) return JSON.stringify({exists: false});
          var nameInput = popup.querySelector("input[placeholder*='聯絡人姓名'], input[placeholder*='联系人姓名']")
                       || popup.querySelector("input[type='text']");
          var telInput = popup.querySelector("input[placeholder*='聯絡人電話'], input[placeholder*='联系人电话']")
                      || popup.querySelector("input[type='tel']");
          var btn = popup.querySelector("button.safety-action__button")
                 || Array.prototype.slice.call(popup.querySelectorAll('button'))
                       .filter(function(b){ return (b.textContent||'').trim() === '確認'; })[0];
          var maxlen = telInput ? (telInput.getAttribute('maxlength') || '') : '';
          return JSON.stringify({
            exists: true,
            has_name_input: !!nameInput,
            has_phone_input: !!telInput,
            has_confirm: !!btn,
            name_placeholder: nameInput ? (nameInput.getAttribute('placeholder') || '') : '',
            phone_placeholder: telInput ? (telInput.getAttribute('placeholder') || '') : '',
            phone_maxlength: maxlen
          });
        })()
        """
        result = self._v150_cdp_eval(js)
        if not result.get("success"):
            raise RuntimeError(f"V1.5.0 联系人弹框读取失败：{result.get('error')}")
        state = json.loads(result["value"])
        logger.info("【%s】联系人弹框状态：%s", tag, state)
        return state

    def _v150_close_contact_dialog(self, tag="v150_safety"):
        """关闭新增联系人弹框（点击右上角关闭按钮或遮罩）。"""
        js = r"""
        (function() {
          var popup = document.querySelector('.contact-popup')
                   || document.querySelector('.contact-editor');
          if (!popup) return JSON.stringify({ok: false, reason: 'no_popup'});
          var closeBtn = popup.querySelector('.van-popup__close-icon, .van-icon-cross, [class*="close"]');
          if (closeBtn) { closeBtn.click(); return JSON.stringify({ok: true, via: 'close'}); }
          var overlay = document.querySelector('.van-overlay');
          if (overlay) { overlay.click(); return JSON.stringify({ok: true, via: 'overlay'}); }
          return JSON.stringify({ok: false, reason: 'no_close_control'});
        })()
        """
        result = self._v150_cdp_eval(js)
        if result.get("success"):
            try:
                state = json.loads(result["value"])
                if state.get("ok"):
                    logger.info("【%s】已关闭联系人弹框（%s）", tag, state.get("via"))
                    return True
            except Exception:
                pass
        # 兜底：按 ESC 关闭
        self._v150_cdp_eval("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
        logger.info("【%s】已通过 ESC 关闭联系人弹框", tag)
        return True

    def v150_safety_clear_contacts(self, tag="v150_safety"):
        """清空全部紧急联系人，返回删除前的联系人列表。

        联系人上限为3个，满员时新增弹框不再弹出，
        因此验证新增弹框的用例需先清空联系人。
        """
        self._ensure_devices_awake()
        before = self.v150_safety_read_contact_list(tag)
        if not before:
            logger.info("【%s】当前无联系人，无需清空", tag)
            return []
        logger.info("【%s】开始清空联系人，共 %d 个", tag, len(before))
        for _ in range(len(before) + 1):
            current = self.v150_safety_read_contact_list(tag)
            if not current:
                break
            self.v150_safety_delete_contact(tag)
        after = self.v150_safety_read_contact_list(tag)
        logger.info("【%s】联系人清空完成，剩余：%s", tag, after)
        return after

    def v150_safety_verify_999_button(self, tag="v150_safety"):
        """验证安全中心 999 报警按钮存在且可点击。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        alarm_labels = ("999", "報警", "报警", "緊急報警", "紧急报警")
        button = [n for n in nodes
                  if any(label in (n.get("label") or "") for label in alarm_labels)
                  and n.get("enabled") != "false"]
        if not button:
            raise RuntimeError("V1.5.0 安全中心未找到999报警按钮")
        logger.info("【%s】999报警按钮已确认，数量=%d", tag, len(button))
        return {"found": True, "count": len(button)}

    def v150_safety_verify_trip_share(self, tag="v150_safety"):
        """验证行程分享功能入口存在。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        texts = {(n.get("label") or "").strip() for n in nodes}
        share_keywords = ("行程分享", "行程分享", "分享行程", "分享")
        found = any(keyword in text for text in texts for keyword in share_keywords)
        if not found:
            logger.warning("【%s】行程分享入口未在当前页面找到", tag)
        else:
            logger.info("【%s】行程分享入口已确认", tag)
        return {"found": found}

    def _v150_contact_form_ready(self):
        """检测联系人添加表单是否已出现。

        H5 弹框（.contact-popup）内的 input/button 不出现在 uiautomator 控件树中，
        因此优先用 CDP 检测弹框是否已渲染，失败再回退到文案组合检测。
        """
        js = r"""
        (function() {
          var popup = document.querySelector('.contact-popup')
                   || document.querySelector('.contact-editor');
          if (!popup) return false;
          var inputs = popup.querySelectorAll('input');
          var btn = popup.querySelector("button.safety-action__button");
          return inputs.length >= 2 && !!btn;
        })()
        """
        result = self._v150_cdp_eval(js)
        if result.get("success"):
            try:
                if str(result.get("value")).strip().lower() == "true":
                    return True
            except Exception:
                pass
        # 回退：控件树特征文案组合
        try:
            root = self._passenger_root()
        except Exception:
            return False
        nodes = self._v150_all_visible_nodes(root)
        inputs = [n for n in nodes if "EditText" in (n.get("class") or "")
                  or n.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")]
        if len(inputs) >= 2:
            return True
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        has_cancel = any(t == "取消" for t in texts)
        has_confirm = any(t in ("確認", "确认", "确定", "確定") for t in texts)
        has_phone_label = any("電話" in t or "电话" in t or "聯絡人" in t or "联络人" in t for t in texts)
        return has_cancel and has_confirm and has_phone_label

    def _v150_get_own_phone(self):
        """获取当前登录账号的手机号。"""
        config = self.order_settings.get("login") or {}
        return config.get("mobile") or ""

    # ----- 安全中心扩展步骤 -----

    def v150_safety_return_center(self, tag="v150_safety", max_attempts=4):
        """从安全中心子页面返回安全中心首页（不回到 App 首页）。

        判断依据：安全中心首页同时含「安全中心」标题 + 「行程分享」或「安全專線」入口，
        而子页面（联系人管理、报警、行程分享详情）只含部分关键词。

        如果已在安全中心首页则直接返回；如果返回键退到了 App 首页，
        则重新点击安全中心入口进入。
        """
        self._ensure_devices_awake()
        for attempt in range(max_attempts):
            # 拨号器返回后 App 可能还在恢复，先确保乘客 App 在前台
            if not self._v150_passenger_foreground():
                package = self.order_settings["packages"]["passenger_hk"]
                logger.info("【%s】乘客 App 不在前台，激活 App", tag)
                try:
                    self.client.app_activate(package)
                except Exception:
                    pass
                # 等待 App 恢复前台
                self._wait(
                    lambda: self._v150_passenger_foreground(),
                    "V1.5.0 拨号返回后乘客 App 未能恢复前台",
                    timeout=10,
                )
                time.sleep(1)
            # App 已在前台，检查页面类型
            try:
                page = self._v150_current_page_type()
            except Exception:
                # 页面树读取失败时等待重试
                time.sleep(1)
                continue
            if page == "home":
                # 已退到 App 首页，重新进入安全中心
                logger.info("【%s】返回键退到了 App 首页，重新进入安全中心", tag)
                return self.v150_open_safety_center(tag)
            # 检查是否已在安全中心首页
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            texts = set()
            for n in nodes:
                for attr in ("label", "content-desc", "text"):
                    val = (n.get(attr) or "").strip()
                    if val:
                        texts.add(val)
            has_title = any("安全中心" in t for t in texts)
            has_entry = (any("行程分享" in t for t in texts)
                         or any("安全專線" in t or "安全专线" in t for t in texts))
            if has_title and has_entry:
                logger.info("【%s】已返回安全中心首页（尝试 %d 次）", tag, attempt + 1)
                return "safety_center"
            # 不在首页，按返回键
            try:
                self.client.driver.back()
            except Exception as exc:
                logger.warning("【%s】返回键失败：%s", tag, exc)
                break
            time.sleep(1.5)
        # 兜底：退到首页再进入安全中心
        logger.info("【%s】未通过返回键到达安全中心首页，走首页重新进入", tag)
        return self.v150_open_safety_center(tag)

    def v150_safety_verify_home_page(self, tag="v150_safety"):
        """验证安全中心首页标题及四个功能入口。

        首页结构：
        - 标题「安全中心」+ 副标题「全方位守護您的出行安全」
        - 安全專線入口
        - 緊急聯絡人入口（带 去設置/已設置 状态）
        - 行程分享入口
        - 999報警按钮
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        title_found = any("安全中心" in t for t in texts)
        subtitle_found = any("全方位守護" in t or "全方位守护" in t for t in texts)
        safety_line_found = any("安全專線" in t or "安全专线" in t for t in texts)
        contact_entry_found = any("緊急聯絡人" in t or "紧急联系人" in t for t in texts)
        trip_share_found = any("行程分享" in t for t in texts)
        alarm_found = any("999" in t or "報警" in t or "报警" in t for t in texts)
        # 緊急聯絡人状态文案：去設置 或 已設置
        contact_status = None
        if any("去設置" in t or "去设置" in t for t in texts):
            contact_status = "unset"
        elif any("已設置" in t or "已设置" in t for t in texts):
            contact_status = "set"
        logger.info("【%s】安全中心首页核验：title=%s subtitle=%s line=%s contact=%s share=%s alarm=%s status=%s",
                     tag, title_found, subtitle_found, safety_line_found,
                     contact_entry_found, trip_share_found, alarm_found, contact_status)
        return {
            "title": title_found,
            "subtitle": subtitle_found,
            "safety_line": safety_line_found,
            "contact_entry": contact_entry_found,
            "trip_share": trip_share_found,
            "alarm": alarm_found,
            "contact_status": contact_status,
        }

    def v150_safety_enter_safety_line(self, tag="v150_safety"):
        """点击安全专线入口，进入安全专线二级页面。"""
        self._ensure_devices_awake()
        clicked = self._click_text(("安全專線", "安全专线"), exact=False, required=False)
        if not clicked:
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            for n in nodes:
                label = (n.get("label") or n.get("content-desc") or "").strip()
                if "安全專線" in label or "安全专线" in label:
                    self.client.click(*center(n))
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError("V1.5.0 安全专线入口未找到")
        self._wait(
            lambda: self._v150_safety_line_page_ready(),
            "V1.5.0 安全专线页面未就绪",
            timeout=10,
        )
        logger.info("【%s】已进入安全专线页面", tag)
        return "safety_line"

    def _v150_safety_line_page_ready(self):
        """检测安全专线页面是否已加载。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        keywords = ("安全專線", "安全专线", "聯繫平台", "联系平台", "聯絡平台",
                    "交通意外", "人身傷害", "人身伤害")
        return any(keyword in text for text in texts for keyword in keywords)

    def v150_safety_verify_safety_line_page(self, tag="v150_safety"):
        """验证安全专线页面文案及联系平台按钮。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        title = any("安全專線" in t or "安全专线" in t for t in texts)
        intro = any("安全專線可處理" in t or "安全专线可处理" in t for t in texts)
        items = {
            "交通意外": any("交通意外" in t for t in texts),
            "人身傷害": any("人身傷害" in t or "人身伤害" in t for t in texts),
            "限制自由": any("限制人身自由" in t for t in texts),
            "性騷擾": any("性騷擾" in t or "性骚扰" in t for t in texts),
            "肢體衝突": any("肢體衝突" in t or "肢体冲突" in t for t in texts),
            "聯絡不到親友": any("聯絡不到親友" in t or "联络不到亲友" in t for t in texts),
        }
        contact_btn = any("聯繫平台" in t or "联系平台" in t or "聯絡平台" in t for t in texts)
        logger.info("【%s】安全专线页核验：title=%s intro=%s items=%s contact_btn=%s",
                     tag, title, intro, items, contact_btn)
        return {
            "title": title,
            "intro": intro,
            "items": items,
            "contact_btn": contact_btn,
        }

    def v150_safety_dial_platform_and_return(self, tag="v150_safety"):
        """点击安全专线「聯絡平台」，进入系统拨号页并校验号码已填写，然后返回 App。

        真机行为：
        - 安全专线页底部「聯絡平台」按钮点击后调起系统拨号器
          （com.android.contacts/.TwelveKeyDialer），乘客 App 退到后台
        - 拨号器中电话号码已预填（平台客服电话），仅展示不拨出
        - 校验完成后按返回键回到乘客 App

        返回 dict: {dialer_opened, phone, back_to_app}
        """
        self._ensure_devices_awake()
        # 1. 点击「聯絡平台」按钮（Button 类型，避免与 StaticText 文案重复）
        clicked = self._v150_click_node_by_text(
            ("聯絡平台", "聯繫平台", "联系平台"),
            node_tags=("XCUIElementTypeButton",), required=True, tag=tag)
        if not clicked:
            raise RuntimeError("V1.5.0 安全专线「聯絡平台」按钮未找到")

        # 2. 等待系统拨号器打开（乘客 App 会退到后台）
        def dialer_ready():
            out = self._v150_adb("shell", "dumpsys", "activity", "activities")
            return "TwelveKeyDialer" in out or "com.android.contacts" in out

        self._wait(dialer_ready, "V1.5.0 系统拨号器未打开", timeout=15)
        logger.info("【%s】已调起系统拨号器", tag)

        # 3. 读取拨号器中的号码
        phone = self._v150_read_dialer_phone(tag)
        logger.info("【%s】拨号器号码=%s", tag, phone)

        # 4. 返回乘客 App（不拨出）
        self._v150_adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(2)
        # 拨号器返回后 App 可能需要激活才能恢复前台
        back_ok = self._v150_passenger_foreground()
        if not back_ok:
            package = self.order_settings["packages"]["passenger_hk"]
            try:
                self.client.app_activate(package)
            except Exception:
                pass
            self._wait(
                lambda: self._v150_passenger_foreground(),
                "V1.5.0 拨号返回后乘客 App 未能恢复前台",
                timeout=10,
            )
            back_ok = self._v150_passenger_foreground()
        logger.info("【%s】已返回乘客 App=%s", tag, back_ok)
        return {"dialer_opened": True, "phone": phone, "back_to_app": back_ok}

    def _v150_read_dialer_phone(self, tag="v150_safety"):
        """读取系统拨号器当前已填写的电话号码。

        优先从拨号器 Activity 的 Intent（dat=tel:+852xxx）读取，
        Appium 在乘客 App 不在前台时无法拿到拨号器的控件树，故不使用 Appium。
        """
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                out = self._v150_adb("shell", "dumpsys", "activity", "activities")
            except Exception:
                time.sleep(1)
                continue
            match = re.search(r"dat=tel:([^\s,}]+)", out)
            if match:
                raw = match.group(1)
                phone = raw.replace("%2B", "+")
                logger.info("【%s】拨号器 Intent 号码=%s", tag, phone)
                return phone
            time.sleep(1)
        logger.warning("【%s】未能从拨号器读取到号码", tag)
        return None

    def _v150_passenger_foreground(self):
        """判断乘客 App 是否在前台（使用 current_package 精确判断）。"""
        package = self.order_settings["packages"]["passenger_hk"]
        try:
            return self.client.driver.current_package == package
        except Exception:
            # driver 调用失败时退到 dumpsys
            try:
                out = self._v150_adb("shell", "dumpsys", "activity", "activities")
                # 检查 mResumedActivity 是否包含乘客包名
                for line in out.splitlines():
                    if "mResumedActivity" in line or "topResumedActivity" in line:
                        return package in line
            except Exception:
                pass
            return False

    def v150_safety_enter_contacts(self, tag="v150_safety"):
        """点击緊急聯絡人入口，进入紧急联系人管理页。"""
        self._ensure_devices_awake()
        clicked = self._click_text(("緊急聯絡人", "紧急联系人"), exact=False, required=False)
        if not clicked:
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            for n in nodes:
                label = (n.get("label") or n.get("content-desc") or "").strip()
                if "緊急聯絡人" in label or "紧急联系人" in label:
                    self.client.click(*center(n))
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError("V1.5.0 紧急联系人入口未找到")
        self._wait(
            lambda: self._v150_contact_page_ready(),
            "V1.5.0 紧急联系人页面未就绪",
            timeout=10,
        )
        logger.info("【%s】已进入紧急联系人页面", tag)
        return "contacts"

    def _v150_contact_page_ready(self):
        """检测紧急联系人页面是否已加载。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        keywords = ("新增緊急聯絡人", "新增联络人", "自動分享行程", "自动分享行程",
                    "聯絡人", "联络人")
        return any(keyword in text for text in texts for keyword in keywords)

    def v150_safety_verify_contact_page(self, tag="v150_safety"):
        """验证紧急联系人管理页文案及功能元素。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        title = any("新增緊急聯絡人" in t or "新增联络人" in t for t in texts)
        auto_share = any("自動分享行程" in t or "自动分享行程" in t for t in texts)
        desc = any("一鍵報警" in t or "一键报警" in t for t in texts)
        add_btn = any("新增緊急聯絡人" in t or "新增联络人" in t for t in texts)
        # 自动分享开关：查找 Switch / toggle 节点
        has_switch = any(n.tag == "XCUIElementTypeSwitch" or "Switch" in (n.get("class") or "")
                        or n.get("resource-id", "").split("/")[-1] in ("switch_auto_share", "sw_auto_share", "toggle")
                        for n in nodes)
        logger.info("【%s】联系人页核验：title=%s auto_share=%s desc=%s add_btn=%s switch=%s",
                     tag, title, auto_share, desc, add_btn, has_switch)
        return {
            "title": title,
            "auto_share_text": auto_share,
            "desc": desc,
            "add_btn": add_btn,
            "has_switch": has_switch,
        }

    def v150_safety_click_add_contact_dialog(self, tag="v150_safety"):
        """点击新增緊急聯絡人按钮，弹出新增弹框。

        页面中「新增緊急聯絡人」可能出现多次（标题+按钮），
        用坐标点击最后一个匹配节点（底部新增按钮）。
        """
        self._ensure_devices_awake()
        # 如果在安全中心首页，先进入联系人页面
        page = self._v150_current_page_type()
        if page == "safety_center":
            clicked = self._click_text(("去設置", "去设置", "已設置", "已设置"),
                                       exact=False, required=False)
            if clicked:
                self._wait(
                    lambda: self._v150_contact_page_ready(),
                    "V1.5.0 紧急联系人页面未就绪",
                    timeout=10,
                )
        # 在联系人页面查找「新增緊急聯絡人」按钮（底部按钮，取最后一个）
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        add_candidates = []
        for n in nodes:
            label = (n.get("label") or n.get("content-desc") or n.get("text") or "").strip()
            if label == "新增緊急聯絡人" or label == "新增联络人":
                add_candidates.append(n)
        if not add_candidates:
            raise RuntimeError("V1.5.0 新增联系人按钮未找到")
        # 取 y 坐标最大的（底部按钮）
        target = max(add_candidates, key=lambda n: int(n.get("y") or n.get("top") or "0"))
        cx, cy = center(target)
        # H5 页面按钮点击：优先用 Appium driver.tap (W3C touch action)
        clicked = False
        try:
            from appium.webdriver.common.appiumby import AppiumBy
            els = self.client.driver.find_elements(
                AppiumBy.XPATH,
                '//android.widget.Button[contains(@text,"新增緊急聯絡人")] | //android.widget.Button[contains(@text,"新增联络人")]')
            if els:
                els[-1].click()
                clicked = True
                time.sleep(2)
        except Exception as exc:
            logger.warning("【%s】Appium Button.click 失败：%s", tag, exc)
        if not clicked or not self._v150_contact_form_ready():
            # fallback: W3C tap 坐标
            try:
                self.client.driver.tap([(cx, cy)], 500)
                time.sleep(2)
                clicked = True
            except Exception as exc:
                logger.warning("【%s】driver.tap 失败：%s", tag, exc)
        if not clicked or not self._v150_contact_form_ready():
            # 最后 fallback: ADB input tap
            self._v150_adb("shell", "input", "tap", str(cx), str(cy))
            time.sleep(2)
        logger.info("【%s】已点击新增联系人按钮（共%d个匹配，取底部）", tag, len(add_candidates))
        self._wait(
            lambda: self._v150_contact_form_ready(),
            "V1.5.0 新增联系人弹框未就绪",
            timeout=10,
        )
        logger.info("【%s】新增联系人弹框已弹出", tag)
        return "add_dialog"

    def v150_safety_fill_contact_dialog(self, tag="v150_safety", *, name="", phone=""):
        """在新增联系人弹框中填写姓名和电话。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        inputs = [n for n in self._v150_all_visible_nodes(root)
                  if self._v150_is_input(n) and n.get("enabled") != "false"]
        if len(inputs) < 2:
            raise RuntimeError(f"V1.5.0 新增联系人弹框输入框数量不足：{len(inputs)}")
        # 第一个输入框=聯絡人姓名，第二个=電話
        native0 = self._login_native(root, inputs[0])
        self._login_replace_text(native0, name)
        native1 = self._login_native(root, inputs[1])
        self._login_replace_text(native1, phone)
        try:
            self.client.dismiss_keyboard()
        except Exception:
            pass
        logger.info("【%s】已填写联系人：name=%s phone=%s", tag, name, phone)
        return {"name": name, "phone": phone}

    def v150_safety_confirm_contact_dialog(self, tag="v150_safety"):
        """点击新增联系人弹框的「確認」按钮。"""
        self._ensure_devices_awake()
        # 用坐标点击，避免 _click_text 在控件不唯一时抛异常
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for n in nodes:
            label = (n.get("label") or n.get("content-desc") or n.get("text") or "").strip()
            if label in ("確認", "确认", "确定", "確定"):
                self.client.click(*center(n))
                time.sleep(2)
                logger.info("【%s】已点击确认按钮", tag)
                return True
        raise RuntimeError("V1.5.0 新增联系人弹框未找到確認按钮")

    def v150_safety_cancel_contact_dialog(self, tag="v150_safety"):
        """点击新增联系人弹框的「取消」按钮。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for n in nodes:
            label = (n.get("label") or n.get("content-desc") or n.get("text") or "").strip()
            if label == "取消":
                self.client.click(*center(n))
                time.sleep(1)
                logger.info("【%s】已点击取消按钮", tag)
                return True
        raise RuntimeError("V1.5.0 新增联系人弹框未找到取消按钮")

    def v150_safety_delete_contact(self, tag="v150_safety", *, name=None, index=0):
        """删除紧急联系人。

        H5 卡片的「刪除」按钮需在页面内点击。优先按 name 删除，未指定 name 时按 index 删除。
        返回删除后的联系人列表。
        """
        self._ensure_devices_awake()
        before = self.v150_safety_read_contact_list(tag)
        if not before:
            logger.info("【%s】当前无联系人可删除", tag)
            return []
        target = None
        if name is not None:
            for c in before:
                if name in (c.get("name") or ""):
                    target = c
                    break
        else:
            target = before[index] if index < len(before) else None
        if target is None:
            logger.info("【%s】未找到目标联系人，当前：%s", tag, before)
            return before

        # 先尝试 CDP 方式删除（H5 页面）
        deleted = False
        js = r"""
        (function() {
          var all = document.querySelectorAll('*');
          var delNodes = [];
          for (var j = 0; j < all.length; j++) {
            var e2 = all[j];
            if (e2.children.length > 0) continue;
            if ((e2.textContent || '').trim() === '刪除') delNodes.push(e2);
          }
          if (!delNodes.length) return JSON.stringify({ok: false, reason: 'no_delete'});
          delNodes[0].click();
          return JSON.stringify({ok: true, via: 'cdp', count: delNodes.length});
        })()
        """
        result = self._v150_cdp_eval(js)
        if result.get("success"):
            try:
                state = json.loads(result["value"])
                deleted = state.get("ok", False)
            except Exception:
                pass
        if not deleted:
            # 兜底：左滑删除
            try:
                root = self._passenger_root()
            except Exception:
                root = None
            if root is not None:
                contact_cards = [n for n in self._v150_all_visible_nodes(root)
                                 if (n.get("resource-id", "").split("/")[-1]
                                     in ("tv_contact_name", "tv_name")
                                     and (n.get("label") or "").strip())]
                if contact_cards:
                    cx, cy = center(contact_cards[0])
                    self.client.swipe(cx + 200, cy, cx - 300, cy, 400)
                    time.sleep(1)
                    self._click_text(("刪除", "删除"), exact=True, required=False)
                    deleted = True
        if not deleted:
            raise RuntimeError("V1.5.0 删除按钮未找到")
        time.sleep(2)
        # 删除后接口可能出现业务失败，等待列表恢复，避免后续新增弹框打不开
        try:
            self.v150_safety_ensure_contacts_ready(tag, timeout=15)
        except RuntimeError as exc:
            logger.warning("【%s】删除后联系人列表未恢复：%s", tag, exc)
        after = self.v150_safety_read_contact_list(tag)
        logger.info("【%s】已删除联系人「%s」，当前列表：%s", tag,
                    target.get("name"), after)
        return after

    def v150_safety_toggle_auto_share(self, tag="v150_safety", enable=True):
        """开启/关闭自动分享行程开关，返回开关状态与选中联系人数。

        开启后全部联系人自动被选中（接单事件向已选联系人发送行程链接）。
        兼容旧调用方式：v150_safety_toggle_auto_share(tag) 不传 enable 时切换开关。
        """
        self._ensure_devices_awake()

        def click_switch():
            js = r"""
            (function() {
              var sw = document.querySelector('button.auto-share__switch')
                     || document.querySelector('.auto-share__switch')
                     || document.querySelector('.auto-share [class*="switch"]');
              if (!sw) return JSON.stringify({ok: false, reason: 'no_switch'});
              sw.click();
              return JSON.stringify({ok: true});
            })()
            """
            result = self._v150_cdp_eval(js)
            if result.get("success"):
                try:
                    if json.loads(result["value"]).get("ok"):
                        return True
                except Exception:
                    pass
            # 兜底：原生控件点击
            try:
                root = self._passenger_root()
                nodes = self._v150_all_visible_nodes(root)
            except Exception:
                return False
            for n in nodes:
                rid = n.get("resource-id", "").split("/")[-1]
                cls = n.get("class") or ""
                if rid in ("switch_auto_share", "sw_auto_share", "toggle") or \
                   "Switch" in cls or n.tag == "XCUIElementTypeSwitch":
                    self.client.click(*center(n))
                    return True
            for n in nodes:
                label = (n.get("label") or n.get("content-desc") or "").strip()
                if "自動分享行程" in label or "自动分享行程" in label:
                    x, y = center(n)
                    self.client.click(x + 300, y)
                    return True
            return False

        def dom_state():
            try:
                return self.v150_safety_get_auto_share_state_cdp(tag)
            except RuntimeError:
                return None

        def vuex_state():
            try:
                return self.v150_safety_read_vuex_store(tag).get("sharingEnabled")
            except Exception:
                return None

        # 目标状态：先确保 DOM 与 Vuex 均为目标值
        deadline = time.monotonic() + 15
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            dom = dom_state()
            vx = vuex_state()
            if dom == enable and vx == enable:
                break
            if dom != enable:
                click_switch()
            elif vx != enable:
                # DOM 已就位但 Vuex 未同步，触发一次开关以重新提交
                click_switch()
            time.sleep(1.2)
        time.sleep(1)

        store = self.v150_safety_read_vuex_store(tag)
        selected = store.get("selectedIds") or []
        result = {
            "enabled": bool(dom_state()),
            "selected_count": len(selected),
            "selected_ids": selected,
            "vuex_sharingEnabled": store.get("sharingEnabled"),
        }
        logger.info("【%s】自动分享开关操作完成：%s", tag, result)
        return result

    def v150_safety_get_auto_share_state(self, tag="v150_safety"):
        """获取自动分享行程开关的当前状态（True=开启）。

        找不到开关时抛出异常，避免静默返回 False 造成误判。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for n in nodes:
            rid = n.get("resource-id", "").split("/")[-1]
            cls = n.get("class") or ""
            if rid in ("switch_auto_share", "sw_auto_share", "toggle") or \
               "Switch" in cls or n.tag == "XCUIElementTypeSwitch":
                value = (n.get("value") or n.get("checked") or "").strip()
                state = value in ("true", "1", "on", "checked")
                logger.info("【%s】自动分享开关状态=%s", tag, state)
                return state
        raise RuntimeError("V1.5.0 自动分享行程开关未找到，无法读取状态")

    def v150_safety_get_auto_share_state_cdp(self, tag="v150_safety"):
        """通过 CDP 读取自动分享行程开关状态（True=开启）。

        H5 开关的真实节点为 button.auto-share__switch（父容器 .auto-share），
        开启时 class 含 auto-share__switch--enabled 且 aria-checked="true"；
        uiautomator 控件树中只暴露为 Other 节点，故走页面内判定。
        """
        js = r"""
        (function() {
          var sw = document.querySelector('button.auto-share__switch')
                 || document.querySelector('.auto-share__switch')
                 || document.querySelector('.auto-share [class*="switch"]');
          if (!sw) return JSON.stringify({found: false});
          var cls = sw.className && sw.className.toString ? sw.className.toString() : '';
          var on = cls.indexOf('--enabled') >= 0
                || sw.getAttribute('aria-checked') === 'true';
          return JSON.stringify({
            found: true,
            enabled: on,
            cls: cls,
            aria: sw.getAttribute('aria-checked') || ''
          });
        })()
        """
        result = self._v150_cdp_eval(js)
        if not result.get("success"):
            raise RuntimeError(f"V1.5.0 自动分享开关读取失败：{result.get('error')}")
        state = json.loads(result["value"])
        if not state.get("found"):
            raise RuntimeError("V1.5.0 页面中未找到自动分享行程开关")
        logger.info("【%s】自动分享开关（CDP）状态=%s cls=%s", tag,
                    state.get("enabled"), state.get("cls"))
        return state.get("enabled")

    def v150_safety_enter_trip_share(self, tag="v150_safety"):
        """点击行程分享入口，进入行程分享二级页面。"""
        self._ensure_devices_awake()
        # 如果在安全中心首页
        clicked = self._click_text(("行程分享",), exact=False, required=False)
        if not clicked:
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            for n in nodes:
                label = (n.get("label") or n.get("content-desc") or "").strip()
                if "行程分享" in label:
                    self.client.click(*center(n))
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError("V1.5.0 行程分享入口未找到")
        self._wait(
            lambda: self._v150_trip_share_page_ready(),
            "V1.5.0 行程分享页面未就绪",
            timeout=10,
        )
        logger.info("【%s】已进入行程分享页面", tag)
        return "trip_share"

    def _v150_trip_share_page_ready(self):
        """检测行程分享页面是否已加载。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        keywords = ("行程分享", "行程資訊", "行程资讯", "司機接單", "司机接单",
                    "第一步", "第二步")
        return any(keyword in text for text in texts for keyword in keywords)

    def v150_safety_verify_trip_share_page(self, tag="v150_safety"):
        """验证行程分享介绍页文案。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        title = any("行程分享" in t for t in texts)
        desc = any("行程安全" in t or "行程資訊" in t or "行程资讯" in t for t in texts)
        step1 = any("第一步" in t for t in texts)
        step2 = any("第二步" in t for t in texts)
        logger.info("【%s】行程分享页核验：title=%s desc=%s step1=%s step2=%s",
                     tag, title, desc, step1, step2)
        return {"title": title, "desc": desc, "step1": step1, "step2": step2}

    def v150_safety_enter_alarm(self, tag="v150_safety"):
        """点击999報警按钮，进入一键报警页面。"""
        self._ensure_devices_awake()
        clicked = self._click_text(("999", "報警", "报警"), exact=False, required=False)
        if not clicked:
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            for n in nodes:
                label = (n.get("label") or n.get("content-desc") or "").strip()
                if "999" in label or "報警" in label or "报警" in label:
                    self.client.click(*center(n))
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError("V1.5.0 999报警按钮未找到")
        self._wait(
            lambda: self._v150_alarm_page_ready(),
            "V1.5.0 一键报警页面未就绪",
            timeout=10,
        )
        logger.info("【%s】已进入一键报警页面", tag)
        return "alarm"

    def _v150_alarm_page_ready(self):
        """检测一键报警页面是否已加载。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        keywords = ("一鍵報警", "一键报警", "虛報警情", "虚报警情",
                    "999", "報警", "报警", "位置", "定位")
        return any(keyword in text for text in texts for keyword in keywords)

    def v150_safety_verify_alarm_page(self, tag="v150_safety"):
        """验证一键报警页面文案及定位信息。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        texts = set()
        for n in nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        title = any("一鍵報警" in t or "一键报警" in t for t in texts)
        warning1 = any("遇到危機" in t or "遇到危机" in t for t in texts)
        warning2 = any("虛報警情" in t or "虚报警情" in t for t in texts)
        location_label = any("當前位置" in t or "当前位置" in t for t in texts)
        # 定位状态文案
        loading = any("正在獲取位置" in t or "正在获取位置" in t for t in texts)
        failed = any("無法獲取當前位置" in t or "无法获取当前位置" in t for t in texts)
        address = any(t for t in texts if location_label and not loading and not failed
                      and "當前位置" not in t and "当前位置" not in t
                      and "一鍵報警" not in t and "一键报警" not in t
                      and "虛報" not in t and "虚报" not in t and "遇到" not in t
                      and "999" not in t and "報警" not in t and "报警" not in t)
        alarm_btn = any("999" in t or "報警" in t or "报警" in t for t in texts)
        locate_btn = any("定位" in t or "重新定位" in t for t in texts)
        location_state = "loading" if loading else ("failed" if failed else ("success" if address else "unknown"))
        logger.info("【%s】报警页核验：title=%s warn1=%s warn2=%s loc_label=%s loc_state=%s alarm_btn=%s loc_btn=%s",
                     tag, title, warning1, warning2, location_label, location_state, alarm_btn, locate_btn)
        return {
            "title": title,
            "warning_crisis": warning1,
            "warning_false_report": warning2,
            "location_label": location_label,
            "location_state": location_state,
            "alarm_btn": alarm_btn,
            "locate_btn": locate_btn,
        }

    def v150_safety_read_contact_list(self, tag="v150_safety", refresh=True):
        """读取联系人列表，返回联系人卡片信息。

        支持两种形态：
        1. 原生控件：tv_contact_name / tv_contact_phone 分别承载姓名与掩码号码
        2. H5 卡片：单个 StaticText 文案「姓名（****1727）」，需拆分

        refresh=True 时先触发 contact/list 重新加载，确保拿到最新数据。
        """
        self._ensure_devices_awake()
        if refresh:
            self.v150_safety_vuex_trigger_reload(tag)
            time.sleep(1)
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        contacts = []
        for n in nodes:
            rid = n.get("resource-id", "").split("/")[-1]
            label = (n.get("label") or "").strip()
            if rid in ("tv_contact_name", "tv_name") and label:
                contacts.append({"name": label, "node": n})
        # 匹配手机号（掩码格式 ****XXXX）
        phone_nodes = []
        for n in nodes:
            rid = n.get("resource-id", "").split("/")[-1]
            label = (n.get("label") or "").strip()
            if rid in ("tv_contact_phone", "tv_phone") and label:
                phone_nodes.append(label)
        result = []
        for i, c in enumerate(contacts):
            phone = phone_nodes[i] if i < len(phone_nodes) else ""
            result.append({"name": c["name"], "phone_masked": phone})
        if not result:
            result = self._v150_read_contact_list_h5(tag)
        logger.info("【%s】联系人列表读取：%s", tag, result)
        return result

    def _v150_read_contact_list_h5(self, tag="v150_safety"):
        """从 H5 卡片文案中解析联系人列表。

        卡片文案形如「童1（****1727）」，姓名与掩码号码合并在同一个 StaticText。
        """
        js = r"""
        (function() {
          var out = [];
          var all = document.querySelectorAll('*');
          for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.children.length > 0) continue;
            var txt = (el.textContent || '').trim();
            var m = txt.match(/^(.+?)\s*[（(]\s*([*•]{2,}\d{4})\s*[）)]\s*$/);
            if (m) {
              out.push({name: m[1].trim(), phone_masked: m[2]});
            }
          }
          return JSON.stringify(out);
        })()
        """
        result = self._v150_cdp_eval(js)
        if not result.get("success"):
            logger.warning("【%s】H5 联系人列表解析失败：%s", tag, result.get("error"))
            return []
        try:
            items = json.loads(result["value"])
        except Exception:
            return []
        return [dict(item) for item in items]

    # ==================== 安全中心接口校验 ====================

    # 需求接口清单（见需求文档接口表）
    SAFETY_API_PATHS = {
        "user_save": "/passenger/user/save",
        "contact_list": "/passenger/contact/list",
        "contact_save": "/passenger/contact/save",
        "contact_delete": "/passenger/contact/delete",
        "contact_share": "/passenger/contact/share",
        "emergency_alarm": "/passenger/emergency/alarm",
        "trip_send": "/passenger/order/tripSend",
    }

    def v150_safety_start_api_capture(self, tag="v150_safety"):
        """操作前清空logcat并绑定乘客App进程PID，用于抓取本次操作产生的接口调用。"""
        try:
            pid = self._v150_receipt_logcat_pid()
        except RuntimeError as exc:
            logger.warning("【%s】无法抓取安全中心接口日志：%s", tag, exc)
            self._safety_logcat_pid = None
            return None
        self._v150_adb("logcat", "-c")
        self._safety_logcat_pid = pid
        logger.info("【%s】已清空logcat准备抓取接口日志，PID=%s", tag, pid)
        return pid

    def v150_safety_collect_api_log(self, tag="v150_safety", timeout=10):
        """抓取本次操作产生的接口调用与响应。

        返回字典：captured、api_calls（接口名/入参/code/message/data_keys）、
        api_names、raw_calls（完整解析结果，便于自定义断言）。
        """
        pid = getattr(self, "_safety_logcat_pid", None)
        if not pid:
            return {"captured": False, "reason": "未启动安全中心接口日志抓取",
                    "api_calls": [], "api_names": [], "raw_calls": []}
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
            lines = output.splitlines() if output else []
            calls = parse_api_calls(lines)
            if any(call.get("code") is not None for call in calls):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.4)
        raw_calls = parse_api_calls(lines)
        summary = summarize_calls(raw_calls)
        safety_calls = [c for c in summary if c.get("api") in self.SAFETY_API_PATHS]
        self._last_safety_api_calls = raw_calls
        logger.info("【%s】安全中心接口日志已抓取：接口=%s",
                    tag, [c["api"] for c in safety_calls])
        return {
            "captured": True, "pid": pid, "total_lines": len(lines),
            "api_calls": safety_calls,
            "api_names": [c["api"] for c in safety_calls],
            "raw_calls": raw_calls,
            "all_calls": summary,
        }

    def v150_safety_assert_api(self, evidence, api_name, *, expect_code=10000,
                              expect_params=None, forbidden_params=None,
                              expect_data_contains=None, tag="v150_safety"):
        """按需求接口表断言接口返回，并返回核对结论。

        evidence 为 v150_safety_collect_api_log 的返回值；断言结果同时写入日志，
        便于将「接口返回」与「前端展示」逐项对照。
        """
        raw_calls = evidence.get("raw_calls") or []
        result = check_api_response(
            raw_calls, api_name, expect_code=expect_code,
            expect_params=expect_params, forbidden_params=forbidden_params,
            expect_data_contains=expect_data_contains)
        matched_call = None
        for call in raw_calls:
            if call.get("api") == api_name:
                matched_call = call
        result["params"] = result.get("params") or {}
        result["data"] = (matched_call or {}).get("data")
        logger.info("【%s】接口 %s 断言：matched=%s passed=%s code=%s reason=%s params=%s",
                    tag, api_name, result.get("matched"), result.get("passed"),
                    result.get("code"), result.get("reason"), result.get("params"))
        return result

    def v150_safety_verify_contact_list_api(self, evidence, tag="v150_safety"):
        """核对 contact/list 接口返回与前端联系人展示是否一致。

        接口出参：{contact_id, area_code, name, phone, auto_share}；
        前端展示：联系人姓名 + 掩码手机号 + 自动分享开关状态。
        """
        result = self.v150_safety_assert_api(evidence, "contact_list", tag=tag)
        raw_calls = evidence.get("raw_calls") or []
        api_contacts = []
        for call in raw_calls:
            if call.get("api") != "contact_list":
                continue
            data = call.get("data")
            if isinstance(data, dict):
                for key in ("list", "contacts", "items", "rows", "data"):
                    value = data.get(key)
                    if isinstance(value, list):
                        api_contacts = value
                        break
            if not api_contacts and isinstance(data, list):
                api_contacts = data
        # 接口返回字段完整性：每个联系人应含 contact_id/area_code/name/phone/auto_share
        field_missing = []
        for idx, item in enumerate(api_contacts):
            if not isinstance(item, dict):
                continue
            for field in ("contact_id", "area_code", "name", "phone", "auto_share"):
                if field not in item:
                    field_missing.append(f"[{idx}].{field}")
        # 前端展示核对：姓名与掩码手机号应能在接口返回中找到对应项
        ui_contacts = self.v150_safety_read_contact_list(tag)
        ui_names = {c["name"] for c in ui_contacts}
        api_names = {str(i.get("name")) for i in api_contacts if isinstance(i, dict)}
        name_missing_in_ui = sorted(api_names - ui_names)
        name_missing_in_api = sorted(ui_names - api_names)
        result["api_contact_count"] = len(api_contacts)
        result["ui_contact_count"] = len(ui_contacts)
        result["field_missing"] = field_missing
        result["name_missing_in_ui"] = name_missing_in_ui
        result["name_missing_in_api"] = name_missing_in_api
        if field_missing:
            result["passed"] = False
            result["reason"] = result.get("reason") or (
                f"contact/list 返回缺少字段：{field_missing}")
        if name_missing_in_ui:
            result["passed"] = False
            result["reason"] = result.get("reason") or (
                f"接口返回的联系人未在前端展示：{name_missing_in_ui}")
        if name_missing_in_api:
            result["passed"] = False
            result["reason"] = result.get("reason") or (
                f"前端展示的联系人未在接口返回中：{name_missing_in_api}")
        logger.info("【%s】contact/list 与前端核对：api=%s ui=%s 字段缺失=%s",
                    tag, sorted(api_names), sorted(ui_names), field_missing)
        return result

    def v150_safety_verify_contact_save_api(self, evidence, *, name=None, phone=None,
                                            auto_share=None, expect_code=10000,
                                            tag="v150_safety"):
        """核对 contact/save 接口：入参 {area_code, name, phone, auto_share} 与返回码。"""
        expect_params = {}
        if name is not None:
            expect_params["name"] = name
        if phone is not None:
            expect_params["phone"] = phone
        if auto_share is not None:
            expect_params["auto_share"] = auto_share
        return self.v150_safety_assert_api(
            evidence, "contact_save", expect_code=expect_code,
            expect_params=expect_params or None, tag=tag)

    def v150_safety_verify_contact_delete_api(self, evidence, *, contact_id=None,
                                              expect_code=10000, tag="v150_safety"):
        """核对 contact/delete 接口：入参 {contact_id} 与返回码。"""
        expect_params = {"contact_id": contact_id} if contact_id is not None else None
        return self.v150_safety_assert_api(
            evidence, "contact_delete", expect_code=expect_code,
            expect_params=expect_params, tag=tag)

    def v150_safety_verify_contact_share_api(self, evidence, *, contact_id=None,
                                             auto_share=None, expect_code=10000,
                                             tag="v150_safety"):
        """核对 contact/share 接口：入参 {contact_id, auto_share} 与返回码。"""
        expect_params = {}
        if contact_id is not None:
            expect_params["contact_id"] = contact_id
        if auto_share is not None:
            expect_params["auto_share"] = auto_share
        return self.v150_safety_assert_api(
            evidence, "contact_share", expect_code=expect_code,
            expect_params=expect_params or None, tag=tag)

    def v150_safety_verify_alarm_api(self, evidence, *, order_no=None,
                                     expect_code=10000, tag="v150_safety"):
        """核对 emergency/alarm 接口：入参 {order_no, longitude, latitude} 与返回码。"""
        expect_params = {}
        if order_no is not None:
            expect_params["order_no"] = order_no
        result = self.v150_safety_assert_api(
            evidence, "emergency_alarm", expect_code=expect_code,
            expect_params=expect_params or None, tag=tag)
        params = result.get("params") or {}
        missing = [k for k in ("order_no", "longitude", "latitude") if k not in params]
        if missing:
            result["passed"] = False
            result["reason"] = result.get("reason") or (
                f"emergency/alarm 请求缺少参数：{missing}")
        logger.info("【%s】emergency/alarm 入参核对：%s", tag, params)
        return result

    def v150_safety_verify_trip_send_api(self, evidence, *, order_no=None,
                                          expect_code=10000, tag="v150_safety"):
        """核对 order/tripSend 接口：入参 {order_no, email} 与返回码。"""
        expect_params = {}
        if order_no is not None:
            expect_params["order_no"] = order_no
        result = self.v150_safety_assert_api(
            evidence, "trip_send", expect_code=expect_code,
            expect_params=expect_params or None, tag=tag)
        params = result.get("params") or {}
        if "email" not in params:
            result["passed"] = False
            result["reason"] = result.get("reason") or "order/tripSend 请求缺少参数 email"
        return result

    def v150_safety_verify_user_save_api(self, evidence, *, expect_code=10000,
                                         tag="v150_safety"):
        """核对 user/save 接口返回码（邮箱等用户信息保存）。"""
        return self.v150_safety_assert_api(
            evidence, "user_save", expect_code=expect_code, tag=tag)

    # ==================== Vuex Store 接口数据读取 ====================
    # 安全中心是 H5 页面（Vue 2 + Vuex），接口参数加密传输无法从 logcat/CDP
    # 解析明文入参。但接口返回数据解密后存入 Vuex store.state.safetyCenter，
    # 可通过 CDP Runtime.evaluate 读取，与前端 UI 展示逐项对比。

    def _v150_cdp_ws_path(self, url_filter="safety"):
        """通过 CDP /json 列表查找安全中心 WebView 页面的 WebSocket 调试路径。

        返回 (ws_path, page_url) 或 (None, None)。
        """
        import urllib.request
        udid = self.order_settings["device"]["udid"]
        pid = self._v150_adb("shell", "pidof", "-s", "com.sunlightmobility.client")
        if not pid:
            return None, None
        sock_name = f"webview_devtools_remote_{pid.strip()}"
        # 每次都重新设置端口转发（App 重启后 PID 会变）
        self._v150_adb("forward", "tcp:9222", f"localabstract:{sock_name}")
        time.sleep(0.3)
        try:
            data = json.loads(
                urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3).read())
        except Exception:
            return None, None
        for page in data:
            if page.get("type") != "page":
                continue
            url = page.get("url", "")
            if url_filter in url or "safety" in url:
                ws_url = page.get("webSocketDebuggerUrl", "")
                from urllib.parse import urlparse
                return urlparse(ws_url).path, url
        # 没找到含 safety 的页面，取第一个 page
        for page in data:
            if page.get("type") == "page":
                ws_url = page.get("webSocketDebuggerUrl", "")
                from urllib.parse import urlparse
                return urlparse(ws_url).path, page.get("url", "")
        return None, None

    def _v150_cdp_eval(self, expression, timeout=10):
        """通过 CDP raw socket 在 WebView 页面执行 JS 表达式并返回结果。

        使用原生 socket 绕过 Chrome 126 Origin 限制。
        返回 dict: {success, value, error}
        """
        import base64 as _b64
        ws_path, page_url = self._v150_cdp_ws_path()
        if not ws_path:
            return {"success": False, "error": "未找到 WebView 调试页面"}

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15)
        try:
            sock.connect(("127.0.0.1", 9222))
            key = _b64.b64encode(os.urandom(16)).decode()
            handshake = (
                f"GET {ws_path} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:9222\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            sock.send(handshake.encode())
            resp = sock.recv(4096)
            if b"101" not in resp:
                return {"success": False, "error": f"WebSocket 握手失败: {resp[:100]}"}

            # 发送 Runtime.evaluate 请求
            msg = json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                }
            })
            payload = msg.encode()
            mask_key = os.urandom(4)
            header = bytearray([0x81])  # FIN | text frame
            if len(payload) < 126:
                header.append(0x80 | len(payload))
            elif len(payload) < 65536:
                header.append(0x80 | 126)
                header.extend(len(payload).to_bytes(2, "big"))
            else:
                header.append(0x80 | 127)
                header.extend(len(payload).to_bytes(8, "big"))
            masked = bytearray(
                b ^ m for b, m in zip(
                    payload, mask_key * (len(payload) // 4 + 1)))[:len(payload)]
            sock.send(bytes(header) + mask_key + bytes(masked))

            # 读取响应帧
            deadline = time.monotonic() + timeout
            sock.settimeout(2)
            frames = []
            while time.monotonic() < deadline:
                try:
                    hdr = sock.recv(2)
                    if len(hdr) < 2:
                        break
                    length = hdr[1] & 0x7F
                    if length == 126:
                        length = int.from_bytes(sock.recv(2), "big")
                    elif length == 127:
                        length = int.from_bytes(sock.recv(8), "big")
                    if hdr[1] & 0x80:  # masked
                        sock.recv(4)
                    data = b""
                    while len(data) < length:
                        chunk = sock.recv(length - len(data))
                        if not chunk:
                            break
                        data += chunk
                    try:
                        frame = json.loads(data.decode())
                        frames.append(frame)
                        if "result" in frame:
                            break
                    except Exception:
                        pass
                except socket.timeout:
                    if frames:
                        break
                    continue
        except Exception as exc:
            return {"success": False, "error": f"CDP 通信异常: {exc}"}
        finally:
            sock.close()

        if not frames:
            return {"success": False, "error": "CDP 无响应"}
        result = frames[-1].get("result", {})
        if "exceptionDetails" in frames[-1]:
            exc_detail = frames[-1]["exceptionDetails"]
            return {"success": False, "error": exc_detail.get("exception", {}).get("description", str(exc_detail))}
        val = result.get("result", {})
        if val.get("type") == "undefined" or val.get("value") is None:
            return {"success": False, "error": "表达式返回 undefined/null"}
        return {"success": True, "value": val.get("value")}

    def v150_safety_read_vuex_store(self, tag="v150_safety"):
        """通过 CDP 读取安全中心 H5 页面的 Vuex store.safetyCenter 状态。

        返回字典包含：
        - loadPhase: 加载阶段 (idle/loading/ready/error)
        - errorKind: 错误类型 (None/requestFailed/...)
        - snapshotValid: 快照是否有效
        - readSeq/writeSeq: 读写序号
        - contacts: 联系人列表 [{contact_id, name, phone, area_code, auto_share}]
        - contactCount/hasContacts/sharingEnabled/selectedIds/canAdd/canWrite: getters
        - bodyText: 页面可见文本（用于与 store 数据对比）
        """
        js_code = """
        (function() {
            var app = document.querySelector('#app');
            if (!app || !app.__vue__) return JSON.stringify({error: 'no_vue'});
            var store = app.__vue__.$store;
            if (!store) return JSON.stringify({error: 'no_store'});
            var sc = store.state.safetyCenter;
            return JSON.stringify({
                loadPhase: sc.loadPhase,
                errorKind: sc.errorKind,
                snapshotValid: sc.snapshotValid,
                readSeq: sc.readSeq,
                writeSeq: sc.writeSeq,
                contacts: sc.contacts,
                ownerScope: sc.ownerScope,
                contactCount: store.getters['safetyCenter/contactCount'],
                hasContacts: store.getters['safetyCenter/hasContacts'],
                sharingEnabled: store.getters['safetyCenter/sharingEnabled'],
                selectedIds: store.getters['safetyCenter/selectedIds'],
                canAdd: store.getters['safetyCenter/canAdd'],
                canWrite: store.getters['safetyCenter/canWrite'],
                bodyText: document.body.innerText.substring(0, 1000)
            });
        })()
        """
        result = self._v150_cdp_eval(js_code, timeout=10)
        if not result.get("success"):
            logger.warning("【%s】Vuex store 读取失败：%s", tag, result.get("error"))
            return {"error": result.get("error"), "contacts": [], "loadPhase": "unknown"}
        try:
            store_data = json.loads(result["value"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("【%s】Vuex store 返回无法解析：%s", tag, result.get("value"))
            return {"error": "json_parse_error", "raw": str(result.get("value"))[:200],
                    "contacts": [], "loadPhase": "unknown"}

        logger.info("【%s】Vuex store 读取成功：loadPhase=%s contacts=%d hasContacts=%s "
                    "sharingEnabled=%s", tag, store_data.get("loadPhase"),
                    len(store_data.get("contacts", [])),
                    store_data.get("hasContacts"), store_data.get("sharingEnabled"))
        self._last_vuex_store = store_data
        return store_data

    def v150_safety_vuex_trigger_reload(self, tag="v150_safety"):
        """通过 Vue 组件方法触发 contact/list 重新加载。

        调用 EmergencyContacts 组件的 loadContacts 方法，等待完成后返回。
        需要当前页面已在联系人管理页。
        """
        js_code = """
        (async function() {
            var app = document.querySelector('#app');
            if (!app || !app.__vue__) return JSON.stringify({error: 'no_vue'});
            var vm = app.__vue__;
            function findComp(c) {
                if (!c) return null;
                if (c.$options && c.$options.name === 'EmergencyContacts') return c;
                for (var i = 0; i < (c.$children || []).length; i++) {
                    var r = findComp(c.$children[i]);
                    if (r) return r;
                }
                return null;
            }
            var comp = findComp(vm);
            if (!comp) return JSON.stringify({error: 'component_not_found'});
            try { comp.loadContacts(); } catch(e) { return JSON.stringify({error: e.message}); }
            // 轮询等待 loadPhase 变为非 loading
            for (var i = 0; i < 20; i++) {
                await new Promise(function(r) { setTimeout(r, 500); });
                var phase = vm.$store.state.safetyCenter.loadPhase;
                if (phase !== 'loading') break;
            }
            return JSON.stringify({ok: true, finalPhase: vm.$store.state.safetyCenter.loadPhase});
        })()
        """
        result = self._v150_cdp_eval(js_code, timeout=15)
        if not result.get("success"):
            logger.warning("【%s】Vuex 触发 reload 失败：%s", tag, result.get("error"))
        else:
            logger.info("【%s】Vuex reload 完成：%s", tag, result.get("value"))
        return result

    def v150_safety_verify_vuex_contact_list(self, tag="v150_safety"):
        """核对 Vuex store 中联系人数据与前端 UI 展示一致。

        1. 读取 Vuex store.safetyCenter.contacts
        2. 读取前端 UI 联系人卡片（v150_safety_read_contact_list）
        3. 对比：联系人数一致、姓名一一对应、auto_share 状态与前端开关一致
        """
        store = self.v150_safety_read_vuex_store(tag)
        if store.get("error"):
            return {"passed": False, "reason": f"Vuex store 读取失败：{store['error']}"}

        # 接口加载失败时重试（删除联系人后 contact/list 可能返回 businessFailed）
        retry = 0
        while store.get("loadPhase") == "error" and retry < 3:
            retry += 1
            logger.warning("【%s】contact/list 加载失败（errorKind=%s），第 %d 次重试",
                           tag, store.get("errorKind"), retry)
            self.v150_safety_vuex_trigger_reload(tag)
            time.sleep(2)
            store = self.v150_safety_read_vuex_store(tag)
            if store.get("error"):
                return {"passed": False,
                        "reason": f"Vuex store 读取失败：{store['error']}"}

        api_contacts = store.get("contacts", [])
        ui_contacts = self.v150_safety_read_contact_list(tag)
        api_names = {str(c.get("name", "")) for c in api_contacts if isinstance(c, dict)}
        ui_names = {c["name"] for c in ui_contacts}

        name_missing_in_ui = sorted(api_names - ui_names)
        name_missing_in_api = sorted(ui_names - api_names)

        result = {
            "passed": True,
            "loadPhase": store.get("loadPhase"),
            "errorKind": store.get("errorKind"),
            "vuex_contact_count": len(api_contacts),
            "ui_contact_count": len(ui_contacts),
            "vuex_names": sorted(api_names),
            "ui_names": sorted(ui_names),
            "name_missing_in_ui": name_missing_in_ui,
            "name_missing_in_api": name_missing_in_api,
            "sharingEnabled": store.get("sharingEnabled"),
            "selectedIds": store.get("selectedIds"),
            "raw_contacts": api_contacts,
        }

        # 接口加载状态校验
        if store.get("loadPhase") == "error":
            result["passed"] = False
            result["reason"] = f"Vuex store 加载失败：errorKind={store.get('errorKind')}"
        # 联系人数一致
        elif len(api_contacts) != len(ui_contacts):
            result["passed"] = False
            result["reason"] = (f"联系人数不一致：Vuex={len(api_contacts)}, "
                                f"UI={len(ui_contacts)}")
        # 姓名一一对应
        elif name_missing_in_ui:
            result["passed"] = False
            result["reason"] = f"Vuex 有但 UI 没展示：{name_missing_in_ui}"
        elif name_missing_in_api:
            result["passed"] = False
            result["reason"] = f"UI 有但 Vuex 没返回：{name_missing_in_api}"

        logger.info("【%s】Vuex vs UI 核对：vuex=%s ui=%s passed=%s reason=%s",
                    tag, sorted(api_names), sorted(ui_names),
                    result["passed"], result.get("reason"))
        return result

    def v150_safety_verify_vuex_sharing_state(self, tag="v150_safety"):
        """核对 Vuex store 中 sharingEnabled 状态与前端自动分享开关一致。

        1. 读取 Vuex store.safetyCenter.sharingEnabled 和 selectedIds
        2. 读取前端自动分享开关状态
        3. 对比：开关状态一致
        """
        store = self.v150_safety_read_vuex_store(tag)
        if store.get("error"):
            return {"passed": False, "reason": f"Vuex store 读取失败：{store['error']}"}

        vuex_sharing = store.get("sharingEnabled", False)
        try:
            ui_sharing = self.v150_safety_get_auto_share_state(tag)
        except RuntimeError as exc:
            ui_sharing = None
            ui_error = str(exc)
        else:
            ui_error = None

        result = {
            "passed": True,
            "vuex_sharingEnabled": vuex_sharing,
            "vuex_selectedIds": store.get("selectedIds"),
            "vuex_hasContacts": store.get("hasContacts"),
            "ui_sharing": ui_sharing,
        }

        if ui_sharing is None:
            result["passed"] = False
            result["reason"] = f"无法读取前端开关状态：{ui_error}"
        elif vuex_sharing != ui_sharing:
            result["passed"] = False
            result["reason"] = (f"自动分享状态不一致：Vuex={vuex_sharing}, "
                                f"UI={ui_sharing}")

        logger.info("【%s】自动分享核对：vuex=%s ui=%s passed=%s",
                    tag, vuex_sharing, ui_sharing, result["passed"])
        return result

    # ==================== 邮箱收据 ====================

    def _v150_all_visible_nodes(self, root=None):
        """返回 visible_nodes 结果，并补充 Flutter 页面中缺少 visible 属性的节点。

        Appium Android 的 page_source 经 normalized_tree 转为类 iOS 控件树：
        - 标签名变为 XCUIElementTypeTextField（EditText）、XCUIElementTypeButton 等
        - 文本在 label 属性（合并了 text 和 content-desc）
        - visible 属性可能为 false 或缺失
        """
        root = root or self._passenger_root()
        nodes = list(visible_nodes(root))
        seen = {id(n) for n in nodes}
        input_tags = {"XCUIElementTypeTextField", "XCUIElementTypeSecureTextField"}
        button_tags = {"XCUIElementTypeButton"}
        extras = [n for n in root.iter()
                  if id(n) not in seen
                  and (n.tag in input_tags
                       or n.tag in button_tags
                       or (n.get("label") or "").strip())]
        return nodes + extras

    def _v150_is_input(self, node):
        """判断节点是否为输入框（兼容 normalized_tree 转换后的标签）。"""
        return node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField",
                           "XCUIElementTypeTextView") or "EditText" in (node.get("class") or "")

    def _v150_click_node_by_text(self, keywords, *, node_tags=None, required=True,
                                 exact=False, tag="v150_safety"):
        """按文案匹配并点击指定类型的节点。

        H5 页面同一文案可能同时出现在 StaticText（说明文案）和 Button（可点按钮）上，
        _click_text 的唯一性校验会因此失败。此处按节点类型过滤后再点击。

        keywords: 候选文案，按顺序尝试
        node_tags: 允许点击的节点标签，如 ("XCUIElementTypeButton",)；None 表示不限
        exact: True 时要求文案完全相等，False 时要求包含
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for keyword in keywords:
            matched = []
            for n in nodes:
                if node_tags and (n.get("class") or n.tag) not in node_tags:
                    continue
                label = (n.get("label") or n.get("content-desc") or n.get("text") or "").strip()
                if not label:
                    continue
                if (label == keyword) if exact else (keyword in label):
                    matched.append(n)
            if len(matched) == 1:
                self.client.click(*center(matched[0]))
                logger.info("【%s】已点击节点（文案=%s, 类型=%s）", tag, keyword,
                            matched[0].get("class") or matched[0].tag)
                return True
            if len(matched) > 1:
                logger.warning("【%s】文案「%s」匹配到 %d 个节点，跳过",
                               tag, keyword, len(matched))
        if required:
            raise RuntimeError(f"V1.5.0 未找到可点击节点：{keywords}")
        return False

    def _v150_adb(self, *args):
        """执行 adb 命令并返回输出。"""
        udid = self.order_settings["device"]["udid"]
        cmd = ["adb", "-s", udid, *args]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                logger.warning("【adb】命令失败：%s → stderr=%s", " ".join(cmd), result.stderr.strip())
            return result.stdout.strip()
        except Exception as exc:
            logger.warning("【adb】命令异常：%s → %s", " ".join(cmd), exc)
            return ""

    def _v150_native_email_input(self, node=None):
        """定位当前前台唯一可操作的原生邮箱输入框，不使用旧页面的坐标。"""
        from appium.webdriver.common.appiumby import AppiumBy

        self._assert_passenger_foreground()
        inputs = [element for element in self.client.driver.find_elements(
            AppiumBy.CLASS_NAME, "android.widget.EditText")
            if element.is_displayed() and element.is_enabled()]
        if len(inputs) != 1:
            raise RuntimeError(f"邮箱输入框必须唯一且可操作，实际找到 {len(inputs)} 个；未输入")
        element = inputs[0]
        resource_id = node.get("resource-id") if node is not None else None
        if resource_id and element.get_attribute("resource-id") != resource_id:
            raise RuntimeError("邮箱输入框与当前页面不匹配；未输入")
        return element

    def _v150_native_email_value(self, element=None):
        """原样读取原生 text，保留空格，不读取不受驱动支持的占位属性。"""
        element = element if element is not None else self._v150_native_email_input()
        value = element.text
        if not isinstance(value, str):
            raise RuntimeError("邮箱输入框读取失败，不能当作空值")
        resource_id = element.get_attribute("resource-id") or ""
        if (resource_id.endswith("/et_email") and value == "請輸入電子郵箱"
                and element.get_attribute("hint") == value):
            return ""
        return value

    def _v150_input_email(self, node, email, tag="v150_email"):
        """原生定位、聚焦、清空、单次输入、原样回读；失败不保存、不切换输入方式。"""
        element = self._v150_native_email_input(node)
        element.click()
        self._wait(
            lambda: self._v150_native_email_input().get_attribute("focused") in (True, "true"),
            "邮箱输入框未获得焦点；未输入", timeout=3,
        )
        self._v150_native_email_input().clear()
        self._wait(lambda: self._v150_native_email_value() == "",
                   "邮箱输入框清空失败；未输入", timeout=3)
        if email:
            self._v150_native_email_input().send_keys(email)
        self._wait(lambda: self._v150_native_email_value() == email,
                   "邮箱输入框原样回读不一致；未保存或发送", timeout=3)
        self.client.dismiss_keyboard()
        typed = self._v150_native_email_value()
        if typed != email:
            raise RuntimeError("收起键盘后邮箱输入值发生变化；未保存或发送")
        logger.info("【%s】邮箱单次输入原样回读一致：%r", tag, typed)
        return typed

    def _v150_click_desc(self, keywords, *, required=True, tag=""):
        """点击 label/content-desc 包含关键词的控件（Flutter 页面使用）。

        normalized_tree 转换后，content-desc 被合并到 label 属性，
        clickable 变为 tag 是否是 XCUIElementTypeButton。
        """
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for keyword in keywords:
            matches = [n for n in nodes
                       if keyword in (n.get("label") or n.get("content-desc") or "").strip()
                       and n.get("enabled") != "false"
                       and (n.tag == "XCUIElementTypeButton"
                            or n.get("clickable") == "true")]
            if len(matches) == 1:
                self.client.click(*center(matches[0]))
                logger.info("【%s】已点击 label/desc 含'%s'的控件", tag, keyword)
                return True
            if len(matches) > 1:
                if required:
                    raise RuntimeError(f"label/desc 含'{keyword}'的控件不唯一：{len(matches)}个")
                return False
        if required:
            raise RuntimeError(f"未找到 label/desc 含以下关键词的可点击控件：{keywords}")
        return False

    def _v150_return_home(self, tag="v150_email", attempts=6):
        """用原生返回键逐级回到首页；已在首页或无法返回时返回当前页类型。

        H5 页面被分类为 unknown，但返回键仍然有效，不提前中断。
        """
        for _ in range(attempts):
            try:
                page = self._v150_current_page_type()
            except Exception:
                page = "unknown"
            if page == "home":
                return True
            # unknown 页面（如 H5）也继续按返回键，不中断
            try:
                self.client.driver.back()
            except Exception as exc:
                logger.warning("【%s】返回键操作失败：%s", tag, exc)
                break
            time.sleep(1.5)
        try:
            return self._v150_current_page_type() == "home"
        except Exception:
            return False

    def _v150_reopen_email_page(self, tag="v150_email"):
        """在 App 内直接回到邮箱管理页，不重启 App，避免启动页识别超时。"""
        try:
            page = self._v150_current_page_type()
        except Exception:
            page = "unknown"
        if page == "email_settings":
            self.client.dismiss_keyboard()
            self.client.driver.back()
            self._wait(lambda: self._v150_current_page_type() == "settings",
                       "邮箱编辑页未返回设置页，不能回读持久化值", timeout=8)
            page = "settings"
        if page == "settings":
            overlays = self._v150_toast_texts()
            if overlays:
                logger.info("【%s】重新进入前等待全屏提示消失：%r", tag, overlays)
                self._wait(lambda: not self._v150_toast_texts(),
                           "全屏提示未消失，不能点击被遮挡的邮箱入口", timeout=8)
            root = self._passenger_root()
            entries = [n for n in visible_nodes(root)
                       if (n.get("label") or n.get("content-desc") or n.get("text")) == "電子郵箱"
                       and n.get("enabled") != "false"]
            if len(entries) == 1:
                self.client.click(*center(entries[0]))
                self._wait(
                    lambda: self._v150_email_page_ready(),
                    "V1.5.0 邮箱管理页面未就绪",
                    timeout=10,
                )
                logger.info("【%s】已在设置页直接重新进入邮箱页", tag)
                return self._v150_current_page_type()
        return self.v150_open_email_settings(tag)

    def v150_open_email_settings(self, tag="v150_email"):
        """进入设置页面，找到邮箱管理入口。"""
        self._ensure_devices_awake()
        # 若已在 App 内但不在首页，先用原生返回键回到首页，避免重启 App 导致启动页识别失败
        at_home = self._v150_return_home(tag)
        self.prepare_passenger_app(tag, launch=not at_home)
        self.ensure_passenger_login(tag)
        # 从首页进入「我的」页面
        self._click_text(["我的"], exact=True, required=True)
        self._wait(
            lambda: self._v150_mine_page_ready(),
            "V1.5.0 我的页面未就绪",
            timeout=10,
        )
        # 进入设置（真机为 iv_setting 图标，回退到文本）
        root = self._passenger_root()
        package = self.order_settings["packages"]["passenger_hk"]
        setting_ids = {package + ":id/" + name for name in ("iv_setting", "setting_icon", "iv_settings")}
        setting_btns = [n for n in visible_nodes(root)
                        if n.get("resource-id") in setting_ids and n.get("enabled") != "false"]
        if len(setting_btns) == 1:
            self._login_native(root, setting_btns[0]).click()
            logger.info("【%s】已点击设置图标 iv_setting", tag)
        else:
            self._click_text(["設置", "设置", "設定"], exact=True, required=True)
        self._wait(
            lambda: self._v150_settings_page_ready(),
            "V1.5.0 设置页面未就绪",
            timeout=10,
        )
        # 查找邮箱入口（Flutter 页面用 content-desc，原生页面用 text/label）
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        email_labels = ("郵箱", "邮箱", "Email", "電子郵箱", "电子邮箱", "电子邮件")
        entry = []
        for n in nodes:
            desc = (n.get("content-desc") or "").strip()
            text = (n.get("text") or "").strip()
            label = (n.get("label") or "").strip()
            visible_text = desc or text or label
            if any(keyword in visible_text for keyword in email_labels) and n.get("enabled") != "false":
                entry.append(n)
        if not entry:
            raise RuntimeError("V1.5.0 设置页面未找到邮箱入口")
        if len(entry) > 1:
            raise RuntimeError("V1.5.0 邮箱入口不唯一，禁止点击")
        self.client.click(* center(entry[0]))
        logger.info("【%s】已点击邮箱入口", tag)
        self._wait(
            lambda: self._v150_email_page_ready(),
            "V1.5.0 邮箱管理页面未就绪",
            timeout=10,
        )
        page = self._v150_current_page_type()
        logger.info("【%s】邮箱管理页面已就绪", tag)
        return page

    def v150_email_read_current(self, tag="v150_email"):
        """原样读取管理页输入值；验证保存结果前须先重新进入页面。"""
        if self._v150_current_page_type() != "email_settings":
            raise RuntimeError("当前不在邮箱管理页，不能将缺少输入框当作邮箱为空")
        current = self._v150_native_email_value()
        logger.info("【%s】当前邮箱原值=%r", tag, current)
        return current

    def v150_email_type(self, tag="v150_email", email=""):
        """在邮箱管理页的输入框内写入邮箱（不做任何保存动作）。

        用于需要单独观察 toast / 保存结果的真机用例。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        inputs = [n for n in self._v150_all_visible_nodes(root)
                  if (self._v150_is_input(n)) and n.get("enabled") != "false"]
        if not inputs:
            edit_labels = ("編輯", "编辑", "修改", "Edit")
            if self._click_text(edit_labels, required=False):
                self._wait(
                    lambda: bool([n for n in self._v150_all_visible_nodes()
                                  if self._v150_is_input(n)]),
                    "V1.5.0 邮箱编辑输入框未出现",
                    timeout=10,
                )
                root = self._passenger_root()
                inputs = [n for n in self._v150_all_visible_nodes(root)
                          if (self._v150_is_input(n)) and n.get("enabled") != "false"]
        if not inputs:
            logger.error("【%s】邮箱页节点诊断：%s", tag, [
                (n.tag, n.get("label"), n.get("value"), n.get("content-desc"),
                 n.get("text"), n.get("enabled"), n.get("visible"))
                for n in self._v150_all_visible_nodes(root)])
            raise RuntimeError("V1.5.0 邮箱管理页未找到邮箱输入框")
        self._v150_input_email(inputs[0], email, tag)
        return email

    def v150_email_click_save(self, tag="v150_email"):
        """点击邮箱管理页的保存按钮（不做回读）。"""
        save_labels = ("保存", "儲存", "確認", "确定", "確定")
        # Flutter 页面用 content-desc 定位保存按钮，原生页面用 text
        if not self._v150_click_desc(save_labels, required=False, tag=tag):
            self._click_text(save_labels, exact=True, required=True)
        logger.info("【%s】已点击邮箱保存按钮", tag)
        return True

    def _v150_email_start_api_capture(self, tag="v150_email"):
        """保存邮箱前清空logcat，后续只抓取本次保存产生的接口调用。"""
        try:
            pid = self._v150_receipt_logcat_pid()
        except RuntimeError as exc:
            logger.warning("【%s】无法抓取邮箱保存接口日志：%s", tag, exc)
            self._email_logcat_pid = None
            return None
        self._v150_adb("logcat", "-c")
        self._email_logcat_pid = pid
        logger.info("【%s】已清空logcat准备抓取邮箱保存接口，PID=%s", tag, pid)
        return pid

    def _v150_email_collect_api_log(self, tag="v150_email", timeout=8):
        """抓取邮箱保存产生的接口调用与响应，等待服务端响应落日志。"""
        pid = getattr(self, "_email_logcat_pid", None)
        if not pid:
            return {"captured": False, "reason": "未启动邮箱接口日志抓取"}
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
            lines = output.splitlines() if output else []
            calls = parse_api_calls(lines)
            if any(call.get("code") is not None for call in calls):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.4)
        api_calls = parse_api_calls(lines)
        evidence = {
            "captured": True, "pid": pid, "total_lines": len(lines),
            "api_calls": summarize_calls(api_calls),
            "api_names": [call["api"] for call in api_calls if call["api"]],
        }
        self._last_email_api_calls = evidence["api_calls"]
        logger.info("【%s】邮箱保存接口日志已抓取：接口=%s", tag, evidence["api_names"])
        return evidence

    def v150_email_save(self, tag="v150_email", *, email="test@example.com"):
        """保存邮箱地址。"""
        current = self.v150_email_read_current(tag)
        saved, state = save_email(current, email)
        logger.info("【%s】邮箱保存离线契约校验：current=%s, submitted=%s → saved=%s, state=%s",
                     tag, current, email, saved, state)
        if not email.strip():
            logger.info("【%s】执行删除邮箱操作", tag)
        self.v150_email_type(tag, email)
        self._v150_email_start_api_capture(tag)
        self.v150_email_click_save(tag)
        self._wait(lambda: self._v150_current_page_type() == "settings",
                   "邮箱保存后未返回设置页", timeout=8)
        self._v150_email_collect_api_log(tag)
        self._v150_reopen_email_page(tag)
        actual = self.v150_email_read_current(tag)
        expected = saved if state != "deleted" else ""
        if actual != expected:
            logger.warning("【%s】邮箱回读不一致：expected=%s, actual=%s", tag, expected, actual)
        else:
            logger.info("【%s】邮箱保存成功：%s", tag, actual)
        return actual

    def _v150_email_page_ready(self):
        """必须同时出现邮箱标题、输入框和保存按钮，不能只匹配设置页入口。"""
        nodes = visible_nodes(self._passenger_root())
        texts = {n.get("label") or n.get("content-desc") or n.get("text") for n in nodes}
        return ("電子郵箱" in texts and "保存" in texts
                and any(self._v150_is_input(n) for n in nodes))

    def _v150_mine_page_ready(self):
        """检测我的页面是否已加载。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        texts = {(n.get("label") or "").strip() for n in nodes}
        mine_keywords = ("我的行程", "設置", "设置", "聯繫客服", "联系客服")
        return any(keyword in text for text in texts for keyword in mine_keywords)

    def _v150_settings_page_ready(self):
        """检测设置页面是否已加载（Flutter 页面用 content-desc）。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        all_texts = set()
        for n in nodes:
            for attr in ("content-desc", "text", "label"):
                val = (n.get(attr) or "").strip()
                if val:
                    all_texts.add(val)
        settings_keywords = ("設置", "设置", "設定", "郵箱", "邮箱", "電子郵箱",
                             "私隱中心", "隐私中心", "安全", "語言", "退出登錄")
        return any(keyword in text for text in all_texts for keyword in settings_keywords)

    # ==================== 收据（电子收据） ====================

    def _v150_toast_texts(self):
        """读取当前页面里 Flutter toast 的文案。

        该 App 的 toast 是 Flutter 全屏 overlay。
        Appium page_source 经 normalized_tree 转换后：
        - android.view.View 变为 XCUIElementTypeOther
        - content-desc 合并到 label 属性
        - bounds 变为 x/y/width/height 属性
        """
        try:
            root = self._passenger_root()
        except Exception as exc:
            logger.warning("【toast】读取页面失败：%s", exc)
            return set()
        texts = set()
        for node in root.iter():
            tag = node.tag
            label = (node.get("label") or "").strip()
            # toast overlay 在 normalized_tree 中表现为 XCUIElementTypeOther，全屏
            if label and tag == "XCUIElementTypeOther":
                x = int(node.get("x") or "0")
                y = int(node.get("y") or "0")
                w = int(node.get("width") or "0")
                h = int(node.get("height") or "0")
                # 全屏 overlay：起点接近 (0,0) 且面积接近全屏
                if x <= 5 and y <= 5 and w > 800 and h > 1500:
                    texts.add(label)
            # 兼容原生 XML（未经 normalized_tree 转换的场景）
            desc = (node.get("content-desc") or "").strip()
            if desc and (node.get("class") or "") == "android.view.View":
                bounds = node.get("bounds") or ""
                if bounds.startswith("[0,0]["):
                    texts.add(desc)
        return texts

    def _v150_wait_toast(self, keywords, *, timeout=6, tag=""):
        """在超时窗口内轮询等待 toast 出现，返回命中的 toast 文案。

        toast 停留时间很短，必须高频轮询页面树，不能只抓一次。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for text in self._v150_toast_texts():
                for keyword in keywords:
                    if keyword in text:
                        logger.info("【%s】已捕获 toast：%s", tag, text)
                        return text
            time.sleep(0.2)
        logger.warning("【%s】未捕获到 toast（关键词=%s）", tag, keywords)
        return ""

    def v150_open_trip_list(self, tag="v150_receipt"):
        """从首页进入「我的行程」列表页。"""
        self._ensure_devices_awake()
        if not self._v150_return_home(tag):
            raise RuntimeError("无法从已识别页面安全返回首页；未创建或操作订单")
        self._click_text(["我的"], exact=True, required=True)
        self._wait(lambda: self._v150_mine_page_ready(), "我的页未就绪", timeout=8)
        self._click_text(["我的行程"], exact=True, required=True)
        self._wait(
            lambda: self._v150_trip_list_ready(),
            "V1.5.0 我的行程列表未就绪",
            timeout=15,
        )
        logger.info("【%s】已进入我的行程列表", tag)
        return "trip_list"

    def _v150_trip_list_ready(self):
        ids = {n.get("resource-id", "").split("/")[-1]
               for n in visible_nodes(self._passenger_root())}
        return {"scheduling_root", "recycler_view"} <= ids

    def _v150_scroll_trip_list(self, *, max_rounds=8):
        """向下滑动我的行程列表，直到出现「已完成」订单或达到上限。"""
        for _ in range(max_rounds):
            root = self._passenger_root()
            nodes = self._v150_all_visible_nodes(root)
            for n in nodes:
                rid = n.get("resource-id", "").split("/")[-1]
                text = (n.get("label") or n.get("text") or "").strip()
                if rid == "tv_type_order" and text in ("已完成", "行程結束"):
                    return True
            self.client.swipe(586, 1800, 586, 900, 300)
            time.sleep(1.2)
        return False

    @staticmethod
    def _v150_receipt_instant_cards(root):
        cards = []
        for card in visible_nodes(root):
            if card.get("resource-id", "").split("/")[-1] != "rl_order_item_layout":
                continue
            fields = {n.get("resource-id", "").split("/")[-1]: n.get("label", "")
                      for n in visible_nodes(card)}
            if fields.get("tv_type_order") == "已完成" and fields.get("tv_type_scheduling") == "即時用車":
                cards.append((card, fields.get("tv_guid_date", "")))
        return cards

    def _v150_receipt_order_number(self):
        nodes = visible_nodes(self._passenger_root())
        values = [n.get("label", "") for n in nodes
                  if n.get("resource-id", "").endswith("/tv_order_no")]
        numbers = re.findall(r"(?<![A-Z0-9])[A-Z0-9]{12}(?![A-Z0-9])", " ".join(values))
        if len(set(numbers)) != 1:
            raise RuntimeError("收据订单编号缺失或不唯一，未发送")
        return numbers[0]

    def v150_open_completed_order_detail(self, tag="v150_receipt"):
        """只读绑定同一条已完成即时订单，并以费用详情的实际支付信息核验前置。"""
        binding = getattr(type(self), "_receipt_order_binding", None)
        self.v150_open_trip_list(tag)
        selected = None
        for _ in range(10):
            cards = self._v150_receipt_instant_cards(self._passenger_root())
            matches = [(card, date) for card, date in cards
                       if binding is None or date == binding["date"]]
            if matches:
                if binding is not None and len(matches) != 1:
                    raise RuntimeError("目标即时订单卡片不唯一，未发送")
                selected, date = matches[0]
                from appium.webdriver.common.appiumby import AppiumBy
                package = self.order_settings["packages"]["passenger_hk"]
                dates = [el for el in self.client.driver.find_elements(
                    AppiumBy.ID, f"{package}:id/tv_guid_date")
                    if el.is_displayed() and el.text == date]
                if len(dates) != 1:
                    raise RuntimeError("目标卡片日期不唯一，未进入订单")
                dates[0].click()
                break
            width, height = self.client.window_size()
            self.client.swipe(width // 2, int(height * .82), width // 2, int(height * .30), .45)
            time.sleep(.5)
        if selected is None:
            raise RuntimeError("十页内未找到目标已完成即时订单，收据测试前置阻塞")
        self._wait(self._v150_order_detail_ready, "订单详情未就绪", timeout=10)
        order_no = self._v150_receipt_order_number()
        if binding is not None and order_no != binding["order_no"]:
            raise RuntimeError("再次进入的订单号不一致，未发送")
        texts = {n.get("label", "") for n in visible_nodes(self._passenger_root())}
        if not any("行程結束" in text for text in texts):
            raise RuntimeError("详情页缺少行程结束证据，未发送")
        if binding is None:
            self._click_text(["費用明細"], exact=True, required=True)
            self._wait(lambda: "實際支付金額" in {
                n.get("label", "") for n in visible_nodes(self._passenger_root())},
                "费用详情未出现实际支付金额，无法确认已支付", timeout=15)
            fee_texts = {n.get("label", "") for n in visible_nodes(self._passenger_root())}
            methods = sorted(t for t in fee_texts if t.startswith("支付方式：") and t != "支付方式：")
            if not methods or "HKD" not in fee_texts:
                raise RuntimeError("费用详情缺少付款方式或金额单位，无法确认已支付")
            evidence = Path(__file__).resolve().parents[1] / "report" / "receipt_evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            prefix = evidence / f"{time.time_ns()}_paid_order"
            prefix.with_suffix(".xml").write_text(self.client.driver.page_source, encoding="utf-8")
            self.client.screenshot(str(prefix.with_suffix(".png")))
            binding = {"date": date, "order_no": order_no, "type": "即時用車",
                       "state": "已完成", "payment": methods, "evidence": str(prefix)}
            self.client.driver.back()
            self._wait(self._v150_order_detail_ready, "费用详情未返回目标订单", timeout=8)
            if self._v150_receipt_order_number() != order_no:
                raise RuntimeError("费用详情返回后订单号变化，未发送")
            type(self)._receipt_order_binding = binding
        self._receipt_precondition = binding
        self._receipt_order_no = order_no
        logger.info("【%s】收据前置已核验：%s", tag, binding)
        return "order_detail"

    def _v150_order_detail_ready(self):
        """检测订单详情页是否已加载（含收据入口或订单号）。"""
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for n in nodes:
            rid = n.get("resource-id", "").split("/")[-1]
            if rid in ("tv_order_no", "tv_sending_email", "ll_sending_email"):
                return True
        return False

    def _v150_receipt_native_field(self, resource_id):
        """按原生 resource-id 定位可见控件，返回其文本；找不到返回空串。"""
        from appium.webdriver.common.appiumby import AppiumBy
        package = self.order_settings["packages"]["passenger_hk"]
        try:
            elements = [el for el in self.client.driver.find_elements(
                AppiumBy.ID, f"{package}:id/{resource_id}") if el.is_displayed()]
        except Exception:
            return ""
        if not elements:
            return ""
        return elements[0].text or ""

    def v150_receipt_prompt_present(self, tag="v150_receipt"):
        """识别收据入口状态：提示栏+设置并发送 / 已设置邮箱的发送入口。"""
        nodes = visible_nodes(self._passenger_root())
        fields = {n.get("resource-id", "").split("/")[-1]: n.get("label", "")
                  for n in nodes if n.get("resource-id")}
        prompt_text = self._v150_receipt_native_field("msg") or fields.get("msg", "")
        set_text = self._v150_receipt_native_field("setting") or fields.get("setting", "")
        send_text = self._v150_receipt_native_field("tv_sending_email") or fields.get("tv_sending_email", "")
        return {"prompt": bool(prompt_text) or "msg" in fields, "prompt_text": prompt_text,
                "set_and_send": bool(set_text) or "setting" in fields, "set_text": set_text,
                "send_button": bool(send_text) or "tv_sending_email" in fields,
                "send_text": send_text}

    def _v150_receipt_element(self, resource_id):
        from appium.webdriver.common.appiumby import AppiumBy
        self._assert_passenger_foreground()
        package = self.order_settings["packages"]["passenger_hk"]
        elements = [el for el in self.client.driver.find_elements(
            AppiumBy.ID, f"{package}:id/{resource_id}") if el.is_displayed()]
        if len(elements) != 1:
            raise RuntimeError(f"收据控件 {resource_id} 不唯一或不可见：{len(elements)}")
        return elements[0]

    def v150_open_receipt_dialog(self, tag="v150_receipt", entry="send"):
        if entry not in ("send", "set_and_send"):
            raise ValueError("未知收据入口")
        binding = getattr(type(self), "_receipt_order_binding", None)
        if binding is None or self._v150_receipt_order_number() != binding["order_no"]:
            raise RuntimeError("未绑定已核验的目标订单，不能打开发送弹框")
        self._wait(lambda: not self._v150_toast_texts(), "全屏提示未消失", timeout=8)
        self._v150_receipt_element("tv_sending_email" if entry == "send" else "setting").click()
        deadline = time.monotonic() + 8
        toasts = set()
        while time.monotonic() < deadline:
            toasts.update(self._v150_receipt_toast_texts())
            state = self._v150_receipt_dialog_state()
            if state["present"]:
                time.sleep(.5)
                state = self._v150_receipt_dialog_state()
                break
            time.sleep(.15)
        state["entry_toasts"] = sorted(toasts)
        if toasts:
            type(self)._receipt_last_send = time.monotonic()
        return state

    @staticmethod
    def _v150_receipt_parse_dialog(source, keyboard=False):
        root = ET.fromstring(source)
        dialogs = [n for n in root.iter() if n.get("resource-id", "").endswith("/dialog_content")
                   and n.get("displayed", "true") == "true"]
        state = {"present": len(dialogs) == 1, "title": "", "subtitle": "",
                 "email_input": False, "email": None, "send_button": False,
                 "send_enabled": False, "send_text": "", "modify": False,
                 "modify_text": "", "close": False, "keyboard": keyboard}
        if not state["present"]:
            return state
        nodes = [n for n in dialogs[0].iter() if n.get("displayed", "true") == "true"]
        fields = {n.get("resource-id", "").split("/")[-1]: n for n in nodes if n.get("resource-id")}
        for key, rid in (("title", "tv_title"), ("subtitle", "tv_subtitle"), ("send_text", "btn_send")):
            if rid in fields:
                state[key] = fields[rid].get("text", "")
        state["send_button"] = "btn_send" in fields
        if state["send_button"]:
            state["send_enabled"] = fields["btn_send"].get("enabled") == "true"
        state["close"] = len([n for n in root.iter()
                              if n.get("resource-id", "").endswith("/iv_close")
                              and n.get("displayed", "true") == "true"]) == 1
        inputs = [n for n in nodes if n.get("class", n.tag) == "android.widget.EditText"]
        state["email_input"] = len(inputs) == 1
        if state["email_input"]:
            node = inputs[0]
            value = node.get("text", "")
            state["email"] = "" if value == node.get("hint") == "請輸入電子郵箱" else value
            state["email_placeholder"] = node.get("hint", "")
            state["focused"] = node.get("focused") == "true"
        else:
            emails = {n.get("text", "") for n in nodes if "@" in n.get("text", "")}
            if len(emails) == 1:
                state["email"] = emails.pop()
        modifications = [n.get("text", "") for n in nodes if n.get("text") == "修改"]
        state["modify"] = len(modifications) == 1
        state["modify_text"] = modifications[0] if modifications else ""
        return state

    def _v150_receipt_dialog_state(self):
        return self._v150_receipt_parse_dialog(self.client.driver.page_source,
                                             self.client.driver.is_keyboard_shown())

    def _v150_receipt_dialog_ready(self):
        return self._v150_receipt_dialog_state()["present"]

    def v150_receipt_modify_email(self, tag="v150_receipt"):
        state = self._v150_receipt_dialog_state()
        if not state["present"] or not state["modify"]:
            raise AssertionError("已设置邮箱的收据弹框缺少「修改」按钮")
        self._click_text(["修改"], exact=True, required=True)
        self._wait(lambda: self._v150_receipt_dialog_state()["email_input"],
                   "点击修改后邮箱未变为输入框", timeout=5)
        time.sleep(.5)
        return self._v150_receipt_dialog_state()

    def _v150_receipt_email_input(self, root=None):
        """返回弹框内邮箱输入框节点。"""
        root = root or self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        for n in nodes:
            if n.get("resource-id", "").split("/")[-1] == "et_email":
                return n
        for n in nodes:
            if self._v150_is_input(n):
                return n
        return None

    def v150_receipt_type_email(self, email, tag="v150_receipt"):
        """在弹框邮箱输入框内输入指定邮箱。"""
        if not self._v150_receipt_dialog_state()["present"]:
            raise RuntimeError("不在发送收据弹框，未输入")
        root = self._passenger_root()
        node = self._v150_receipt_email_input(root)
        if node is None:
            raise RuntimeError("V1.5.0 发送收据弹框内未找到邮箱输入框")
        self._v150_input_email(node, email, tag)
        logger.info("【%s】已在收据弹框输入邮箱：%s", tag, email)
        return email

    def v150_receipt_read_saved_email(self, tag="v150_receipt"):
        """读取弹框当前展示/编辑的原值；持久化须另到管理页回读。"""
        state = self._v150_receipt_dialog_state()
        if not state["present"] or state["email"] is None:
            raise RuntimeError("弹框邮箱不可读取，不能当作未设置")
        return state["email"]

    def v150_receipt_click_send(self, tag="v150_receipt"):
        state = self._v150_receipt_dialog_state()
        if not state["present"] or not state["send_button"]:
            raise AssertionError("收据弹框缺少發送按钮")
        if not state["send_enabled"]:
            raise AssertionError("收据发送按钮不可点击；未提交")
        type(self)._receipt_last_send = time.monotonic()
        self._v150_receipt_element("btn_send").click()
        logger.info("【%s】仅点击一次收据发送按钮", tag)
        return True

    @staticmethod
    def _v150_receipt_toast_regions(image):
        """提取本版本录屏已确认的居中深色提示框；不按期望文案筛选。"""
        import cv2
        height, width = image.shape[:2]
        mask = cv2.inRange(image, (0, 0, 0), (85, 85, 85))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if (.20 * width <= w <= .85 * width and .015 * height <= h <= .12 * height
                    and .30 * height <= y <= .70 * height
                    and cv2.contourArea(contour) >= .80 * w * h):
                regions.append((x, y, w, h))
        return regions

    def _v150_receipt_visual_toasts(self):
        import cv2
        import numpy as np
        from jryg_hk_android.JRYG_android_route_ocr import recognize_map
        image = cv2.imdecode(np.frombuffer(self.client.driver.get_screenshot_as_png(), dtype=np.uint8),
                             cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("收据提示截图无法读取")
        directory = getattr(self, "_receipt_case_directory",
                            Path(__file__).resolve().parents[1] / "report/receipt_evidence")
        directory.mkdir(parents=True, exist_ok=True)
        texts = set()
        for x, y, w, h in self._v150_receipt_toast_regions(image):
            path = directory / f"{time.time_ns()}_visual_toast.png"
            if not cv2.imwrite(str(path), image[y:y + h, x:x + w]):
                raise RuntimeError("收据提示截图证据写入失败")
            observations = recognize_map(path, 1)
            path.with_suffix(".json").write_text(json.dumps(observations, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
            accepted = [o["text"] for o in sorted(observations, key=lambda o: (o["y"], o["x"]))
                        if o.get("confidence", 0) >= .95 and o.get("text")]
            if len(accepted) == 1:
                texts.add(accepted[0])
            if hasattr(self, "_receipt_record"):
                self._receipt_record["evidence"].append({"phase": "visual_toast", "screenshot": str(path),
                                                        "ocr": observations})
        return texts

    def _v150_receipt_toast_texts(self):
        from appium.webdriver.common.appiumby import AppiumBy
        native = {el.text for el in self.client.driver.find_elements(
            AppiumBy.CLASS_NAME, "android.widget.Toast") if el.text}
        accessible = native | self._v150_toast_texts()
        return accessible or self._v150_receipt_visual_toasts()

    def _v150_receipt_logcat_pid(self):
        """获取乘客App进程PID，用于后续定向抓取logcat。"""
        package = self.order_settings["packages"]["passenger_hk"]
        pid = self._v150_adb("shell", "pidof", "-s", package).strip()
        if not re.fullmatch(r"\d+", pid):
            raise RuntimeError("乘客App进程不存在或不唯一，无法抓取收据接口日志")
        return pid

    def v150_receipt_start_network_capture(self, tag="v150_receipt"):
        """点击发送前清空logcat缓冲，后续只抓取本次发送产生的新日志。"""
        pid = self._v150_receipt_logcat_pid()
        self._v150_adb("logcat", "-c")
        self._receipt_logcat_pid = pid
        logger.info("【%s】已清空logcat并绑定PID=%s，准备抓取收据接口日志", tag, pid)
        return pid

    def v150_receipt_collect_network_log(self, tag="v150_receipt", order_no=None, timeout=8):
        """抓取本次发送产生的logcat，还原接口调用与响应并提取收据相关记录。"""
        pid = getattr(self, "_receipt_logcat_pid", None)
        if not pid:
            return {"captured": False, "reason": "未启动网络日志抓取"}
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
            lines = output.splitlines() if output else []
            calls = parse_api_calls(lines)
            if any(call.get("code") is not None for call in calls):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.4)
        relevant = []
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in (
                "send_trip_info", "tripsend", "trip_receipt", "receipt", "email",
                "已發送", "稍後查看", "郵箱格式", "頻繁", "频繁",
                "order_no", "invoice", "user_info_changed", "getinfo",
                "/passenger/user/save", "/passenger/contact/",
                "/passenger/emergency/alarm",
            )):
                relevant.append(line.strip())
        api_calls = parse_api_calls(lines)
        evidence = {
            "captured": True, "pid": pid, "total_lines": len(lines),
            "relevant_lines": len(relevant), "log": relevant[:80],
            "order_no": order_no,
            "api_calls": summarize_calls(api_calls),
            "api_names": [call["api"] for call in api_calls if call["api"]],
        }
        path_dir = getattr(self, "_receipt_case_directory",
                           Path(__file__).resolve().parents[1] / "report/receipt_evidence")
        path_dir.mkdir(parents=True, exist_ok=True)
        path = path_dir / f"{time.time_ns()}_network_log.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        if hasattr(self, "_receipt_record"):
            self._receipt_record["evidence"].append(
                {"phase": "network_log", "log_file": str(path),
                 "relevant_lines": evidence["relevant_lines"],
                 "api_calls": evidence["api_calls"]})
            self._receipt_record["network_log_summary"] = {
                "captured": True, "relevant_lines": evidence["relevant_lines"],
                "api_names": evidence["api_names"]}
            self._receipt_record["api_calls"] = evidence["api_calls"]
        logger.info("【%s】收据接口日志已抓取：%d行相关记录，接口=%s → %s", tag,
                    evidence["relevant_lines"], evidence["api_names"], path)
        return evidence

    def v150_receipt_observe_toasts(self, timeout=6):
        """记录原生Toast及Flutter提示的实际文案，不以子串匹配代替精确要求。"""
        deadline = time.monotonic() + timeout
        observed = set()
        while time.monotonic() < deadline:
            current = self._v150_receipt_toast_texts()
            if current - observed and callable(getattr(self, "_capture", None)):
                self._capture("toast_observed")
            observed.update(current)
            if observed and not current:
                break
            time.sleep(.15)
        return sorted(observed)

    def v150_receipt_close_dialog(self, tag="v150_receipt"):
        """点击真实关闭按钮，不用返回键或遮罩替代需求中的关闭按钮。"""
        before = self._v150_receipt_dialog_ready()
        if not before:
            return False
        self._v150_receipt_element("iv_close").click()
        self._wait(
            lambda: not self._v150_receipt_dialog_ready(),
            "V1.5.0 发送收据弹框未关闭",
            timeout=8,
        )
        logger.info("【%s】已关闭发送收据弹框", tag)
        return True

    # ==================== 收银台 ====================
    def v150_verify_cashier_order(self, tag="v150_cashier"):
        """验证收银台支付方式排列顺序。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        texts = {(n.get("label") or "").strip() for n in nodes}
        cashier_keywords = list(getattr(E, "CASHIER_PAGE_KEYWORDS", ())) + ["先付後乘", "預付車費", "收銀台"]
        if not any(keyword in text for text in texts for keyword in cashier_keywords):
            raise RuntimeError("V1.5.0 当前页面不是收银台页面")
        prefix = E.PASSENGER_BUNDLE_ID + ":id/"
        payment_nodes = [n for n in nodes
                         if n.get("resource-id", "").split("/")[-1] in
                         ("tv_payment_name", "tv_pay_name", "tv_name")]
        if not payment_nodes:
            all_texts = [(n.get("label") or "").strip() for n in nodes]
            payment_names = {
                "AlipayHK": [t for t in all_texts if "Alipay" in t or "支付寶" in t],
                "WeChatPay": [t for t in all_texts if "WeChat" in t or "微信" in t],
                "Octopus": [t for t in all_texts if "Octopus" in t or "八達通" in t or "八达通" in t],
                "Card": [t for t in all_texts if "信用卡" in t or "扣帳卡" in t or "扣帐卡" in t],
            }
        else:
            payment_names = {}
            for n in payment_nodes:
                label = (n.get("label") or "").strip()
                if "Alipay" in label or "支付寶" in label:
                    payment_names["AlipayHK"] = payment_names.get("AlipayHK", []) + [label]
                elif "WeChat" in label or "微信" in label:
                    payment_names["WeChatPay"] = payment_names.get("WeChatPay", []) + [label]
                elif "Octopus" in label or "八達通" in label or "八达通" in label:
                    payment_names["Octopus"] = payment_names.get("Octopus", []) + [label]
                elif "信用卡" in label or "扣帳卡" in label or "扣帐卡" in label:
                    payment_names["Card"] = payment_names.get("Card", []) + [label]
        enabled_methods = [method for method in PAYMENT_ORDER if method in payment_names]
        logger.info("【%s】收银台支付方式顺序=%s", tag, enabled_methods)
        expected = [method for method in PAYMENT_ORDER if method in payment_names]
        if enabled_methods != expected:
            raise RuntimeError(
                f"V1.5.0 收银台支付方式顺序不一致：实际={enabled_methods}，预期={expected}")
        if "WeChatPay" not in payment_names:
            logger.info("【%s】WeChatPay 已隐藏（未开启），收银台不显示", tag)
        return {"order": enabled_methods, "count": len(enabled_methods)}

    def v150_verify_cashier_no_duplicate(self, tag="v150_cashier"):
        """验证收银台支付方式不重复出现。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        payment_nodes = [n for n in nodes
                         if n.get("resource-id", "").split("/")[-1] in
                         ("tv_payment_name", "tv_pay_name", "tv_name")]
        labels = [(n.get("label") or "").strip() for n in payment_nodes]
        duplicates = {label for label in labels if labels.count(label) > 1}
        if duplicates:
            raise RuntimeError(f"V1.5.0 收银台存在重复支付方式：{duplicates}")
        logger.info("【%s】收银台支付方式无重复", tag)
        return {"duplicates": False, "count": len(labels)}

    def v150_verify_wechat_uninstalled_prompt(self, tag="v150_cashier"):
        """验证未安装微信时收银台显示安装提示而非跳转下载链接。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        texts = {(n.get("label") or "").strip() for n in nodes}
        install_keywords = ("請安裝應用", "请安装应用", "安裝微信", "安装微信", "未安裝", "未安装")
        found = any(keyword in text for text in texts for keyword in install_keywords)
        has_download_link = any("http" in text.lower() for text in texts
                                if "download" in text.lower() or "下載" in text or "下载" in text)
        if found and has_download_link:
            logger.warning("【%s】微信未安装提示存在但同时出现下载链接，需检查", tag)
        elif found:
            logger.info("【%s】微信未安装提示已确认，无下载链接", tag)
        else:
            logger.info("【%s】当前页面未出现微信未安装提示（可能已安装微信）", tag)
        return {"prompt_found": found, "has_download_link": has_download_link}

    # ==================== 公共工具方法 ====================

    def _v150_current_page_type(self):
        """判断当前页面类型，返回页面标识字符串。

        基于真机 dump 验证的 resource-id 和文案特征：
        - home: tv_home_reservation / tv_safe / tv_start_address / tv_destination
        - time_picker: time_wheels / btn_confirm / tv_title「選擇出發時間」
        - booking: reservation_title / reservation_departure_time / reservation_confirm
        - safety_center: tv_safe「安全中心」/ 緊急聯絡人 / 999
        - email_settings: 郵箱 / Email
        - mine: 我的行程 / 設置
        - settings: 設置 / 隱私
        - cashier: CASHIER_PAGE_KEYWORDS
        - vehicle_page: 確認呼叫
        - calling: 正在為您呼叫
        """
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        # Flutter 页面节点可能缺少 visible 属性，补充遍历所有节点
        flutter_nodes = [n for n in root.iter()
                         if n not in nodes and (n.get("label") or n.get("content-desc") or n.get("text"))]
        all_nodes = nodes + flutter_nodes
        ids = {n.get("resource-id", "").split("/")[-1] for n in all_nodes}
        texts = set()
        for n in all_nodes:
            for attr in ("label", "content-desc", "text"):
                val = (n.get(attr) or "").strip()
                if val:
                    texts.add(val)
        # 时间选择器弹窗（最高优先级，因为它是首页上的弹窗）
        if ids.intersection({"time_wheels", "btn_confirm"}) or \
           texts.intersection({"選擇出發時間", "选择出发时间"}):
            return "time_picker"
        # 预约页面（时间确认后）
        if "reservation_title" in ids or "reservation_confirm" in ids:
            return "booking"
        if "dialog_content" in ids and "btn_send" in ids:
            return "receipt_dialog"
        if "tv_order_no" in ids and any("行程結束" in t for t in texts):
            return "order_detail"
        if "scheduling_root" in ids and "recycler_view" in ids:
            return "trip_list"
        if "費用詳情" in texts:
            return "fee_detail"
        if ids.intersection({"tv_home_reservation", "tv_start_address", "tv_destination"}):
            return "home"
        # 路线/车型页
        if texts.intersection({"確認呼叫", "确认呼叫"}):
            return "vehicle_page"
        # 呼叫中
        if texts.intersection({"正在為您呼叫", "正在為您預約", "取消訂單", "取消订单"}):
            return "calling"
        # 收银台
        cashier_keywords = set(getattr(E, "CASHIER_PAGE_KEYWORDS", ()))
        if texts.intersection(cashier_keywords):
            return "cashier"
        # 安全中心
        if texts.intersection({"安全中心", "緊急聯絡人", "紧急联系人", "999"}):
            return "safety_center"
        # 邮箱设置页（必须同时有输入框 + 保存按钮，区分设置页的邮箱入口）
        has_input = any(self._v150_is_input(n) for n in all_nodes)
        has_save = any("保存" in t or "儲存" in t for t in texts)
        if has_input and has_save and texts.intersection({"郵箱", "邮箱", "Email", "電子郵箱", "电子邮件"}):
            return "email_settings"
        if texts.intersection({"私隱中心", "隐私中心", "平台協議及規則"}):
            return "settings"
        if "iv_setting" in ids or "我的行程" in texts:
            return "mine"
        return "unknown"

    def v150_screenshot(self, name="v150_debug"):
        """截图并保存到 screenshots 目录，文件名前缀为 v150_，自动补 .png 扩展名。"""
        fname = f"v150_{name}_{int(time.time())}"
        if not fname.endswith(".png"):
            fname += ".png"
        self._ios_screenshot(fname)
