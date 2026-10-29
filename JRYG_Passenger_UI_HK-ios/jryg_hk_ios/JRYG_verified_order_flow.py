"""乘客UI下单与订单接口硬校验的编排，不凭点击成功推断订单成功。

流程主线：
  1. 打开 App、UI 登录并核实账号（见 ios_open_app / ios_login）。
  2. 首页起点输入框 → 输入“北角地铁站” → 选中并确认起点已生效。
  3. 点击“想去哪裡？”→ 输入终点 → 报价页核对起终点。
  4. 选择车型与支付方式 → 确认呼叫。
  5. 由 OrderGuard 绑定该订单，核实目标司机接单、完成终态。

核心原则：
  - 起点未确认前不允许进入终点输入。
  - 任何“点击成功”都不等于订单成功，必须以接口证据为准。
"""

import math
import os
import time
from decimal import Decimal, InvalidOperation

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_order_api import HKOrderAPI
from jryg_hk_ios.JRYG_order_guard import OrderGuard, number, require
from jryg_hk_ios.JRYG_logger import logger


class VerifiedOrderFlow:
    """下单流程编排：UI 操作 + 订单接口硬校验。"""

    def _order_wait(self, description, predicate, timeout, recover=None):
        """等待页面条件成立，且等待时长受订单总时限约束。

        超时时间取「页面等待上限」与「订单剩余总时限」的较小值。
        """
        guard = self._ensure_order_guard()
        return self.monitor.wait_for(description, predicate,
                                     timeout=min(timeout, guard.remaining()),
                                     recover=recover or self._recover_blocking_popup)

    def _recover_blocking_popup(self, page):
        """等待过程中弹出隐私协议/权限/活动弹窗时自动处理，避免等待超时。"""
        if page.state == "privacy_agreement":
            if self._click_text("同意"):
                logger.info("  >> 等待期间已同意隐私协议")
                time.sleep(2)
        elif page.state == "permission_dialog":
            if not self._click_text("去授權"):
                self._click_text("去授权")
            time.sleep(1)
            try:
                # 系统级弹窗可能需要额外确认
                self.client.alert.accept()
            except Exception:
                pass
            time.sleep(2)
        elif page.state == "activity_popup":
            logger.info("  >> 等待期间关闭活动弹窗")
            self.monitor.dismiss_activity_popup(self.client)

    def _ensure_order_guard(self):
        """懒加载订单校验器，确保整个流程共享同一个校验器实例。"""
        if getattr(self, "order_guard", None) is None:
            config = SETTINGS.get("order_validation", {})
            api = HKOrderAPI.from_environment()
            try:
                self.order_guard = OrderGuard(
                    api, config.get("start_names", ["北角(地鐵站)", "北角地鐵站"]),
                    config.get("end_names", ["香港大學"]),
                    max_attempts=int(config.get("max_attempts", 5)),
                    dispatch_timeout=float(config.get("dispatch_timeout", 90)),
                    state_timeout=float(config.get("state_timeout", 30)),
                    completion_timeout=float(config.get("completion_timeout", 90)),
                    total_timeout=float(config.get("total_timeout", 900)),
                )
                # 先确认当前没有未完成订单，作为后续重下单的前提
                self.order_guard.unfinished()
            except Exception:
                # 初始化失败要关闭连接，避免句柄泄漏
                api.close()
                raise
        return self.order_guard

    def _passenger_account_page(self):
        """仅通过UI检查登录，不建立API会话或退出账号。

        首页（home_unlogged）和已登录个人中心（mine_logged）都视为已验证状态，
        避免在首页和个人中心之间来回切换。
        """
        # 最多 8 轮，用于处理弹窗与跳转
        for _ in range(8):
            page = self._passenger_ready()
            # 必须是乘客端 App，避免误操作其它 App
            require(page.root.get("bundleId") == self.PASSENGER_BUNDLE, "前台不是乘客App，停止登录操作")
            # 这些状态都说明账号/页面已核实，无需继续
            if page.state in ("mine_logged", "mine_unlogged", "login_phone_input",
                              "login_code_input", "home_unlogged", "route_selected",
                              "order_active", "order_complete", "order_cancelled"):
                return page
            if page.state == "privacy_agreement":
                # 同意隐私协议后才能继续
                require(self._click_text("同意"), "无法点击隐私协议「同意」")
                logger.info("已同意隐私协议，继续核实乘客账号")
                time.sleep(2)
                continue
            if page.state == "permission_dialog":
                # 授予权限并接受系统弹窗
                if not self._click_text("去授權"):
                    self._click_text("去授权")
                time.sleep(1)
                try:
                    self.client.alert.accept()
                except Exception:
                    pass
                time.sleep(2)
                continue
            if page.state == "activity_popup":
                # 关闭活动弹窗
                self.monitor.dismiss_activity_popup(self.client)
                continue
            if page.state == "unknown":
                # 可能是页面加载中或弹框遮挡，等待重试
                time.sleep(1)
                continue
            # 其它状态尝试退出当前页，回到可核实状态
            require(self.monitor.click_text(self.client, "我的", "slm_icon_navi_arrow_left",
                                            "icon pay alert close", "slm icon lbs search back"),
                    "无法通过UI核实乘客账号，停止下单")
        require(False, "核实真机乘客账号超时")

    def _verify_passenger_account(self):
        """核实当前登录的是测试账号，并回到首页准备下单。"""
        page = self._passenger_account_page()
        # 如果当前不在个人中心，先跳到个人中心核实账号
        if page.state != "mine_logged":
            logger.info("  >> 跳转到个人中心核实乘客账号")
            self._click_text("我的")
            page = self._order_wait("个人中心", lambda p: p.state in ("mine_logged", "mine_unlogged"),
                                   timeout=15)
        require(page.state == "mine_logged", "App UI登录尚未成功")
        # 必须是目标测试账号，否则禁止操作订单
        require(page.matches_account(self.PHONE_NUMBER), "真机乘客账号不是测试账号，禁止操作订单")
        logger.info("  >> 乘客账号核实通过，回到首页")
        # 核实完后回到首页，关闭弹框
        self._goto_home_and_dismiss_popups()

    def _run_verified_order(self, place_order):
        """执行一轮完整下单：UI 下单 → 绑定订单 → 推进完成 → UI 显示完成。"""
        guard = self._ensure_order_guard()
        # guard.run 负责绑定新订单、等待目标司机、调用完成回调并验证终态
        result = guard.run(place_order, self._finish_bound_order, self._prepare_order_route)
        # 回到乘客端，确认 App 侧也显示完成且不再等待司机
        self._activate_app(self.PASSENGER_BUNDLE, wait=2)
        self._order_wait(
            "乘客端显示完成且不再等待司机",
            lambda p: p.root.get("bundleId") == self.PASSENGER_BUNDLE and
            p.state == "order_complete", timeout=30)
        self._capture(f"completed_{result.order_no}")
        return result

    def _finish_bound_order(self, no):
        """推进已绑定订单到完成终态：核对路线 → 逐步更新服务状态 → 确认收款。"""
        guard = self.order_guard
        # 再次确认订单号与目标司机一致
        guard.require_target(no)
        api = guard.api
        detail = api.service_detail(no)
        order = detail["order"]
        # 司机端订单的起终点必须与本轮 UI 选择的一致
        require(order.get("start_address") in guard.start_names and
                order.get("end_address") in guard.end_names, "司机订单路线与乘客下单路线不一致")
        coordinates = {}
        for key in ("start_lat", "start_lng", "end_lat", "end_lng"):
            try:
                coordinates[key] = float(order[key])
            except (KeyError, ValueError, TypeError):
                # 缺少坐标就不能上报服务状态
                require(False, f"服务详情缺少有效坐标 {key}")
            # 纬度限 ±90，经度限 ±180
            limit = 90 if key.endswith("lat") else 180
            require(math.isfinite(coordinates[key]) and abs(coordinates[key]) <= limit,
                    f"服务坐标无效 {key}")
        current = number(detail["service"].get("service_status"), "service_status")
        # 服务状态只能是 0~4，已知状态才继续推进
        require(0 <= current <= 4, "未知服务状态，不能跳步或直接确认收款")
        # 从当前状态逐步推进到 4（到达目的地），不跳步
        for step in range(current + 1, 5):
            guard.require_target(no)
            # step 4 是到达终点，其余为到达上车点
            point = "end" if step == 4 else "start"
            guard.remaining()
            api.service_change(no, step, coordinates[f"{point}_lat"], coordinates[f"{point}_lng"])
            # 轮询确认服务端状态已更新
            detail = guard.poll(
                f"确认司机服务状态{step}", lambda: api.service_detail(no),
                lambda data: number(data["service"].get("service_status"), "service_status") == step,
                guard.state_timeout)
            logger.info("已核实司机11000005 order_no=%s service_status=%s", no, step)
            if step == 4:
                # 服务端要求到达后等待 20 秒才能继续流转
                logger.info("到达目的地(status=4)后需等待20秒方可继续流转")
                guard.remaining()
                guard.sleep(20)
        if self.current_scenario == "charter":
            # 包车为预付订单，脚本不代替用户付款，只核实已完成/已支付结果
            logger.info("包车预付订单保留服务端金额，仅查询已完成/已支付结果")
            return
        guard.require_target(no)
        require(self.current_scenario in ("cash", "postpay"), "缺少本次计价与支付方式证据")
        try:
            amount = Decimal(str(self.FARE_AMOUNT))
        except InvalidOperation:
            require(False, "测试车费不是有效金额")
        require(amount.is_finite() and amount > 0, "测试车费必须大于0")
        guard.remaining()
        api.confirm_bill(no, amount)
        if self.current_scenario == "cash":
            # 现金单：确认收款后再把服务状态推进到 5（完成）
            guard.require_target(no)
            guard.remaining()
            api.service_change(no, 5, coordinates["end_lat"], coordinates["end_lng"])
        else:
            # 后付单必须由乘客真实支付，不能用确认收款替代
            logger.info("后付订单等待乘客实际支付，不能用现金确认收款替代电子支付")

    def _passenger_ready(self):
        """确保乘客端在前台并返回当前页面快照。"""
        if not self._is_app_running(self.PASSENGER_BUNDLE):
            self._activate_app(self.PASSENGER_BUNDLE, wait=2)
        return self.monitor.inspect()

    def _prepare_order_route(self):
        """登录及账号核验后准备路线，不在此方法中提交订单。

        必须从首页起点输入框选择北角地铁站，核实起点栏已生效后，
        才能进入终点搜索；最后核对报价页的起终点。
        起点入口不唯一、起点未确认或页面不符合预期时，不继续下单。
        """
        guard = self._ensure_order_guard()
        # 未完成订单必须先清除，防止在旧单仍有效时准备重复下单。
        require(not guard.unfinished(), "未完成订单尚未清除，禁止重下")
        # 最多 15 轮，用于处理弹窗与页面跳转
        for _ in range(15):
            page = self._passenger_ready()
            # 每次进入新页面先关闭可能弹出的城市/活动弹框
            if page.state == "activity_popup":
                self.monitor.dismiss_activity_popup(self.client)
                continue
            if page.state == "privacy_agreement":
                self._click_text("同意")
                time.sleep(2)
                continue
            if page.state == "permission_dialog":
                if not self._click_text("去授權"):
                    self._click_text("去授权")
                time.sleep(1)
                try:
                    self.client.alert.accept()
                except Exception:
                    pass
                time.sleep(2)
                continue
            if page.state == "unknown":
                # 可能有广告/弹窗遮挡，尝试关闭后再检查
                self._dismiss_home_popups()
                time.sleep(1)
                continue
            # 城市切换弹框：含取消/确认且不是呼叫页
            if page.has("取消", "取消") and page.has("確認", "确认", "确定") and \
               not page.has("確認呼叫", "确认呼叫"):
                logger.info("  >> 路线准备期间检测到城市弹框，点击确认")
                if not self._click_text("確認"):
                    self._click_text("确认")
                time.sleep(2)
                continue
            if page.state == "route_selected":
                # 旧报价即使地址相同，也不能替代本轮从首页选择并确认起点。
                require(self.monitor.click_text(self.client, "slm_icon_navi_arrow_left"),
                        "旧路线无法返回首页设置起点，停止下单")
                continue
            if page.state == "home_unlogged":
                # home_unlogged 是首页页面分类，不代表此处需要重新登录。
                entry = self._home_origin_entry(page)
                # 起点入口必须唯一，否则不能确定点击目标
                require(entry is not None, "无法唯一识别首页起点输入框，禁止点击终点或定位按钮")
                origin, _ = entry
                logger.info("点击首页起点输入框，输入：%s", self.START_ADDRESS)
                # 点击当前页面元素的中心，而不是固定坐标或地图定位按钮。
                self.client.click(int(float(origin.get("x", 0)) + float(origin.get("width")) / 2),
                                  int(float(origin.get("y", 0)) + float(origin.get("height")) / 2))
                # 等待进入起点搜索页（存在输入框与起点标记）
                self._order_wait("起点搜索", lambda p: p.has_type("TextField") and
                                 p.has("slm_icon_search_start_dot"), timeout=15)
                self._select_address(self.START_ADDRESS, guard.start_names, "slm_icon_search_start_dot")
                # 点击搜索结果不等于起点生效；必须返回首页并核对起点栏地址。
                self._order_wait("首页起点确认为北角地铁站", self._home_origin_confirmed, timeout=20)
                self._capture("verified_origin")

                # 起点确认后才能点击终点输入框
                logger.info("起点已确认，点击终点输入框，输入：%s", self.DEST_ADDRESS)
                require(self.monitor.click_text(self.client, "想去哪裡？"), "未找到首页终点输入框")
                # 缺少起点的提示也结束等待，随后明确报错，不能当作进入搜索页成功。
                page = self._order_wait(
                    "终点搜索", lambda p: p.has("請先輸入起點", "请先输入起点") or
                    (p.has_type("TextField") and p.has("slm_icon_search_end_dot")), timeout=15)
                # 出现“请先输入起点”说明起点未真正生效，立即失败且不重复点击
                require(not page.has("請先輸入起點", "请先输入起点"),
                        "App提示请先输入起点，停止输入终点，不再重复点击")
                self._select_address(self.DEST_ADDRESS, guard.end_names, "slm_icon_search_end_dot")
                page = self._order_wait("新路线报价", lambda p: p.state == "route_selected", timeout=25)
                # 报价页出现不代表路线正确，仍需同时核对起点与终点。
                require(page.has(*guard.start_names) and page.has(*guard.end_names), "起终点核实失败")
                self._capture("verified_route")
                return
            # 其它页面尝试退出，回到首页继续
            if self.monitor.click_text(self.client, "icon pay alert close", "主頁", "返回首頁",
                                       "slm_icon_navi_arrow_left", "重新下單", "slm icon lbs search back"):
                time.sleep(1)
                continue
            require(False, f"无法安全回到报价页，当前state={page.state}")
        require(False, "返回报价页超时，禁止盲点确认呼叫")

    def _home_origin_entry(self, page):
        """返回唯一的（起点按钮，所属起点栏）；无法唯一识别时返回 None。

        选择器依据已保存的 iOS 首页结构：滚动区域内宽度大于 100 的可见匿名按钮。
        定位按钮有名称、地图气泡不在此滚动区域内，均不作为起点输入框。
        """
        # 只在首页识别起点入口
        if page.state != "home_unlogged":
            return None
        # 建立 子节点 -> 父节点 映射，用于向上检查可见性
        parents = {child: parent for parent in page.root.iter() for child in parent}
        entries = []
        # 首页滚动区域内的匿名按钮才是候选起点入口
        for node in page.root.findall(".//XCUIElementTypeScrollView//XCUIElementTypeButton"):
            # 过滤不可见、禁用、有名字（定位按钮）、尺寸异常的控件
            if (node.get("visible") != "true" or node.get("enabled", "true") == "false"
                    or node.get("label") or node.get("name")
                    or float(node.get("width", 0)) <= 100 or float(node.get("height", 0)) <= 0):
                continue
            # 子按钮标为可见仍不够；隐藏父容器下的缓存控件不能点击。
            ancestor = parents.get(node)
            while ancestor is not None and ancestor.get("visible", "true") != "false":
                ancestor = parents.get(ancestor)
            if ancestor is None:
                # ancestor 为 None 说明祖先全部可见，可以作为候选
                entries.append((node, parents[node]))
        # 多个候选意味着定位有歧义，不能默认点击第一个。
        return entries[0] if len(entries) == 1 else None

    def _home_origin_confirmed(self, page):
        """核实已返回首页，且起点栏显示允许的北角地铁站名称。

        已保存截图中起点文字可见，但对应 XML 将文字标为不可见，
        因此只在已识别的可见起点栏内读取这类文字，不全局放开隐藏节点。
        此校验不是点击独立的“确认起点”按钮，也不以搜索框或历史记录为依据。
        """
        # 未回到首页或仍提示缺少起点，都不算确认
        if not page.has("想去哪裡？") or page.has("請先輸入起點", "请先输入起点"):
            return False
        entry = self._home_origin_entry(page)
        if entry is None:
            return False
        _, row = entry
        # 兼容“從/从”和空格差异，保留完整地址匹配，避免接受“北角地铁站附近”。
        accepted = {prefix + "".join(name.split())
                    for prefix in ("從", "从") for name in self.order_guard.start_names}
        # 只读取起点栏内的文本节点
        return any("".join(node.get(key, "").split()) in accepted
                   for node in row for key in ("label", "name", "value"))

    def _select_address(self, query, accepted, marker):
        """在指定类型的搜索页输入地址，并点击名称精确匹配的可见结果。

        query 为搜索关键字，accepted 为允许的结果名称，marker 区分起点与终点。
        此方法只负责搜索和选中，选中后的首页起点确认由调用方另行校验。
        """
        page = self.monitor.inspect()
        if marker == "slm_icon_search_end_dot":
            # 页面可能在等待结束后变化，输入终点前再次检查缺少起点的提示。
            require(not page.has("請先輸入起點", "请先输入起点"),
                    "App提示请先输入起点，停止输入终点")
        # 页面标记必须与目标一致，防止在错误页面输入
        require(page.has(marker), "起终点输入框类型不匹配")
        field = self.client(type="TextField")
        require(field.exists, "地址输入框不存在")
        field.set_text(query)
        time.sleep(1.5)  # 等待输入完成，避免 set_text 丢字

        def result_nodes(page):
            """只接受可见、未禁用且名称完全匹配的文本结果，不默认选择首条地址。"""
            return [n for n in page.nodes if n.tag.endswith("StaticText") and
                    n.get("label") in accepted and n.get("enabled", "true") != "false"]

        # 输入后需主动触发搜索：优先点「搜索」按钮，否则等待联想结果
        page = self.monitor.inspect()
        if not result_nodes(page):
            if self.monitor.click_text(self.client, "搜尋", "搜索"):
                logger.info("已触发搜索按钮: %s", query)
                time.sleep(1.5)

        # 等待精确匹配的结果出现
        page = self._order_wait("精确地址搜索结果", lambda p: bool(result_nodes(p)), timeout=25)
        node = result_nodes(page)[0]
        # 点击结果文本中心
        self.client.click(int(float(node.get("x", 0)) + float(node.get("width", 0)) / 2),
                          int(float(node.get("y", 0)) + float(node.get("height", 0)) / 2))

    def _place_verified_meter(self, payment_method):
        """打表场景：核实路线 → 选车型 → 选支付方式 → 确认呼叫。"""
        require(payment_method in ("cash", "postpay"), "不支持的打表支付方式")
        # 记录本次场景，供完成阶段决定确认收款方式
        self.current_scenario = payment_method
        self.order_guard.remaining()
        page = self.monitor.inspect()
        guard = self.order_guard
        # 下单前必须再次核实报价页路线
        require(page.state == "route_selected" and page.has(*guard.start_names) and
                page.has(*guard.end_names), "下单前必须核实路线")
        # 选择打表的士车型
        require(self.monitor.click_text(self.client, "打錶的士"), "打表车型不存在")
        page = self._order_wait("打表支付入口", lambda p: p.has("可選服務：本次已選擇"), timeout=15)
        # 从入口文本中取出完整条目名称再点击，避免匹配到不完整文案
        entry = next((t for t in page.texts if t.startswith("可選服務：本次已選擇")), None)
        require(entry and self.monitor.click_text(self.client, entry), "未找到支付入口")
        self._order_wait("支付方式弹窗", lambda p: p.has("請選擇本單支付方式"), timeout=15)
        # 现金 / 电子支付
        label = "現金支付" if payment_method == "cash" else "電子支付"
        require(self.monitor.click_text(self.client, label), "未找到指定支付方式")
        require(self.monitor.click_text(self.client, "確認選擇"), "未确认支付方式")
        expected = f"可選服務：本次已選擇{label}，請行程結束後支付"
        # 等待车型与支付方式都落到页面上
        page = self._order_wait("确认车型和支付", lambda p: p.state == "route_selected" and p.has(expected), timeout=20)
        # 提交前路线不能变化
        require(page.has(*guard.start_names) and page.has(*guard.end_names), "提交前路线已变化")
        self._capture(f"verified_{payment_method}_before_call")
        guard.remaining()
        # 点击确认呼叫；此处只代表提交，不代表下单成功
        require(self.monitor.click_text(self.client, "確認呼叫"), "未点击到呼叫按钮")
        logger.info("仅已点击呼叫，尚未判定下单或完成成功")

    def _place_verified_charter(self):
        """包车场景：核实路线 → 选包车价车型 → 确认呼叫 → 等待预付页。"""
        # 记录本次场景
        self.current_scenario = "charter"
        self.order_guard.remaining()
        require(self.monitor.click_text(self.client, "包車價的士"), "包车价车型不存在")
        self.order_guard.remaining()
        require(self.monitor.click_text(self.client, "確認呼叫"), "包车价呼叫入口不存在")
        self._order_wait("包车价预付页面", lambda p: p.has("預付車費"), timeout=20)
        # 包车预付需人工完成支付，脚本不代替付款
        logger.warning("包车预付需在真机核对金额并完成指定钱包/银行卡支付；"
                       "脚本不重复付款、不以跳转成功代替支付成功，超时即失败")
        self._order_wait(
            "人工确认包车价支付并返回当前订单",
            lambda p: p.root.get("bundleId") == self.PASSENGER_BUNDLE and p.state == "order_active",
            timeout=120)

    def _order_scenarios(self):
        """根据环境变量决定本轮要执行的下单场景。"""
        choice = os.environ.get("HK_IOS_ORDER_SCENARIO", "full")
        require(choice in ("full", "charter", "cash", "postpay"),
                "HK_IOS_ORDER_SCENARIO只支持full/charter/cash/postpay")
        # full 表示依次执行包车、后付、现金三个场景
        return ("charter", "postpay", "cash") if choice == "full" else (choice,)
