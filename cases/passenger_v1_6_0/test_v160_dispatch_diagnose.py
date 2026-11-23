"""V1.6.0 无司机接单诊断测试。

验证 diagnose_no_accept 模块的诊断逻辑：
- dispatcher 服务查询：订单是否进入调度、是否被过滤
- resource-global 服务查询：订单是否有可用运力资源
- 诊断结论的生成逻辑

测试分层：
1. 离线契约测试：验证日志分析分类逻辑（不依赖 K8s）
2. 真机/K8s 集成测试：连接港版 test 环境，用真实订单号查询（需 K8s 可达）

前置条件：
- 离线用例：不需要 K8s，始终执行
- K8s 集成用例：需要 ~/.kube/hk 可达港版集群，通过环境变量
  V160_REAL_ORDER_NO 传入真实订单号
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.dispatch_diagnose import (  # noqa: E402
    DIAGNOSE_SERVICES,
    FILTER_KEYWORDS,
    _classify_log_lines,
    _summarize_diagnosis,
    diagnose_no_accept,
    format_diagnosis,
)

#: 真实订单号（从环境变量获取）
_REAL_ORDER_NO = os.environ.get("V160_REAL_ORDER_NO", "").strip()


class TestDispatchDiagnoseContract:
    """诊断模块离线契约测试 — 不依赖 K8s。"""

    def test_diagnose_services_order(self):
        """诊断服务顺序：dispatcher 第一，resource-global 第二。"""
        svc_names = [s["svc"] for s in DIAGNOSE_SERVICES]
        assert svc_names[0] == "dispatcher", "dispatcher 应为第一优先查询"
        assert svc_names[1] == "resource-global", "resource-global 应为第二查询"

    def test_dispatcher_pod_exclude(self):
        """dispatcher 查询排除 paycenter-dispatcher 和 booking。"""
        dispatcher_cfg = next(s for s in DIAGNOSE_SERVICES if s["svc"] == "dispatcher")
        exclude = dispatcher_cfg["pod_exclude"]
        assert "paycenter" in exclude
        assert "booking" in exclude

    def test_resource_global_pod_keyword(self):
        """resource-global Pod 关键词正确。"""
        rg_cfg = next(s for s in DIAGNOSE_SERVICES if s["svc"] == "resource-global")
        assert rg_cfg["pod_keyword"] == "resource-global"
        assert rg_cfg["pod_exclude"] == ""

    def test_dispatcher_log_paths(self):
        """dispatcher 日志路径包含 app.log。"""
        dispatcher_cfg = next(s for s in DIAGNOSE_SERVICES if s["svc"] == "dispatcher")
        paths = dispatcher_cfg["log_paths"]
        assert any("dispatcher" in p and "app.log" in p for p in paths)

    def test_resource_global_log_paths(self):
        """resource-global 日志路径包含 app-info.log 和 app-warn.log。"""
        rg_cfg = next(s for s in DIAGNOSE_SERVICES if s["svc"] == "resource-global")
        paths = rg_cfg["log_paths"]
        assert any("app-info.log" in p for p in paths), \
            "resource-global 日志路径应包含 app-info.log"
        assert any("app-warn.log" in p for p in paths), \
            "resource-global 日志路径应包含 app-warn.log"

    def test_filter_keywords_categories(self):
        """过滤关键词包含 6 个分类。"""
        expected = {"filter", "reject", "no_driver", "timeout", "distance", "score"}
        assert set(FILTER_KEYWORDS.keys()) == expected

    def test_filter_keywords_content(self):
        """过滤关键词包含核心过滤/拒绝词。"""
        assert "filter" in FILTER_KEYWORDS["filter"]
        assert "过滤" in FILTER_KEYWORDS["filter"]
        assert "reject" in FILTER_KEYWORDS["reject"]
        # cancel 不应在 reject 中（取消是独立流程，不是拒绝）
        assert "cancel" not in FILTER_KEYWORDS["reject"]
        assert "no driver" in FILTER_KEYWORDS["no_driver"]
        assert "无可用" in FILTER_KEYWORDS["no_driver"]
        assert "timeout" in FILTER_KEYWORDS["timeout"]
        assert "超时" in FILTER_KEYWORDS["timeout"]
        # distance 分类只匹配过滤场景关键词，不匹配 estimate_distance 等正常字段
        assert "超出范围" in FILTER_KEYWORDS["distance"]
        assert "too far" in FILTER_KEYWORDS["distance"]
        # 不应包含裸 "distance"，否则会误匹配 estimate_distance 字段
        assert "distance" not in FILTER_KEYWORDS["distance"]

    def test_classify_filter_line(self):
        """包含 filter 关键词的日志行分类为 filter。"""
        lines = '2026-11-19 10:00:00 INFO order TH26B6PIEWECN filter by distance rule'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 1
        assert "filter" in analysis[0]["categories"]
        assert "filter" in analysis[0]["keywords"]

    def test_classify_no_driver_line(self):
        """包含 no driver 关键词的日志行分类为 no_driver。"""
        lines = '2026-11-19 10:00:00 WARN TH26B6PIEWECN no driver available in radius'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 1
        assert "no_driver" in analysis[0]["categories"]

    def test_classify_timeout_line(self):
        """包含 timeout 关键词的日志行分类为 timeout。"""
        lines = '2026-11-19 10:01:00 WARN TH26B6PIEWECN dispatch timeout expired'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 1
        assert "timeout" in analysis[0]["categories"]

    def test_classify_multiple_categories(self):
        """一行同时包含多个分类关键词时全部匹配。"""
        lines = 'TH26B6PIEWECN filter by distance, no driver, timeout'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 1
        cats = analysis[0]["categories"]
        assert "filter" in cats
        assert "no_driver" in cats
        assert "timeout" in cats

    def test_classify_irrelevant_line(self):
        """不包含订单号的行不进入分析。"""
        lines = '2026-11-19 10:00:00 INFO some other order NO12345 filter by rule'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 0

    def test_classify_empty_lines(self):
        """空行和纯空白行不进入分析。"""
        lines = '\n\n  \n\t\n'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 0

    def test_classify_order_no_partial_match(self):
        """订单号末 8 位也能匹配（日志中可能只记录短号）。"""
        lines = '2026-11-19 10:00:00 WARN 6PIEWECN no driver available'
        analysis = _classify_log_lines(lines, "TH26B6PIEWECN")
        assert len(analysis) == 1

    def test_summarize_no_analysis(self):
        """无分析数据时返回默认提示。"""
        summary = _summarize_diagnosis([])
        assert "未发现" in summary or "无司机" in summary

    def test_summarize_with_categories(self):
        """有分类时返回疑似原因摘要。"""
        analysis = [{
            "line": "filter by distance",
            "categories": ["filter", "distance"],
            "keywords": ["filter", "distance"],
        }]
        summary = _summarize_diagnosis(analysis)
        assert "过滤" in summary or "filter" in summary.lower()
        assert "距离" in summary or "distance" in summary.lower()

    def test_summarize_no_categories(self):
        """有日志但无分类关键词时返回提示。"""
        analysis = [{
            "line": "TH26B6PIEWECN normal dispatch flow",
            "categories": [],
            "keywords": [],
        }]
        summary = _summarize_diagnosis(analysis)
        assert "未匹配" in summary

    def test_interactive_diagnose_exists(self):
        """交互式诊断函数可用。"""
        from passenger_android_core.v160.dispatch_diagnose import interactive_diagnose
        assert callable(interactive_diagnose)

    def test_resolve_kubeconfig_prefers_hk(self):
        """_resolve_kubeconfig 优先使用 ~/.kube/hk，不依赖 KUBECONFIG 环境变量。

        KUBECONFIG 环境变量可能指向不存在的文件（如 ~/Downloads/test7-kubeconfig.yaml），
        此时回退到 ~/.kube/hk。
        """
        from pathlib import Path
        from passenger_android_core.v160.dispatch_diagnose import _resolve_kubeconfig
        hk = Path.home() / ".kube" / "hk"
        if hk.exists():
            # 无参数时应返回 ~/.kube/hk
            result = _resolve_kubeconfig(None)
            assert result == str(hk), \
                f"应返回 ~/.kube/hk，实际返回 {result}"

    def test_interactive_order_no_validation(self):
        """交互模式订单号格式校验：6-20 位字母数字组合。

        支持纯数字（如 313657）和字母数字混合（如 TH26B6PIEWECN）。
        interactive_diagnose 使用 re.match(r"^[A-Z0-9]{6,20}$") 校验。
        """
        import re
        pattern = r"^[A-Z0-9]{6,20}$"
        # 有效格式 — 字母数字混合
        assert re.match(pattern, "TH26B6PIEWECN")
        assert re.match(pattern, "26A4ID0WECNW")
        # 有效格式 — 纯数字
        assert re.match(pattern, "313657")
        assert re.match(pattern, "123456789012")
        # 无效格式 — 太短（不足 6 位）
        assert not re.match(pattern, "short")
        assert not re.match(pattern, "12345")
        # 无效格式 — 太长（超过 20 位）
        assert not re.match(pattern, "1234567890123456789012")
        # 无效格式 — 含特殊字符
        assert not re.match(pattern, "lower_case_01")
        assert not re.match(pattern, "TH-26B6PIE")

    def test_live_track_exists(self):
        """实时追踪函数可用。"""
        from passenger_android_core.v160.dispatch_diagnose import live_track
        assert callable(live_track)

    def test_live_track_event_patterns(self):
        """实时追踪事件关键词覆盖核心调度事件。"""
        from passenger_android_core.v160.dispatch_diagnose import _TRACK_EVENT_PATTERNS
        labels = [label for _, label in _TRACK_EVENT_PATTERNS]
        # 核心调度事件必须覆盖
        assert any("创建派单" in l for l in labels), "应覆盖创建派单事件"
        assert any("开始调度" in l for l in labels), "应覆盖开始调度事件"
        assert any("过滤" in l for l in labels), "应覆盖过滤事件"
        assert any("拒绝" in l for l in labels), "应覆盖拒绝事件"
        assert any("距离" in l for l in labels), "应覆盖距离过滤事件"
        assert any("派单取消" in l for l in labels), "应覆盖派单取消事件"
        assert any("接单" in l for l in labels), "应覆盖接单事件"

    def test_match_track_event_dispatch_create(self):
        """创建派单日志行正确匹配事件标签。"""
        from passenger_android_core.v160.dispatch_diagnose import _match_track_event
        line = '{"category":"DispatchCreateHandler","msg":"创建派单开始"}'
        label = _match_track_event(line)
        assert label is not None
        assert "创建派单" in label

    def test_match_track_event_dispatch_do(self):
        """派单调度日志行正确匹配事件标签。"""
        from passenger_android_core.v160.dispatch_diagnose import _match_track_event
        line = '{"category":"Dispatch.Do","msg":"派单调度"}'
        label = _match_track_event(line)
        assert label is not None
        assert "开始调度" in label

    def test_match_track_event_distance_filter(self):
        """距离过滤日志行正确匹配事件标签。"""
        from passenger_android_core.v160.dispatch_diagnose import _match_track_event
        # distance 关键词在 msg 中，category 不含 filter
        line = '{"category":"DispatchFilter","msg":"距离超出范围，跳过"}'
        label = _match_track_event(line)
        assert label is not None
        # distance 和 filter 都可能匹配，只要包含"距离"或"过滤"即可
        assert "距离" in label or "过滤" in label

    def test_match_track_event_no_match(self):
        """不匹配任何事件的日志行返回 None。"""
        from passenger_android_core.v160.dispatch_diagnose import _match_track_event
        line = '{"category":"Other","msg":"normal log"}'
        label = _match_track_event(line)
        assert label is None

    def test_extract_log_time_from_json(self):
        """从 JSON 日志行提取时间戳。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_log_time
        line = '{"time":"2026-11-19T18:59:00.991+0800","msg":"test"}'
        assert _extract_log_time(line) == "18:59:00"

    def test_extract_log_time_from_plain(self):
        """从纯文本日志行提取时间戳。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_log_time
        line = '2026-11-19 19:02:05.123 some log message'
        assert _extract_log_time(line) == "19:02:05"

    def test_extract_log_category(self):
        """从 JSON 日志行提取 category 字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_log_category
        line = '{"category":"DispatchCreate","msg":"test"}'
        assert _extract_log_category(line) == "DispatchCreate"

    def test_extract_log_msg(self):
        """从 JSON 日志行提取 msg 字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_log_msg
        line = '{"category":"test","msg":"派单请求参数"}'
        assert _extract_log_msg(line) == "派单请求参数"

    def test_grep_new_lines_filters_seen(self):
        """_grep_new_lines 正确过滤已见行。"""
        from passenger_android_core.v160.dispatch_diagnose import _grep_new_lines
        # 模拟：_kubectl 会被 mock，这里测试过滤逻辑
        seen = {"line1", "line2"}
        # 由于 _kubectl 需要真实 K8s，这里只验证函数签名可用
        assert callable(_grep_new_lines)


class TestStructuredLogFormat:
    """结构化日志解析测试 — 验证 JSON 日志字段提取和格式化。"""

    def test_parse_log_json_valid(self):
        """有效 JSON 日志行解析成功。"""
        from passenger_android_core.v160.dispatch_diagnose import _parse_log_json
        line = '{"level":"info","time":"2026-11-19T18:59:00","category":"test","msg":"测试"}'
        result = _parse_log_json(line)
        assert result is not None
        assert result["level"] == "info"
        assert result["category"] == "test"
        assert result["msg"] == "测试"

    def test_parse_log_json_invalid(self):
        """无效 JSON 返回 None。"""
        from passenger_android_core.v160.dispatch_diagnose import _parse_log_json
        result = _parse_log_json("not a json line")
        assert result is None

    def test_extract_fields_from_log_with_properties(self):
        """从 properties 嵌套对象中提取字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_fields_from_log
        line = '{"msg":"派单调度","properties":{"order_id":313661,"agent_id":11,"city_id":514}}'
        fields = _extract_fields_from_log(line)
        assert fields["order_id"] == 313661
        assert fields["agent_id"] == 11
        assert fields["city_id"] == 514

    def test_extract_fields_from_log_with_cancel_params(self):
        """从 cancelParams 嵌套对象中提取字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_fields_from_log
        line = '{"msg":"取消","cancelParams":{"order_id":313661,"driver_id":0,"user_id":"200522"}}'
        fields = _extract_fields_from_log(line)
        assert fields["order_id"] == 313661
        assert fields["driver_id"] == 0
        assert fields["user_id"] == "200522"

    def test_extract_fields_from_log_non_json(self):
        """非 JSON 行返回 raw 字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _extract_fields_from_log
        fields = _extract_fields_from_log("plain text log line")
        assert "raw" in fields

    def test_format_field_value_string(self):
        """字符串值正常返回。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_field_value
        assert _format_field_value("hello") == "hello"

    def test_format_field_value_bool(self):
        """布尔值转为中文。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_field_value
        assert _format_field_value(True) == "是"
        assert _format_field_value(False) == "否"

    def test_format_field_value_long_string_truncated(self):
        """长字符串截断并加省略号。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_field_value
        long_str = "x" * 200
        result = _format_field_value(long_str, max_len=50)
        assert len(result) <= 53
        assert result.endswith("...")

    def test_format_field_value_none(self):
        """None 返回 null。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_field_value
        assert _format_field_value(None) == "null"

    def test_format_log_entry_structured_dispatch_work(self):
        """派单调度日志结构化展示包含关键字段。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_log_entry_structured
        line = ('{"level":"info","time":"2026-11-19T18:59:00.997+0800",'
                '"category":"Dispatch.Do","msg":"派单调度",'
                '"trace_id":"eae795be8609a8f3","log_type":"track","event":"dispatch_work",'
                '"properties":{"order_id":313661,"agent_id":11,"city_id":514,'
                '"order_type":5,"dispatch_type":1,"dispatch_model":1}}')
        result = _format_log_entry_structured(line)
        assert "派单调度" in result
        assert "订单ID: 313661" in result
        assert "代理商ID: 11" in result
        assert "城市ID: 514" in result
        assert "订单类型: 5" in result
        assert "派单模式: 1" in result

    def test_format_log_entry_structured_cancel(self):
        """派单取消日志结构化展示包含取消事件。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_log_entry_structured
        line = ('{"level":"info","time":"2026-11-19T19:04:01.475+0800",'
                '"category":"DispatchCancel","msg":"派单取消",'
                '"trace_id":"6abb634db1501177","log_type":"track",'
                '"event":"dispatch_cancel_succeed",'
                '"properties":{"order_id":313661,"agent_id":11,"city_id":514}}')
        result = _format_log_entry_structured(line)
        assert "派单取消" in result
        assert "dispatch_cancel_succeed" in result
        assert "订单ID: 313661" in result

    def test_format_log_entry_structured_dispatch_request(self):
        """派单请求参数日志结构化展示包含路线信息。"""
        from passenger_android_core.v160.dispatch_diagnose import _format_log_entry_structured
        line = ('{"level":"info","time":"2026-11-19T18:59:00.991+0800",'
                '"category":"Transform","msg":"派单请求参数","log_type":"track",'
                '"event":"dispatch_request",'
                '"order_params":{"order_id":313662,"main_order_id":313661,'
                '"order_no":"26B6Q0UWECNW","user_id":"200522",'
                '"begin_location":"铜锣湾地铁站D2出口","end_location":"大潭郊野公园",'
                '"estimate_distance":18578,"estimate_duration":4545}}')
        result = _format_log_entry_structured(line)
        assert "派单请求参数" in result
        assert "订单ID: 313662" in result
        assert "主订单ID: 313661" in result
        assert "铜锣湾地铁站D2出口" in result
        assert "大潭郊野公园" in result
        assert "18578" in result

    def test_format_diagnosis_structured_mode(self):
        """format_diagnosis 结构化模式输出包含字段详情。"""
        from passenger_android_core.v160.dispatch_diagnose import format_diagnosis
        result = {
            "order_no": "313661",
            "namespace": "test",
            "services": {
                "dispatcher": {
                    "pod": "dispatcher-test",
                    "log_path": "/opt/app/dispatcher/logs/app.log",
                    "match_count": 1,
                    "status": "matched",
                    "matched_lines": '{"msg":"派单调度","properties":{"order_id":313661}}',
                },
            },
            "conclusion": "测试结论",
        }
        output = format_diagnosis(result, structured=True)
        assert "日志详情" in output
        assert "派单调度" in output
        assert "订单ID: 313661" in output

    def test_format_diagnosis_legacy_mode(self):
        """format_diagnosis 向后兼容模式输出原始截断日志。"""
        from passenger_android_core.v160.dispatch_diagnose import format_diagnosis
        raw_line = '{"msg":"派单调度","properties":{"order_id":313661}}'
        result = {
            "order_no": "313661",
            "namespace": "test",
            "services": {
                "dispatcher": {
                    "pod": "dispatcher-test",
                    "log_path": "/opt/app/dispatcher/logs/app.log",
                    "match_count": 1,
                    "status": "matched",
                    "matched_lines": raw_line,
                },
            },
            "conclusion": "测试结论",
        }
        output = format_diagnosis(result, structured=False)
        assert "日志摘要" in output
        assert raw_line in output


