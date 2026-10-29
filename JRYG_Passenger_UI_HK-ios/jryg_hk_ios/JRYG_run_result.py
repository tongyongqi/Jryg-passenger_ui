"""区分收集、跳过、普通通过及有订单完成证据的E2E通过。

核心原则：只有“同一订单、目标司机、已完成且已支付”全部取得证据，
才允许把整轮执行判为通过；仅收集用例、跳过或提前返回一律不算通过。
"""


class E2EResult:
    """pytest 钩子收集器：统计各类用例结果并给出最终结论。"""

    def __init__(self):
        """初始化各类结果计数器，全部从 0 开始统计。"""
        # 普通通过数量（仅统计 call 阶段通过的用例）
        self.passed = 0
        # 跳过数量
        self.skipped = 0
        # 失败数量
        self.failed = 0
        # 带订单完成证据的通过数量
        self.verified = 0

    def pytest_runtest_logreport(self, report):
        """pytest 每阶段结束后回调，累加各类结果计数。

        只在 call 阶段通过才计入 passed，
        避免 setup/teardown 阶段的中间结果污染统计。
        """
        if report.skipped:
            self.skipped += 1
        if report.failed:
            self.failed += 1
        if report.when == "call" and report.passed:
            self.passed += 1
            # order_verified=True 表示该用例完成了订单硬校验
            if dict(report.user_properties).get("order_verified") is True:
                self.verified += 1

    def outcome(self, exit_code, collect_only=False):
        """根据统计结果返回 (退出码, 说明文本)。

        仅收集用例时明确标注“未执行”，不得表述为全部通过。
        任何失败、跳过、未执行或证据数量不匹配都返回非 0 退出码。
        """
        if collect_only:
            # 仅收集模式：没有真正执行真机订单流程
            return int(exit_code), "仅收集用例，未执行真机订单流程"
        if exit_code:
            # pytest 自身报告失败
            return int(exit_code), "执行失败，订单流程未通过"
        if self.failed or self.skipped or not self.passed or self.verified != self.passed:
            # 存在失败/跳过/未执行，或部分通过缺少订单证据，一律不算通过
            return 1, "未获得完整订单校验证据（可能未执行、跳过或提前返回），不得判为通过"
        return 0, "全部通过：同一订单、目标司机、已完成且已支付均已校验"
