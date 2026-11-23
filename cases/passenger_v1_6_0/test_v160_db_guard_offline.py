"""第一批数据库查询防护回归；仅使用合成配置和游标，不连接真实数据库。"""

from contextlib import contextmanager
import importlib
import json
from unittest.mock import Mock

import pytest

from passenger_android_core.v160 import db_verify as db


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    import pymysql
    import requests
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("离线回归禁止连接数据库、HTTP 或执行设备命令")

    monkeypatch.setattr(pymysql, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(db, "_DB_CFG", {
        "realtime_db": "fixture_order_db",
        "order_info_table": "fixture_orders",
        "child_order_table": "fixture_children",
    })


@pytest.fixture
def cursor(monkeypatch):
    cur = Mock()
    cur.fetchmany.return_value = []
    cur.fetchall.return_value = []

    @contextmanager
    def fake_cursor():
        yield cur

    monkeypatch.setattr(db, "db_cursor", fake_cursor)
    return cur


@pytest.mark.parametrize("key", ["realtime_db", "order_info_table", "child_order_table"])
@pytest.mark.parametrize("value", [None, "", "child;DROP", "name.with.dot", " name", 1])
def test_identifiers_never_fall_back_or_enter_database(monkeypatch, key, value):
    monkeypatch.setitem(db._DB_CFG, key, value)
    connect = Mock(side_effect=AssertionError("不得在配置验证前连接"))
    monkeypatch.setattr(db, "db_cursor", connect)
    query = db.query_child_orders if key == "child_order_table" else db.query_order_info_by_no
    with pytest.raises(ValueError, match="必须配置"):
        query("fixture-order")
    connect.assert_not_called()


def test_missing_child_table_is_not_used_as_table_name(monkeypatch):
    monkeypatch.delitem(db._DB_CFG, "child_order_table")
    connect = Mock()
    monkeypatch.setattr(db, "db_cursor", connect)
    with pytest.raises(ValueError, match="child_order_table"):
        db.query_child_orders("fixture-main")
    connect.assert_not_called()


@pytest.mark.parametrize("order_no", [None, "", " ", " order", 17])
def test_invalid_order_key_never_queries(cursor, order_no):
    with pytest.raises(ValueError, match="准确订单号"):
        db.query_order_info_by_no(order_no)
    cursor.execute.assert_not_called()


def test_exact_identifiers_and_bound_order_key(cursor):
    record = {"order_no": "fixture-order", "use_time": None}
    cursor.fetchmany.return_value = [record]
    assert db.query_order_info_by_no("fixture-order") == record
    sql, params = cursor.execute.call_args.args
    assert "FROM `fixture_order_db`.`fixture_orders` WHERE order_no = %s LIMIT 2" in sql
    assert "SELECT order_no, order_type, payment_collection_mode, business_type" in sql
    assert "SELECT *" not in sql
    assert params == ("fixture-order",)
    cursor.fetchmany.assert_called_once_with(2)
    cursor.fetchone.assert_not_called()


@pytest.mark.parametrize("query", [db.query_order_info_by_no, db.query_contract_version])
def test_duplicate_orders_fail_instead_of_taking_first(cursor, query):
    cursor.fetchmany.return_value = [{"order_no": "fixture-order"}] * 2
    with pytest.raises(AssertionError, match="多条记录"):
        query("fixture-order")


@pytest.mark.parametrize("query", [db.query_order_info_by_no, db.query_contract_version])
def test_absent_record_remains_absent(cursor, query):
    assert query("fixture-order") is None


def test_child_query_uses_exact_config_and_parameters(cursor):
    assert db.query_child_orders("fixture-main", order_type=6) == []
    sql, params = cursor.execute.call_args.args
    assert "FROM `fixture_order_db`.`fixture_children`" in sql
    assert "WHERE main_order_no = %s AND order_type = %s" in sql
    assert params == ("fixture-main", 6)


@pytest.mark.parametrize("raw,error", [("", json.JSONDecodeError), ("{", json.JSONDecodeError),
                                      ("[]", TypeError), (False, TypeError), ([], TypeError)])
def test_invalid_additional_info_does_not_become_missing_version(cursor, raw, error):
    cursor.fetchmany.return_value = [{"additional_info": raw}]
    with pytest.raises(error):
        db.query_contract_version("fixture-order")


@pytest.mark.parametrize("raw,expected", [(None, None), ({}, None),
                                        ('{"hk_passenger_contract_version":"1.6.0"}', "1.6.0")])
def test_version_query_distinguishes_null_missing_and_value(cursor, raw, expected):
    cursor.fetchmany.return_value = [{"additional_info": raw}]
    assert db.query_contract_version("fixture-order") == expected


def test_missing_column_is_not_defaulted(cursor):
    cursor.fetchmany.return_value = [{}]
    with pytest.raises(KeyError, match="additional_info"):
        db.query_contract_version("fixture-order")


@pytest.fixture
def real_cases(monkeypatch):
    module = importlib.import_module("cases.passenger_v1_6_0.test_v160_order_center_db")
    monkeypatch.setattr(module, "_REAL_ORDER_NO", "fixture-generic")
    monkeypatch.setattr(module, "_INSTANT_ORDER_NO", "fixture-instant")
    monkeypatch.setattr(module, "_BOOKING_ORDER_NO", "fixture-booking")
    return module


def test_instant_and_booking_cases_use_separate_keys(monkeypatch, real_cases):
    instant = Mock(return_value={"order_no": "fixture-instant", "business_type": 2,
                                "payment_collection_mode": 1, "order_type": 5})
    booking = Mock(return_value={"order_no": "fixture-booking", "order_type": 6,
                                "use_time": "fixture-selected-time"})
    monkeypatch.setattr(real_cases, "assert_ride_hailing_order", instant)
    monkeypatch.setattr(real_cases, "assert_booking_order", booking)
    case = real_cases.TestV160OrderDbReal()
    case.test_real_ride_hailing_order_fields()
    case.test_real_ride_hailing_instant_order_type()
    case.test_real_booking_order_fields()
    case.test_real_booking_has_use_time()
    assert all(call.args == ("fixture-instant",) for call in instant.call_args_list)
    assert all(call.args == ("fixture-booking",) for call in booking.call_args_list)
    assert instant.call_count == booking.call_count == 2


def test_same_order_for_distinct_scenarios_is_configuration_error(monkeypatch, real_cases):
    monkeypatch.setattr(real_cases, "_BOOKING_ORDER_NO", "fixture-instant")
    with pytest.raises(ValueError, match="不同订单号"):
        real_cases._need_real_order("fixture-instant")


def test_database_setup_does_not_swallow_programming_error(monkeypatch, real_cases):
    monkeypatch.setattr(real_cases, "_get_connection", Mock(side_effect=KeyError("host")))
    setup = real_cases.db_available.__wrapped__()
    with pytest.raises(KeyError, match="host"):
        next(setup)


def test_incomplete_child_case_is_explicitly_blocked(real_cases):
    method = real_cases.TestV160OrderDbReal.test_real_child_orders
    assert any(mark.name == "skip" and "结构未确认" in mark.kwargs["reason"]
               for mark in method.pytestmark)
    with pytest.raises(NotImplementedError):
        method(real_cases.TestV160OrderDbReal())


@pytest.mark.parametrize("name", ["test_estimate_response_contains_car_types",
                                 "test_estimate_ride_hailing_has_five_types",
                                 "test_estimate_response_amount_is_numeric"])
def test_unconfirmed_http_fields_are_blocked_without_requests(name):
    module = importlib.import_module("cases.passenger_v1_6_0.test_v160_http_api_real")
    method = getattr(module.TestV160EstimateApi, name)
    assert any(mark.name == "skip" and "需求未明确" in mark.kwargs["reason"]
               for mark in method.pytestmark)
    with pytest.raises(NotImplementedError):
        method(module.TestV160EstimateApi())
