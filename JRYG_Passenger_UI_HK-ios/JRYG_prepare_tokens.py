"""准备 E2E 测试所需的乘客端 token 和司机端会话文件。

用 urllib 直接发 HTTP 请求（绕过 requests/urllib3 兼容性问题）。

生成：
  1. 乘客端登录 access_token → 写入 tmp/passenger_token.txt
  2. 司机端 smsCodeLogin 完整 JSON 回包 → 写入 tmp/driver_session.json

输出 export 命令供 source 使用。
"""

import base64
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from JRYG_Passenger_API_HK.common.hk_config import config

SIGN_KEY = config.SIGN_KEY
AREA_CODE = config.AREA_CODE
PASSENGER_MOBILE = config.PASSENGER_MOBILE
DRIVER_MOBILE = config.DRIVER_MOBILE
CAPTCHA = "123456"

PASSENGER_BASE = config.PASSENGER_BASE_URL
DRIVER_BASE = config.DRIVER_BASE_URL

DRIVER_DEVICE_NO = config.DRIVER_DEVICE_NO
DRIVER_LATITUDE = config.DRIVER_LATITUDE
DRIVER_LONGITUDE = config.DRIVER_LONGITUDE
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
    # 乘客端 token 不再获取（与 App 登录互踢，改用司机端降级）
    """main —— 公开方法：main。

        :return: None"""
    session = login_driver()

    tmp_dir = Path(__file__).resolve().parent / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    session_file = tmp_dir / "driver_session.json"
    session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    token_file = tmp_dir / "passenger_token.txt"
    token_file.write_text("", encoding="utf-8")

    print(f"\n[完成]")
    print(f"  passenger_token=（不再使用，改用司机端降级）")
    print(f"  session_file={session_file}")
    print()
    print(f"export HK_PASSENGER_ACCESS_TOKEN=''")
    print(f"export HK_DRIVER_SESSION_FILE='{session_file}'")
    sys.stdout.flush()

    return "", str(session_file)


if __name__ == "__main__":
    main()
