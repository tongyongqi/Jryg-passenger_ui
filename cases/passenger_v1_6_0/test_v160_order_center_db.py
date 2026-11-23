"""香港乘客端 V1.6.0 订单落库直查测试。

编写时间：2026-11-19
本期功能：网约车与预约订单的 PolarDB 落库字段校验
需求映射：
- /passenger/order/create 兼容网约车、预约一口价
- 命中 V1.6.0 的新订单写入 hk_passenger_contract_version=1.6.0
- 订单支持一单多车型数据存储

前置条件：需内网可达 PolarDB（172.31.104.3:3306）。
连接、认证、配置与 SQL 错误保留为错误，不自动归类为 VPN 阻塞。
执行前必须确认测试环境、准确库表及字段映射。
即时正向用例使用 V160_REAL_INSTANT_ORDER_NO，预约使用 V160_REAL_BOOKING_ORDER_NO；
两者必须是不同订单；通用 V160_REAL_ORDER_NO 仅用于版本与列表查询。
本文件不需要 App 与设备。

数据来源说明（99% 真实原则）：
- 空路径用例：使用不存在的订单号 NOT_EXIST_V160_ORDER 验证查询函数在
  「查不到」时的返回行为（None / 空列表），不涉及业务字段断言。
- 正向断言用例：通过环境变量 V160_REAL_ORDER_NO 传入真实下单后获取的订单号，
  DB 可达且提供了真实订单号时才执行落库字段断言；未提供时明确 skip 并标注
  「需真实下单后传入 order_no」，不伪造订单号、不 mock 查询结果。
- 常量校验用例：不依赖 DB 连接，始终执行。

VPN 连接后运行方式：
  # 1. 连接 VPN（确保 172.31.104.3:3306 可达）
  # 2. 设置环境变量并运行

  # 空路径用例 + 断言封装行为 + 常量校验（无需真实订单号）
  pytest cases/passenger_v1_6_0/test_v160_order_center_db.py -v

  # 正向断言用例（需 DB 可达 + 真实订单号）
  V160_REAL_ORDER_NO=TH26B6PIEWECN \
  V160_REAL_USER_ID=301025 \
  pytest cases/passenger_v1_6_0/test_v160_order_center_db.py -v -k real

  # 全量运行（空路径 + 正向断言 + 封装行为 + 常量）
  V160_REAL_ORDER_NO=TH26B6PIEWECN \
  V160_REAL_USER_ID=301025 \
  pytest cases/passenger_v1_6_0/test_v160_order_center_db.py -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v150.db_verify import _get_connection  # noqa: E402
from passenger_android_core.v160.db_verify import (  # noqa: E402
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    ORDER_TYPE_BOOKING,
    ORDER_TYPE_INSTANT,
    assert_booking_order,
    assert_contract_version,
    assert_ride_hailing_order,
    query_child_orders,
    query_contract_version,
    query_order_info_by_no,
    query_orders_by_user,
)

#: 真实订单号（从环境变量获取，不硬编码伪造值）
_REAL_ORDER_NO = os.environ.get("V160_REAL_ORDER_NO", "").strip()
_INSTANT_ORDER_NO = os.environ.get("V160_REAL_INSTANT_ORDER_NO", "").strip()
_BOOKING_ORDER_NO = os.environ.get("V160_REAL_BOOKING_ORDER_NO", "").strip()
#: 真实用户 ID（从环境变量获取，用于订单列表查询）
_REAL_USER_ID = os.environ.get("V160_REAL_USER_ID", "").strip()
#: 真实母订单号（从环境变量获取，用于一单多车型子订单查询）
_REAL_MAIN_ORDER_NO = os.environ.get("V160_REAL_MAIN_ORDER_NO", "").strip()
#: 不存在的订单号（仅用于验证空路径，不用于正向断言）
_NONEXIST_ORDER_NO = "NOT_EXIST_V160_ORDER"


@pytest.fixture(scope="module")
def db_available():
    """验证数据库连接，初始化错误保持为 setup error，不猜测为 VPN 问题。"""
    conn = _get_connection()
    try:
        yield
    finally:
        conn.close()


def _need_real_order(order_no=None, setting="V160_REAL_ORDER_NO"):
    """仅缺少输入时阻塞；不把查询异常或字段不符降级为跳过。"""
    value = _REAL_ORDER_NO if order_no is None else order_no
    if not value:
        pytest.skip(f"测试数据不足：需提供 {setting} 对应场景的真实订单号")
    if _INSTANT_ORDER_NO and _INSTANT_ORDER_NO == _BOOKING_ORDER_NO:
        raise ValueError("即时订单与预约订单必须使用不同订单号")
    return value


class TestV160OrderDbConstants:
    """V1.6.0 常量校验 — 不依赖 DB 连接，始终执行。

    将常量校验独立出来，避免 DB 不可达时被 module 级 skip 误伤。
    """

    def test_business_type_constants(self):
        """运力类型常量：出租车=1、网约车=2。"""
        assert BUSINESS_TAXI == 1
        assert BUSINESS_RIDE_HAILING == 2

    def test_order_type_constants(self):
        """订单类型常量：即时=5、预约=6。"""
        assert ORDER_TYPE_INSTANT == 5
        assert ORDER_TYPE_BOOKING == 6


@pytest.mark.usefixtures("db_available")
class TestV160OrderDb:
    """V1.6.0 订单落库校验 — 空路径。

    使用不存在的订单号验证查询函数在「查不到」时的返回行为，
    不涉及业务字段断言。正向断言见 TestV160OrderDbReal。
    前置：PolarDB 可达（需 VPN）。
    """

    def test_query_order_info_by_no_not_found(self):
        """不存在的订单号返回 None，不抛异常。"""
        assert query_order_info_by_no(_NONEXIST_ORDER_NO) is None

    def test_query_orders_by_user_empty(self):
        """不存在的乘客返回空列表。"""
        assert query_orders_by_user(999999999, limit=1) == []

    def test_query_orders_by_user_with_order_type(self):
        """按 order_type 过滤不报错。"""
        assert query_orders_by_user(999999999, order_type=ORDER_TYPE_BOOKING,
                                    limit=1) == []

    def test_query_child_orders_empty(self):
        """不存在的母订单返回空子订单列表。"""
        assert query_child_orders(_NONEXIST_ORDER_NO) == []

    def test_query_contract_version_none(self):
        """不存在的订单返回 None 版本标记。"""
        assert query_contract_version(_NONEXIST_ORDER_NO) is None


@pytest.mark.usefixtures("db_available")
class TestV160OrderDbReal:
    """V1.6.0 订单落库校验 — 正向断言（需真实订单号）。

    前置：
    1. PolarDB 可达（需 VPN）
    2. 通过环境变量 V160_REAL_ORDER_NO 传入真实下单后的订单号

    未提供订单号时自动 skip，不伪造订单号、不 mock 查询结果。
    连 VPN + 传真实订单号后直接运行，不需要改任何代码。

    运行命令：
      V160_REAL_ORDER_NO=TH26B6PIEWECN \
      V160_REAL_USER_ID=301025 \
      pytest cases/passenger_v1_6_0/test_v160_order_center_db.py -v -k real
    """

    def test_real_order_exists(self):
        """真实订单号在 order_info 表中可查到记录。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 在 order_info 表中未找到"

    def test_real_order_has_business_type(self):
        """真实订单落库 business_type 字段非空。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("business_type") is not None, \
            f"订单 {_REAL_ORDER_NO} business_type 为空"

    def test_real_order_business_type_value(self):
        """真实订单落库 business_type 值为 1（出租车）或 2（网约车）。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("business_type") in (BUSINESS_TAXI, BUSINESS_RIDE_HAILING), \
            f"订单 {_REAL_ORDER_NO} business_type={record.get('business_type')}，期望 1 或 2"

    def test_real_order_has_order_type(self):
        """真实订单落库 order_type 字段值为 5（即时）或 6（预约）。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("order_type") in (ORDER_TYPE_INSTANT, ORDER_TYPE_BOOKING), \
            f"订单 {_REAL_ORDER_NO} order_type={record.get('order_type')}，期望 5 或 6"

    def test_real_order_has_payment_collection_mode(self):
        """真实订单落库 payment_collection_mode 字段非空。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("payment_collection_mode") is not None, \
            f"订单 {_REAL_ORDER_NO} payment_collection_mode 为空"

    def test_real_order_payment_collection_mode_value(self):
        """真实订单 payment_collection_mode 值为 1（先付）或 2（后付）。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("payment_collection_mode") in (1, 2), \
            f"订单 {_REAL_ORDER_NO} payment_collection_mode={record.get('payment_collection_mode')}，期望 1 或 2"

    def test_real_order_has_order_status(self):
        """真实订单落库 order_status 字段非空。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("order_status") is not None, \
            f"订单 {_REAL_ORDER_NO} order_status 为空"

    def test_real_order_has_pay_status(self):
        """真实订单落库 pay_status 字段非空。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        assert record.get("pay_status") is not None, \
            f"订单 {_REAL_ORDER_NO} pay_status 为空"

    def test_real_order_has_use_time(self):
        """真实订单落库 use_time 字段非空（预约订单的用车时间）。"""
        _need_real_order()
        record = query_order_info_by_no(_REAL_ORDER_NO)
        assert record, f"真实订单号 {_REAL_ORDER_NO} 未找到"
        # 即时订单 use_time 可能为空，预约订单应有值
        order_type = record.get("order_type")
        if order_type == ORDER_TYPE_BOOKING:
            assert record.get("use_time"), \
                f"预约订单 {_REAL_ORDER_NO} use_time 为空"

    def test_real_ride_hailing_order_fields(self):
        """即时网约车订单：business_type=2、先付、order_type=5。"""
        order_no = _need_real_order(_INSTANT_ORDER_NO, "V160_REAL_INSTANT_ORDER_NO")
        record = assert_ride_hailing_order(order_no, expect_order_type=ORDER_TYPE_INSTANT)
        assert record["business_type"] == BUSINESS_RIDE_HAILING
        assert record["payment_collection_mode"] == 1

    def test_real_ride_hailing_instant_order_type(self):
        """真实网约车即时订单 order_type=5。"""
        order_no = _need_real_order(_INSTANT_ORDER_NO, "V160_REAL_INSTANT_ORDER_NO")
        record = assert_ride_hailing_order(order_no, expect_order_type=ORDER_TYPE_INSTANT)
        assert record["order_no"] == order_no

    def test_real_booking_order_fields(self):
        """真实预约订单断言：order_type=6。

        使用 assert_booking_order 封装，断言 order_type == 6（预约）。
        """
        order_no = _need_real_order(_BOOKING_ORDER_NO, "V160_REAL_BOOKING_ORDER_NO")
        record = assert_booking_order(order_no)
        assert record["order_no"] == order_no
        assert record["order_type"] == ORDER_TYPE_BOOKING

    def test_real_booking_has_use_time(self):
        """真实预约订单 use_time 非空（预约用车时间已落库）。"""
        order_no = _need_real_order(_BOOKING_ORDER_NO, "V160_REAL_BOOKING_ORDER_NO")
        record = assert_booking_order(order_no)
        assert record["order_no"] == order_no
        assert record["use_time"] is not None, "预约时间未落库"
        assert record["use_time"] != "", "预约时间为空字符串"

    def test_real_contract_version(self):
        """真实 V1.6.0 订单携带 hk_passenger_contract_version=1.6.0。

        通过 additional_info 中的版本标记，确认订单命中 V1.6.0 灰度。
        """
        _need_real_order()
        version = assert_contract_version(_REAL_ORDER_NO)
        assert version == "1.6.0"

    def test_real_user_orders(self):
        """真实用户 ID 可查到订单列表，且包含真实订单号。

        前置：V160_REAL_USER_ID 已提供。
        """
        if not _REAL_USER_ID:
            pytest.skip(
                "未提供真实用户 ID（V160_REAL_USER_ID），"
                "用户订单列表正向查询需真实用户 ID"
            )
        orders = query_orders_by_user(int(_REAL_USER_ID), limit=20)
        assert orders, f"用户 {_REAL_USER_ID} 订单列表为空"
        order_nos = [o.get("order_no") for o in orders]
        assert _REAL_ORDER_NO in order_nos, \
            f"真实订单 {_REAL_ORDER_NO} 不在用户 {_REAL_USER_ID} 的订单列表中"

    @pytest.mark.skip(reason="结构未确认：缺少真实子订单表名、关联约束及本场景子单数量依据")
    def test_real_child_orders(self):
        raise NotImplementedError("需核实子订单查询契约，不用通用订单回退或列表类型断言冒充通过")


@pytest.mark.usefixtures("db_available")
class TestV160OrderDbAssertions:
    """V1.6.0 断言封装行为校验（使用不存在的订单号验证失败路径）。

    前置：PolarDB 可达（需 VPN），因为断言封装内部要执行真实 SQL 查询。
    """

    def test_assert_ride_hailing_order_raises_when_missing(self):
        """网约车订单断言在订单不存在时抛出「未找到订单」。"""
        with pytest.raises(AssertionError, match="未找到订单"):
            assert_ride_hailing_order(_NONEXIST_ORDER_NO)

    def test_assert_booking_order_raises_when_missing(self):
        """预约订单断言在订单不存在时抛出「未找到订单」。"""
        with pytest.raises(AssertionError, match="未找到订单"):
            assert_booking_order(_NONEXIST_ORDER_NO)

    def test_assert_contract_version_raises_when_missing(self):
        """契约版本断言在订单不存在时抛出断言错误。"""
        with pytest.raises(AssertionError):
            assert_contract_version(_NONEXIST_ORDER_NO)
