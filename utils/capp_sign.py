"""
API 签名模块 —— form-urlencoded 模式

真实请求格式：
    - Content-Type: application/x-www-form-urlencoded
    - Sign 放在 Header 中
    - Body 为 key=value 格式
    - 签名结果大写 MD5
"""
import hashlib
import json


def md5_encode(text: str) -> str:
    """MD5 编码（大写）"""
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()


def _serialize_value(v) -> str:
    """将参数值序列化为字符串：dict/list 转为 JSON，其他转为字符串"""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(',', ':'), ensure_ascii=False)
    return str(v)


def driver_app_sign(data: dict, key: str) -> str:
    """
    App 接口签名算法

    规则:
    1. 按 key 字母顺序排序
    2. 拼接为 key1=value1&key2=value2 格式（含 JSON 序列化）
    3. 末尾追加 &key=SECRET_KEY
    4. MD5 加密，返回大写
    """
    filtered = {k: v for k, v in data.items() if v is not None and k != "sign"}
    sorted_keys = sorted(filtered.keys())
    param_str = "&".join(f"{k}={_serialize_value(filtered[k])}" for k in sorted_keys)
    sign_str = f"{param_str}&key={key}"
    return md5_encode(sign_str)



def build_base_secret(token: str = "") -> str:
    """Base-Secret: MD5(token)，未登录时 MD5 空字符串"""
    return md5_encode(token or "")


def build_form_body(data: dict) -> str:
    """
    构建 form-urlencoded 请求体
    排序并拼接为 key1=value1&key2=value2
    dict/list 类型自动 JSON 序列化
    """
    sorted_keys = sorted(data.keys())
    return "&".join(f"{k}={_serialize_value(data[k])}" for k in sorted_keys)
