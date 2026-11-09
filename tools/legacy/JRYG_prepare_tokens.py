"""历史接口辅助工具：准备乘客端 token 和司机端会话文件。

当前香港iOS全UI订单不调用本文件；直接运行可能发送登录请求并写会话文件，
不能用于司机UI出车、接单或支付核验的替代路径。保留历史入口，不改变其逻辑。

用 urllib 直接发 HTTP 请求（绕过 requests/urllib3 兼容性问题）。

生成：
  1. 乘客端登录 access_token → 写入 tmp/passenger_token.txt（已弃用，不再获取）
  2. 司机端 smsCodeLogin 完整 JSON 回包 → 写入 tmp/driver_session.json

输出 export 命令供 source 使用。

注意：乘客端 token 不再获取（与 App UI 登录互踢），改用司机端降级方案。
"""

import base64       # 编码 Yg-Header-Hint-Content 头
import hashlib      # 生成 MD5 签名
import json         # 解析/序列化 JSON 响应
import os
import sys
import time         # 时间戳（nonce、trace_id）
import urllib.parse # URL 编码表单数据
import urllib.request  # 发送 HTTP 请求（绕过 requests 依赖）
from pathlib import Path  # 文件路径操作

# 历史工具从tools/legacy定位原工作区根，输出仍保留在香港UI项目的tmp中。
UI_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = UI_DIR.parent
sys.path.insert(0, str(BASE_DIR))

# 导入港版 API 配置（签名密钥、手机号、URL 等）
from JRYG_Passenger_API_HK.common.hk_config import config

# 签名密钥（用于接口请求签名）
SIGN_KEY = config.SIGN_KEY
# 区号（港版 +852）
AREA_CODE = config.AREA_CODE
# 乘客端测试手机号
PASSENGER_MOBILE = config.PASSENGER_MOBILE
# 司机端测试手机号
DRIVER_MOBILE = config.DRIVER_MOBILE
# 测试验证码（固定 123456）
CAPTCHA = "123456"

# 乘客端 API 基地址
PASSENGER_BASE = config.PASSENGER_BASE_URL
# 司机端 API 基地址
DRIVER_BASE = config.DRIVER_BASE_URL

# 司机端设备编号
DRIVER_DEVICE_NO = config.DRIVER_DEVICE_NO
# 司机端初始纬度（香港）
DRIVER_LATITUDE = config.DRIVER_LATITUDE
# 司机端初始经度（香港）
DRIVER_LONGITUDE = config.DRIVER_LONGITUDE
# 城市 ID（香港）
CITY_ID = config.CITY_ID


def build_hint_content():
    """构造 Yg-Header-Hint-Content 头（Base64 编码的 JSON）。"""
    hint = {
        "app_timeout_ms": "15",
        "city_id": CITY_ID,
        "device_no": DRIVER_DEVICE_NO,
        "loc_lat": DRIVER_LATITUDE,
        "loc_lng": DRIVER_LONGITUDE,
        "loc_type": "12",
        "timestamp_unix": str(int(time.time())),
    }
    return base64.b64encode(json.dumps(hint).encode()).decode()


def generate_sign(params: dict, bundle_version: str = None) -> str:
    """参数按 key 升序拼接 + &key=SIGN_KEY → MD5 大写。

    乘客端末尾只追加 &key=SIGN_KEY。
    司机端末尾追加 &key=SIGN_KEY&yg_bundle_version=1.2.2。
    """
    sorted_str = "&".join(f"{k}={params[k]}" for k in sorted(params))
    raw = sorted_str + f"&key={SIGN_KEY}"
    if bundle_version:
        raw += f"&yg_bundle_version={bundle_version}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def post_form(base_url: str, uri: str, body: dict, headers_extra: dict,
              bundle_version: str = None) -> dict:
    """用 urllib 发 POST 表单请求。"""
    nonce = str(int(time.time() * 1000))
    sign_params = dict(body)
    sign_params["nonce"] = nonce
    sign = generate_sign(sign_params, bundle_version)

    final_body = dict(body)
    final_body["nonce"] = nonce

    data = urllib.parse.urlencode(final_body).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "YGPassenger/1.4.0(Android;Android16;SM-S9280;guanwang)",
        "Accept-Encoding": "identity",
        "Yg-Language": "zh-HK",
        "Accept-Language": "zh-HK",
        "Yg-Bundle-Version": "1.4.0",
        "data-type": "0",
        "sign": sign,
    }
    headers.update(headers_extra)

    url = f"{base_url}{uri}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def login_passenger():
    """乘客端登录，返回 access_token。"""
    # 1. 发送验证码
    body = {"area_code": AREA_CODE, "mobile": PASSENGER_MOBILE, "scene": "100"}
    resp = post_form(PASSENGER_BASE, "/passenger/user/sendAuthCode", body, {})
    assert resp.get("code") == 10000, f"乘客端发送验证码失败: {resp}"
    print(f"[乘客端] 验证码已发送")
    time.sleep(0.5)

    # 2. 登录
    body = {
        "area_code": AREA_CODE,
        "mobile": PASSENGER_MOBILE,
        "captcha": CAPTCHA,
        "login_method": "0",
    }
    resp = post_form(PASSENGER_BASE, "/passenger/user/login", body, {})
    assert resp.get("code") == 10000, f"乘客端登录失败: {resp}"
    token = resp["data"]["access_token"]
    print(f"[乘客端] 登录成功, user_id={resp['data'].get('user_id')}, token={token[:12]}...")
    return token


