"""V1.6.0 无司机接单诊断模块。

当乘客下单后长时间无司机接单时，按以下顺序诊断：
1. dispatcher 服务：查询订单是否进入调度、是否被过滤规则拦截
2. resource-global 服务：查询订单是否有可用运力资源

诊断流程：
  订单号传入 → 先搜 dispatcher 日志 → 有匹配则分析过滤原因
             → 无匹配则搜 resource-global 日志 → 有匹配则分析资源状态
             → 两者均无匹配则报告"订单未进入调度链路"

支持环境：
  - K8s 环境（港版 test/dev）通过 kubectl 查询
  - pre 环境通过 JumpServer SSH（pre_grep.exp）查询物理机日志

依赖：
  - kubectl（KUBECONFIG 指向 ~/.kube/hk）
  - trace_query.py 同目录的 pre_grep.exp（pre 环境用）

使用方式：
  # Python 调用
  from passenger_android_core.v160.dispatch_diagnose import diagnose_no_accept
  result = diagnose_no_accept("TH26B6PIEWECN", namespace="test")

  # 命令行调用
  python3 -m passenger_android_core.v160.dispatch_diagnose TH26B6PIEWECN test

环境变量：
  KUBECONFIG 未设置时默认使用 ~/.kube/hk（港版集群）
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("JRYG_HK_android")

# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════

#: 港版集群 kubeconfig 默认路径
_DEFAULT_KUBECONFIG = str(Path.home() / ".kube" / "hk")

#: 可用的 kubeconfig 文件列表（按优先级排序）
#: 每个 kubeconfig 对应一个 K8s 集群，Pod 名称和服务结构可能不同
_KUBECONFIG_CANDIDATES: List[Dict] = [
    {
        "path": str(Path.home() / ".kube" / "hk"),
        "name": "hk",
        "label": "港版集群 (k8s-test.sunlightmobility.hk)",
        "namespaces": ["test"],
        # 港版集群的服务定义
        # 日志路径按优先级：app.log（当前）→ app-info.log → app-debug.log
        # 压缩日志 (.gz) 由 _grep_in_pod 自动搜索
        "services": [
            {
                "svc": "dispatcher",
                "pod_keyword": "dispatcher",
                "pod_exclude": "booking|paycenter",
                "log_paths": [
                    "/opt/app/dispatcher/logs/app.log",
                    "/opt/app/jryg-dispatcher/logs/app.log",
                ],
                "log_glob": "app*.log*",
                "label": "调度服务",
            },
            {
                "svc": "resource-global",
                "pod_keyword": "resource-global",
                "pod_exclude": "",
                "log_paths": [
                    "/opt/app/resource-global/logs/app-info.log",
                    "/opt/app/resource-global/logs/app-warn.log",
                    "/opt/app/resource-global/logs/app.log",
                ],
                "log_glob": "app*.log*",
                "label": "全局运力资源",
            },
        ],
    },
    {
        "path": str(Path.home() / ".kube" / "config"),
        "name": "config",
        "label": "内网集群 (172.19.16.110)",
        "namespaces": ["test", "dev", "pre", "test1", "test2", "test3"],
        # 内网集群的服务定义
        # test namespace: /opt/app/dispatcher/logs/ (app-info.log + app-debug.log)
        # dev namespace:  /opt/app/jryg-dispatcher/logs/ (路径前缀多了 jryg-)
        # 日志路径按优先级：app-info.log → app-debug.log（debug 包含更多调度细节）
        "services": [
            {
                "svc": "dispatcher",
                "pod_keyword": "dispatcher",
                "pod_exclude": "booking|paycenter",
                "log_paths": [
                    # test namespace 路径
                    "/opt/app/dispatcher/logs/app-info.log",
                    "/opt/app/dispatcher/logs/app-debug.log",
                    # dev namespace 路径（前缀多了 jryg-）
                    "/opt/app/jryg-dispatcher/logs/app-info.log",
                    "/opt/app/jryg-dispatcher/logs/app-debug.log",
                ],
                "log_glob": "app*.log*",
                "label": "调度服务",
            },
            {
                "svc": "resource-precise-dispatch",
                "pod_keyword": "resource-precise-dispatch",
                "pod_exclude": "",
                "log_paths": [
                    "/opt/app/resource-precise-dispatch/logs/app-info.log",
                    "/opt/app/resource-precise-dispatch/logs/app-debug.log",
                    "/opt/app/resource/logs/app-info.log",
                    "/opt/app/resource/logs/app-debug.log",
                ],
                "log_glob": "app*.log*",
                "label": "精准运力调度",
            },
        ],
    },
]


def _list_available_kubeconfigs() -> List[Dict]:
    """返回所有文件存在且可连通的 kubeconfig 配置。"""
    available = []
    for cfg in _KUBECONFIG_CANDIDATES:
        if Path(cfg["path"]).exists():
            available.append(cfg)
    return available


def _detect_kubeconfig(kubeconfig: Optional[str] = None,
                       namespace: str = "test") -> Tuple[str, List[Dict]]:
    """自动检测并选择可用的 kubeconfig，返回路径和对应的服务配置列表。

    优先级：
    1. 显式传入的 kubeconfig 参数（如果文件存在）
    2. 逐个尝试候选 kubeconfig，用 kubectl get pods 验证连通性
    3. 回退到第一个存在的 kubeconfig（给出明确报错）

    :return: (kubeconfig_path, services_list)
    """
    # 1. 显式传入
    if kubeconfig and Path(kubeconfig).exists():
        # 找到对应的配置
        for cfg in _KUBECONFIG_CANDIDATES:
            if cfg["path"] == str(Path(kubeconfig).resolve()):
                return cfg["path"], cfg["services"]
        # 未知 kubeconfig，用默认服务配置
        return kubeconfig, _KUBECONFIG_CANDIDATES[0]["services"]

    # 2. 逐个尝试候选 kubeconfig（按优先级顺序，hk 优先）
    # 使用 15 秒超时，港版集群可能连接较慢
    for cfg in _KUBECONFIG_CANDIDATES:
        if not Path(cfg["path"]).exists():
            continue
        # 只尝试 namespace 在候选列表中的 kubeconfig
        if namespace not in cfg["namespaces"] and namespace not in ("test", "dev", "pre"):
            continue
        # 快速验证连通性（15秒超时）
        try:
            out = _kubectl(cfg["path"], "get", "pods", "-n", namespace,
                          "--no-headers", timeout=15)
            if out.strip() and "Error" not in out and "error" not in out:
                logger.info("【dispatch_diagnose】使用 kubeconfig: %s (%s)",
                           cfg["name"], cfg["label"])
                return cfg["path"], cfg["services"]
        except Exception:
            continue

    # 3. 回退到第一个存在的
    for cfg in _KUBECONFIG_CANDIDATES:
        if Path(cfg["path"]).exists():
            logger.warning("【dispatch_diagnose】所有 kubeconfig 连通性验证失败，回退到 %s",
                          cfg["path"])
            return cfg["path"], cfg["services"]

    # 无可用 kubeconfig
    return _DEFAULT_KUBECONFIG, _KUBECONFIG_CANDIDATES[0]["services"]


#: 默认诊断服务列表（港版集群，向后兼容）
DIAGNOSE_SERVICES: List[Dict] = _KUBECONFIG_CANDIDATES[0]["services"]

#: 关键过滤/拒绝日志关键词（用于分类诊断原因）
FILTER_KEYWORDS = {
    "filter": [
        "filter", "filtered", "过滤", "拦截",
        "exclude", "skip", "ignore", "blacklist", "黑名单",
        "筛掉", "排除",
    ],
    "reject": [
        "reject", "rejected", "拒绝", "refuse",
        "deny", "denied",
        # 注意：不含 cancel，取消是独立流程，不是拒绝
    ],
    "no_driver": [
        "no driver", "no available", "无可用", "无司机",
        "empty", "not found driver", "driver list empty",
        "candidate empty", "no candidate", "候选为空",
    ],
    "timeout": [
        "timeout", "超时", "expire", "expired", "过期",
    ],
    "distance": [
        # 只匹配距离过滤/拒绝场景，不匹配 estimate_distance 等正常字段
        "too far", "距离超出", "超出范围", "超出半径",
        "out of range", "beyond radius", "距离过远",
        "distance filter", "distance exceed", "超出距离",
    ],
    "score": [
        "score", "评分", "weight", "权重",
        "priority", "优先级",
    ],
}


# ═══════════════════════════════════════════════════
# K8s 操作封装
# ═══════════════════════════════════════════════════

def _resolve_kubeconfig(kubeconfig: Optional[str] = None) -> str:
    """解析实际使用的 kubeconfig 路径。

    优先级：
    1. 显式传入的 kubeconfig 参数
    2. ~/.kube/hk（港版集群默认路径，如果文件存在）
    3. 环境变量 KUBECONFIG（如果文件存在）
    4. 回退到 ~/.kube/hk（即使不存在，给出明确报错）

    这样避免 KUBECONFIG 环境变量指向不存在的文件时导致 kubectl 失败。
    """
    if kubeconfig and Path(kubeconfig).exists():
        return kubeconfig

    hk_path = Path.home() / ".kube" / "hk"
    if hk_path.exists():
        return str(hk_path)

    env_kc = os.environ.get("KUBECONFIG", "")
    if env_kc:
        # KUBECONFIG 可能是冒号分隔的多路径，取第一个存在的
        for part in env_kc.split(":"):
            part = part.strip()
            if part and Path(part).exists():
                return part

    # 全部不存在，回退到默认路径（让 kubectl 报明确的错误）
    return str(hk_path)


def _kubectl(kubeconfig: str, *args, timeout: int = 30) -> str:
    """执行 kubectl 命令，返回 stdout。

    :raises RuntimeError: 命令执行失败。
    """
    cmd = ["kubectl", "--kubeconfig", kubeconfig] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "not found" in err.lower() or "error from server" in err.lower():
                return ""
            raise RuntimeError(f"kubectl 失败: {' '.join(cmd[-4:])}: {err}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"kubectl 超时({timeout}s): {' '.join(cmd[-4:])}")


def _find_pod(kubeconfig: str, namespace: str, keyword: str, exclude: str = "") -> Optional[str]:
    """在 namespace 中查找匹配关键词的 Pod 名。

    :param keyword: Pod 名称包含的关键词。
    :param exclude: Pod 名称排除的正则（如 "booking|paycenter"）。
    :return: 第一个 Running Pod 的名称，未找到返回 None。
    """
    out = _kubectl(kubeconfig, "get", "pods", "-n", namespace, timeout=30)
    for line in out.split("\n"):
        if keyword not in line:
            continue
        if "Running" not in line:
            continue
        if exclude and re.search(exclude, line):
            continue
        parts = line.split()
        if parts:
            return parts[0]
    return None


def _find_log_path(kubeconfig: str, namespace: str, pod: str,
                   candidates: List[str]) -> Optional[str]:
    """在 Pod 内探测日志文件路径，返回第一个存在的路径。"""
    for path in candidates:
        try:
            out = _kubectl(
                kubeconfig, "exec", "-n", namespace, pod, "--",
                "sh", "-c", f"[ -f '{path}' ] && echo '{path}'",
                timeout=30,
            )
            if out.strip():
                return out.strip().split("\n")[0]
        except RuntimeError:
            # 文件不存在时 sh -c 返回 exit code 1，继续尝试下一个路径
            continue
    # 兜底 find
    try:
        out = _kubectl(
            kubeconfig, "exec", "-n", namespace, pod, "--",
            "sh", "-c", "find /opt/app -maxdepth 5 -name 'app*.log*' 2>/dev/null | head -5",
            timeout=30,
        )
        for line in out.strip().split("\n"):
            line = line.strip()
            if line and ("app.log" in line or "app-info" in line or "app-warn" in line or "app-debug" in line):
                return line
    except RuntimeError:
        pass
    return None


def _find_all_log_paths(kubeconfig: str, namespace: str, pod: str,
                        candidates: List[str]) -> List[str]:
    """在 Pod 内探测所有存在的日志文件路径。

    与 _find_log_path 不同，返回所有存在的路径列表（而非仅第一个）。
    用于多日志文件搜索（如 app-info.log + app-debug.log）。
    """
    found = []
    for path in candidates:
        try:
            out = _kubectl(
                kubeconfig, "exec", "-n", namespace, pod, "--",
                "sh", "-c", f"[ -f '{path}' ] && echo '{path}'",
                timeout=15,
            )
            if out.strip():
                found.append(out.strip().split("\n")[0])
        except RuntimeError:
            continue
    if found:
        return found
    # 兜底 find
    try:
        out = _kubectl(
            kubeconfig, "exec", "-n", namespace, pod, "--",
            "sh", "-c", "find /opt/app -maxdepth 5 -name 'app*.log*' 2>/dev/null | head -10",
            timeout=30,
        )
        for line in out.strip().split("\n"):
            line = line.strip()
            if line and ("app.log" in line or "app-info" in line or "app-warn" in line or "app-debug" in line):
                found.append(line)
    except RuntimeError:
        pass
    return found


def _grep_in_pod(kubeconfig: str, namespace: str, pod: str,
                 log_path: str, keyword: str, max_lines: int = 200) -> str:
    """在 Pod 内的日志文件中 grep 关键词，返回匹配行。

    支持压缩文件（.gz）回退搜索。
    """
    # 主日志文件 — tail 取最后 N 行（保留最近的事件，包括取消/拒绝等终态）
    out = _kubectl(
        kubeconfig, "exec", "-n", namespace, pod, "--",
        "sh", "-c",
        f"grep -F '{keyword}' '{log_path}' 2>/dev/null | tail -{max_lines}",
        timeout=30,
    )
    if out.strip():
        return out

    # 压缩文件回退（最近 3 个）
    log_dir = str(Path(log_path).parent)
    out = _kubectl(
        kubeconfig, "exec", "-n", namespace, pod, "--",
        "sh", "-c",
        f"ls -t '{log_dir}'/app*.log.gz 2>/dev/null | head -3",
        timeout=10,
    )
    for gz in out.strip().split("\n"):
        gz = gz.strip()
        if not gz:
            continue
        out = _kubectl(
            kubeconfig, "exec", "-n", namespace, pod, "--",
            "sh", "-c",
            f"zcat '{gz}' | grep -F '{keyword}' | tail -{max_lines}",
            timeout=20,
        )
        if out.strip():
            return out

    # stdout 回退
    out = _kubectl(
        kubeconfig, "logs", "-n", namespace, pod, "--tail=30000",
        timeout=60,
    )
    lines = [l for l in out.split("\n") if keyword in l][:max_lines]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 日志分析
# ═══════════════════════════════════════════════════

def _classify_log_lines(lines: str, order_no: str) -> List[Dict]:
    """分析日志行，分类标记可能的过滤/拒绝原因。

    :return: 分析结果列表，每条包含 line, category, keywords_matched。
    """
    results = []
    for line in lines.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 只保留包含订单号的行（或与订单号在同一请求链路中的行）
        if order_no not in line:
            # 放宽：包含订单号的部分子串也保留（如订单号去掉前缀）
            short = order_no[-8:] if len(order_no) > 8 else order_no
            if short not in line:
                continue

        matched_categories = []
        matched_keywords = []
        line_lower = line.lower()
        for category, keywords in FILTER_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in line_lower:
                    matched_categories.append(category)
                    matched_keywords.append(kw)
                    break

        results.append({
            "line": line,
            "categories": matched_categories,
            "keywords": matched_keywords,
        })
    return results


def _summarize_diagnosis(analysis: List[Dict]) -> str:
    """从分析结果中提取摘要原因。"""
    if not analysis:
        return "未发现过滤/拒绝关键词，订单可能正常进入调度但无司机响应"

    all_categories = []
    for item in analysis:
        all_categories.extend(item["categories"])

    if not all_categories:
        return "日志中包含订单号但未匹配已知过滤/拒绝关键词"

    # 统计各类别出现次数
    from collections import Counter
    counter = Counter(all_categories)
    parts = []
    for cat, count in counter.most_common():
        label_map = {
            "filter": "过滤/拦截",
            "reject": "拒绝",
            "no_driver": "无可用司机",
            "timeout": "超时",
            "distance": "距离/范围",
            "score": "评分/权重",
        }
        label = label_map.get(cat, cat)
        parts.append(f"{label}({count}次)")

    return "疑似原因: " + ", ".join(parts)


# ═══════════════════════════════════════════════════
# 主诊断函数
# ═══════════════════════════════════════════════════

def diagnose_no_accept(order_no: str, namespace: str = "test",
                        kubeconfig: Optional[str] = None) -> Dict:
    """诊断订单无司机接单的原因。

    查询顺序：
    1. dispatcher 服务日志 — 查看订单是否进入调度、是否被过滤
    2. resource-global 服务日志 — 查看订单是否有可用运力资源

    :param order_no: 订单号（如 TH26B6PIEWECN 或 313657）
    :param namespace: K8s namespace（test / dev）
    :param kubeconfig: kubeconfig 路径，默认 ~/.kube/hk
    :return: 诊断结果字典，包含各服务的匹配情况和分析
    """
    # 自动检测可用的 kubeconfig 和对应的服务配置
    kc, services = _detect_kubeconfig(kubeconfig, namespace)
    result = {
        "order_no": order_no,
        "namespace": namespace,
        "kubeconfig": kc,
        "timestamp": datetime.now().isoformat(),
        "services": {},
        "summary": "",
        "conclusion": "",
    }

    any_match = False

    for svc_cfg in services:
        svc_name = svc_cfg["svc"]
        logger.info("【dispatch_diagnose】查询 %s(%s) 日志，订单号=%s",
                    svc_name, svc_cfg["label"], order_no)

        # 查找 Pod
        pod = _find_pod(kc, namespace, svc_cfg["pod_keyword"], svc_cfg["pod_exclude"])
        if not pod:
            logger.warning("【dispatch_diagnose】%s Pod 未找到", svc_name)
            result["services"][svc_name] = {
                "pod": None,
                "log_path": None,
                "match_count": 0,
                "matched_lines": "",
                "analysis": [],
                "status": "pod_not_found",
            }
            continue

        # 查找日志路径（返回所有存在的路径，不只第一个）
        all_log_paths = _find_all_log_paths(kc, namespace, pod, svc_cfg["log_paths"])
        if not all_log_paths:
            logger.warning("【dispatch_diagnose】%s(%s) 日志文件未找到", svc_name, pod)
            result["services"][svc_name] = {
                "pod": pod,
                "log_path": None,
                "match_count": 0,
                "matched_lines": "",
                "analysis": [],
                "status": "log_not_found",
            }
            continue

        # 在所有日志文件中 grep 订单号，合并结果
        all_matched = []
        matched_log_path = all_log_paths[0]  # 主日志路径（用于展示）
        for lp in all_log_paths:
            matched = _grep_in_pod(kc, namespace, pod, lp, order_no, max_lines=200)
            if matched.strip():
                all_matched.extend(matched.strip().split("\n"))
                # 如果第一个文件没匹配到，用实际匹配到的文件路径
                if matched_log_path == all_log_paths[0] and lp != all_log_paths[0]:
                    matched_log_path = lp

        matched = "\n".join(all_matched)
        match_count = len([l for l in matched.split("\n") if l.strip()])

        # 分析日志
        analysis = _classify_log_lines(matched, order_no)
        summary = _summarize_diagnosis(analysis)

        result["services"][svc_name] = {
            "pod": pod,
            "log_path": matched_log_path,
            "log_paths_searched": all_log_paths,
            "match_count": match_count,
            "matched_lines": matched[:50000] if matched else "",  # 截断保护
            "analysis": analysis[:50],  # 最多保留 50 条分析
            "analysis_summary": summary,
            "status": "matched" if match_count > 0 else "no_match",
        }

        if match_count > 0:
            any_match = True
            logger.info("【dispatch_diagnose】%s 匹配 %d 行，摘要: %s",
                        svc_name, match_count, summary)
        else:
            logger.info("【dispatch_diagnose】%s 无匹配", svc_name)

    # 生成总结论
    if not any_match:
        result["conclusion"] = (
            "订单号在 dispatcher 和 resource-global 日志中均无匹配，"
            "可能原因：1)订单未进入调度链路；2)订单已被取消；"
            "3)日志已轮转被压缩，建议用 trace_query 全链路追踪确认"
        )
    else:
        parts = []
        for svc_name, svc_result in result["services"].items():
            if svc_result.get("match_count", 0) > 0:
                parts.append(
                    f"{svc_name}: {svc_result['match_count']}行匹配, "
                    f"{svc_result.get('analysis_summary', '')}"
                )
        result["conclusion"] = "; ".join(parts) if parts else "有匹配但无明确原因"

    result["summary"] = result["conclusion"]
    return result


def _parse_log_json(line: str) -> Optional[Dict]:
    """尝试解析 JSON 日志行，失败则返回 None。"""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


#: 日志字段中文标签映射
_FIELD_LABELS = {
    "order_id": "订单ID",
    "main_order_id": "主订单ID",
    "order_no": "订单号",
    "parent_order_no": "父订单号",
    "user_id": "用户ID",
    "driver_id": "司机ID",
    "agent_id": "代理商ID",
    "city_id": "城市ID",
    "car_type_id": "车型ID",
    "car_type_ids": "车型ID列表",
    "dispatch_type": "派单类型",
    "dispatch_model": "派单模式",
    "order_type": "订单类型",
    "busi_type": "业务类型",
    "begin_lng": "起点经度",
    "begin_lat": "起点纬度",
    "end_lng": "终点经度",
    "end_lat": "终点纬度",
    "begin_location": "起点地址",
    "end_location": "终点地址",
    "estimate_distance": "预估距离(米)",
    "estimate_duration": "预估时长(秒)",
    "use_time": "用车时间",
    "is_test": "测试订单",
    "tail_phone": "尾号",
    "postpaid_order": "后付订单",
    "event": "事件",
    "log_type": "日志类型",
    "trace_id": "追踪ID",
    "category": "日志分类",
    "msg": "日志消息",
    "level": "日志级别",
    "time": "时间",
    "current_time": "当前时间戳",
    "key": "缓存键",
    "msg_id": "MQ消息ID",
    "kids_use_car": "儿童用车",
    "pet_use_car": "宠物用车",
}

#: 需要展示的关键字段（按优先级排序）
_KEY_FIELDS_ORDER = [
    "time", "level", "category", "msg", "event", "log_type", "trace_id",
    "order_id", "main_order_id", "order_no", "parent_order_no",
    "user_id", "driver_id", "agent_id", "city_id",
    "car_type_id", "car_type_ids", "order_type", "busi_type",
    "dispatch_type", "dispatch_model",
    "begin_location", "end_location",
    "begin_lng", "begin_lat", "end_lng", "end_lat",
    "estimate_distance", "estimate_duration", "use_time",
    "is_test", "tail_phone", "postpaid_order",
    "kids_use_car", "pet_use_car",
    "current_time", "key", "msg_id",
]

#: 排除不展示的字段（噪音或过长）
_EXCLUDE_FIELDS = {
    "line", "app_name", "d", "message",  # 原始消息体、代码行、应用名
    "created_time", "estimate_time",  # 与 use_time 重复
    "assignTimeSpanM",  # 内部缓存数据
    "dynamic_rate", "discount_rate", "origin_rate",  # 费率噪音
    "limit_before_rate", "limit_after_rate", "fixed_price_rate", "log_mark",
}


def _extract_fields_from_log(line: str) -> Dict:
    """从一条 JSON 日志行中提取所有可见字段（含嵌套）。

    将 properties、cancelParams、order_params、dispatch_order、info 等
    嵌套对象的字段提升到顶层，方便统一展示。
    """
    parsed = _parse_log_json(line)
    if not parsed:
        return {"raw": line[:300]}

    # 收集所有字段（含嵌套对象提升）
    flat = {}
    nested_keys = (
        "properties", "cancelParams", "order_params", "dispatch_order",
        "info", "d", "message",
    )
    for key, value in parsed.items():
        if key in nested_keys and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[sub_key] = sub_value
        elif key in nested_keys and isinstance(value, str):
            # message 字段可能是 JSON 字符串
            try:
                inner = json.loads(value)
                if isinstance(inner, dict):
                    for sub_key, sub_value in inner.items():
                        flat[sub_key] = sub_value
                else:
                    flat[key] = value
            except (json.JSONDecodeError, ValueError):
                flat[key] = value
        else:
            flat[key] = value

    return flat


def _format_field_value(value, max_len: int = 120) -> str:
    """格式化字段值为简洁可读的字符串。

    :param max_len: 字符串值的最大显示长度，超出截断并加...。
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if len(value) > max_len:
            return value[:max_len] + "..."
        return value
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    if isinstance(value, dict):
        s = json.dumps(value, ensure_ascii=False)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    return str(value)


