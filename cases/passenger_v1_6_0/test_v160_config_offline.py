"""香港乘客端 V1.6.0 配置接入校验测试。

编写时间：2026-11-19
验证 config/JRYG_settings.yaml 中的 v160 与 car_type 配置段能被契约层
正确加载、校验并与内置默认车型保持一致。

覆盖技术方案 7.1（MSE 车型事实与读模型）：
- types 的顺序即车型排序
- code 非空且唯一
- 组合键 id+biz_mode+charge_mode 唯一
- multi_pay_mode 仅 taxi 显式为 true，其他未配置按 false
- disabled 未配置按 false
- mapping、types、images 是同级配置

运行：pytest cases/passenger_v1_6_0/test_v160_config_offline.py -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.JRYG_config import SETTINGS  # noqa: E402
from passenger_android_core.v160.contract import (  # noqa: E402
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    CHARGE_FIXED_PRICE,
    CHARGE_METERED,
    DEFAULT_CAR_TYPES,
    RIDE_HAILING_CODES,
    build_car_type_catalog,
    validate_car_type_config,
)


class TestV160Settings:
    """v160 配置段。"""

    def test_v160_section_exists(self):
        """SETTINGS 中存在 v160 配置段。"""
        assert "v160" in SETTINGS

    def test_grayscale_config(self):
        """灰度配置含开关、agent 范围和最低客户端版本三项。"""
        gray = SETTINGS["v160"]["grayscale"]
        assert "enabled" in gray
        assert "scope_agent_ids" in gray
        assert "min_client_version" in gray

    def test_booking_config(self):
        """预约配置：出发时间入口与取消次数限制均开启，每日上限 5 次。"""
        booking = SETTINGS["v160"]["booking"]
        assert booking["departure_entry_enabled"] is True
        assert booking["cancel_limit_enabled"] is True
        assert booking["daily_cancel_limit"] == 5

    def test_time_range_config(self):
        """预约时间范围配置为 30 分钟至 72 小时（4320 分钟）。"""
        time_range = SETTINGS["v160"]["time_range"]
        assert time_range["min_minutes"] == 30
        assert time_range["max_minutes"] == 72 * 60


class TestCarTypeSettings:
    """car_type 配置段。"""

    def test_car_type_section_exists(self):
        """SETTINGS 中存在 car_type 配置段。"""
        assert "car_type" in SETTINGS

    def test_config_passes_validation(self):
        """实际发布的 car_type 配置通过契约校验，无错误。"""
        errors = validate_car_type_config(SETTINGS)
        assert errors == []

    def test_types_count(self):
        """配置车型数量与内置默认车型数量一致。"""
        assert len(SETTINGS["car_type"]["types"]) == len(DEFAULT_CAR_TYPES)

    def test_types_order_matches_default(self):
        """配置车型顺序与内置默认顺序一致（即展示顺序）。"""
        codes = [t["code"] for t in SETTINGS["car_type"]["types"]]
        assert codes == [e.code for e in DEFAULT_CAR_TYPES]

    def test_ride_hailing_codes_in_config(self):
        """5 个网约车型编码全部在配置中登记。"""
        codes = [t["code"] for t in SETTINGS["car_type"]["types"]]
        for code in RIDE_HAILING_CODES:
            assert code in codes

    def test_multi_pay_mode_only_taxi(self):
        """仅 taxi 显式配置 multi_pay_mode=true，其他车型为 false。"""
        for item in SETTINGS["car_type"]["types"]:
            if item["code"] == "taxi":
                assert item.get("multi_pay_mode") is True
            else:
                assert item.get("multi_pay_mode", False) is False

    def test_mapping_is_sibling_of_types(self):
        """mapping、types、images 三者同级配置。"""
        car_type = SETTINGS["car_type"]
        assert "types" in car_type
        assert "mapping" in car_type
        assert "images" in car_type

    def test_mapping_entries_hit_types(self):
        """mapping 每条记录的组合键都能命中已配置车型。"""
        types = SETTINGS["car_type"]["types"]
        keys = {(t["id"], t["biz_mode"], t["charge_mode"]) for t in types}
        for item in SETTINGS["car_type"]["mapping"]:
            key = (item["id"], item["biz_mode"], item["charge_mode"])
            assert key in keys

    def test_mapping_codes_exist_in_types(self):
        """mapping 每条记录的 code 都能在 types 中找到。"""
        codes = {t["code"] for t in SETTINGS["car_type"]["types"]}
        for item in SETTINGS["car_type"]["mapping"]:
            assert item["code"] in codes


class TestCarTypeCatalogFromConfig:
    """从 YAML 配置构建读模型。"""

    def test_build_catalog_from_config(self):
        """从实际配置构建读模型，得到 7 条车型。"""
        catalog = build_car_type_catalog(SETTINGS)
        assert len(catalog.entries) == 7

    def test_chartered_taxi_from_config(self):
        """配置构建的包車價的士条目字段正确。"""
        catalog = build_car_type_catalog(SETTINGS)
        entry = catalog.require_by_code("chartered_taxi")
        assert entry.id == 1
        assert entry.biz_mode == BUSINESS_TAXI
        assert entry.charge_mode == CHARGE_FIXED_PRICE
        assert entry.multi_pay_mode is False

    def test_taxi_from_config(self):
        """配置构建的打錶的士条目为打表计费且支持多支付方式。"""
        catalog = build_car_type_catalog(SETTINGS)
        entry = catalog.require_by_code("taxi")
        assert entry.charge_mode == CHARGE_METERED
        assert entry.multi_pay_mode is True

    @pytest.mark.parametrize("code,car_type_id", [
        ("economy", 1), ("preferred", 9), ("comfort", 2),
        ("business", 3), ("luxury", 4),
    ])
    def test_ride_hailing_from_config(self, code, car_type_id):
        """配置构建的网约车 5 车型 id 与一口价计费正确。"""
        catalog = build_car_type_catalog(SETTINGS)
        entry = catalog.require_by_code(code)
        assert entry.id == car_type_id
        assert entry.biz_mode == BUSINESS_RIDE_HAILING
        assert entry.charge_mode == CHARGE_FIXED_PRICE

    def test_composite_key_unique_in_config(self):
        """配置构建后组合键仍保持唯一。"""
        catalog = build_car_type_catalog(SETTINGS)
        keys = [e.composite_key for e in catalog.entries]
        assert len(keys) == len(set(keys))

    def test_same_id_not_overwritten(self):
        """配置构建后出租车与网约车同 ID 不互相覆盖。"""
        catalog = build_car_type_catalog(SETTINGS)
        assert catalog.get_by_composite(1, BUSINESS_TAXI,
                                        CHARGE_FIXED_PRICE).code == "chartered_taxi"
        assert catalog.get_by_composite(1, BUSINESS_RIDE_HAILING,
                                        CHARGE_FIXED_PRICE).code == "economy"

    def test_disabled_defaults_false(self):
        """配置未显式禁用任何车型，disabled 默认为 false。"""
        catalog = build_car_type_catalog(SETTINGS)
        for entry in catalog.entries:
            assert entry.disabled is False
