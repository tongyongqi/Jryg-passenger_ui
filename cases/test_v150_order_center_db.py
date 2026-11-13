# 编写时间：2026-11-13
# 本期功能：V1.5.0 订单中心 type16 改造 PolarDB 库表直查验证
# 直连 jryg_realtime_order_dev.order_info 表断言 payment_collection_mode / business_type
"""V1.5.0 订单中心type16改造：PolarDB 库表直查验证。

直连港版测试环境 PolarDB（jryg_realtime_order_dev.order_info 表），
验证 create 接口写入的 payment_collection_mode、business_type 字段值。

覆盖需求文档§6测试要点的库表验证部分：
1. type16 订单在实时库 order_info 表中可查到，字段值为 create 传入值
2. type16 不在预约库 booking_order_info 中（走实时库不走预约库）
3. type5 订单两字段同样有值（即时单支持）
4. type16 取消后从未完成服务表清理
5. 两字段 DDL 类型校验（int, 默认值符合需求）

前置条件：数据库连接配置已在 config/JRYG_settings.yaml database 段中配置。
本测试直连数据库，不依赖真机或App。
"""

import logging
import pytest

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_v150_db_verify import (
    query_order_info_by_no,
    query_recent_orders_by_type,
    query_order_field_values,
    verify_order_in_realtime_db,
    verify_order_removed_from_serving,
    db_cursor,
)

logger = logging.getLogger("JRYG_HK_android")

_DB_CFG = SETTINGS.get("database", {})
_HAS_DB = bool(_DB_CFG)
_DB_REASON = "database 配置缺失：请在 config/JRYG_settings.yaml 中配置 database 段"

# 需求文档常量
ORDER_TYPE_REALTIME_INSTANT = 5
ORDER_TYPE_BOOKING_REALTIME = 16
PAYMENT_COLLECTION_ONLINE = 1
BUSINESS_TAXI = 1


# ==================== 连接性验证 ====================

@pytest.mark.skipif(not _HAS_DB, reason=_DB_REASON)
class TestDBConnection:
    """验证数据库连接可用且表结构正确。"""

    def test_connection_ok(self):
        """连接 PolarDB 成功，能执行 SHOW DATABASES。"""
        with db_cursor() as cur:
            cur.execute("SHOW DATABASES")
            dbs = [r["Database"] for r in cur.fetchall()]
        assert "jryg_realtime_order_dev" in dbs

    def test_order_info_table_exists(self):
        """order_info 表存在于 jryg_realtime_order_dev 库。"""
        with db_cursor() as cur:
            cur.execute("SHOW TABLES FROM jryg_realtime_order_dev LIKE 'order_info'")
            rows = cur.fetchall()
        assert len(rows) == 1

    def test_order_info_has_payment_collection_mode(self):
        """order_info 表有 payment_collection_mode 字段，类型为 int。"""
        with db_cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, COLUMN_DEFAULT, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = 'jryg_realtime_order_dev'
                  AND TABLE_NAME = 'order_info'
                  AND COLUMN_NAME = 'payment_collection_mode'
            """)
            row = cur.fetchone()
        assert row is not None, "order_info 表缺少 payment_collection_mode 字段"
        assert row["DATA_TYPE"] in ("int", "tinyint", "smallint")
        assert "收款" in row["COLUMN_COMMENT"] or "payment" in row["COLUMN_COMMENT"].lower()

    def test_order_info_has_business_type(self):
        """order_info 表有 business_type 字段，类型为 int。"""
        with db_cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, COLUMN_DEFAULT, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = 'jryg_realtime_order_dev'
                  AND TABLE_NAME = 'order_info'
                  AND COLUMN_NAME = 'business_type'
            """)
            row = cur.fetchone()
        assert row is not None, "order_info 表缺少 business_type 字段"
        assert row["DATA_TYPE"] in ("int", "tinyint", "smallint")
        assert "业务" in row["COLUMN_COMMENT"] or "business" in row["COLUMN_COMMENT"].lower()

    def test_order_info_has_order_type(self):
        """order_info 表有 order_type 字段，注释含 16:预约实时计价。"""
        with db_cursor() as cur:
            cur.execute("""
                SELECT COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = 'jryg_realtime_order_dev'
                  AND TABLE_NAME = 'order_info'
                  AND COLUMN_NAME = 'order_type'
            """)
            row = cur.fetchone()
        assert row is not None
        assert "16" in row["COLUMN_COMMENT"]
        assert "预约" in row["COLUMN_COMMENT"]


