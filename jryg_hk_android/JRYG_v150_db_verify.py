"""V1.5.0 订单中心type16改造：PolarDB 库表直查模块。

连接港版测试环境 PolarDB（MySQL协议），直接查询 jryg_realtime_order_dev.order_info 表，
验证 create 接口写入的 payment_collection_mode、business_type 字段值。

需求文档依据：
- type16（预约实时计价）走实时库，不走预约库 booking.OrderInfo
- entity.OrderInfo 有 gorm 列、payment_collection_mode int、business_type int
- 改造前两字段为 0/默认值，改造后应写入 create 传入的真实值

连接信息从 config/JRYG_settings.yaml 的 database 段读取。
"""

import logging
from contextlib import contextmanager

import pymysql

from jryg_hk_android.JRYG_config import SETTINGS

logger = logging.getLogger("JRYG_HK_android")

# 从 YAML 读取数据库配置
_DB_CFG = SETTINGS.get("database", {})


def _get_connection():
    """创建 PolarDB 连接，配置缺失时抛出明确错误。"""
    if not _DB_CFG:
        raise RuntimeError(
            "database 配置缺失：请在 config/JRYG_settings.yaml 中配置 database 段")
    return pymysql.connect(
        host=_DB_CFG["host"],
        port=int(_DB_CFG["port"]),
        user=_DB_CFG["user"],
        password=_DB_CFG["password"],
        charset=_DB_CFG.get("charset", "utf8mb4"),
        connect_timeout=int(_DB_CFG.get("connect_timeout", 10)),
        read_timeout=int(_DB_CFG.get("read_timeout", 10)),
        cursorclass=pymysql.cursors.DictCursor,
    )


@contextmanager
def db_cursor():
    """上下文管理器：自动连接和关闭，返回 DictCursor。"""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_order_info_by_no(order_no):
    """按 order_no 查询 order_info 表，返回订单记录字典。

    查询字段：order_no, order_type, payment_collection_mode, business_type,
    order_status, pay_status, prepay_status。

    返回 None 表示未找到订单。
    """
    db = _DB_CFG.get("realtime_db", "jryg_realtime_order_dev")
    table = _DB_CFG.get("order_info_table", "order_info")
    sql = (
        f"SELECT order_no, order_type, payment_collection_mode, business_type, "
        f"order_status, pay_status, prepay_status "
        f"FROM `{db}`.`{table}` WHERE order_no = %s LIMIT 1"
    )
    with db_cursor() as cur:
        cur.execute(sql, (order_no,))
        row = cur.fetchone()
    if row:
        logger.info("DB查询 order_info order_no=%s → type=%s, payment_collection_mode=%s, business_type=%s",
                     order_no, row["order_type"], row["payment_collection_mode"], row["business_type"])
    else:
        logger.warning("DB查询 order_info order_no=%s 未找到", order_no)
    return row


def query_recent_orders_by_type(order_type, limit=5):
    """按 order_type 查询最近 N 条订单记录。

    用于验证特定类型订单的字段分布。
    """
    db = _DB_CFG.get("realtime_db", "jryg_realtime_order_dev")
    table = _DB_CFG.get("order_info_table", "order_info")
    sql = (
        f"SELECT order_no, order_type, payment_collection_mode, business_type, "
        f"order_status, pay_status "
        f"FROM `{db}`.`{table}` WHERE order_type = %s "
        f"ORDER BY id DESC LIMIT %s"
    )
    with db_cursor() as cur:
        cur.execute(sql, (order_type, limit))
        rows = cur.fetchall()
    logger.info("DB查询 order_info type=%s → %d 条", order_type, len(rows))
    return rows


def query_order_field_values(order_no):
    """仅查询两新字段值，用于精确断言。

    返回 {"payment_collection_mode": int, "business_type": int} 或 None。
    """
    db = _DB_CFG.get("realtime_db", "jryg_realtime_order_dev")
    table = _DB_CFG.get("order_info_table", "order_info")
    sql = (
        f"SELECT payment_collection_mode, business_type "
        f"FROM `{db}`.`{table}` WHERE order_no = %s LIMIT 1"
    )
    with db_cursor() as cur:
        cur.execute(sql, (order_no,))
        row = cur.fetchone()
    if row:
        return {
            "payment_collection_mode": int(row["payment_collection_mode"]),
            "business_type": int(row["business_type"]),
        }
    return None


def verify_order_in_realtime_db(order_no):
    """验证订单存储在实时库而非预约库。

    type16 应在 jryg_realtime_order_dev.order_info 中可查到，
    不应在 jryg_booking_order_dev.booking_order_info 中查到。
    """
    result = {"in_realtime": False, "in_booking": False}
    # 查实时库
    row = query_order_info_by_no(order_no)
    if row:
        result["in_realtime"] = True
        result["order_type"] = row["order_type"]
    # 查预约库
    booking_db = _DB_CFG.get("booking_db", "jryg_booking_order_dev")
    sql = f"SELECT order_no FROM `{booking_db}`.`booking_order_info` WHERE order_no = %s LIMIT 1"
    with db_cursor() as cur:
        cur.execute(sql, (order_no,))
        booking_row = cur.fetchone()
    result["in_booking"] = booking_row is not None
    logger.info("DB验证 order_no=%s → realtime=%s, booking=%s",
                 order_no, result["in_realtime"], result["in_booking"])
    return result


def verify_order_removed_from_serving(order_no):
    """验证取消后订单从未完成服务表清理。

    type16 取消后应从 order_driver_serving 表消失。
    """
    db = _DB_CFG.get("realtime_db", "jryg_realtime_order_dev")
    sql = f"SELECT order_no FROM `{db}`.`order_driver_serving` WHERE order_no = %s LIMIT 1"
    with db_cursor() as cur:
        cur.execute(sql, (order_no,))
        row = cur.fetchone()
    removed = row is None
    logger.info("DB验证 order_no=%s → order_driver_serving removed=%s", order_no, removed)
    return {"removed_from_serving": removed}
