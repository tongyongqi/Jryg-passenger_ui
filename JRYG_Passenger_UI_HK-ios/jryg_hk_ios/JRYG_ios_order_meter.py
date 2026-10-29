"""打表的士流程：每单必须由11000005接单并完成，才允许执行下一单。

执行顺序说明：
  每个支付场景都是一次独立的“下单 → 绑定 → 完成”闭环，
  上一单未取得完成证据前不会开始下一单。
"""

from jryg_hk_ios.JRYG_ios_base import IOSBase
from jryg_hk_ios.JRYG_order_guard import require


class IOSOrderMeter(IOSBase):
    """打表的士下单模块。"""

    def order_meter_taxi(self, payment_method=None):
        """执行打表下单。

        payment_method 为空时依次执行后付与现金两个场景，
        否则只执行指定场景。返回各场景的完成订单证据列表。
        """
        # 未指定时按默认顺序覆盖两种支付方式
        methods = (payment_method,) if payment_method else ("postpay", "cash")
        results = []
        for method in methods:
            # 每单都走完整硬校验：调用成功才算完成
            results.append(self._run_verified_order(lambda: self._place_verified_meter(method)))
        return results

    def _place_meter_order(self, payment_method="cash"):
        """兼容旧调用方，但不再只提交订单就返回True。"""
        return self.order_meter_taxi(payment_method)[0]

    def _driver_process_order(self):
        """旧司机 UI 滑动流程已停用，直接失败提示改用绑定订单流程。"""
        require(False, "旧司机UI滑动流程已停用，请调用order_meter_taxi的绑定订单流程")

    def _driver_return_home(self):
        """核实订单完成后切到司机端并返回首页。"""
        guard = self._ensure_order_guard()
        # 再次确认完成终态，避免带着未完成订单切页面
        guard.verify_completed(guard.bound_order_no)
        self._activate_app(self.DRIVER_BUNDLE, wait=2)
        require(self.monitor.click_text(self.client, "返回首頁"), "未找到司机返回首页入口")

    def _passenger_check_order_complete(self):
        """切回乘客端确认订单显示完成，并返回完成证据。"""
        guard = self._ensure_order_guard()
        # 接口侧先确认完成
        result = guard.verify_completed(guard.bound_order_no)
        self._activate_app(self.PASSENGER_BUNDLE, wait=2)
        # UI 侧也要显示完成
        self._order_wait("乘客确认订单完成", lambda p: p.state == "order_complete", timeout=30)
        self._capture(f"completed_{result.order_no}")
        return result