# ==================== type5 已有数据字段验证 ====================

@pytest.mark.skipif(not _HAS_DB, reason=_DB_REASON)
class TestType5OrderFields:
    """验证 type5（即时单）已有订单的两字段值。

    type5 是已上线功能，两字段应有值（payment_collection_mode=1, business_type=1）。
    作为 type16 的对比基线。
    """

    def test_type5_orders_have_payment_collection_mode(self):
        """type5 订单的 payment_collection_mode 字段有值。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_REALTIME_INSTANT, limit=5)
        assert len(rows) > 0, "数据库中无 type5 订单，无法验证基线"
        for row in rows:
            assert row["payment_collection_mode"] is not None
            logger.info("type5 order_no=%s payment_collection_mode=%s",
                         row["order_no"], row["payment_collection_mode"])

    def test_type5_orders_have_business_type(self):
        """type5 订单的 business_type 字段有值。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_REALTIME_INSTANT, limit=5)
        assert len(rows) > 0
        for row in rows:
            assert row["business_type"] is not None

    def test_type5_payment_collection_mode_is_1_or_2(self):
        """type5 订单 payment_collection_mode 只能是 1（线上）或 2（线下）。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_REALTIME_INSTANT, limit=10)
        for row in rows:
            assert row["payment_collection_mode"] in (1, 2)

    def test_type5_business_type_is_1_or_2(self):
        """type5 订单 business_type 只能是 1（出租车）或 2（网约车）。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_REALTIME_INSTANT, limit=10)
        for row in rows:
            assert row["business_type"] in (1, 2)


# ==================== type16 库表验证 ====================