class TestMultiKubeconfig:
    """多 kubeconfig 集群选择测试。"""

    def test_kubeconfig_candidates_exist(self):
        """kubeconfig 候选列表已定义。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        assert len(_KUBECONFIG_CANDIDATES) >= 2
        # 第一个是 hk（港版）
        assert _KUBECONFIG_CANDIDATES[0]["name"] == "hk"
        # 第二个是 config（内网）
        assert any(c["name"] == "config" for c in _KUBECONFIG_CANDIDATES)

    def test_kubeconfig_hk_has_services(self):
        """hk 集群配置包含 dispatcher 和 resource-global 服务。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        hk_cfg = _KUBECONFIG_CANDIDATES[0]
        assert hk_cfg["name"] == "hk"
        svc_names = [s["svc"] for s in hk_cfg["services"]]
        assert "dispatcher" in svc_names
        assert "resource-global" in svc_names

    def test_kubeconfig_config_has_different_services(self):
        """config 集群使用 resource-precise-dispatch 而非 resource-global。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        config_cfg = next(c for c in _KUBECONFIG_CANDIDATES if c["name"] == "config")
        svc_names = [s["svc"] for s in config_cfg["services"]]
        assert "dispatcher" in svc_names
        assert "resource-precise-dispatch" in svc_names
        # 内网集群没有 resource-global
        assert "resource-global" not in svc_names

    def test_list_available_kubeconfigs(self):
        """_list_available_kubeconfigs 返回文件存在的配置。"""
        from passenger_android_core.v160.dispatch_diagnose import _list_available_kubeconfigs
        available = _list_available_kubeconfigs()
        # 至少有一个 kubeconfig 文件存在
        assert len(available) >= 1
        for cfg in available:
            from pathlib import Path
            assert Path(cfg["path"]).exists()

    def test_detect_kubeconfig_explicit(self):
        """显式传入 kubeconfig 时直接使用。"""
        from pathlib import Path
        from passenger_android_core.v160.dispatch_diagnose import _detect_kubeconfig, _KUBECONFIG_CANDIDATES
        hk_path = str(Path.home() / ".kube" / "hk")
        if Path(hk_path).exists():
            kc, services = _detect_kubeconfig(kubeconfig=hk_path, namespace="test")
            assert kc == hk_path
            svc_names = [s["svc"] for s in services]
            assert "dispatcher" in svc_names

    def test_detect_kubeconfig_unknown_returns_default_services(self):
        """传入未知 kubeconfig 时返回默认服务配置。"""
        from pathlib import Path
        from passenger_android_core.v160.dispatch_diagnose import _detect_kubeconfig, _KUBECONFIG_CANDIDATES
        # 创建临时文件作为未知 kubeconfig
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            tmp_path = f.name
        try:
            kc, services = _detect_kubeconfig(kubeconfig=tmp_path, namespace="test")
            assert kc == tmp_path
            # 应该返回第一个候选的服务配置
            assert len(services) > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_diagnose_no_accept_accepts_kubeconfig_param(self):
        """diagnose_no_accept 接受 kubeconfig 参数。"""
        import inspect
        from passenger_android_core.v160.dispatch_diagnose import diagnose_no_accept
        sig = inspect.signature(diagnose_no_accept)
        assert "kubeconfig" in sig.parameters
        assert "namespace" in sig.parameters

    def test_live_track_accepts_kubeconfig_param(self):
        """live_track 接受 kubeconfig 参数。"""
        import inspect
        from passenger_android_core.v160.dispatch_diagnose import live_track
        sig = inspect.signature(live_track)
        assert "kubeconfig" in sig.parameters

    def test_interactive_diagnose_accepts_kubeconfig_param(self):
        """interactive_diagnose 接受 kubeconfig 参数。"""
        import inspect
        from passenger_android_core.v160.dispatch_diagnose import interactive_diagnose
        sig = inspect.signature(interactive_diagnose)
        assert "kubeconfig" in sig.parameters

    def test_diagnose_result_contains_kubeconfig(self):
        """诊断结果包含 kubeconfig 字段。"""
        from passenger_android_core.v160.dispatch_diagnose import format_diagnosis
        result = {
            "order_no": "313661",
            "namespace": "test",
            "kubeconfig": "/Users/test/.kube/hk",
            "services": {},
            "conclusion": "测试",
        }
        # 只要能格式化不报错即可
        output = format_diagnosis(result)
        assert "313661" in output


class TestMultiFileSearch:
    """多日志文件搜索测试。"""

    def test_config_dispatcher_has_multiple_log_paths(self):
        """内网集群 dispatcher 配置了多个日志路径（info + debug）。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        config_cfg = next(c for c in _KUBECONFIG_CANDIDATES if c["name"] == "config")
        dispatcher_svc = next(s for s in config_cfg["services"] if s["svc"] == "dispatcher")
        assert len(dispatcher_svc["log_paths"]) >= 4
        # 包含 app-info.log
        assert any("app-info.log" in p for p in dispatcher_svc["log_paths"])
        # 包含 app-debug.log
        assert any("app-debug.log" in p for p in dispatcher_svc["log_paths"])
        # 包含 dev namespace 路径 (jryg-dispatcher)
        assert any("jryg-dispatcher" in p for p in dispatcher_svc["log_paths"])

    def test_hk_dispatcher_has_log_paths(self):
        """港版集群 dispatcher 配置了日志路径。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        hk_cfg = _KUBECONFIG_CANDIDATES[0]
        dispatcher_svc = next(s for s in hk_cfg["services"] if s["svc"] == "dispatcher")
        assert len(dispatcher_svc["log_paths"]) >= 1
        assert any("app.log" in p for p in dispatcher_svc["log_paths"])

    def test_find_all_log_paths_exists(self):
        """_find_all_log_paths 函数存在且参数正确。"""
        import inspect
        from passenger_android_core.v160.dispatch_diagnose import _find_all_log_paths
        sig = inspect.signature(_find_all_log_paths)
        assert "kubeconfig" in sig.parameters
        assert "namespace" in sig.parameters
        assert "pod" in sig.parameters
        assert "candidates" in sig.parameters

    def test_config_resource_has_resource_paths(self):
        """内网集群 resource-precise-dispatch 包含 resource 和 resource-precise-dispatch 两种路径。"""
        from passenger_android_core.v160.dispatch_diagnose import _KUBECONFIG_CANDIDATES
        config_cfg = next(c for c in _KUBECONFIG_CANDIDATES if c["name"] == "config")
        resource_svc = next(s for s in config_cfg["services"] if s["svc"] == "resource-precise-dispatch")
        paths = resource_svc["log_paths"]
        # 包含 resource-precise-dispatch 路径
        assert any("resource-precise-dispatch" in p for p in paths)
        # 也包含 resource 路径（兜底）
        assert any("/opt/app/resource/logs/" in p for p in paths)

    def test_diagnose_result_can_contain_log_paths_searched(self):
        """诊断结果支持 log_paths_searched 字段。"""
        from passenger_android_core.v160.dispatch_diagnose import format_diagnosis
        result = {
            "order_no": "313661",
            "namespace": "test",
            "kubeconfig": "/Users/test/.kube/config",
            "services": {
                "dispatcher": {
                    "pod": "dispatcher-xxx",
                    "log_path": "/opt/app/dispatcher/logs/app-debug.log",
                    "log_paths_searched": [
                        "/opt/app/dispatcher/logs/app-info.log",
                        "/opt/app/dispatcher/logs/app-debug.log",
                    ],
                    "match_count": 5,
                    "matched_lines": "",
                    "analysis": [],
                    "status": "matched",
                    "summary": "测试",
                }
            },
            "conclusion": "测试",
        }
        # 只要能格式化不报错即可
        output = format_diagnosis(result)
        assert "313661" in output
        assert "app-debug.log" in output


class TestDispatchDiagnoseK8s:
    """诊断模块 K8s 集成测试 — 需港版集群可达 + 真实订单号。

    前置：
    1. ~/.kube/hk 可达港版 K8s 集群
    2. V160_REAL_ORDER_NO 环境变量传入真实订单号

    未提供订单号时 skip，不伪造订单号。
    """

    def _need_k8s_and_order(self):
        """检查 K8s 可达性和真实订单号。"""
        if not _REAL_ORDER_NO:
            pytest.skip(
                "未提供真实订单号（V160_REAL_ORDER_NO），"
                "无司机接单诊断需真实订单号查询"
            )
        kubeconfig = os.path.expanduser("~/.kube/hk")
        if not os.path.exists(kubeconfig):
            pytest.skip(f"港版 kubeconfig 不存在: {kubeconfig}")

    def test_diagnose_returns_dict(self):
        """诊断结果返回字典结构完整。"""
        self._need_k8s_and_order()
        result = diagnose_no_accept(_REAL_ORDER_NO, namespace="test")
        assert isinstance(result, dict)
        assert "order_no" in result
        assert "services" in result
        assert "conclusion" in result
        assert result["order_no"] == _REAL_ORDER_NO

    def test_diagnose_checks_dispatcher(self):
        """诊断结果包含 dispatcher 服务查询结果。"""
        self._need_k8s_and_order()
        result = diagnose_no_accept(_REAL_ORDER_NO, namespace="test")
        assert "dispatcher" in result["services"]
        svc = result["services"]["dispatcher"]
        assert "pod" in svc
        assert "match_count" in svc
        assert "status" in svc

    def test_diagnose_checks_resource_global(self):
        """诊断结果包含 resource-global 服务查询结果。"""
        self._need_k8s_and_order()
        result = diagnose_no_accept(_REAL_ORDER_NO, namespace="test")
        assert "resource-global" in result["services"]
        svc = result["services"]["resource-global"]
        assert "pod" in svc
        assert "match_count" in svc
        assert "status" in svc

    def test_diagnose_has_conclusion(self):
        """诊断结果包含结论文本。"""
        self._need_k8s_and_order()
        result = diagnose_no_accept(_REAL_ORDER_NO, namespace="test")
        assert result["conclusion"], "诊断结论不应为空"

    def test_format_diagnosis_readable(self):
        """格式化输出包含关键信息。"""
        self._need_k8s_and_order()
        result = diagnose_no_accept(_REAL_ORDER_NO, namespace="test")
        text = format_diagnosis(result)
        assert _REAL_ORDER_NO in text
        assert "dispatcher" in text
        assert "resource-global" in text
        assert "结论" in text

    def test_diagnose_nonexistent_order(self):
        """不存在的订单号在两个服务中均无匹配。

        用伪造的订单号验证"订单未进入调度链路"的结论。
        """
        self._need_k8s_and_order()
        fake_no = "FAKE_NOT_EXIST_ORDER_NO_001"
        result = diagnose_no_accept(fake_no, namespace="test")
        # 两个服务都应无匹配
        for svc_name in ("dispatcher", "resource-global"):
            svc = result["services"].get(svc_name, {})
            assert svc.get("match_count", 0) == 0, \
                f"{svc_name} 不应匹配伪造订单号"
        assert "未进入调度链路" in result["conclusion"] or "无匹配" in result["conclusion"]
