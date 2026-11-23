"""V1.6.0 PolarDB 库表直查模块。

复用 V1.5.0 的连接与游标管理，补充 V1.6.0 新增维度：
- 网约车订单（business_type=2）的落库校验
- 预约订单（order_type=6）的落库校验
- 一单多车型（order_levels）的子订单存储校验
- 订单附加信息中的 hk_passenger_contract_version 版本标记

需求文档依据：
- 创建订单 /passenger/order/create 兼容网约车、预约一口价
- 创建支付单 /passenger/order/pay 兼容网约车、预约一口价，支付成功后进入可派单
- order-service 下单支持一单多车型数据存储，接单回写主订单信息
- 命中 V1.6.0 的新订单写入订单附加信息 hk_passenger_contract_version=1.6.0

连接信息从 config/JRYG_settings.yaml 的 database 段读取。
"""

import json
import logging
import re

from passenger_android_core.v150.db_verify import db_cursor
from passenger_android_core.JRYG_config import SETTINGS

logger = logging.getLogger("JRYG_HK_android")

_DB_CFG = SETTINGS.get("database", {})

#: 业务类型（运力类型）
BUSINESS_TAXI = 1
BUSINESS_RIDE_HAILING = 2

#: 订单类型
ORDER_TYPE_INSTANT = 5
ORDER_TYPE_BOOKING = 6


def _table(name):
    """读取必填库表标识符；配置键不能作为物理名称回退。"""
    value = _DB_CFG.get(name)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"database.{name} 必须配置为已核实的准确库表名")
    return f"`{value}`"


def _require_order_no(order_no):
    if not isinstance(order_no, str) or not order_no.strip() or order_no != order_no.strip():
        raise ValueError("查询必须提供非空且无首尾空白的准确订单号")


def _query_unique(sql, order_no):
    _require_order_no(order_no)
    with db_cursor() as cur:
        cur.execute(sql, (order_no,))
        rows = cur.fetchmany(2)
    if len(rows) > 1:
        raise AssertionError("同一订单关联到多条记录，不能取首条作为唯一订单")
    return rows[0] if rows else None


def query_order_info_by_no(order_no):
    """按 order_no 查询 order_info 表，返回订单记录字典。

    查询字段：order_no, order_type, payment_collection_mode, business_type,
    order_status, pay_status, prepay_status, use_time。

    返回 None 表示未找到订单。
    """
    db = _table("realtime_db")
    table = _table("order_info_table")
    sql = (
        "SELECT order_no, order_type, payment_collection_mode, business_type, "
        "order_status, pay_status, prepay_status, use_time "
        f"FROM {db}.{table} WHERE order_no = %s LIMIT 2"
    )
    return _query_unique(sql, order_no)


def query_orders_by_user(user_id, order_type=None, limit=10):
    """按乘客 id 查询订单列表。

    :param order_type: 订单类型过滤，None 表示不限。
    :return: 订单记录列表。
    """
    db = _table("realtime_db")
    table = _table("order_info_table")
    sql = (
        "SELECT order_no, order_type, payment_collection_mode, business_type, "
        "order_status, pay_status, use_time "
        f"FROM {db}.{table} WHERE user_id = %s"
    )
    params = [user_id]
    if order_type is not None:
        sql += " AND order_type = %s"
        params.append(order_type)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with db_cursor() as cur:
        cur.execute(sql, tuple(params))
        return list(cur.fetchall() or [])


def query_child_orders(main_order_no, order_type=ORDER_TYPE_BOOKING):
    """查询一单多车型的子订单。

    需求文档：/order/v1/agent/order/main/child/list 支持 order_type=6 的预约订单，
    订单支持一单多车型数据存储，接单回写主订单信息。

    :return: 子订单记录列表；配置缺失或查询失败直接抛错。
    """
    _require_order_no(main_order_no)
    db = _table("realtime_db")
    table = _table("child_order_table")
    sql = (
        "SELECT order_no, main_order_no, order_type, car_type_id, "
        "business_type, order_status, estimate_amount "
        f"FROM {db}.{table} WHERE main_order_no = %s AND order_type = %s "
        "ORDER BY id ASC"
    )
    with db_cursor() as cur:
        cur.execute(sql, (main_order_no, order_type))
        return list(cur.fetchall() or [])


def query_contract_version(order_no):
    """查询订单附加信息中的 hk_passenger_contract_version 版本标记。

    :return: 版本字符串；未标记时返回 None。
    """
    db = _table("realtime_db")
    table = _table("order_info_table")
    sql = (
        "SELECT additional_info FROM "
        f"{db}.{table} WHERE order_no = %s LIMIT 2"
    )
    row = _query_unique(sql, order_no)
    if row is None:
        return None
    raw = row["additional_info"]
    if raw is None:
        return None
    info = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(info, dict):
        raise TypeError("additional_info 必须是 JSON 对象，不能将结构错误当作未标记")
    return info.get("hk_passenger_contract_version")


# ---------------------------------------------------------------------------
# 断言封装
# ---------------------------------------------------------------------------
def assert_ride_hailing_order(order_no, expect_order_type=ORDER_TYPE_INSTANT):
    """校验网约车订单落库字段。

    :return: 订单记录字典。
    :raises AssertionError: 字段不符合预期。
    """
    record = query_order_info_by_no(order_no)
    assert record, f"未找到订单 {order_no}"
    assert record.get("business_type") == BUSINESS_RIDE_HAILING, \
        f"business_type 期望 {BUSINESS_RIDE_HAILING}，实际 {record.get('business_type')}"
    assert record.get("order_type") == expect_order_type, \
        f"order_type 期望 {expect_order_type}，实际 {record.get('order_type')}"
    # 网约车一口价先付
    assert record.get("payment_collection_mode") == 1, \
        f"payment_collection_mode 期望 1（先付），实际 {record.get('payment_collection_mode')}"
    logger.info("【db】网约车订单落库校验通过：%s", record)
    return record


def assert_booking_order(order_no, expect_business_type=None,
                         expect_payment_collection_mode=None):
    """校验预约订单落库字段。

    :param expect_business_type: 期望运力类型，None 表示不校验。
    :param expect_payment_collection_mode: 期望支付模式，None 表示不校验。
    :return: 订单记录字典。
    :raises AssertionError: 字段不符合预期。
    """
    record = query_order_info_by_no(order_no)
    assert record, f"未找到订单 {order_no}"
    assert record.get("order_type") == ORDER_TYPE_BOOKING, \
        f"order_type 期望 {ORDER_TYPE_BOOKING}，实际 {record.get('order_type')}"
    if expect_business_type is not None:
        assert record.get("business_type") == expect_business_type, \
            f"business_type 期望 {expect_business_type}，实际 {record.get('business_type')}"
    if expect_payment_collection_mode is not None:
        assert record.get("payment_collection_mode") == expect_payment_collection_mode, \
            (f"payment_collection_mode 期望 {expect_payment_collection_mode}，"
             f"实际 {record.get('payment_collection_mode')}")
    logger.info("【db】预约订单落库校验通过：%s", record)
    return record


def assert_contract_version(order_no, expect="1.6.0"):
    """校验订单携带 V1.6.0 版本标记。

    :raises AssertionError: 未标记或标记不符。
    """
    version = query_contract_version(order_no)
    assert version == expect, \
        f"hk_passenger_contract_version 期望 {expect}，实际 {version}"
    logger.info("【db】订单 %s 版本标记校验通过：%s", order_no, version)
    return version
