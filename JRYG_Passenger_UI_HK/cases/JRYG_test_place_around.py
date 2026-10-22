"""测试用例：/map-service/v2/place 周围搜索接口验证。

测试场景：
  TC1:  place_type=1 时走周围搜索逻辑
  TC2:  place_type=1 时 language 透传至高德 /v3/place/around（language=trd）
  TC3:  [质检] place_type 非法或缺失时路由逻辑 [待确认]
  TC4:  /v3/place/around 请求参数 language=trd
  TC5:  返回结果 name/pname/cityname/adname/address 为繁体中文
  TC6:  返回文案与高德 /v3/place/around language=trd 对应字段一致
  TC7:  /v3/place/around 请求参数 language=en
  TC8:  返回结果 name/cityname/address 为英文
  TC9:  [质检] pname/adname 保持高德原始返回值
  TC10: 周围搜索保持默认简体中文

前置条件：
  1. mitmdump 已启动并加载 JRYG_mitm_proxy.py（端口 8080）
  2. App 已通过 /map-service/v2/place 发起周围搜索请求（place_type=1）
  3. 高德 /v3/place/around 下游请求已被捕获

运行方式：
  pytest -v -s JRYG_Passenger_UI_HK/cases/JRYG_test_place_around.py
"""

import pytest

from JRYG_Passenger_UI_HK.common.JRYG_place_verifier import (
    print_verification_report,
    verify_place_type_around,
    verify_language_passthrough,
    verify_place_type_routing,
    verify_around_language_trd,
    verify_around_response_traditional,
    verify_around_response_matches_amap_trd,
    verify_around_language_en,
    verify_around_response_english,
    verify_pname_adname_not_converted,
    verify_around_default_simplified,
)


class TestPlaceAroundSearch:
    """/map-service/v2/place 周围搜索接口测试"""

    @pytest.fixture(autouse=True, scope="class")
    def setup_captures(self):
        """测试类初始化：保留 mitmdump 捕获的数据，测试结束后打印完整报告"""
        # 不清空数据 — mitmdump 在测试运行期间实时写入捕获文件
        yield
        # 测试结束后打印完整验证报告
        print_verification_report()


class TestTC01PlaceTypeAround:
    """TC1: place_type=1 时走周围搜索逻辑"""

    def test_place_type_is_one(self):
        """验证上游请求 place_type=1"""
        errors = verify_place_type_around()
        assert not errors, f"验证失败: {errors}"


class TestTC02LanguagePassthroughTRD:
    """TC2: place_type=1 时 language=trd 透传至高德 /v3/place/around"""

    def test_language_trd_passthrough(self):
        """验证 language=trd 透传到下游"""
        errors = verify_language_passthrough("trd")
        assert not errors, f"验证失败: {errors}"


class TestTC03PlaceTypeRouting:
    """TC3: [质检] place_type 非法或缺失时路由逻辑 [待确认]"""

    def test_place_type_routing(self):
        """验证 place_type 非法或缺失时的路由逻辑（信息收集）"""
        errors = verify_place_type_routing()
        # [待确认] 用例仅做信息收集，errors 中的信息打印但不阻断
        if errors:
            pytest.skip(f"[待确认] {errors}")


class TestTC04AroundLanguageTRD:
    """TC4: /v3/place/around 请求参数 language=trd"""

    def test_around_request_has_language_trd(self):
        """验证下游请求包含 language=trd"""
        errors = verify_around_language_trd()
        assert not errors, f"验证失败: {errors}"


class TestTC05AroundResponseTraditional:
    """TC5: 返回结果 name/pname/cityname/adname/address 为繁体中文"""

    def test_response_fields_traditional(self):
        """验证 language=trd 时返回字段为繁体中文"""
        errors = verify_around_response_traditional()
        assert not errors, f"验证失败: {errors}"


class TestTC06AroundResponseMatchesAmap:
    """TC6: 返回文案与高德 /v3/place/around language=trd 对应字段一致"""

    def test_upstream_matches_amap(self):
        """验证上游返回与高德原始返回无差异"""
        errors = verify_around_response_matches_amap_trd()
        assert not errors, f"验证失败: {errors}"


class TestTC07AroundLanguageEN:
    """TC7: /v3/place/around 请求参数 language=en"""

    def test_around_request_has_language_en(self):
        """验证下游请求包含 language=en"""
        errors = verify_around_language_en()
        assert not errors, f"验证失败: {errors}"


class TestTC08AroundResponseEnglish:
    """TC8: 返回结果 name/cityname/address 为英文"""

    def test_response_fields_english(self):
        """验证 language=en 时返回字段为英文"""
        errors = verify_around_response_english()
        assert not errors, f"验证失败: {errors}"


class TestTC09PnameAdnameNotConverted:
    """TC9: [质检] pname/adname 保持高德原始返回值"""

    def test_pname_adname_not_converted(self):
        """验证 pname/adname 在 language=en 时不进行英文转换"""
        errors = verify_pname_adname_not_converted()
        assert not errors, f"验证失败: {errors}"


class TestTC10AroundDefaultSimplified:
    """TC10: 周围搜索保持默认简体中文"""

    def test_default_simplified_chinese(self):
        """验证默认场景返回简体中文"""
        errors = verify_around_default_simplified()
        assert not errors, f"验证失败: {errors}"