def _format_log_entry_structured(line: str) -> str:
    """将一条 JSON 日志行格式化为结构化的多行展示。

    输出格式：
      [18:59:00] 创建派单开始消费 | trace=aB3x...
        订单ID: 313662  主订单ID: 313661  订单号: 26B6Q0UWECNW
        用户ID: 200522  城市ID: 514  代理商ID: 11
        起点: 铜锣湾地铁站D2出口  终点: 大潭郊野公园
        预估距离: 18578米  预估时长: 4545秒  用车时间: 2026-11-19 18:59:00
    """
    fields = _extract_fields_from_log(line)
    if "raw" in fields:
        # 非 JSON 行
        return f"  {fields['raw']}"

    time_str = _extract_log_time(line)
    category = fields.get("category", "")
    msg = fields.get("msg", "")
    trace_id = fields.get("trace_id", "")
    event = fields.get("event", "")

    # 标题行
    header_parts = [f"[{time_str}]"]
    if msg:
        header_parts.append(msg)
    if event and event != msg:
        header_parts.append(f"event={event}")
    if trace_id:
        header_parts.append(f"trace={trace_id}")
    header = " | ".join(header_parts)

    # 字段行：按优先级顺序展示，每行 2-3 个字段
    displayed = {"time", "category", "msg", "event", "trace_id"}
    field_line_parts = []
    for field_name in _KEY_FIELDS_ORDER:
        if field_name in displayed or field_name in _EXCLUDE_FIELDS:
            continue
        if field_name not in fields:
            continue
        value = fields[field_name]
        label = _FIELD_LABELS.get(field_name, field_name)
        formatted = _format_field_value(value)
        if formatted and formatted != "null":
            field_line_parts.append(f"{label}: {formatted}")
            displayed.add(field_name)

    # 补充未在预设顺序中的字段
    for field_name, value in fields.items():
        if field_name in displayed or field_name in _EXCLUDE_FIELDS:
            continue
        if field_name.startswith("_"):
            continue
        label = _FIELD_LABELS.get(field_name, field_name)
        formatted = _format_field_value(value)
        if formatted and formatted != "null":
            field_line_parts.append(f"{label}: {formatted}")

    # 每 3 个字段一行
    lines = [f"  {header}"]
    for i in range(0, len(field_line_parts), 3):
        chunk = "  ".join(field_line_parts[i:i + 3])
        lines.append(f"    {chunk}")

    return "\n".join(lines)


