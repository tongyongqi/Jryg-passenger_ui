"""从 UI 时间线及客户端入口日志生成接口清单；原始日志只在内存中处理。"""

import argparse
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "JRYG_api_catalog.json"
ROLES = {"passenger": "乘客端", "driver": "司机端"}
SERVICES = {"passenger": "passenger", "driver": "driver-api-new"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
ENTRY_AWK = (r'/"category"[[:space:]]*:[[:space:]]*"api"/ && /[iI][oO][sS]/ '
             r'{buffer[count % limit]=$0; count++} '
             r'END {start=(count>limit ? count-limit : 0); '
             r'for(i=start; i<count; i++) print buffer[i % limit]}')


def load_config(namespace=None):
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if namespace or os.environ.get("HK_API_NAMESPACE"):
        config["namespace"] = namespace or os.environ["HK_API_NAMESPACE"]
    if os.environ.get("HK_TRACE_QUERY_PATH"):
        config["trace_query_path"] = os.environ["HK_TRACE_QUERY_PATH"]
    if os.environ.get("HK_API_CATALOG") == "0":
        config["enabled"] = False
    return config


def parse_time(value, timezone="Asia/Hong_Kong"):
    try:
        if isinstance(value, (float, int)):
            seconds = value / 1000 if value > 100000000000 else value
            return datetime.fromtimestamp(seconds, ZoneInfo(timezone))
        if not isinstance(value, str) or not value:
            return None
        text = value.strip().replace("Z", "+00:00")
        if re.fullmatch(r"\d{10}(?:\.\d+)?|\d{13}", text):
            return parse_time(float(text), timezone)
        text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
        result = datetime.fromisoformat(text)
        return result if result.tzinfo else result.replace(tzinfo=ZoneInfo(timezone))
    except (ValueError, OverflowError, OSError):
        return None


def safe_path(uri):
    if not isinstance(uri, str):
        return None
    try:
        path = unquote(urlsplit(uri).path)
    except ValueError:
        return None
    if not path.startswith("/") or re.search(r"[\s\\\x00-\x1f]", path):
        return None
    parts = []
    sensitive = {"token", "access_token", "mobile", "phone", "otp", "card", "email", "password"}
    previous = ""
    for part in path.split("/"):
        original = part
        if (previous in sensitive or part.isdigit() or "@" in part or re.fullmatch(r"[a-fA-F0-9-]{16,}", part)
                or (len(part) >= 10 and any(char.isdigit() for char in part))):
            part = "{id}"
        parts.append(part)
        previous = original.lower()
    return "/".join(parts)


def decode_lines(text):
    rows, bad = [], 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
        except ValueError:
            bad += 1
            continue
        rows.append((row, number))
    return rows, bad


def has_clue(row, clues):
    if not clues:
        return False
    fields = ("mobile", "phone", "phone_num", "driver_mobile", "order_no", "order_id",
              "trace_id", "request", "request_body", "request_query", "request_raw_query",
              "request_post")
    text = json.dumps({key: row[key] for key in fields if key in row}, ensure_ascii=False)
    return any(re.search(r"(?<![A-Za-z0-9])" + re.escape(str(clue)) + r"(?![A-Za-z0-9])", text)
               for clue in clues if clue)


def is_ios_client(row):
    headers = row.get("request_header") or row.get("headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except ValueError:
            headers = {}
    agent = str(row.get("user_agent") or "")
    if isinstance(headers, dict):
        agent += " " + " ".join(str(value) for key, value in headers.items() if key.lower() == "user-agent")
    return bool(re.search(r"\biOS", agent, re.IGNORECASE))


def read_steps(path):
    rows, bad = decode_lines(Path(path).read_text(encoding="utf-8"))
    merged = {}
    for row, _ in rows:
        key = row.get("step_id")
        if key:
            merged[key] = row
    return list(merged.values()), bad


def associate_step(timestamp, role, steps, padding):
    exact, nearby = [], []
    for row in steps:
        if row.get("role") != role:
            continue
        start = parse_time(row.get("started_at"))
        end = parse_time(row.get("finished_at"))
        if start is None or end is None:
            continue
        duration = (end - start).total_seconds()
        if start <= timestamp <= end:
            exact.append((duration, start, row))
        elif start - timedelta(seconds=padding) <= timestamp <= end + timedelta(seconds=padding):
            distance = min(abs((timestamp - start).total_seconds()), abs((timestamp - end).total_seconds()))
            nearby.append((distance, duration, start, row))
    if exact:
        return min(exact, key=lambda entry: (entry[0], -entry[1].timestamp()))[2], "时间窗关联，非因果证明"
    if nearby:
        return min(nearby, key=lambda entry: (entry[0], entry[1], -entry[2].timestamp()))[3], "邻近时间窗关联，待确认"
    return None, "未关联具体 UI 步骤"


def build_catalog(logs, steps, clues, config):
    timezone = config.get("server_timezone", "Asia/Hong_Kong")
    padding = float(config.get("step_padding_seconds", 5))
    starts = [parse_time(row.get("started_at")) for row in steps]
    ends = [parse_time(row.get("finished_at")) for row in steps]
    starts, ends = [t for t in starts if t], [t for t in ends if t]
    warnings = []
    if not starts or not ends:
        return [], ["没有完整 UI 时间窗，未查询或关联接口"]
    start, end = min(starts) - timedelta(seconds=padding), max(ends) + timedelta(seconds=padding)
    decoded = []
    for role, source, text in logs:
        rows, bad = decode_lines(text)
        if bad:
            warnings.append(f"{ROLES[role]}有 {bad} 行非 JSON 或截断日志，已跳过")
        for row, number in rows:
            timestamp = parse_time(row.get("time"), timezone)
            if timestamp is not None and start <= timestamp <= end:
                decoded.append((role, source, row, number, timestamp))
    traces = {role: set() for role in ROLES}
    identities = {role: set() for role in ROLES}

    def client_identity(role, row):
        for field in (("driver_id", "login_id") if role == "driver" else ("user_id", "login_id")):
            value = row.get(field)
            if value and str(value) != "0":
                return field, str(value)
        return None

    for role, _, row, _, _ in decoded:
        trace = row.get("trace_id")
        if has_clue(row, clues.get(role, set())):
            if trace:
                traces[role].add(str(trace))
            if row.get("category") == "api" and is_ios_client(row):
                identity = client_identity(role, row)
                if identity:
                    identities[role].add(identity)
    endpoints, seen = {}, set()
    for role, source, row, number, timestamp in decoded:
        if row.get("category") != "api" or not is_ios_client(row):
            continue
        if not (has_clue(row, clues.get(role, set())) or str(row.get("trace_id", "")) in traces[role]
                or client_identity(role, row) in identities[role]):
            continue
        method = str(row.get("request_method", "")).upper()
        path = safe_path(row.get("request_uri"))
        if method not in METHODS or path is None or path in ("/source", "/status") or path.startswith("/session/"):
            continue
        identity = (role, row.get("request_id") or row.get("trace_id"), method, path, timestamp.isoformat())
        if identity in seen:
            continue
        seen.add(identity)
        request_time = parse_time(row.get("request_time"), timezone)
        association_time = request_time if request_time and start <= request_time <= timestamp else timestamp
        step, certainty = associate_step(association_time, role, steps, padding)
        key = (role, method, path)
        record = endpoints.setdefault(key, {"role": role, "method": method, "path": path,
                                            "count": 0, "cases": [], "ui_steps": [], "evidence": []})
        record["count"] += 1
        if step:
            if step.get("case") not in record["cases"]:
                record["cases"].append(step.get("case"))
            if step["name"] not in record["ui_steps"]:
                record["ui_steps"].append(step["name"])
        status = row.get("response_status", row.get("status"))
        if not isinstance(status, int) or not 100 <= status <= 599:
            status = None
        record["evidence"].append({"time": timestamp.isoformat(timespec="milliseconds"),
                                   "request_time": association_time.isoformat(timespec="milliseconds"),
                                   "http_status": status, "source": source, "line": number,
                                   "step_id": step["step_id"] if step else None, "association": certainty})
    if not endpoints:
        warnings.append("未找到本次测试账号/订单/trace 对应的 iOS 客户端入口请求；不代表 App 没有调用接口")
    return sorted(endpoints.values(), key=lambda row: (row["role"], row["path"], row["method"])), warnings


def purpose(record, config):
    labels = config.get("endpoint_labels") or {}
    key = record["method"] + " " + record["path"]
    if key in labels:
        return labels[key]
    if record["path"].endswith("/real-order/place"):
        return "下单"
    return "用途待确认"


def write_catalog(directory, records, warnings, config):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"cluster": config.get("cluster"), "namespace": config.get("namespace"),
               "scope": "仅本次 UI 测试触发且有日志证据的 iOS 客户端入口接口", "warnings": list(dict.fromkeys(warnings)),
               "interfaces": records}
    (directory / "接口明细.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"接口清单｜香港 {config.get('namespace', '未配置')}｜{len(records)} 个接口",
             "范围：乘客/司机入口 category=api；排除后端出站 category=http、WDA 和其他账号。",
             "仅覆盖本次 UI 流程；银行/Alipay 外部网页及未记录到入口日志的接口不在此清单。",
             "UI 步骤按时间窗关联，不是已验证的接口业务用途；用途待确认项可在配置 endpoint_labels 中标注。",
             "未保存请求参数、响应正文、手机号、验证码、银行卡、Cookie 或 Token。", ""]
    for record in records:
        steps = "、".join(record["ui_steps"]) or "未关联具体步骤"
        lines.append(f"{record['method']} {record['path']}  # {purpose(record, config)}｜{ROLES[record['role']]}｜UI：{steps}｜{record['count']} 次")
    if not records:
        lines.append("暂无有证据的接口记录。")
    if payload["warnings"]:
        lines.extend(["", "采集提示：", *[f"- {warning}" for warning in payload["warnings"]]])
    target = directory / "接口清单.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


class TraceQueryBackend:
    """复用 trace_query 的集群配置，独立查询入口，避免全链路脚本落盘原始敏感日志。"""

    def __init__(self, config):
        self.config = config
        path = Path(config["trace_query_path"]).expanduser()
        spec = importlib.util.spec_from_file_location("hk_api_trace_query", path)
        if spec is None or spec.loader is None:
            raise ValueError("trace_query 不可加载")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cluster = module.CLUSTERS[config["cluster"]]
        if config["namespace"] not in cluster["namespaces"]:
            raise ValueError("namespace 不属于所选集群")
        self.kubeconfig = os.environ.get("HK_API_KUBECONFIG") or cluster["kubeconfig"]
        self.deadline = time.monotonic() + float(config.get("total_timeout", 90))

    def command(self, *args):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("接口采集总时限已到")
        timeout = min(float(self.config.get("command_timeout", 20)), remaining)
        result = subprocess.run(["kubectl", "--kubeconfig", self.kubeconfig, *args],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("kubectl 只读查询失败")
        return result.stdout

    def collect(self, started_at):
        namespace = self.config["namespace"]
        pods = json.loads(self.command("get", "pods", "-n", namespace, "-o", "json"))["items"]
        logs, warnings = [], []
        cap = int(self.config.get("tail_lines", 20000))
        if not 1 <= cap <= 100000:
            raise ValueError("tail_lines 超出允许范围")
        for role, service in SERVICES.items():
            matches = [pod for pod in pods if re.fullmatch(re.escape(service) + r"-[a-f0-9]+-[a-z0-9]+", pod["metadata"]["name"])
                       and pod.get("status", {}).get("phase") == "Running"]
            if not matches:
                warnings.append(f"没有运行中的{ROLES[role]}入口 Pod")
            for pod in matches:
                name = pod["metadata"]["name"]
                candidates = " ".join(f"/opt/app/{prefix}{service}{suffix}/logs/{filename}"
                                      for prefix, suffix in (("", ""), ("jryg-", ""), ("jryg-", "-api"))
                                      for filename in ("app.log", "app-info.log"))
                script = (f"for p in {candidates}; do if [ -f \"$p\" ]; then "
                          f"awk -v limit={cap + 1} '{ENTRY_AWK}' \"$p\"; exit $?; fi; done; exit 3")
                try:
                    text = self.command("exec", "-n", namespace, name, "--", "sh", "-c", script)
                except (RuntimeError, subprocess.TimeoutExpired):
                    try:
                        text = self.command("logs", "-n", namespace, name, f"--since-time={started_at}", f"--tail={cap + 1}")
                        warnings.append(f"{ROLES[role]}文件日志不可读，改查 Pod stdout；覆盖可能不完整")
                    except (RuntimeError, subprocess.TimeoutExpired, TimeoutError):
                        warnings.append(f"{ROLES[role]}入口查询失败或超时，未重试任何 UI 业务操作")
                        continue
                except TimeoutError:
                    warnings.append("接口采集达到总时限，后续入口未查询")
                    continue
                lines = text.splitlines()
                if len(lines) > cap:
                    warnings.append(f"{ROLES[role]}入口日志达到 {cap} 行上限，仅分析末尾窗口，可能遗漏或轮转")
                    text = "\n".join(lines[-cap:])
                logs.append((role, name, text))
        return logs, warnings


def finish_capture(plugin, config):
    warnings = list(plugin.recorder.warnings)
    logs = []
    if plugin.recorder.steps:
        try:
            backend = TraceQueryBackend(config)
            start = parse_time(plugin.recorder.started_at).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
            logs, notes = backend.collect(start)
            warnings.extend(notes)
        except (Exception, KeyboardInterrupt) as exc:
            warnings.append(f"后端采集未完成（{type(exc).__name__}），保留 UI 时间线；可稍后重新生成，不重跑订单")
    records, notes = build_catalog(logs, plugin.recorder.steps, plugin.clues, config)
    return write_catalog(plugin.recorder.directory, records, warnings + notes, config)


def merge_catalogs(directory, config):
    directory = Path(directory)
    merged, warnings = {}, []
    paths = sorted(directory.glob("*_api/接口明细.json"))
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        warnings.extend(payload.get("warnings", []))
        for row in payload.get("interfaces", []):
            key = (row["role"], row["method"], row["path"])
            if key not in merged:
                merged[key] = row
            else:
                saved = merged[key]
                saved["count"] += row["count"]
                for field in ("cases", "ui_steps"):
                    saved[field] = list(dict.fromkeys(saved[field] + row[field]))
                saved["evidence"].extend(row["evidence"])
    if not paths:
        warnings.append("子任务尚未产生接口报告，可能在设备准备阶段停止")
    return write_catalog(directory, sorted(merged.values(), key=lambda row: (row["role"], row["path"], row["method"])), warnings, config)


def main(argv=None):
    parser = argparse.ArgumentParser(description="用已保存的 UI 时间线和入口日志重新生成接口清单，不启动 App 或下单")
    parser.add_argument("--steps", required=True, help="ui_steps.jsonl 路径")
    parser.add_argument("--namespace", choices=("test", "dev"))
    parser.add_argument("--log", action="append", default=[], help="passenger=日志路径 或 driver=日志路径；不填则查询后端")
    parser.add_argument("--output", help="输出目录，默认与时间线同目录")
    options = parser.parse_args(argv)
    config = load_config(options.namespace)
    steps, bad = read_steps(options.steps)
    clues = {"passenger": {os.environ.get("HK_PASSENGER_MOBILE", "")}, "driver": {os.environ.get("HK_DRIVER_MOBILE", "")}}
    from ui_framework.JRYG_config import SETTINGS
    from ui_framework.JRYG_ios_ui_base import iOSBase
    clues["passenger"].add(str(iOSBase.LOGIN_PHONE))
    clues["driver"].add(str((SETTINGS.get("driver") or {}).get("mobile", "")))
    for role in clues:
        clues[role].update(os.environ.get("HK_API_ORDER_NO", "").split(","))
        clues[role].update(os.environ.get("HK_API_TRACE_ID", "").split(","))
    logs, warnings = [], []
    if bad:
        warnings.append(f"UI 时间线有 {bad} 行损坏，已跳过")
    try:
        if options.log:
            for value in options.log:
                role, separator, path = value.partition("=")
                if not separator or role not in ROLES:
                    parser.error("--log 必须使用 passenger=路径 或 driver=路径")
                logs.append((role, f"{role}-offline-{len(logs) + 1}", Path(path).read_text(encoding="utf-8")))
        elif steps:
            start = min(parse_time(row["started_at"]) for row in steps).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
            logs, notes = TraceQueryBackend(config).collect(start)
            warnings.extend(notes)
        records, notes = build_catalog(logs, steps, clues, config)
    except Exception as exc:
        warnings.append(f"采集失败（{type(exc).__name__}），未启动 UI 或重提订单")
        records, notes = [], []
    target = write_catalog(options.output or Path(options.steps).parent, records, warnings + notes, config)
    print(f"[接口清单] {target}")
    return 1 if not records or warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
