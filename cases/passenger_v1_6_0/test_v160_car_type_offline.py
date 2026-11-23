"""香港乘客端 V1.6.0 车型品类契约离线测试。

编写时间：2026-11-19
本期功能：新增网约车运力（经济/优选/舒适/商务/豪华 5 车型）
需求映射：
- 需求 1：即时与预约业务均新增网约车运力，5 种车型；三语名称映射；单选下单
- 技术方案 7.1：MSE 车型事实与读模型（code 唯一、组合键唯一、同 ID 不覆盖）
- 需求 14：车辆图片按司机侧颜色适配，未获取到颜色按运力类型兜底

运行：pytest cases/passenger_v1_6_0/test_v160_car_type_offline.py -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.contract import (  # noqa: E402
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    CAR_TYPE_NAMES,
    CHARGE_FIXED_PRICE,
    CHARGE_METERED,
    DEFAULT_CAR_TYPES,
    RIDE_HAILING_CODES,
    TAXI_CODES,
    CarTypeCatalog,
    CarTypeEntry,
    CarTypeSelection,
    build_estimate_car_types,
    build_car_type_catalog,
    default_vehicle_color,
    localize_car_type,
    payment_collection_mode,
    payment_profile_of,
    resolve_payment_collection_mode,
    validate_car_type_config,
    resolve_vehicle_image,
)


# ===========================================================================
# Section 1：车型三语名称映射（需求 1）
# ===========================================================================
class TestCarTypeNames:
    """车型名称按 PRD 分别映射为繁/简/英三种语言。"""

    def test_five_ride_hailing_types_present(self):
        """网约车 5 车型编码齐全（economy/preferred/comfort/business/luxury）。"""
        assert set(CAR_TYPE_NAMES) == {
            "economy", "preferred", "comfort", "business", "luxury",
        }

    @pytest.mark.parametrize("code,zh_hant,zh_hans,en", [
        ("economy", "經濟型", "经济型", "Economy"),
        ("preferred", "優選型", "优选型", "Preferred"),
        ("comfort", "舒適型", "舒适型", "Comfort"),
        ("business", "商務型", "商务型", "Business"),
        ("luxury", "豪華型", "豪华型", "Luxury"),
    ])
    def test_name_mapping_exact(self, code, zh_hant, zh_hans, en):
        """各车型繁/简/英三语名称与 PRD 逐字一致。"""
        name = CAR_TYPE_NAMES[code]
        assert (name.zh_hant, name.zh_hans, name.en) == (zh_hant, zh_hans, en)

    @pytest.mark.parametrize("language,expected", [
        ("zh-Hant", "經濟型"),
        ("zh-HK", "經濟型"),
        ("zh-TW", "經濟型"),
        ("zh-Hans", "经济型"),
        ("zh-CN", "经济型"),
        ("en", "Economy"),
        ("en-US", "Economy"),
        ("en-GB", "Economy"),
    ])
    def test_localize_by_language(self, language, expected):
        """按语言标识（zh-Hant/zh-HK/zh-TW/zh-Hans/zh-CN/en-*）返回对应语种车型名。"""
        assert localize_car_type("economy", language) == expected

    def test_unknown_code_raises(self):
        """未知车型编码必须报错，不得静默返回默认名。"""
        with pytest.raises(ValueError, match="未知车型编码"):
            localize_car_type("not_exist")

    def test_unsupported_language_raises(self):
        """不支持的语言必须报错，不得静默降级。"""
        with pytest.raises(ValueError, match="不支持的语言"):
            localize_car_type("economy", "fr-FR")


# ===========================================================================
# Section 2：车型条目与读模型（技术方案 7.1）
# ===========================================================================
class TestCarTypeCatalog:
    """types 顺序即车型排序；code 与组合键双索引。"""

    def test_default_entries_count(self):
        """默认车型 7 条：2 个出租车 + 5 个网约车。"""
        assert len(DEFAULT_CAR_TYPES) == 7

    def test_chartered_taxi_entry(self):
        """包車價的士：id=1、biz_mode=出租车、charge_mode=一口价、不支持多支付方式。"""
        entry = CarTypeCatalog().require_by_code("chartered_taxi")
        assert entry.id == 1
        assert entry.biz_mode == BUSINESS_TAXI
        assert entry.charge_mode == CHARGE_FIXED_PRICE
        assert entry.multi_pay_mode is False

    def test_metered_taxi_entry(self):
        """打錶的士：id=1、biz_mode=出租车、charge_mode=打表、支持多支付方式。"""
        entry = CarTypeCatalog().require_by_code("taxi")
        assert entry.id == 1
        assert entry.biz_mode == BUSINESS_TAXI
        assert entry.charge_mode == CHARGE_METERED
        # multi_pay_mode 仅 taxi 显式配置为 true
        assert entry.multi_pay_mode is True

    @pytest.mark.parametrize("code,car_type_id", [
        ("economy", 1),
        ("preferred", 9),
        ("comfort", 2),
        ("business", 3),
        ("luxury", 4),
    ])
    def test_ride_hailing_entries(self, code, car_type_id):
        """网约车 5 车型：各自 id 映射正确，均为一口价、不支持多支付方式。"""
        entry = CarTypeCatalog().require_by_code(code)
        assert entry.id == car_type_id
        assert entry.biz_mode == BUSINESS_RIDE_HAILING
        assert entry.charge_mode == CHARGE_FIXED_PRICE
        assert entry.multi_pay_mode is False

    def test_code_must_be_unique(self):
        """车型 code 全局唯一。"""
        codes = [e.code for e in DEFAULT_CAR_TYPES]
        assert len(codes) == len(set(codes))

    def test_composite_key_must_be_unique(self):
        """组合键 id+biz_mode+charge_mode 唯一。"""
        keys = [e.composite_key for e in DEFAULT_CAR_TYPES]
        assert len(keys) == len(set(keys))

    def test_same_id_different_biz_mode_not_overwritten(self):
        """出租车与网约车同 ID 时不互相覆盖。"""
        catalog = CarTypeCatalog()
        chartered = catalog.get_by_composite(1, BUSINESS_TAXI, CHARGE_FIXED_PRICE)
        economy = catalog.get_by_composite(1, BUSINESS_RIDE_HAILING, CHARGE_FIXED_PRICE)
        assert chartered.code == "chartered_taxi"
        assert economy.code == "economy"

    def test_composite_lookup_missing_returns_none(self):
        """组合键未命中车型时返回 None，不抛异常。"""
        assert CarTypeCatalog().get_by_composite(99, 2, 3) is None

    def test_types_order_is_sort_order(self):
        """types 配置顺序即车型展示顺序：出租车在前，网约车按 PRD 次序。"""
        catalog = CarTypeCatalog()
        codes = [e.code for e in catalog.entries]
        assert codes.index("chartered_taxi") < codes.index("taxi")
        assert codes.index("economy") < codes.index("preferred") < codes.index("comfort")
        assert codes.index("comfort") < codes.index("business") < codes.index("luxury")

    def test_ride_hailing_list_ordered(self):
        """网约车车型列表顺序与 RIDE_HAILING_CODES 一致。"""
        catalog = CarTypeCatalog()
        assert [e.code for e in catalog.ride_hailing_entries()] == list(RIDE_HAILING_CODES)

    def test_taxi_list_ordered(self):
        """出租车车型列表顺序与 TAXI_CODES 一致。"""
        catalog = CarTypeCatalog()
        assert [e.code for e in catalog.taxi_entries()] == list(TAXI_CODES)

    def test_disabled_entry_excluded(self):
        """disabled=true 的车型不出现在可用车型列表中。"""
        entries = list(DEFAULT_CAR_TYPES) + [
            CarTypeEntry(code="off", id=77, biz_mode=2, charge_mode=3,
                         icon="off_icon", disabled=True),
        ]
        catalog = CarTypeCatalog(entries)
        assert "off" not in [e.code for e in catalog.enabled_entries()]

    def test_taxi_display_names(self):
        """出租车车型展示文案：包車價的士/打錶的士/Metered Taxi。"""
        catalog = CarTypeCatalog()
        assert catalog.name_of("chartered_taxi", "zh-Hant") == "包車價的士"
        assert catalog.name_of("taxi", "zh-Hant") == "打錶的士"
        assert catalog.name_of("taxi", "en") == "Metered Taxi"


# ===========================================================================
# Section 3：配置校验（技术方案 7.1）
# ===========================================================================
class TestCarTypeConfigValidation:
    """发布配置必须逐项显式提供 id、code、biz_mode、charge_mode、icon。"""

    def _valid_config(self):
        """构造一份合法的 car_type 配置作为校验基线。"""
        return {
            "car_type": {
                "types": [
                    {"id": 1, "code": "chartered_taxi", "biz_mode": 1,
                     "charge_mode": 3, "icon": "a.png"},
                    {"id": 1, "code": "economy", "biz_mode": 2,
                     "charge_mode": 3, "icon": "b.png"},
                ],
                "images": {},
            }
        }

    def test_valid_config_passes(self):
        """合法配置校验无错误。"""
        assert validate_car_type_config(self._valid_config()) == []

    def test_missing_car_type_config(self):
        """缺少 config.car_type 配置时明确报错。"""
        assert validate_car_type_config({}) == ["缺少 config.car_type 配置"]

    def test_empty_types(self):
        """config.car_type.types 缺失或为空时明确报错。"""
        errors = validate_car_type_config({"car_type": {"types": []}})
        assert errors == ["config.car_type.types 缺失或为空"]

    @pytest.mark.parametrize("missing", ["id", "code", "biz_mode", "charge_mode", "icon"])
    def test_missing_required_field(self, missing):
        """id/code/biz_mode/charge_mode/icon 五项必填字段缺一即报错。"""
        config = self._valid_config()
        del config["car_type"]["types"][0][missing]
        errors = validate_car_type_config(config)
        assert any(missing in e for e in errors)

    def test_duplicate_code_rejected(self):
        """code 重复必须被拒绝。"""
        config = self._valid_config()
        config["car_type"]["types"][1]["code"] = "chartered_taxi"
        errors = validate_car_type_config(config)
        assert any("code 重复" in e for e in errors)

    def test_duplicate_composite_key_rejected(self):
        """组合键重复必须被拒绝。"""
        config = self._valid_config()
        config["car_type"]["types"][1]["id"] = 1
        config["car_type"]["types"][1]["biz_mode"] = 1
        config["car_type"]["types"][1]["charge_mode"] = 3
        errors = validate_car_type_config(config)
        assert any("组合键重复" in e for e in errors)

    def test_mapping_must_hit_existing_type(self):
        """mapping 组合键必须命中已配置车型，否则报错。"""
        config = self._valid_config()
        config["car_type"]["mapping"] = [
            {"id": 99, "biz_mode": 2, "charge_mode": 3, "code": "economy"},
        ]
        errors = validate_car_type_config(config)
        assert any("未命中任何车型" in e for e in errors)

    def test_multi_pay_mode_default_false(self):
        """未配置 multi_pay_mode 时按 false。"""
        config = self._valid_config()
        catalog = build_car_type_catalog(config)
        assert catalog.require_by_code("chartered_taxi").multi_pay_mode is False

    def test_disabled_default_false(self):
        """未配置 disabled 时按 false。"""
        config = self._valid_config()
        catalog = build_car_type_catalog(config)
        assert catalog.require_by_code("economy").disabled is False

    def test_mapping_is_sibling_of_types(self):
        """mapping、types、images 是同级配置。"""
        config = self._valid_config()
        config["car_type"]["images"] = {"economy": "e.png"}
        assert validate_car_type_config(config) == []


# ===========================================================================
# Section 4：单选约束（需求 1）
# ===========================================================================
class TestSingleSelection:
    """车型列表继续仅支持单选下单。"""

    def test_select_one_type(self):
        """选中单一车型后 selected_code/has_selection/is_single 正确。"""
        selection = CarTypeSelection(candidates=["economy", "comfort"])
        selected = selection.select("economy")
        assert selected.selected_code == "economy"
        assert selected.has_selection is True
        assert selected.is_single is True

    def test_switch_selection_overwrites(self):
        """切换车型时覆盖上一次选择，不累积多选。"""
        selection = CarTypeSelection(candidates=["economy", "comfort"])
        selection = selection.select("economy")
        selection = selection.select("comfort")
        assert selection.selected_code == "comfort"

    def test_select_not_in_candidates_raises(self):
        """选择候选之外的车型必须报错。"""
        selection = CarTypeSelection(candidates=["economy"])
        with pytest.raises(ValueError, match="车型不可选"):
            selection.select("luxury")

    def test_clear_selection(self):
        """清空选择后 selected_code 为 None。"""
        selection = CarTypeSelection(candidates=["economy"]).select("economy")
        assert selection.clear().selected_code is None

    def test_selection_is_immutable(self):
        """选择操作不可变：原对象不被修改。"""
        selection = CarTypeSelection(candidates=["economy"])
        selection.select("economy")
        assert selection.selected_code is None


# ===========================================================================
# Section 5：下单支付分流（技术方案 7.2）
# ===========================================================================
class TestPaymentProfile:
    """一口价先付、打表后付；预约不支持优惠券。"""

    def test_chartered_taxi_instant_is_advance(self):
        """包車價的士即时：先付（advance），支持优惠券。"""
        entry = CarTypeCatalog().require_by_code("chartered_taxi")
        profile = payment_profile_of(entry, is_booking=False)
        assert profile.payment_mode == "advance"
        assert profile.support_coupon is True

    def test_metered_taxi_is_after(self):
        """打錶的士即时：后付（after），支持优惠券。"""
        entry = CarTypeCatalog().require_by_code("taxi")
        profile = payment_profile_of(entry, is_booking=False)
        assert profile.payment_mode == "after"
        assert profile.support_coupon is True

    @pytest.mark.parametrize("code", list(RIDE_HAILING_CODES))
    def test_ride_hailing_is_advance(self, code):
        """网约车 5 车型即时：先付（advance），支持优惠券。"""
        entry = CarTypeCatalog().require_by_code(code)
        profile = payment_profile_of(entry, is_booking=False)
        assert profile.payment_mode == "advance"
        assert profile.support_coupon is True

    @pytest.mark.parametrize("code", ["chartered_taxi", "taxi"] + list(RIDE_HAILING_CODES))
    def test_booking_supports_no_coupon(self, code):
        """预约业务全部车型不支持优惠券。"""
        entry = CarTypeCatalog().require_by_code(code)
        profile = payment_profile_of(entry, is_booking=True)
        assert profile.support_coupon is False

    @pytest.mark.parametrize("code", list(RIDE_HAILING_CODES))
    def test_ride_hailing_no_cancel_fee_no_price_adjust(self, code):
        """网约车不支持取消费，不支持多退少补。"""
        entry = CarTypeCatalog().require_by_code(code)
        profile = payment_profile_of(entry, is_booking=False)
        assert profile.support_cancel_fee is False
        assert profile.support_price_adjust is False

    def test_payment_collection_mode_values(self):
        """一口价车型 payment_collection_mode=1，打表车型=2。"""
        catalog = CarTypeCatalog()
        assert payment_collection_mode(catalog.require_by_code("economy")) == 1
        assert payment_collection_mode(catalog.require_by_code("taxi")) == 2

    def test_fixed_price_rejects_offline_payment(self):
        """一口价订单只接受线上预付支付。"""
        with pytest.raises(ValueError, match="仅支持线上预付"):
            resolve_payment_collection_mode("economy", True, False)

    def test_fixed_price_accepts_online_payment(self):
        """一口价车型接受线上支付时 payment_collection_mode=1。"""
        assert resolve_payment_collection_mode("economy", True, True) == 1

    def test_metered_booking_uses_after_payment(self):
        """打表车型无论即时/预约均走线下后付，payment_collection_mode=2。"""
        assert resolve_payment_collection_mode("taxi", True, False) == 2


# ===========================================================================
# Section 6：询价 car_types 入参（技术方案）
# ===========================================================================
class TestEstimateCarTypes:
    """order-service 询价接口的 car_types 入参构造。"""

    def test_build_taxi_car_types(self):
        """出租车询价 car_types：business_type=1。"""
        assert build_estimate_car_types(1, 5, [1, 2]) == [
            {"business_type": 1, "order_type": 5, "car_type_id": [1, 2]},
        ]

    def test_build_ride_hailing_car_types(self):
        """网约车询价 car_types：business_type=2 且 5 个车型 id。"""
        assert build_estimate_car_types(2, 5, [1, 2, 3, 4, 5]) == [
            {"business_type": 2, "order_type": 5, "car_type_id": [1, 2, 3, 4, 5]},
        ]

    def test_booking_order_type_6(self):
        """预约询价 car_types 的 order_type=6。"""
        payload = build_estimate_car_types(2, 6, [1, 2, 3, 4, 5])
        assert payload[0]["order_type"] == 6


# ===========================================================================
# Section 7：车辆图片颜色适配（需求 14）
# ===========================================================================
class TestVehicleImageColor:
    """订单详情车辆图片按司机侧车辆颜色适配。"""

    def test_taxi_default_red(self):
        """出租车未获取到司机侧颜色时兜底为红色车辆图片。"""
        assert resolve_vehicle_image(BUSINESS_TAXI, None) == "vehicle_red"

    def test_ride_hailing_default_white(self):
        """网约车未获取到司机侧颜色时兜底为白色车辆图片。"""
        assert resolve_vehicle_image(BUSINESS_RIDE_HAILING, None) == "vehicle_white"

    def test_taxi_default_color_helper(self):
        """默认颜色辅助函数：出租车 red、网约车 white。"""
        assert default_vehicle_color(BUSINESS_TAXI) == "red"
        assert default_vehicle_color(BUSINESS_RIDE_HAILING) == "white"

    def test_color_applied_for_taxi(self):
        """出租车按司机侧颜色取对应车辆图片资源。"""
        assert resolve_vehicle_image(BUSINESS_TAXI, "white") == "vehicle_white"

    def test_color_applied_for_ride_hailing(self):
        """网约车按司机侧颜色取对应车辆图片资源。"""
        assert resolve_vehicle_image(BUSINESS_RIDE_HAILING, "red") == "vehicle_red"

    def test_color_case_insensitive(self):
        """司机侧颜色大小写不敏感。"""
        assert resolve_vehicle_image(BUSINESS_TAXI, "RED") == "vehicle_red"

    def test_unknown_color_falls_back(self):
        """未知颜色按运力类型兜底，不报错。"""
        assert resolve_vehicle_image(BUSINESS_TAXI, "rainbow") == "vehicle_red"
        assert resolve_vehicle_image(BUSINESS_RIDE_HAILING, "rainbow") == "vehicle_white"

    def test_empty_color_falls_back(self):
        """空颜色按运力类型兜底。"""
        assert resolve_vehicle_image(BUSINESS_RIDE_HAILING, "") == "vehicle_white"