def format_diagnosis(result: Dict, structured: bool = True) -> str:
    """格式化诊断结果为可读文本。

    :param structured: True 时解析 JSON 日志并结构化展示字段，
                       False 时保留原始截断格式（向后兼容）。
    """
    lines = []
    lines.append("═" * 60)
    lines.append(f"  无司机接单诊断: {result['order_no']} @ {result['namespace']}")
    lines.append("═" * 60)
    lines.append("")

    for svc_name, svc_result in result["services"].items():
        lines.append(f"【{svc_name}】")
        lines.append(f"  Pod: {svc_result.get('pod', '未找到')}")
        lines.append(f"  日志: {svc_result.get('log_path', '未找到')}")
        # 如果搜索了多个文件，展示搜索范围
        searched = svc_result.get("log_paths_searched", [])
        if searched and len(searched) > 1:
            lines.append(f"  搜索文件: {len(searched)} 个")
        lines.append(f"  匹配: {svc_result.get('match_count', 0)} 行")
        lines.append(f"  状态: {svc_result.get('status', 'unknown')}")

        if svc_result.get("analysis_summary"):
            lines.append(f"  分析: {svc_result['analysis_summary']}")

        if svc_result.get("matched_lines"):
            matched_lines = [l for l in svc_result["matched_lines"].split("\n") if l.strip()]
            # 显示全部匹配日志（tail 已限制为最近 200 行）
            display_lines = matched_lines

            if structured:
                lines.append(f"  日志详情（结构化展示，共 {len(display_lines)} 条）:")
                lines.append("")
                for line in display_lines:
                    formatted = _format_log_entry_structured(line.strip())
                    lines.append(formatted)
                    lines.append("")
            else:
                lines.append("  日志摘要（前 10 行）:")
                for line in display_lines[:10]:
                    if line.strip():
                        lines.append(f"    {line.strip()[:200]}")
        lines.append("")

    lines.append("─" * 60)
    lines.append(f"结论: {result.get('conclusion', '')}")
    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════

