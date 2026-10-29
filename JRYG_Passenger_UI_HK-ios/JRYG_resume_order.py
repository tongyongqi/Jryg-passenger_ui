"""续跑当前进行中的订单：完成司机端状态流转（status=4 结束行程 → status=5 确认收款）。

用途：
  上一次 E2E 运行已完成 UI 下单且司机 11000005 接单，但因地址搜索等待超时中断，
  留下一笔 service_status=3（已接载）的未完成订单。本脚本接管该订单并跑完后续流转。

安全约束（与 JRYG_order_guard 一致）：
  - 目标司机必须是 11000005（driver_id=31），否则拒绝操作
  - 起终点必须与测试路线一致
  - 订单未达终态（order_status=5 且 pay_status=1）不报通过
  - 状态流转用订单终点坐标，status=4 后等待 20 秒再继续

运行：
  export HK_PASSENGER_ACCESS_TOKEN=...
  export HK_DRIVER_SESSION_FILE=...
  python3 JRYG_resume_order.py
"""

import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from jryg_hk_ios.JRYG_order_api import HKOrderAPI
from jryg_hk_ios.JRYG_order_guard import OrderValidationError, number, require
from jryg_hk_ios.JRYG_logger import logger

START_NAMES = ("北角(地鐵站)", "北角地鐵站")
END_NAMES = ("香港大學",)
TARGET_DRIVER_ID = "31"
STATUS_WAIT_AFTER_4 = 20


def resolve_order_no(api):
    """确定要续跑的订单：优先用参数指定，否则取未完成列表中唯一一笔。"""
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if argv:
        return argv[0].strip()
    rows = api.unfinished()
    require(len(rows) == 1, f"未完成订单数量应为1，实际{len(rows)}，禁止猜测")
    return rows[0]["order_no"]


def main():
    """main —— 公开方法：main。

        :return: None"""
    api = HKOrderAPI.from_environment()
    require(api.driver_id == TARGET_DRIVER_ID,
            f"当前司机会话不是目标司机11000005(driver_id={TARGET_DRIVER_ID})")

    no = resolve_order_no(api)
    logger.info("【续跑】目标订单 order_no=%s", no)

    detail = api.service_detail(no)
    order = detail["order"]
    require(order.get("start_address") in START_NAMES and
            order.get("end_address") in END_NAMES,
            f"订单路线与测试路线不一致: {order.get('start_address')} → {order.get('end_address')}")

    coordinates = {}
    for key in ("start_lat", "start_lng", "end_lat", "end_lng"):
        try:
            coordinates[key] = float(order[key])
        except (KeyError, TypeError, ValueError):
            require(False, f"服务详情缺少有效坐标 {key}")
        limit = 90 if key.endswith("lat") else 180
        require(abs(coordinates[key]) <= limit, f"服务坐标无效 {key}")

    # 目标司机硬校验
    status = api.status(no)
    driver_id = str(status.get("driver_id"))
    require(driver_id == TARGET_DRIVER_ID,
            f"订单接单司机不是11000005(driver_id={driver_id})，拒绝流转")

    current = number(detail["service"].get("service_status"), "service_status")
    logger.info("【续跑】当前 service_status=%s, driver_id=%s", current, driver_id)

    # 状态流转：补齐到 status=4（结束行程）
    for step in range(current + 1, 5):
        point = "end" if step == 4 else "start"
        logger.info("【续跑】serviceChange status=%s (%s坐标)", step, point)
        api.service_change(no, step, coordinates[f"{point}_lat"], coordinates[f"{point}_lng"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = api.service_detail(no)
            if number(detail["service"].get("service_status"), "service_status") == step:
                break
            time.sleep(2)
        else:
            raise OrderValidationError(f"未能确认 service_status={step}，禁止继续")
        logger.info("【续跑】已核实 service_status=%s", step)

        if step == 4:
            logger.info("【续跑】到达目的地(status=4)后等待 %d 秒再继续", STATUS_WAIT_AFTER_4)
            time.sleep(STATUS_WAIT_AFTER_4)

    # 确认账单 + status=5 确认收款
    logger.info("【续跑】confirmBill 填写测试车费")
    api.confirm_bill(no, 5)

    logger.info("【续跑】serviceChange status=5 确认收款")
    api.service_change(no, 5, coordinates["end_lat"], coordinates["end_lng"])
    time.sleep(3)

    # 终态硬校验：passenger.order_status=5 && driver.order_status=8 && pay_status=1
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = api.status(no)
        trip = api.trip_detail(no)
        trip_order = trip.get("order", {})
        passenger_status = number(status.get("order_status"), "order_status")
        driver_status = number(trip_order.get("order_status"), "driver.order_status")
        pay_status = number(trip_order.get("pay_status"), "pay_status")
        logger.info("【续跑】passenger_status=%s driver_status=%s pay_status=%s",
                    passenger_status, driver_status, pay_status)
        if passenger_status == 5 and driver_status == 8 and pay_status == 1:
            logger.info("【续跑完成】order_no=%s 已完成且已支付，driver_id=%s",
                        no, TARGET_DRIVER_ID)
            break
        time.sleep(3)
    else:
        raise OrderValidationError("订单未达完成终态，禁止报告通过")

    remaining = api.unfinished()
    require(not remaining, f"仍存在未完成订单: {remaining}")
    logger.info("【续跑全部通过】无未完成订单")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error("【续跑失败】%s", exc)
        raise