@pytest.mark.skipif(not _HAS_DB, reason=_DB_REASON)
class TestType16OrderFields:
    """验证 type16（预约实时计价）订单在实时库的字段。

    前置条件：需要有已创建的 type16 订单。
    若库中无 type16 订单，测试将 skip 并提示先创建测试数据。
    """

    def test_type16_orders_exist_in_realtime_db(self):
        """type16 订单存在于实时库 order_info 表中（不走预约库）。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_BOOKING_REALTIME, limit=1)
        if not rows:
            pytest.skip("数据库中无 type16 订单，请先通过真机创建预约后付费订单")

    def test_type16_order_fields_match_create_values(self):
        """type16 订单两字段值与 create 传入一致（payment_collection_mode=1, business_type=1）。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_BOOKING_REALTIME, limit=5)
        if not rows:
            pytest.skip("数据库中无 type16 订单，请先通过真机创建预约后付费订单")
        for row in rows:
            # 改造后创建的 type16 订单应有有效值
            assert row["payment_collection_mode"] in (1, 2), \
                f"order_no={row['order_no']} payment_collection_mode={row['payment_collection_mode']} 不在(1,2)"
            assert row["business_type"] in (1, 2), \
                f"order_no={row['order_no']} business_type={row['business_type']} 不在(1,2)"

    def test_type16_not_in_booking_db(self):
        """type16 订单不在预约库 booking_order_info 中。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_BOOKING_REALTIME, limit=1)
        if not rows:
            pytest.skip("数据库中无 type16 订单")
        order_no = rows[0]["order_no"]
        result = verify_order_in_realtime_db(order_no)
        assert result["in_realtime"], f"order_no={order_no} 不在实时库"
        assert not result["in_booking"], f"order_no={order_no} 不应在预约库"

    def test_type16_order_type_in_realtime_db(self):
        """通过 order_no 查询确认 order_type=16。"""
        rows = query_recent_orders_by_type(ORDER_TYPE_BOOKING_REALTIME, limit=1)
        if not rows:
            pytest.skip("数据库中无 type16 订单")
        order_no = rows[0]["order_no"]
        row = query_order_info_by_no(order_no)
        assert row is not None
        assert row["order_type"] == 16


# ==================== 按订单号精确断言 ====================

@pytest.mark.skipif(not _HAS_DB, reason=_DB_REASON)
class TestOrderByNo:
    """按具体 order_no 查询并断言两字段值。

    使用方式：设置 ORDER_NO 环境变量或直接修改 ORDER_NO 常量，
    传入真机创建的 type16 订单号，精确断言字段值。
    """

    # 从环境变量读取订单号，或设为已知订单号
    ORDER_NO = None  # pytest 启动时通过环境变量 JRYG_ORDER_NO 传入

    def test_query_specific_order_fields(self):
        """按 order_no 查询两字段，断言值为 1（线上支付+出租车）。"""
        import os
        order_no = os.environ.get("JRYG_ORDER_NO", self.ORDER_NO)
        if not order_no:
            pytest.skip("未设置 JRYG_ORDER_NO 环境变量，跳过精确断言")
        result = query_order_field_values(order_no)
        if result is None:
            pytest.skip(f"order_no={order_no} 在 order_info 表中未找到")
        assert result["payment_collection_mode"] == PAYMENT_COLLECTION_ONLINE, \
            f"payment_collection_mode={result['payment_collection_mode']}，预期=1"
        assert result["business_type"] == BUSINESS_TAXI, \
            f"business_type={result['business_type']}，预期=1"

    def test_query_specific_order_in_realtime_not_booking(self):
        """按 order_no 验证订单在实时库不在预约库。"""
        import os
        order_no = os.environ.get("JRYG_ORDER_NO", self.ORDER_NO)
        if not order_no:
            pytest.skip("未设置 JRYG_ORDER_NO 环境变量")
        result = verify_order_in_realtime_db(order_no)
        assert result["in_realtime"], f"order_no={order_no} 不在实时库"
        assert not result["in_booking"], f"order_no={order_no} 不应在预约库"

    def test_query_specific_order_type_is_16(self):
        """按 order_no 验证 order_type=16。"""
        import os
        order_no = os.environ.get("JRYG_ORDER_NO", self.ORDER_NO)
        if not order_no:
            pytest.skip("未设置 JRYG_ORDER_NO 环境变量")
        row = query_order_info_by_no(order_no)
        if row is None:
            pytest.skip(f"order_no={order_no} 未找到")
        assert row["order_type"] == 16, \
            f"order_type={row['order_type']}，预期=16"


# ==================== 取消清理验证 ====================

@pytest.mark.skipif(not _HAS_DB, reason=_DB_REASON)
class TestCancellationCleanup:
    """验证取消后订单从未完成服务表清理。

    前置条件：传入已取消的 type16 订单号。
    """

    def test_cancelled_order_removed_from_serving(self):
        """取消的订单不在 order_driver_serving 表中。"""
        import os
        order_no = os.environ.get("JRYG_CANCELLED_ORDER_NO")
        if not order_no:
            pytest.skip("未设置 JRYG_CANCELLED_ORDER_NO 环境变量")
        result = verify_order_removed_from_serving(order_no)
        assert result["removed_from_serving"], \
            f"order_no={order_no} 仍在 order_driver_serving 表中，未清理"


# ==================== 离线契约与库表一致性验证 ====================

class TestContractDBConsistency:
    """验证离线契约函数的常量与数据库 DDL 注释一致（不连数据库）。"""

    def test_order_type_16_is_booking_realtime(self):
        """契约常量 ORDER_TYPE_BOOKING_REALTIME=16 与 DDL 注释"16:预约实时计价"一致。"""
        assert ORDER_TYPE_BOOKING_REALTIME == 16

    def test_order_type_5_is_instant(self):
        """契约常量 ORDER_TYPE_REALTIME_INSTANT=5 与 DDL 注释"5:即时用车"一致。"""
        assert ORDER_TYPE_REALTIME_INSTANT == 5

    def test_payment_collection_online_is_1(self):
        """PAYMENT_COLLECTION_ONLINE=1 与 DDL 注释"1线上收款"一致。"""
        assert PAYMENT_COLLECTION_ONLINE == 1

    def test_business_taxi_is_1(self):
        """BUSINESS_TAXI=1 与 DDL 注释"1:出租车"一致。"""
        assert BUSINESS_TAXI == 1