def _grep_new_lines(kubeconfig: str, namespace: str, pod: str,
                    log_path: str, keyword: str,
                    seen_lines: set, max_lines: int = 500) -> List[str]:
    """查询日志中包含 keyword 的行，过滤已见行，返回新增行列表。

    :param seen_lines: 已见行的集合（会被更新）。
    :return: 新增行列表（保持原始顺序）。
    """
    out = _kubectl(
        kubeconfig, "exec", "-n", namespace, pod, "--",
        "sh", "-c",
        f"grep -F '{keyword}' '{log_path}' 2>/dev/null | tail -{max_lines}",
        timeout=30,
    )
    new_lines = []
    for line in out.split("\n"):
        line = line.strip()
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)
        new_lines.append(line)
    return new_lines


#: 实时追踪时关注的关键事件关键词（category → 中文标签）
_TRACK_EVENT_PATTERNS = [
    (r"DispatchCreate|创建派单|创建订单|派单请求", "📋 创建派单"),
    (r"Dispatch\.Do|派单调度|开始调度", "🔄 开始调度"),
    (r"filter|filtered|过滤|拦截|排除|跳过", "🚫 过滤"),
    (r"reject|拒绝|否定", "❌ 拒绝"),
    (r"distance|距离|超出范围|半径", "📏 距离过滤"),
    (r"no driver|无可用|无司机|empty", "📭 无司机"),
    (r"timeout|超时|过期", "⏰ 超时"),
    (r"score|评分|权重|优先级", "📊 评分"),
    (r"DispatchCancel|派单取消|取消派单", "🛑 派单取消"),
    (r"DelAssignOrder|删除指派|DelPublishOrder|删除抢派", "🗑️ 删除订单池"),
    (r"Assign|指派|assign", "📤 指派"),
    (r"Grab|抢单|grab", "🤝 抢单"),
    (r"accept|接单|Accept", "✅ 接单"),
    (r"driver.*info|司机信息|DriverInfo", "🚗 司机信息"),
    (r"resource|运力|Resource", "📦 运力资源"),
]


