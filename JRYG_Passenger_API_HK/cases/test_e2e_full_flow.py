"""端到端全流程测试：乘客下单 → 司机接单 → 状态流转 → 完成收款（纯接口）。

关键修正：
  1. 不能与App同时登录（token冲突），运行前先关闭App
  2. 结束行程(status=4)时坐标必须用订单终点坐标（否则"請按照導航繼續送乘客"）
  3. 状态流转从status=2开始（status=1是接单后自动进入）
  4. 接单(grab)后等待5秒让系统处理
  5. polling用order_no字段判断是否有订单（不是order_id）
  6. 估价时用搜索结果中的poi_id和car_type=taxi匹配

指派/抢单模式：
  - GET /driverApi/config/getDispatchConfig 返回 assign_mode/grab_mode 开关
  - assign_mode=true 时系统自动派单，polling可获取已派发订单
  - grab_mode=true 时司机可主动抢单
"""
import sys
import os
import time
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_API_HK.cases.JRYG_test_hk_api import HKApiClient
from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import HKDriverApiClient, DRIVER_LATITUDE, DRIVER_LONGITUDE
from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient
from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache

# 搜索关键词
BEGIN_SEARCH_KEYWORD = "銅鑼灣"
END_SEARCH_KEYWORD = "香港"

# 搜索定位坐标
SEARCH_LATITUDE = "22.278893"
SEARCH_LONGITUDE = "114.180418"

# 司机默认位置（铜锣湾附近）
DRIVER_LAT = DRIVER_LATITUDE  # 22.277409
DRIVER_LNG = DRIVER_LONGITUDE  # 114.188752

# 账单金额
ORDER_AMOUNT = "88"
OTHER_AMOUNT = "0"

# 等待时间
STATUS_WAIT = 2  # 状态变更间隔（秒）
GRAB_WAIT = 5  # 接单后等待（秒）
POLLING_TIMEOUT = 120  # polling超时（秒）— 增加到120秒等系统调度
POLLING_INTERVAL = 3  # polling间隔（秒）


def step(n, title):
    print(f"\n{'='*60}")
    print(f"  步骤 {n}: {title}")
    print(f"{'='*60}")


def ok(msg):
    print(f"  [✓] {msg}")


def fail(msg):
    print(f"  [✗] {msg}")


def info(msg):
    print(f"  [i] {msg}")


def check_code(resp, step_name, expected=10000):
    code = resp.get("code")
    if code == expected:
        ok(f"{step_name} 成功 (code={code})")
        return True
    else:
        fail(f"{step_name} 失败: code={code}, message={resp.get('message', '')}")
        return False