def login_driver():
    """司机端登录，返回完整 JSON 回包。"""
    driver_headers = {
        "User-Agent": "YGDriver/1.2.2(Android;Android14;Pixel 8;guangwang)",
        "Yg-Bundle-Version": "1.2.2",
        "Yg-Header-Hint-Content": build_hint_content(),
    }

    # 1. 登录场景检查（GET，可能返回签名有误但不影响后续流程）
    scene_url = f"{DRIVER_BASE}/driverApi/passport/loginSceneCheck?country_code={urllib.parse.quote(AREA_CODE)}&mobile={DRIVER_MOBILE}&nonce={int(time.time()*1000)}"
    scene_sign_params = {"country_code": AREA_CODE, "mobile": DRIVER_MOBILE,
                         "nonce": str(int(time.time() * 1000))}
    scene_sign = generate_sign(scene_sign_params, "1.2.2")
    scene_req = urllib.request.Request(scene_url, headers={**driver_headers, "sign": scene_sign})
    try:
        with urllib.request.urlopen(scene_req, timeout=15) as resp:
            scene_resp = json.loads(resp.read().decode("utf-8"))
        print(f"[司机端] 场景检查: code={scene_resp.get('code')}")
    except Exception as e:
        print(f"[司机端] 场景检查跳过: {e}")
    time.sleep(0.3)

    # 2. 发送验证码
    body = {
        "country_code": AREA_CODE,
        "business_type": "driver_login_code",
        "mobile": DRIVER_MOBILE,
    }
    resp = post_form(DRIVER_BASE, "/driverApi/passport/sendCode", body, driver_headers,
                     bundle_version="1.2.2")
    print(f"[司机端] 发送验证码: code={resp.get('code')}, msg={resp.get('message')}")
    time.sleep(2)  # 等待验证码缓存写入

    # 3. 验证码登录（带重试）
    body = {
        "country_code": AREA_CODE,
        "code": CAPTCHA,
        "codeType": "0",
        "mobile": DRIVER_MOBILE,
    }
    for attempt in range(1, 4):
        resp = post_form(DRIVER_BASE, "/driverApi/passport/smsCodeLogin", body, driver_headers,
                         bundle_version="1.2.2")
        code = resp.get("code")
        if code == 10000:
            break
        print(f"[司机端] 登录尝试{attempt}失败: code={code}, msg={resp.get('message')}")
        if attempt < 3:
            # 重新发送验证码再试
            time.sleep(5)
            send_body = {
                "country_code": AREA_CODE,
                "business_type": "driver_login_code",
                "mobile": DRIVER_MOBILE,
            }
            send_resp = post_form(DRIVER_BASE, "/driverApi/passport/sendCode", send_body,
                                  driver_headers, bundle_version="1.2.2")
            print(f"[司机端] 重新发送验证码: code={send_resp.get('code')}")
            time.sleep(3)
    assert resp.get("code") == 10000, f"司机端登录失败: {resp}"
    driver_info = resp.get("data", {}).get("driver_info", {})
    print(f"[司机端] 登录成功, driver_id={driver_info.get('driver_id')}, "
          f"name={driver_info.get('driver_name')}")
    return resp


def main():
    """主入口：执行司机端登录并保存会话文件。

    乘客端 token 不再获取（与 App UI 登录互踢，改用司机端降级方案）。

    :return: (空字符串, 司机端会话文件路径) 元组。
    """
    # 执行司机端登录，获取完整 JSON 回包
    session = login_driver()

    # 创建 tmp 目录（存放会话文件）
    tmp_dir = UI_DIR / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    # 将司机端会话 JSON 写入文件，供后续测试读取
    session_file = tmp_dir / "driver_session.json"
    session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    # 乘客端 token 文件留空（不再使用）
    token_file = tmp_dir / "passenger_token.txt"
    token_file.write_text("", encoding="utf-8")

    # 输出 export 命令，供 shell source 使用
    print(f"\n[完成]")
    print(f"  passenger_token=（不再使用，改用司机端降级）")
    print(f"  session_file={session_file}")
    print()
    print(f"export HK_PASSENGER_ACCESS_TOKEN=''")
    print(f"export HK_DRIVER_SESSION_FILE='{session_file}'")
    sys.stdout.flush()

    return "", str(session_file)


if __name__ == "__main__":
    # 直接运行此文件时执行 main()，生成会话文件
    main()
