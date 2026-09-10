"""
接口自动化测试框架 —— 数据驱动模式
    测试用例全部在 config.yaml 中定义，框架自动处理签名、断言、报告

真实请求格式:
    - Content-Type: application/x-www-form-urlencoded
    - Sign 放在请求头
    - 请求头含 Base-Secret / Do-Encrypt / Encrypt-Status
    - Body 为 key=value 格式
"""
import json
import os
import re
import time
from collections import OrderedDict

import requests
import yaml
from loguru import logger

from utils.capp_sign import build_base_secret, build_form_body, driver_app_sign

# 配置日志
os.makedirs("test_log", exist_ok=True)
log_file = f"test_log/api_test_{time.strftime('%Y%m%d_%H%M%S')}.log"
logger.add(log_file, rotation="10 MB", retention="7 days", encoding="utf-8", level="INFO")


def _resolve_vars(obj, variables: dict):
    """递归解析 ${var_name} 变量引用"""
    if isinstance(obj, str):
        def repl(m):
            var_name = m.group(1)
            return str(variables.get(var_name, m.group(0)))
        return re.sub(r"\$\{(\w+)\}", repl, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_vars(v, variables) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_vars(v, variables) for v in obj]
    return obj


def _get_json_path(data: dict, path: str):
    """从 JSON 中按路径取值，如 'data.access_token', 'data.estimates.0.price_token'"""
    keys = path.split(".")
    current = data
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        elif isinstance(current, list) and k.isdigit():
            idx = int(k)
            current = current[idx] if idx < len(current) else None
        else:
            return None
    return current


def _assert_result(resp, resp_json: dict, assertions: list) -> (bool, str):
    """执行断言校验"""
    for rule in assertions:
        typ = rule.get("type", "")
        expected = rule.get("expected")
        operator = rule.get("operator", "==")

        if typ == "status_code":
            actual = resp.status_code
        elif typ == "json_path":
            actual = _get_json_path(resp_json, rule.get("path", ""))
        else:
            return False, f"未知断言类型: {typ}"

        if operator == "==" and actual != expected:
            return False, f"[{typ}] 期望={expected}, 实际={actual}"
        elif operator == "!=" and actual == expected:
            return False, f"[{typ}] 期望 != {expected}, 但实际为 {expected}"
        elif operator == ">" and not (actual is not None and actual > expected):
            return False, f"[{typ}] 期望 > {expected}, 实际={actual}"
        elif operator == "<" and not (actual is not None and actual < expected):
            return False, f"[{typ}] 期望 < {expected}, 实际={actual}"
        elif operator == ">=" and not (actual is not None and actual >= expected):
            return False, f"[{typ}] 期望 >= {expected}, 实际={actual}"
        elif operator == "<=" and not (actual is not None and actual <= expected):
            return False, f"[{typ}] 期望 <= {expected}, 实际={actual}"
        elif operator == "contains" and expected not in str(actual):
            return False, f"[{typ}] 期望包含 '{expected}', 实际={actual}"
        elif operator == "in" and actual not in expected:
            return False, f"[{typ}] 期望 in {expected}, 实际={actual}"

    return True, "全部断言通过"