def main():
    print("\n" + "=" * 60)
    print("  端到端全流程测试：乘客下单 → 司机完成 → 收款（纯接口）")
    print("=" * 60)

    # ================================================================
    # 【测试前置】清理 Redis 缓存（避免上次测试的派单/抢单缓存干扰）
    # ================================================================
    step(0, "清理 Redis driver 缓存（agent/phone/grab/publish）")
    try:
        deleted = clean_driver_cache()
        ok(f"Redis 缓存清理完成，删除 {deleted} 个 key")
    except Exception as e:
        fail(f"Redis 缓存清理失败: {e}（继续测试）")

    # ================================================================
    # 【司机端】登录 + 出车
    # ================================================================
    step(1, "司机端 - 登录")
    driver = HKDriverApiClient()

    _, resp = driver.send_auth_code()
    check_code(resp, "发送验证码")

    _, resp = driver.login()
    if not check_code(resp, "验证码登录"):
        return
    driver.access_token = resp["data"]["sign_info"]["access_token"]
    driver_info = resp["data"]["driver_info"]
    ok(f"司机: {driver_info.get('driver_name')} (id={driver_info.get('driver_id')}, car_type={driver_info.get('car_type')})")

    # ================================================================
    step(2, "司机端 - 出车上线")
    _, resp = driver.handle_work_status(1)
    if not check_code(resp, "出车上线"):
        return
    info(f"提示: {resp.get('data', {}).get('voice_text', '')}")

    # ================================================================
    # 【关键】启动 Socket 长连接：登录 + 心跳 + 位置上报
    # 没有 Socket 长连接，服务端不知道司机位置，不会派发订单
    # ================================================================
    step("2.5", "司机端 - 启动 Socket 长连接（位置上报）")
    socket_client = JRYGSocketClient(driver.access_token, lat=DRIVER_LAT, lng=DRIVER_LNG)
    if not socket_client.connect():
        fail("Socket 长连接失败！polling 将无法收到订单")
        return
    ok("Socket 长连接已建立，心跳 + 位置上报已启动")
    # 等待位置上报稳定
    info("等待 10 秒让位置上报稳定...")
    time.sleep(10)

    # ================================================================
    step(3, "司机端 - 查询派单配置 (getDispatchConfig)")
    _, resp = driver.get("/driverApi/config/getDispatchConfig")
    if check_code(resp, "派单配置"):
        options = resp.get("data", {}).get("options", {})
        info(f"指派模式(assign_mode): {options.get('assign_mode')}")
        info(f"抢单模式(grab_mode): {options.get('grab_mode')}")
        info(f"预约模式(booking_mode): {options.get('booking_mode')}")

    # ================================================================
    # 【乘客端】登录 + 搜索 + 估价 + 下单
    # ================================================================
    step(4, "乘客端 - 登录")
    passenger = HKApiClient()

    _, resp = passenger.send_auth_code()
    check_code(resp, "发送验证码")

    _, resp = passenger.login()
    if not check_code(resp, "验证码登录"):
        return
    passenger.access_token = resp["data"]["access_token"]
    ok(f"乘客 user_id: {resp['data'].get('user_id')}")

    # 清理未完成订单
    passenger.cleanup_unfinished_orders()

    # ================================================================
    step(5, "乘客端 - 搜索起终点地址")
    _, resp = passenger.search_address(
        SEARCH_LATITUDE, SEARCH_LONGITUDE, 1, name=BEGIN_SEARCH_KEYWORD)
    if not check_code(resp, "搜索起点"):
        return
    begin = resp["data"]["list"][0]
    info(f"起点: {begin['name']} (lat={begin['latitude']}, lng={begin['longitude']}, poi_id={begin.get('poi_id')})")

    _, resp = passenger.search_address(
        SEARCH_LATITUDE, SEARCH_LONGITUDE, 2, name=END_SEARCH_KEYWORD)
    if not check_code(resp, "搜索终点"):
        return
    end = resp["data"]["list"][0]
    info(f"终点: {end['name']} (lat={end['latitude']}, lng={end['longitude']}, poi_id={end.get('poi_id')})")

    # ================================================================
    step(6, "乘客端 - 估价")
    _, resp = passenger.estimate_order(
        begin_location=begin["name"],
        begin_latitude=begin["latitude"],
        begin_longitude=begin["longitude"],
        end_location=end["name"],
        end_latitude=end["latitude"],
        end_longitude=end["longitude"],
        begin_poi_id=begin.get("poi_id", ""),
        end_poi_id=end.get("poi_id", ""),
    )
    if not check_code(resp, "估价"):
        return

    estimates = resp.get("data", {}).get("estimates", [])
    if not estimates:
        fail("无估价结果")
        return
    # 优先选择taxi类型
    taxi = next((e for e in estimates if e.get("car_type") == "taxi"), estimates[0])
    estimate_id = taxi.get("estimate_id")
    info(f"估价ID: {estimate_id}, car_type: {taxi.get('car_type')}")

    # ================================================================
    step(7, "乘客端 - 下单")
    _, resp = passenger.create_order(estimate_id=estimate_id)
    if not check_code(resp, "下单"):
        return
    order_no = resp["data"]["order_no"]
    ok(f"订单号: {order_no}")

    # ================================================================
    step(8, f"乘客端 - 查询订单状态（下单后）")
    _, resp = passenger.get_order_status(order_no)
    info(f"order_status: {resp.get('data', {}).get('order_status')}")

    # ================================================================
    # 【司机端】轮询 + 接单
    # ================================================================
    step(9, f"司机端 - 轮询订单（超时{POLLING_TIMEOUT}s）")
    info(f"司机位置: lat={DRIVER_LAT}, lng={DRIVER_LNG}")

    polled_order = None
    start_time = time.time()
    poll_count = 0

    while time.time() - start_time < POLLING_TIMEOUT:
        poll_count += 1
        _, resp = driver.polling_order()
        code = resp.get("code")
        if code != 10000:
            fail(f"polling异常: code={code}, msg={resp.get('message')}")
            time.sleep(POLLING_INTERVAL)
            continue

        data = resp.get("data", {})
        # 用order_no判断（不是order_id）
        polled_no = data.get("order_no", "")
        if polled_no and polled_no != "":
            polled_order = data
            ok(f"第{poll_count}次轮询获取到订单! order_no={polled_no}")
            info(f"order_id: {data.get('order_id')}, order_status: {data.get('order_status')}")
            break

        if poll_count % 5 == 0:
            info(f"第{poll_count}次轮询... 暂无订单 (elapsed={time.time()-start_time:.0f}s)")
        time.sleep(POLLING_INTERVAL)

    if not polled_order:
        fail("polling超时，尝试直接grab接单")
        # 即使polling没拿到，也尝试直接grab
        _, resp = driver.grab_order(order_no)
        info(f"grab响应: code={resp.get('code')}, msg={resp.get('message')}")
        if resp.get("code") != 10000:
            fail("直接接单也失败，取消订单并退出")
            passenger.prepare_cancel_order(order_no)
            passenger.cancel_order(order_no)
            return
        ok("直接接单请求已受理")
    else:
        if polled_order.get("order_no") != order_no:
            info(f"注意: polled订单号({polled_order.get('order_no')}) != 乘客下单({order_no})")

    # ================================================================
    step(10, "司机端 - 接单")
    # 指派模式下 grab 返回 23000，但订单已自动派发给司机
    # 直接调用 serviceChange status=1 即可完成接单
    _, resp = driver.grab_order(order_no)
    info(f"grab响应: code={resp.get('code')}, msg={resp.get('message')}")
    if resp.get("code") == 10000:
        ok(f"接单成功! 等待{GRAB_WAIT}秒...")
    elif resp.get("code") == 10011:
        ok("订单已被自己接走，继续")
    elif resp.get("code") == 23000 and polled_order:
        # 指派模式: grab 不可用，但订单已派发，直接 serviceChange
        ok(f"指派模式: 订单已派发(status={polled_order.get('order_status')}), 跳过grab")
    else:
        if polled_order and polled_order.get("order_no") == order_no:
            ok(f"订单已通过指派派发, 跳过grab")
        else:
            fail(f"接单失败: {resp}")
            passenger.cancel_order(order_no)
            return
    time.sleep(GRAB_WAIT)

    # ================================================================
    # 【司机端】状态流转
    # 指派模式下 status=1(已出发) 是接单后的第一步
    # ================================================================
    step("10.5", "司机端 - 已出发 (serviceChange status=1)")
    _, resp = driver.service_change(order_no, service_status=1,
                                     latitude=DRIVER_LAT, longitude=DRIVER_LNG)
    if check_code(resp, "已出发"):
        order_data = resp.get("data", {}).get("order", {})
        service = resp.get("data", {}).get("service", {})
        info(f"order_status: {order_data.get('order_status')} ({order_data.get('order_status_name')})")
        info(f"service_status: {service.get('service_status')} ({service.get('service_status_name')})")
    time.sleep(STATUS_WAIT)

    # ================================================================
    # 【司机端】状态流转
    # ================================================================
    step(11, "司机端 - 到达上车地点 (serviceChange status=2)")
    _, resp = driver.service_change(order_no, service_status=2,
                                    latitude=DRIVER_LAT, longitude=DRIVER_LNG)
    if check_code(resp, "到达上车点"):
        order_data = resp.get("data", {}).get("order", {})
        service = resp.get("data", {}).get("service", {})
        info(f"order_status: {order_data.get('order_status')} ({order_data.get('order_status_name')})")
        info(f"service_status: {service.get('service_status')} ({service.get('service_status_name')})")
    time.sleep(STATUS_WAIT)

    # ================================================================
    step(12, "司机端 - 开始行程 (serviceChange status=3)")
    _, resp = driver.service_change(order_no, service_status=3,
                                    latitude=DRIVER_LAT, longitude=DRIVER_LNG)
    if check_code(resp, "开始行程"):
        order_data = resp.get("data", {}).get("order", {})
        service = resp.get("data", {}).get("service", {})
        info(f"order_status: {order_data.get('order_status')} ({order_data.get('order_status_name')})")
        info(f"service_status: {service.get('service_status')} ({service.get('service_status_name')})")
    time.sleep(STATUS_WAIT)

    # ================================================================
    # 模拟行驶到终点（Socket位置上报逐步移动）
    # 服务端要求司机沿导航路线行驶足够距离才能结束行程
    # 否则返回 20156 "請按照導航繼續送乘客"
    # ================================================================
    step("12.5", "模拟行驶到终点（Socket位置逐步移动）")
    _, detail = driver.get_service_detail(order_no)
    start_lat = float(begin["latitude"])
    start_lng = float(begin["longitude"])
    end_lat = float(end["latitude"])
    end_lng = float(end["longitude"])
    if detail.get("code") == 10000:
        order_detail = detail.get("data", {}).get("order", {})
        start_lat = float(order_detail.get("start_lat", start_lat))
        start_lng = float(order_detail.get("start_lng", start_lng))
        end_lat = float(order_detail.get("end_lat", end_lat))
        end_lng = float(order_detail.get("end_lng", end_lng))
    info(f"起点({start_lat},{start_lng}) → 终点({end_lat},{end_lng})")

    MOVE_STEPS = 30  # 30步×2秒=60秒
    for i in range(MOVE_STEPS + 1):
        t = i / MOVE_STEPS
        socket_client.lat = start_lat + (end_lat - start_lat) * t
        socket_client.lng = start_lng + (end_lng - start_lng) * t
        time.sleep(2)
        if (i + 1) % 10 == 0:
            info(f"行驶中 step {i+1}/{MOVE_STEPS}: ({socket_client.lat:.6f},{socket_client.lng:.6f})")
    ok("已到达终点附近")

    # ================================================================
    # 结束行程：必须用订单终点坐标，且需等待服务端状态同步
    step(13, "司机端 - 结束行程 (serviceChange status=4, 用终点坐标)")
    info(f"使用终点坐标: lat={end_lat}, lng={end_lng}")

    time.sleep(3)  # 等待服务端状态同步
    _, resp = driver.service_change(order_no, service_status=4,
                                    latitude=end_lat, longitude=end_lng)
    if check_code(resp, "结束行程"):
        service = resp.get("data", {}).get("service", {})
        info(f"service_status: {service.get('service_status')} ({service.get('service_status_name')})")
        info(f"next: {service.get('next_service_status')} ({service.get('next_service_status_name')})")
    else:
        info(f"完整响应: {resp}")
        # 如果返回20156（请按照导航继续送乘客），再行驶一段后重试
        if resp.get("code") == 20156:
            info("服务端要求继续行驶，再移动10步...")
            for i in range(10):
                socket_client.lat = end_lat
                socket_client.lng = end_lng
                time.sleep(2)
            _, resp = driver.service_change(order_no, service_status=4,
                                            latitude=end_lat, longitude=end_lng)
            check_code(resp, "结束行程(重试)")
        else:
            time.sleep(3)
            info("重试结束行程...")
            _, resp = driver.service_change(order_no, service_status=4,
                                            latitude=end_lat, longitude=end_lng)
            check_code(resp, "结束行程(重试)")
    time.sleep(STATUS_WAIT)

    # ================================================================
    step(14, f"司机端 - 确认账单 (confirmBill, 金额={ORDER_AMOUNT} HKD)")
    _, resp = driver.confirm_bill(order_no, order_amount=ORDER_AMOUNT, other_amount=OTHER_AMOUNT)
    check_code(resp, "确认账单")
    if resp.get("code") != 10000:
        info(f"响应: {resp}")
    time.sleep(STATUS_WAIT)

    # ================================================================
    step(15, "司机端 - 确认收款 (serviceChange status=5)")
    _, resp = driver.service_change(order_no, service_status=5,
                                    latitude=end["latitude"], longitude=end["longitude"])
    if check_code(resp, "确认收款"):
        ok("收款成功!")
    else:
        info(f"响应: {resp}")
    time.sleep(STATUS_WAIT)

    # ================================================================
    # 【验证】订单最终状态
    # ================================================================
    step(16, "司机端 - 行程详情（验证完成）")
    _, resp = driver.get_trip_detail(order_no)
    completed = False
    if resp.get("code") == 10000:
        order = resp.get("data", {}).get("order", {})
        fee = resp.get("data", {}).get("fee", {})
        completed = order.get("order_status") == 8 and order.get("pay_status") == 1
        ok(f"order_status: {order.get('order_status')} ({order.get('order_status_name')})")
        ok(f"pay_status: {order.get('pay_status')} ({order.get('pay_status_name')})")
        ok(f"order_fee: {fee.get('order_fee')} {fee.get('unit')}")
    else:
        fail(f"查询行程详情失败: {resp}")

    # ================================================================
    step(17, "乘客端 - 查询订单最终状态")
    _, resp = passenger.get_order_status(order_no)
    info(f"乘客端订单状态: {resp.get('data', {})}")

    # ================================================================
    step(18, "司机端 - 收车下线")
    _, resp = driver.handle_work_status(0)
    completed = check_code(resp, "收车下线") and completed

    # 断开 Socket 长连接
    socket_client.disconnect()
    ok("Socket 长连接已断开")

    # ================================================================
    print("\n" + "=" * 60)
    print("  端到端全流程测试结束")
    print("=" * 60)
    print(f"  订单号: {order_no}")
    print(f"  起点: {begin['name']}")
    print(f"  终点: {end['name']}")
    print(f"  账单设定金额: {ORDER_AMOUNT} HKD")
    print(f"  轮询次数: {poll_count}")
    print(f"  验证结果: {'通过' if completed else '失败'}")
    return completed


@pytest.mark.e2e
def test_e2e_full_flow():
    assert main(), "订单未达到已完成、已支付状态，或流程提前失败"


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