def _match_track_event(line: str) -> Optional[str]:
    """匹配日志行是否包含关注的事件，返回事件标签。"""
    for pattern, label in _TRACK_EVENT_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return label
    return None


def _extract_log_time(line: str) -> str:
    """从 JSON 日志行中提取时间戳，返回简短格式（HH:MM:SS）。"""
    # 匹配 "time":"2026-11-19T18:59:00.991+0800"
    m = re.search(r'"time"\s*:\s*"(\d{4}-\d{2}-\d{2}T(\d{2}:\d{2}:\d{2}))', line)
    if m:
        return m.group(2)
    # 匹配非 JSON 格式的时间
    m = re.search(r'(\d{2}:\d{2}:\d{2})', line)
    if m:
        return m.group(1)
    return "--:--:--"


def _extract_log_category(line: str) -> str:
    """从 JSON 日志行中提取 category 字段。"""
    m = re.search(r'"category"\s*:\s*"([^"]+)"', line)
    if m:
        return m.group(1)
    return ""


def _extract_log_msg(line: str) -> str:
    """从 JSON 日志行中提取 msg 字段。"""
    m = re.search(r'"msg"\s*:\s*"([^"]+)"', line)
    if m:
        return m.group(1)
    # 非 JSON 行，截取前 120 字符
    return line[:120]