class ApiTestFramework:
    """接口自动化测试框架"""

    def __init__(self, config_dir: str = "config"):
        # 从 config/ 目录加载拆分后的配置文件
        self.config = {}
        for name in ("base", "variables", "categories"):
            cfg_file = os.path.join(config_dir, f"{name}.yaml")
            if os.path.isfile(cfg_file):
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                # base/variables 直接平铺到 config 下，categories 保持嵌套
                if name == "base":
                    self.config["base"] = data
                elif name == "variables":
                    self.config["variables"] = data
                elif name == "categories":
                    self.config["categories"] = data.get("categories", [])

        base = self.config.get("base", {})
        self.base_url = base.get("base_url", "").rstrip("/")
        self.sign_key = base.get("sign_key", "")
        self.timeout = base.get("timeout", 10)
        self.default_headers = base.get("headers", {
            "User-Agent": "YGPassenger/5.6.0(iOS;iOS15.6.1;iPhone13,4;appstore)",
            "Do-Encrypt": "2",
            "Encrypt-Status": "2",
        })

        self.variables = self.config.get("variables", {})
        base_cfg = self.config.get("base", {})
        for key in ["sign_key"]:
            if key in base_cfg and key not in self.variables:
                self.variables[key] = base_cfg[key]
        self.results = []
        self.session = requests.Session()
        self._login_setup = self.config.get("base", {}).get("setup_login")

        # 加载各分类的测试用例
        self.test_cases = self._load_categories()

    def _load_categories(self) -> list:
        """加载 test_cases/ 下各分类的用例，附加 category 字段"""
        categories = self.config.get("categories", [])
        all_cases = []

        # 同时兼容旧格式：config.yaml 中直接定义 test_cases
        inline_cases = self.config.get("test_cases", [])
        for case in inline_cases:
            case["category"] = ""
            all_cases.append(case)

        for cat in categories:
            cat_file = os.path.join("test_cases", cat, "config.yaml")
            if not os.path.isfile(cat_file):
                logger.warning(f"  分类 [{cat}] 配置文件不存在: {cat_file}")
                continue
            with open(cat_file, "r", encoding="utf-8") as f:
                cat_config = yaml.safe_load(f) or {}
            cat_cases = cat_config.get("test_cases", [])
            # 分类级 base_url 覆盖（如司机端/管理后台/高德地图等独立域名）
            cat_base_url = cat_config.get("base_url", "").rstrip("/")
            for case in cat_cases:
                case["category"] = cat
                # 用例级 base_url 优先，其次分类级 base_url
                if not case.get("base_url") and cat_base_url:
                    case["base_url"] = cat_base_url
                all_cases.append(case)
            if cat_base_url:
                logger.info(f"  加载分类 [{cat}]: {len(cat_cases)} 条用例 (base_url={cat_base_url})")
            else:
                logger.info(f"  加载分类 [{cat}]: {len(cat_cases)} 条用例")

        return all_cases

    def log_result(self, case_name: str, passed: bool, detail: str = "", category: str = ""):
        status = "PASS" if passed else "FAIL"
        prefix = f"[{category}] " if category else ""
        if passed:
            logger.success(f"  {chr(10003)} {prefix}{case_name}")
        else:
            logger.error(f"  {chr(10007)} {prefix}{case_name}  |  {detail}")
        self.results.append({
            "case": case_name,
            "category": category,
            "status": status,
            "detail": detail,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _send(self, method: str, path: str, params: dict, desc: str,
              extra_headers: dict = None, access_token: str = "",
              body_type: str = "form", base_url: str = "",
              sign_key: str = "") -> (requests.Response, dict):
        """
        发送请求：添加 nonce → 签名 → 设置请求头 → 发送

        body_type: "form" (默认) → application/x-www-form-urlencoded
                   "json"         → application/json
        base_url: 用例级覆盖（如高德地图等独立域名），为空则用全局 base_url
        sign_key: 用例级签名密钥（如司机端独立签名），为空则用全局 sign_key
        GET:  参数拼接到 URL query string
        """
        url = f"{base_url or self.base_url}{path}"
        method = method.upper()

        # 1. 添加 nonce（毫秒时间戳）
        params["nonce"] = str(int(time.time() * 1000))

        # 2. 签名
        sign_val = driver_app_sign(params, sign_key or self.sign_key)
        logger.info(f"    [DEBUG] sign_type=default, key={sign_key or self.sign_key}, params={list(params.keys())}")

        # 3. 请求头
        headers = dict(self.default_headers)
        headers.update({
            "Sign": sign_val,
            "Base-Secret": build_base_secret(access_token),
            "Accept": "*/*",
        })
        # Cookie 方式传递 token（解决部分接口 Authorization 头无法被正确解析的问题）
        if access_token:
            headers["Cookie"] = f"yg_access_token={access_token}"
        if extra_headers:
            headers.update(extra_headers)

        logger.info(f"  [{desc}] {method} {url}")
        logger.info(f"    参数: {params}")
        logger.info(f"    Headers: { {k: v[:50]+'...' if isinstance(v, str) and len(v)>50 else v for k, v in headers.items() if k not in ('User-Agent', 'Accept')} }")
        logger.info(f"    Sign={sign_val}")

        try:
            if method == "GET":
                # GET: 参数拼接到 query string
                form_body = build_form_body(params)
                url = f"{url}?{form_body}"
                logger.info(f"    query: ?{form_body}")
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
            else:
                # POST: form-urlencoded 或 JSON body
                if body_type == "json":
                    headers["Content-Type"] = "application/json"
                    body_str = json.dumps(params, ensure_ascii=False)
                    logger.info(f"    json body: {body_str[:500]}")
                    resp = self.session.post(url, data=body_str, headers=headers, timeout=self.timeout)
                else:
                    form_body = build_form_body(params)
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    logger.info(f"    body: {form_body}")
                    resp = self.session.post(url, data=form_body, headers=headers, timeout=self.timeout)

            logger.info(f"    响应: status={resp.status_code}, len={len(resp.text)}, "
                        f"Encrypt={resp.headers.get('Encrypt-Status')}, "
                        f"DataType={resp.headers.get('Data-Type')}")

            # 解析 JSON 响应
            resp_json = {}
            if resp.text.strip():
                try:
                    resp_json = resp.json()
                    logger.info(f"    响应体: {json.dumps(resp_json, ensure_ascii=False)[:500]}")
                except Exception:
                    logger.warning(f"    JSON 解析失败: {resp.text[:200]}")

            return resp, resp_json

        except requests.RequestException as e:
            logger.error(f"    请求异常: {e}")
            raise

    def _clear_sms_cache(self):
        """发送验证码前清除 Redis 频率限制缓存"""
        redis_config = self.config.get("redis", {})
        if not redis_config:
            return
        try:
            import redis
            r = redis.Redis(
                host=redis_config.get("host", "127.0.0.1"),
                port=redis_config.get("port", 6379),
                db=redis_config.get("db", 0),
                password=redis_config.get("password", ""),
            )
            key = redis_config.get("cache_key", "")
            if key:
                r.delete(key)
                logger.info(f"  [Redis] 已清除缓存 key: {key}")
        except Exception as e:
            logger.warning(f"  [Redis] 清除缓存异常: {e}")

    def _pre_send_code(self, pre_config: dict, tag: str = "", wait: int = 1):
        """发送验证码（登录前置步骤），返回是否成功"""
        if not pre_config:
            return True
        # 发送前清除 Redis 缓存，避免频率限制
        self._clear_sms_cache()
        send_path = pre_config.get("path", "")
        send_params = _resolve_vars(pre_config.get("params", {}), self.variables)
        label = f"{tag}发送验证码" if tag else "发送验证码"
        try:
            _, resp_json = self._send("POST", send_path, send_params, label)
            code = resp_json.get("code")
            if code == 10000:
                if wait > 0:
                    logger.info(f"  [{label}] 验证码发送成功，等待{wait}s使验证码生效...")
                    time.sleep(wait)
                else:
                    logger.info(f"  [{label}] 验证码发送成功（无等待）")
                return True
            else:
                logger.error(f"  [{label}] 验证码发送失败! code={code}, msg={resp_json.get('message', '')}")
                return False
        except Exception as e:
            logger.error(f"  [{label}] 验证码发送异常: {e}")
            return False

    def _do_setup_login(self, wait: int = 1):
        """前置登录：先发送验证码，再执行登录接口，将 token 等提取到 variables"""
        if not self._login_setup:
            return
        logger.info("-" * 55)
        logger.info("  [前置登录] 开始获取登录态...")

        # Step 1: 发送验证码
        pre_send = self._login_setup.get("pre_send_code")
        if not self._pre_send_code(pre_send, tag="前置登录-", wait=wait):
            logger.error("  [前置登录] 发送验证码失败，停止登录")
            logger.info("-" * 55)
            return

        # Step 2: 登录
        login_path = self._login_setup.get("path", "")
        login_params = _resolve_vars(self._login_setup.get("params", {}), self.variables)
        extract_map = self._login_setup.get("extract", {})

        try:
            _, resp_json = self._send("POST", login_path, login_params, "前置登录")

            if resp_json.get("code") == 10000:
                for var_name, json_path in extract_map.items():
                    val = _get_json_path(resp_json, json_path)
                    if val is not None:
                        self.variables[var_name] = val
                        logger.info(f"    {var_name} = {str(val)[:50]}...")
                logger.info("  [前置登录] 登录成功，token 已就绪")
            else:
                logger.error(f"  [前置登录] 登录失败! code={resp_json.get('code')}, "
                             f"msg={resp_json.get('message', '')}")
        except Exception as e:
            logger.error(f"  [前置登录] 登录异常: {e}")
        logger.info("-" * 55)

    def run(self):
        """执行全部测试用例"""
        total = len(self.test_cases)
        categories_list = self.config.get("categories", [])
        cat_info = f", 分类: {', '.join(categories_list)}" if categories_list else ""

        logger.info("=" * 55)
        logger.info(f"  接口自动化测试开始 | 用例数: {total}{cat_info}")
        logger.info(f"  目标地址: {self.base_url}")
        logger.info("=" * 55)

        # 统一前置登录：只执行一次，后续所有 need_login 用例复用同一 token
        self._do_setup_login()

        for idx, case in enumerate(self.test_cases, 1):
            name = case.get("name", f"Case-{idx}")
            category = case.get("category", "")
            desc = case.get("description", "")
            method = case.get("method", "POST")
            path = case.get("path", "")
            params = case.get("params", {})
            body_type = case.get("body_type", "form")
            assertions = case.get("asserts", [])
            repeat = case.get("repeat", 1)

            # 动态生成预约用车时间为未来时间（2天后，格式 YYYY-MM-DD HH:mm）
            from datetime import datetime, timedelta
            future = datetime.now() + timedelta(days=2)
            self.variables["Use_Time"] = future.strftime("%Y-%m-%d %H:%M")
            self.variables["Reserve_Use_Time"] = self.variables["Use_Time"]

            # 变量替换
            params = _resolve_vars(params, self.variables)

            # 构建额外请求头
            extra_headers = {}
            need_login = case.get("need_login", False)
            token = ""

            # need_login: 只需从变量中取 token 设置 Authorization 头
            if need_login:
                # 如果用例配置了 re_login，先重新登录获取新 token（无等待）
                if case.get("re_login"):
                    self._do_setup_login(wait=0)
                token = self.variables.get("access_token", "")
                if token:
                    extra_headers["Authorization"] = f"Bearer {token}"
                else:
                    logger.warning(f"  登录未成功，跳过 Authorization 头")

            # 用例自定义 headers（支持 ${var}）
            for k, v in case.get("headers", {}).items():
                extra_headers[_resolve_vars(k, self.variables)] = _resolve_vars(v, self.variables)

            cat_tag = f"[{category}] " if category else ""
            logger.info(f"\n[{idx}/{total}] {cat_tag}{name}")
            if desc:
                logger.info(f"  说明: {desc}")

            try:
                resp, resp_json = None, {}
                for r in range(repeat):
                    resp, resp_json = self._send(method, path, params,
                                                 f"{name}-第{r+1}次" if repeat > 1 else name,
                                                 extra_headers=extra_headers,
                                                access_token=token,
                                                body_type=body_type,
                                                base_url=case.get("base_url", ""))

                # 响应提取：将响应中的字段存入全局变量
                extract_map = case.get("extract", {})
                if extract_map and resp_json:
                    for var_name, json_path in extract_map.items():
                        val = _get_json_path(resp_json, json_path)
                        if val is not None:
                            self.variables[var_name] = str(val)
                            logger.info(f"  [提取] {var_name} = {str(val)[:80]}")
                        else:
                            logger.warning(f"  [提取] {var_name} 未找到路径: {json_path}")

                if assertions:
                    passed, detail = _assert_result(resp, resp_json, assertions)
                    self.log_result(name, passed, detail, category)
                else:
                    passed = resp is not None and resp.status_code == 200
                    self.log_result(name, passed, f"HTTP {resp.status_code}" if resp else "无响应", category)

            except Exception as e:
                self.log_result(name, False, f"异常: {e}", category)

        self._print_report()

    def _print_report(self):
        """打印测试报告（按分类分组）"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = total - passed

        # 按分类分组
        groups = OrderedDict()
        for r in self.results:
            cat = r.get("category", "")
            groups.setdefault(cat, []).append(r)

        lines = [
            "",
            "=" * 55,
            "                 测 试 报 告",
            "=" * 55,
        ]
        for cat, items in groups.items():
            cat_label = f"[{cat}]" if cat else "[默认]"
            cat_passed = sum(1 for r in items if r["status"] == "PASS")
            lines.append(f"\n  ---- {cat_label} ({cat_passed}/{len(items)}) ----")
            for r in items:
                icon = chr(10003) if r["status"] == "PASS" else chr(10007)
                lines.append(f"    {icon} {r['case']}")
                if r["detail"]:
                    lines.append(f"         {r['detail']}")

        lines += [
            "",
            "-" * 55,
            f"  总计: {total}  |  通过: {passed}  |  失败: {failed}",
            f"  通过率: {passed / total * 100:.1f}%" if total else "  通过率: N/A",
            "=" * 55,
        ]

        for line in lines:
            logger.info(line)

        # 按分类统计
        cat_summary = {}
        for cat, items in groups.items():
            cat_passed = sum(1 for r in items if r["status"] == "PASS")
            cat_summary[cat or "default"] = {"total": len(items), "passed": cat_passed, "failed": len(items) - cat_passed}

        report_file = f"test_log/report_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "summary": {"total": total, "passed": passed, "failed": failed},
                "categories": cat_summary,
                "cases": self.results,
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"\nJSON 报告: {report_file}")
