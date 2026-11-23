"""香港乘客端 V1.6.0 计费明细与计价规则契约离线测试。

编写时间：2026-11-19
本期功能：预估详情/费用详情增加计费明细，新增计价规则页
需求映射：
- 需求 2：预估详情、费用详情展示起步价/里程费/时长费/远途费/合计，提供计价规则页
- 需求 3：计价规则区分工作日、休息日和即时、预约业务
- PRD 展示口径：报价及费用最多保留 1 位小数，末尾为 0 时不显示
- 接口：/passenger/charge/rule、/passenger/estimate/detail、/passenger/order/fee

运行：pytest cases/passenger_v1_6_0/test_v160_charge_offline.py -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.charge_contract import (  # noqa: E402
    CURRENCY_HKD,
    DAY_TYPE_RESTDAY,
    DAY_TYPE_WORKDAY,
    FEE_ITEM_CHARTER_TOTAL,
    FEE_ITEM_DISTANCE,
    FEE_ITEM_DURATION,
    FEE_ITEM_LONG_DISTANCE,
    FEE_ITEM_START_FARE,
    FEE_ITEM_TOTAL,
    ChargeRule,
    ChargeRuleDay,
    ChargeRuleItem,
    build_charge_rule_payload,
    build_fee_details,
    charge_rule_business_type,
    charge_rule_request,
    charge_rule_title,
    estimate_detail_payload,
    fee_detail_title,
    fee_item_unit_label,
    fixed_price_amount_text,
    format_amount,
    format_amount_with_unit,
    long_distance_desc,
    order_fee_payload,
    payment_method_visible,
    total_is_pre_discount,
)


# ===========================================================================
# Section 1：金额格式化（PRD 展示口径）
# ===========================================================================
class TestAmountFormat:
    """最多保留 1 位小数，末尾为 0 时不显示。"""

    @pytest.mark.parametrize("value,expected", [
        (18, "18"),
        (18.0, "18"),
        (18.5, "18.5"),
        (16.8, "16.8"),
        (0, "0"),
        (0.0, "0"),
        (0.5, "0.5"),
        (100, "100"),
        (38.13, "38.1"),
        (12.34, "12.3"),
        (12.35, "12.4"),
    ])
    def test_format_amount(self, value, expected):
        """金额最多保留 1 位小数，四舍五入，末尾为 0 时不显示。"""
        assert format_amount(value) == expected

    def test_format_amount_with_unit(self):
        """带币种单位的金额文案：18.0 → "18 HKD"。"""
        assert format_amount_with_unit(18.0) == "18 HKD"

    def test_fixed_price_amount_text(self):
        """一口价金额文案前缀为「一口價」。"""
        assert fixed_price_amount_text(16.8) == "一口價16.8 HKD"

    def test_fixed_price_amount_text_trailing_zero(self):
        """一口价金额末尾为 0 时不显示小数位。"""
        assert fixed_price_amount_text(18.0) == "一口價18 HKD"

    def test_none_raises(self):
        """None 金额必须报错，不得当作 0 处理。"""
        with pytest.raises(ValueError):
            format_amount(None)

    def test_empty_string_raises(self):
        """空字符串金额必须报错。"""
        with pytest.raises(ValueError):
            format_amount("")

    def test_invalid_raises(self):
        """非数字金额必须报「金额非法」。"""
        with pytest.raises(ValueError, match="金额非法"):
            format_amount("abc")


# ===========================================================================
# Section 2：费项明细（需求 2）
# ===========================================================================
class TestFeeDetails:
    """预估详情/费用详情的 fee_details 结构。"""

    FEE_MAP = {
        FEE_ITEM_START_FARE: 23.0,
        FEE_ITEM_DISTANCE: 42.6,
        FEE_ITEM_DURATION: 8.4,
        FEE_ITEM_LONG_DISTANCE: 0,
        FEE_ITEM_TOTAL: 74.0,
    }

    def test_fee_details_contains_all_items(self):
        """费项明细按起步价/里程费/时长费/远途费/合计顺序完整输出。"""
        details = build_fee_details(self.FEE_MAP)
        titles = [d["title"] for d in details]
        assert titles == [
            FEE_ITEM_START_FARE, FEE_ITEM_DISTANCE, FEE_ITEM_DURATION,
            FEE_ITEM_LONG_DISTANCE, FEE_ITEM_TOTAL,
        ]

    def test_fee_details_values_formatted(self):
        """费项金额按展示口径格式化后输出。"""
        details = {d["title"]: d["value"] for d in build_fee_details(self.FEE_MAP)}
        assert details[FEE_ITEM_START_FARE] == "23"
        assert details[FEE_ITEM_DISTANCE] == "42.6"
        assert details[FEE_ITEM_TOTAL] == "74"

    def test_missing_item_skipped(self):
        """缺失的费项直接跳过，不输出空项。"""
        details = build_fee_details({FEE_ITEM_START_FARE: 23.0})
        assert len(details) == 1

    def test_total_is_pre_discount(self):
        """合计为优惠前总计。"""
        assert total_is_pre_discount(self.FEE_MAP) is True

    def test_estimate_detail_payload_structure(self):
        """预估详情出参含 order_type=5 及费项列表。"""
        payload = estimate_detail_payload(5, self.FEE_MAP)
        assert payload["order_type"] == 5
        assert payload["order_type_name"] == "即時用車"
        assert isinstance(payload["fee_details"], list)

    def test_order_fee_payload_structure(self):
        """订单费用详情出参含 order_type=6（预约）。"""
        payload = order_fee_payload(6, self.FEE_MAP)
        assert payload["order_type"] == 6
        assert payload["order_type_name"] == "預約用車"

    def test_booking_chartered_total_renamed(self):
        """包车费名称在预约业务调整为「總車費」。"""
        details = build_fee_details(self.FEE_MAP, order_type=6, is_chartered=True)
        titles = [d["title"] for d in details]
        assert FEE_ITEM_CHARTER_TOTAL in titles
        assert FEE_ITEM_TOTAL not in titles

    def test_instant_chartered_total_not_renamed(self):
        """即时业务包车费名称保持「合計」，不做重命名。"""
        details = build_fee_details(self.FEE_MAP, order_type=5, is_chartered=True)
        titles = [d["title"] for d in details]
        assert FEE_ITEM_TOTAL in titles
        assert FEE_ITEM_CHARTER_TOTAL not in titles

    def test_title_estimate(self):
        """预估详情页标题：{车型名}-預估詳情。"""
        assert fee_detail_title("經濟型", True) == "經濟型-預估詳情"

    def test_title_fee(self):
        """费用详情页标题：{车型名}-費用詳情。"""
        assert fee_detail_title("經濟型", False) == "經濟型-費用詳情"

    def test_payment_method_only_in_fee_page(self):
        """支付方式仅在费用详情页展示，预估详情页不展示。"""
        assert payment_method_visible(is_estimate=True) is False
        assert payment_method_visible(is_estimate=False) is True


# ===========================================================================
# Section 3：计价规则（需求 3）
# ===========================================================================
class TestChargeRule:
    """计价规则区分工作日、休息日以及即时、预约业务。"""

    def _rule(self, order_type=5):
        """构造含工作日/休息日两段的示例计价规则。"""
        return ChargeRule(
            car_type="economy",
            car_type_name="經濟型",
            car_type_img="economy.png",
            order_type=order_type,
            order_type_name="即時用車" if order_type == 5 else "預約用車",
            rules=[
                ChargeRuleDay(
                    day_type=DAY_TYPE_WORKDAY,
                    day_type_name="工作日",
                    items=[
                        ChargeRuleItem(FEE_ITEM_START_FARE, "含5公里 10分鐘", "23"),
                        ChargeRuleItem(FEE_ITEM_DISTANCE, "普通時段 00:00-10:00", "2.5/公里"),
                        ChargeRuleItem(FEE_ITEM_DURATION, "普通時段 00:00-10:00", "1.2/分鍾"),
                        ChargeRuleItem(FEE_ITEM_LONG_DISTANCE, "超过50公里", "3/公里"),
                    ],
                ),
                ChargeRuleDay(
                    day_type=DAY_TYPE_RESTDAY,
                    day_type_name="休息日",
                    items=[
                        ChargeRuleItem(FEE_ITEM_START_FARE, "含5公里 10分鐘", "28"),
                    ],
                ),
            ],
        )

    def test_payload_structure(self):
        """计价规则出参含车型信息、业务类型和规则段共 6 个字段。"""
        payload = build_charge_rule_payload(self._rule())
        assert set(payload) == {
            "car_type", "car_type_name", "car_type_img",
            "order_type", "order_type_name", "rules",
        }

    def test_payload_rules_structure(self):
        """规则段结构：day_type/day_type_name/items，item 含 title/desc/value。"""
        payload = build_charge_rule_payload(self._rule())
        day = payload["rules"][0]
        assert set(day) == {"day_type", "day_type_name", "items"}
        assert set(day["items"][0]) == {"title", "desc", "value"}

    def test_workday_and_restday_both_present(self):
        """工作日与休息日两段规则同时返回。"""
        payload = build_charge_rule_payload(self._rule())
        day_types = [d["day_type"] for d in payload["rules"]]
        assert DAY_TYPE_WORKDAY in day_types
        assert DAY_TYPE_RESTDAY in day_types

    def test_day_rule_lookup(self):
        """按 day_type 查找对应规则段，未知类型返回 None。"""
        rule = self._rule()
        assert rule.day_rule(DAY_TYPE_WORKDAY) is not None
        assert rule.day_rule(DAY_TYPE_RESTDAY) is not None
        assert rule.day_rule("unknown") is None

    def test_business_type_display(self):
        """计价规则页业务类型文案：5=即時用車、6=預約用車。"""
        assert charge_rule_business_type(5) == "即時用車"
        assert charge_rule_business_type(6) == "預約用車"

    def test_title(self):
        """计价规则页标题：{车型名}-計價規則。"""
        assert charge_rule_title("經濟型") == "經濟型-計價規則"

    def test_request_by_estimate_id(self):
        """计价规则入参支持 estimate_id。"""
        assert charge_rule_request(estimate_id="abc") == {"estimate_id": "abc"}

    def test_request_by_order_no(self):
        """计价规则入参支持 order_no。"""
        assert charge_rule_request(order_no="TH26B6PIEWECN") == {"order_no": "TH26B6PIEWECN"}

    def test_request_requires_one(self):
        """estimate_id 与 order_no 必须至少提供一个。"""
        with pytest.raises(ValueError, match="estimate_id 或 order_no"):
            charge_rule_request()

    @pytest.mark.parametrize("title,expected", [
        (FEE_ITEM_START_FARE, ""),
        (FEE_ITEM_DISTANCE, "/公里"),
        (FEE_ITEM_DURATION, "/分鍾"),
        (FEE_ITEM_LONG_DISTANCE, "/公里"),
    ])
    def test_fee_item_unit_label(self, title, expected):
        """费项单位后缀：里程费/远途费为「/公里」，时长费为「/分鍾」。"""
        assert fee_item_unit_label(title) == expected


# ===========================================================================
# Section 4：远途费公里段（需求 2 / 计价规则页）
# ===========================================================================
class TestLongDistanceDesc:
    """远途费公里段展示。"""

    def test_with_max_km(self):
        """远途费有最大公里时展示区间：超过50公里-100公里。"""
        assert long_distance_desc(50, 100) == "超过50公里-100公里"

    def test_without_max_km(self):
        """远途费无最大公里时只展示「超过50公里」。"""
        assert long_distance_desc(50) == "超过50公里"

    def test_with_none_max_km(self):
        """最大公里为 None 时按无上界处理。"""
        assert long_distance_desc(50, None) == "超过50公里"

    def test_decimal_km_trimmed(self):
        """公里数为小数时不显示小数位。"""
        assert long_distance_desc(50.0, 100.0) == "超过50公里-100公里"

    def test_currency_constant(self):
        """币种固定为 HKD。"""
        assert CURRENCY_HKD == "HKD"