def live_track(order_no: str, namespace: str = "test",
               interval: int = 5, max_rounds: int = 0,
               kubeconfig: Optional[str] = None):
    """实时追踪订单调度日志。

    每 interval 秒查询一次 dispatcher 和 resource-global 日志，
    显示新增的与订单相关的日志行。

    :param order_no: 订单号。
    :param namespace: K8s namespace。
    :param interval: 查询间隔秒数，默认 5 秒。
    :param max_rounds: 最大查询轮数，0 表示无限（Ctrl+C 退出）。
    :param kubeconfig: kubeconfig 路径。
    """
    import time as _time

    kc, services = _detect_kubeconfig(kubeconfig, namespace)

    # 查找各服务的 Pod 和日志路径
    service_info = []
    for svc_cfg in services:
        svc_name = svc_cfg["svc"]
        pod = _find_pod(kc, namespace, svc_cfg["pod_keyword"], svc_cfg["pod_exclude"])
        if not pod:
            print(f"  ⚠️ {svc_name} Pod 未找到")
            continue
        log_path = _find_log_path(kc, namespace, pod, svc_cfg["log_paths"])
        if not log_path:
            print(f"  ⚠️ {svc_name}({pod}) 日志文件未找到")
            continue
        service_info.append({
            "svc": svc_name,
            "label": svc_cfg["label"],
            "pod": pod,
            "log_path": log_path,
        })
        print(f"  ✓ {svc_name}({svc_cfg['label']}) → {pod} / {log_path}")

    if not service_info:
        print("❌ 无可用服务 Pod，实时追踪终止")
        return

    # 记录每个服务已见的日志行
    seen_lines = {svc["svc"]: set() for svc in service_info}

    # 第一次查询：先加载已有日志作为基线（不输出），只追踪新增
    print()
    print(f"━━━ 开始实时追踪订单 {order_no}（每 {interval}s 查询一次，Ctrl+C 退出）━━━")
    print()

    # 基线扫描：把当前已有日志全部标记为已见
    for svc in service_info:
        try:
            _grep_new_lines(kc, namespace, svc["pod"], svc["log_path"],
                            order_no, seen_lines[svc["svc"]])
        except Exception:
            pass  # 基线失败不影响后续

    baseline_counts = {svc["svc"]: len(seen_lines[svc["svc"]]) for svc in service_info}
    for svc in service_info:
        print(f"  📊 {svc['svc']} 基线日志: {baseline_counts[svc['svc']]} 行")
    print()
    print("  ⏳ 等待新增日志...")
    print()

    round_num = 0
    try:
        while True:
            round_num += 1
            if max_rounds > 0 and round_num > max_rounds:
                print(f"\n已达最大轮数 {max_rounds}，追踪结束")
                break

            now_str = datetime.now().strftime("%H:%M:%S")
            has_new = False

            for svc in service_info:
                try:
                    new_lines = _grep_new_lines(
                        kc, namespace, svc["pod"], svc["log_path"],
                        order_no, seen_lines[svc["svc"]],
                    )
                except Exception as exc:
                    print(f"  [{now_str}] ⚠️ {svc['svc']} 查询失败: {exc}")
                    continue

                if not new_lines:
                    continue

                has_new = True
                for line in new_lines:
                    time_str = _extract_log_time(line)
                    category = _extract_log_category(line)
                    msg = _extract_log_msg(line)
                    event_label = _match_track_event(line)

                    # 简洁输出
                    svc_tag = svc["svc"][:8]
                    if event_label:
                        print(f"  [{now_str}] {event_label} [{svc_tag}] {time_str} {category} | {msg}")
                    else:
                        print(f"  [{now_str}] 📄 [{svc_tag}] {time_str} {category} | {msg}")

            if not has_new:
                # 无新日志时每 30 秒输出一次心跳
                if round_num % (30 // interval) == 0:
                    print(f"  [{now_str}] 💓 心跳：订单 {order_no} 暂无新日志")

            _time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n━━━ 用户中断，追踪结束 ━━━")
        # 输出统计
        print(f"  追踪轮数: {round_num}")
        for svc in service_info:
            total = len(seen_lines[svc["svc"]])
            baseline = baseline_counts[svc["svc"]]
            new_count = total - baseline
            print(f"  {svc['svc']}: 基线 {baseline} 行，新增 {new_count} 行，总计 {total} 行")


def interactive_diagnose(namespace: str = "test",
                        kubeconfig: Optional[str] = None):
    """交互式诊断：提示用户输入订单号后执行查询。

    使用方式：
      # 无参数启动交互模式
      python3 -m passenger_android_core.v160.dispatch_diagnose

      # 指定 namespace 后交互输入订单号
      python3 -m passenger_android_core.v160.dispatch_diagnose test

    输入 exit 或 quit 退出。
    """
    print()
    print("═" * 60)
    print("  无司机接单诊断工具（交互模式）")
    print(f"  环境: {namespace}")
    print("═" * 60)

    # 显示可用 kubeconfig
    available = _list_available_kubeconfigs()
    print()
    print("  可用集群:")
    for i, cfg in enumerate(available):
        marker = " ← 默认" if i == 0 else ""
        print(f"    [{i}] {cfg['name']} - {cfg['label']}{marker}")
    print()
    print("  输入 kube 切换集群，输入订单号开始查询，输入 exit 退出。")
    print()

    current_kubeconfig = kubeconfig  # 可能为 None（自动检测）或显式路径

    while True:
        try:
            order_no = input("订单号 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出")
            break

        if not order_no:
            continue
        if order_no.lower() in ("exit", "quit", "q", "退出"):
            print("已退出")
            break

        # kube 命令：切换 kubeconfig
        if order_no.lower() in ("kube", "k", "集群", "切换"):
            print()
            print("  可用集群:")
            for i, cfg in enumerate(available):
                exists = "✓" if Path(cfg["path"]).exists() else "✗"
                ns_list = ", ".join(cfg["namespaces"][:4])
                marker = " ← 当前" if current_kubeconfig == cfg["path"] else ""
                print(f"    [{i}] {exists} {cfg['name']} - {cfg['label']}")
                print(f"        namespace: {ns_list}")
            print()
            try:
                choice = input("选择集群编号 > ").strip()
                idx = int(choice)
                if 0 <= idx < len(available):
                    current_kubeconfig = available[idx]["path"]
                    print(f"  ✓ 已切换到: {available[idx]['label']}")
                else:
                    print(f"  ⚠️ 编号超出范围")
            except (ValueError, EOFError, KeyboardInterrupt):
                # 输入非数字，取消切换
                current_kubeconfig = None
                print("  ✓ 已重置为自动检测模式")
            print()
            continue

        # ns 命令：切换 namespace
        if order_no.lower().startswith("ns ") or order_no.lower().startswith("namespace "):
            ns_parts = order_no.split(None, 1)
            if len(ns_parts) == 2:
                namespace = ns_parts[1].strip()
                print(f"  ✓ namespace 已切换为: {namespace}")
            print()
            continue

        # 订单号格式校验：
        # - 支持纯数字（如 313657）和字母数字混合（如 TH26B6PIEWECN）
        # - 长度 6-20 位
        # - 不含空格、特殊字符（自动转大写）
        order_no = order_no.upper()
        if not re.match(r"^[A-Z0-9]{6,20}$", order_no):
            print(f"⚠️ 订单号格式异常: {order_no}")
            print("  订单号应为 6-20 位字母或数字（如 TH26B6PIEWECN 或 313657）")
            print("  或输入 kube 切换集群，ns <name> 切换 namespace")
            print()
            continue

        print()
        print(f"开始查询订单 {order_no} ...")
        try:
            result = diagnose_no_accept(order_no, namespace=namespace,
                                        kubeconfig=current_kubeconfig)
            print(format_diagnosis(result))
        except Exception as exc:
            print(f"❌ 查询失败: {type(exc).__name__}: {exc}")
        print()

        # 订单仍在呼叫中时，询问是否实时追踪
        print("─" * 60)
        print()
        print("  订单还在呼叫中？输入 track 开启实时日志追踪（Ctrl+C 退出）")
        print("  输入新订单号继续查询，输入 exit 退出")
        print()
        try:
            action = input("操作 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出")
            break

        if action in ("track", "t", "追踪", "实时"):
            try:
                live_track(order_no, namespace=namespace, interval=5)
            except KeyboardInterrupt:
                pass
            print()
            print("─" * 60)
            print()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 无参数 → 交互模式；有参数 → 单次查询
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("用法:")
        print("  交互模式: python3 dispatch_diagnose.py [namespace]")
        print("  单次查询: python3 dispatch_diagnose.py <order_no> [namespace]")
        print("  实时追踪: python3 dispatch_diagnose.py live <order_no> [namespace]")
        print("  指定集群: python3 dispatch_diagnose.py --kube <hk|config> <order_no> [namespace]")
        print("  集群列表: python3 dispatch_diagnose.py kube")
        print()
        print("可用集群:")
        for cfg in _list_available_kubeconfigs():
            exists = "✓" if Path(cfg["path"]).exists() else "✗"
            print(f"  {exists} {cfg['name']:8s} - {cfg['label']}")
            print(f"           namespace: {', '.join(cfg['namespaces'])}")
            print(f"           services:  {', '.join(s['svc'] for s in cfg['services'])}")
        print()
        print("示例:")
        print("  python3 dispatch_diagnose.py                        # 交互模式")
        print("  python3 dispatch_diagnose.py 313661                  # 单次查询")
        print("  python3 dispatch_diagnose.py 313661 dev              # dev 环境")
        print("  python3 dispatch_diagnose.py live 313661             # 实时追踪")
        print("  python3 dispatch_diagnose.py --kube hk 313661        # 指定港版集群")
        print("  python3 dispatch_diagnose.py --kube config 313661 dev # 指定内网+dev")
        print()
        # 无参数时进入交互模式；--help 时只显示帮助
        if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help", "help"):
            sys.exit(0)
        ns = "test"
        interactive_diagnose(namespace=ns)
        sys.exit(0)

    # kube 命令：列出可用集群
    if sys.argv[1].lower() in ("kube", "k", "集群"):
        print("可用 kubeconfig 集群:")
        for i, cfg in enumerate(_list_available_kubeconfigs()):
            exists = "✓" if Path(cfg["path"]).exists() else "✗"
            print(f"  [{i}] {exists} {cfg['name']:8s} - {cfg['label']}")
            print(f"       namespace: {', '.join(cfg['namespaces'])}")
            print(f"       services:  {', '.join(s['svc'] for s in cfg['services'])}")
            print(f"       path:      {cfg['path']}")
        sys.exit(0)

    # --kube 参数：指定 kubeconfig
    explicit_kubeconfig = None
    args = sys.argv[1:]
    if args and args[0].lower() in ("--kube", "-k"):
        if len(args) < 2:
            print("用法: python3 dispatch_diagnose.py --kube <hk|config> <order_no> [namespace]")
            sys.exit(1)
        kube_name = args[1].lower()
        for cfg in _KUBECONFIG_CANDIDATES:
            if cfg["name"] == kube_name:
                explicit_kubeconfig = cfg["path"]
                break
        if not explicit_kubeconfig:
            # 也接受路径
            if Path(args[1]).exists():
                explicit_kubeconfig = args[1]
            else:
                print(f"未知 kubeconfig: {args[1]}")
                print(f"可选: {', '.join(c['name'] for c in _KUBECONFIG_CANDIDATES)}")
                sys.exit(1)
        args = args[2:]  # 移除 --kube 和参数名

    if not args:
        interactive_diagnose(namespace="test", kubeconfig=explicit_kubeconfig)
        sys.exit(0)

    # 第一个参数是 namespace（test/dev）还是订单号还是 live
    first = args[0]
    if first.lower() in ("test", "dev", "pre"):
        # 第一个参数是 namespace → 交互模式
        ns = first.lower()
        interactive_diagnose(namespace=ns, kubeconfig=explicit_kubeconfig)
    elif first.lower() in ("live", "track", "实时", "追踪"):
        # live 模式：python3 dispatch_diagnose.py live <order_no> [namespace]
        if len(args) < 2:
            print("用法: python3 dispatch_diagnose.py live <order_no> [namespace]")
            sys.exit(1)
        order_no = args[1]
        ns = args[2] if len(args) > 2 else "test"
        live_track(order_no, namespace=ns, interval=5, kubeconfig=explicit_kubeconfig)
    else:
        # 第一个参数是订单号 → 单次查询
        order_no = first
        ns = args[1] if len(args) > 1 else "test"
        result = diagnose_no_accept(order_no, namespace=ns, kubeconfig=explicit_kubeconfig)
        print(format_diagnosis(result))
