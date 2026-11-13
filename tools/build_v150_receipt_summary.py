"""生成 V1.5.0 收据/邮箱功能验收汇总报告。

合并多批真机执行结果，逐条展示每条用例的通过状态、需求项判定，
并把接口层抓取（retrofit logcat 还原）的服务端响应作为独立证据列出。

用法：
    .venv/bin/python tools/build_v150_receipt_summary.py \
        --run report/v150_receipt_acceptance_20261112_125234_evidence \
        --run report/v150_receipt_visual_probe_20261112_evidence \
        --run report/v150_receipt_verified_20261112_evidence \
        --out report/v150_receipt_summary_20261112
"""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 接口逻辑名 -> 需求文档接口路径
API_LABEL = {
    "user_save": "POST /passenger/user/save",
    "contact_list": "GET /passenger/contact/list",
    "contact_save": "POST /passenger/contact/save",
    "contact_delete": "POST /passenger/contact/delete",
    "contact_share": "POST /passenger/contact/share",
    "emergency_alarm": "POST /passenger/emergency/alarm",
    "trip_send": "POST /passenger/order/tripSend",
    "user_info": "GET /passenger/user/getInfo",
    "order_detail": "POST /passenger/order/detail",
    "order_list": "GET /passenger/order/list",
}


def load_runs(run_dirs):
    """合并多批执行结果，按用例 nodeid 去重，后执行覆盖先执行。"""
    merged = {}
    order = []
    for raw in run_dirs:
        path = Path(raw)
        results = path / "results.json"
        if not results.is_file():
            continue
        for record in json.loads(results.read_text(encoding="utf-8")):
            nodeid = record["nodeid"]
            if nodeid not in merged:
                order.append(nodeid)
            record["run"] = path.name
            merged[nodeid] = record
    return [merged[nodeid] for nodeid in order]


def case_title(nodeid):
    """从 nodeid 提取可读用例名。"""
    parts = nodeid.split("::")
    return parts[-1] if len(parts) > 1 else nodeid


def api_rows(record):
    """列出该用例抓取到的接口调用与响应。"""
    rows = []
    for evidence in record.get("evidence", []):
        for call in evidence.get("api_calls", []) or []:
            rows.append(call)
    if not rows:
        rows = record.get("api_calls", []) or []
    return rows


def render_api_table(record):
    """渲染接口层证据表格。"""
    rows = api_rows(record)
    if not rows:
        return '<p class="no-api">本次执行未捕获到接口层证据。</p>'
    parts = ['<table class="api"><thead><tr><th>接口</th><th>请求参数</th>'
             '<th>响应码</th><th>服务端消息</th></tr></thead><tbody>']
    for call in rows:
        name = call.get("api") or "未识别"
        label = API_LABEL.get(name, call.get("url", "") or name)
        params = call.get("params") or {}
        params_text = "、".join(f"{k}={v}" for k, v in params.items()) or "—"
        code = call.get("code")
        code_class = "ok" if code == 10000 else ("bad" if code else "none")
        parts.append(
            f'<tr><td class="mono">{html.escape(str(label))}</td>'
            f'<td class="mono">{html.escape(params_text)}</td>'
            f'<td class="mono {code_class}">{html.escape(str(code))}</td>'
            f'<td>{html.escape(str(call.get("message") or "—"))}</td></tr>')
    parts.append("</tbody></table>")
    return "".join(parts)


def render_case(record):
    """渲染单条用例。"""
    status = record.get("status", "unknown")
    passed = status == "passed"
    badge = '<span class="badge pass">PASS</span>' if passed else '<span class="badge fail">FAIL</span>'
    checks = record.get("checks", []) or []
    total = len(checks)
    ok = sum(1 for c in checks if c.get("passed"))
    title = case_title(record["nodeid"])

    rows = []
    for check in checks:
        mark = '<span class="mark ok">✓</span>' if check.get("passed") else '<span class="mark bad">✗</span>'
        category = check.get("category", "")
        cat_html = f'<span class="cat">{html.escape(category)}</span>' if category else ""
        actual = check.get("actual")
        actual_text = html.escape(json.dumps(actual, ensure_ascii=False)
                                  if not isinstance(actual, str) else actual)
        rows.append(
            f'<tr><td>{mark}</td><td>{html.escape(str(check.get("requirement", "")))} {cat_html}</td>'
            f'<td class="mono">{html.escape(str(check.get("expected", "")))}</td>'
            f'<td class="mono">{actual_text}</td></tr>')

    checks_html = ('<table class="checks"><thead><tr><th></th><th>需求项</th>'
                   '<th>预期</th><th>实际</th></tr></thead><tbody>'
                   + "".join(rows) + "</tbody></table>") if rows else ""

    evidence = []
    for item in record.get("evidence", []) or []:
        for key in ("xml", "screenshot", "video"):
            if item.get(key):
                evidence.append(f'<a href="{html.escape(str(item[key]))}">{key}</a>')
        if item.get("log_file"):
            evidence.append('<a href="#">接口日志</a>')

    return f"""
    <details class="case {'pass' if passed else 'fail'}" {'open' if not passed else ''}>
      <summary>
        {badge}
        <span class="title">{html.escape(title)}</span>
        <span class="ratio">{ok}/{total} 项</span>
        <span class="run">{html.escape(record.get('run', ''))}</span>
      </summary>
      <div class="body">
        {checks_html}
        <h4>接口层证据</h4>
        {render_api_table(record)}
        <div class="evidence">{' · '.join(evidence) or '无'}</div>
      </div>
    </details>"""


def build(runs, out_base, defects):
    records = load_runs(runs)
    passed = sum(1 for r in records if r.get("status") == "passed")
    failed = len(records) - passed

    api_total = sum(len(api_rows(r)) for r in records)

    cases_html = "".join(render_case(r) for r in records)

    defect_html = ""
    if defects:
        items = []
        for defect in defects:
            items.append(f"""
        <div class="defect">
          <div class="did">{html.escape(str(defect.get('id', '')))}</div>
          <div class="dtitle">{html.escape(str(defect.get('title', '')))}</div>
          <div class="dbody">{html.escape(str(defect.get('detail', '')))}</div>
          <div class="dcases">影响用例：{html.escape(str(defect.get('cases', '')))}</div>
        </div>""")
        defect_html = ('<h2>已确认缺陷</h2>'
                       '<p class="note">以下为多次分批执行后归并的真实产品缺陷，'
                       '与用例执行次数无关。</p>' + "".join(items))

    html_text = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>V1.5.0 行程收據驗收匯總</title>
<style>
 * {{ box-sizing: border-box; }}
 body {{ font-family: -apple-system, "PingFang HK", "Helvetica Neue", sans-serif;
   margin: 0; padding: 24px; background: #f5f6f8; color: #1c1e21; }}
 h1 {{ font-size: 22px; margin: 0 0 4px; }}
 .sub {{ color: #65676b; font-size: 13px; margin-bottom: 20px; }}
 .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
 .card {{ background: #fff; border-radius: 10px; padding: 14px 20px;
   box-shadow: 0 1px 3px rgba(0,0,0,.08); min-width: 120px; }}
 .card .n {{ font-size: 24px; font-weight: 600; }}
 .card .l {{ font-size: 12px; color: #65676b; margin-top: 2px; }}
 .card.pass .n {{ color: #0a8f3c; }}
 .card.fail .n {{ color: #d93025; }}
 .card.api .n {{ color: #1a73e8; }}
 h2 {{ font-size: 17px; margin: 28px 0 10px; }}
 .note {{ font-size: 13px; color: #65676b; margin: 0 0 12px; }}
 details.case {{ background: #fff; border-radius: 8px; margin-bottom: 8px;
   box-shadow: 0 1px 2px rgba(0,0,0,.06); overflow: hidden; }}
 details.case summary {{ display: flex; align-items: center; gap: 10px;
   padding: 11px 14px; cursor: pointer; list-style: none; }}
 details.case summary::-webkit-details-marker {{ display: none; }}
 .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
 .badge.pass {{ background: #e6f4ea; color: #0a8f3c; }}
 .badge.fail {{ background: #fce8e6; color: #d93025; }}
 .title {{ font-size: 13.5px; font-weight: 500; flex: 1; }}
 .ratio {{ font-size: 12px; color: #65676b; }}
 .run {{ font-size: 11px; color: #8a8c90; }}
 .body {{ padding: 0 14px 14px; border-top: 1px solid #eceef0; }}
 table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12.5px; }}
 th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #f0f1f3;
   vertical-align: top; }}
 th {{ color: #65676b; font-weight: 500; background: #fafbfc; }}
 .mono {{ font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }}
 .mark.ok {{ color: #0a8f3c; font-weight: 700; }}
 .mark.bad {{ color: #d93025; font-weight: 700; }}
 .cat {{ font-size: 10.5px; color: #8a8c90; border: 1px solid #e4e6e8;
   border-radius: 3px; padding: 0 4px; margin-left: 4px; }}
 .ok {{ color: #0a8f3c; }} .bad {{ color: #d93025; }} .none {{ color: #8a8c90; }}
 .evidence {{ margin-top: 10px; font-size: 12px; }}
 .evidence a {{ color: #1a73e8; margin-right: 10px; }}
 .no-api {{ font-size: 12.5px; color: #8a8c90; margin: 8px 0 0; }}
 .defect {{ background: #fff; border-left: 3px solid #d93025; border-radius: 6px;
   padding: 12px 16px; margin-bottom: 8px; }}
 .did {{ font-size: 11px; color: #d93025; font-weight: 700; }}
 .dtitle {{ font-size: 14px; font-weight: 600; margin: 3px 0 6px; }}
 .dbody {{ font-size: 12.5px; color: #3c3f42; line-height: 1.6; }}
 .dcases {{ font-size: 11.5px; color: #8a8c90; margin-top: 6px; }}
 .filter {{ margin-bottom: 16px; }}
 .filter button {{ font-size: 12.5px; padding: 5px 14px; margin-right: 8px;
   border: 1px solid #dadce0; background: #fff; border-radius: 14px; cursor: pointer; }}
 .filter button.on {{ background: #1a73e8; color: #fff; border-color: #1a73e8; }}
</style>
</head>
<body>
<h1>V1.5.0 行程收據／電子郵箱 驗收匯總</h1>
<div class="sub">合併 {len(runs)} 批真機執行結果，逐條用例獨立展示，附接口層服務端響應證據</div>

<div class="cards">
  <div class="card"><div class="n">{len(records)}</div><div class="l">用例總數</div></div>
  <div class="card pass"><div class="n">{passed}</div><div class="l">通過</div></div>
  <div class="card fail"><div class="n">{failed}</div><div class="l">失敗</div></div>
  <div class="card api"><div class="n">{api_total}</div><div class="l">接口調用證據</div></div>
</div>

{defect_html}

<h2>用例明細</h2>
<div class="filter">
  <button class="on" onclick="flt(this,'all')">全部</button>
  <button onclick="flt(this,'pass')">僅通過</button>
  <button onclick="flt(this,'fail')">僅失敗</button>
</div>
{cases_html}

<script>
function flt(btn, kind) {{
  document.querySelectorAll('.filter button').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('details.case').forEach(d => {{
    d.style.display = (kind === 'all' || d.classList.contains(kind)) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    out_base.with_suffix(".html").write_text(html_text, encoding="utf-8")
    out_base.with_suffix(".json").write_text(json.dumps({
        "runs": [str(r) for r in runs],
        "counts": {"total": len(records), "passed": passed, "failed": failed},
        "defects": defects or [],
        "cases": [{"nodeid": r["nodeid"], "status": r.get("status"),
                   "checks": r.get("checks", []),
                   "api_calls": api_rows(r),
                   "evidence": r.get("evidence", [])} for r in records],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {out_base.with_suffix('.html')}")
    print(f"已生成 {out_base.with_suffix('.json')}")
    print(f"用例 {len(records)} 条：通过 {passed}，失败 {failed}，接口证据 {api_total} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True,
                        help="执行结果证据目录（含 results.json），可重复指定")
    parser.add_argument("--out", required=True, help="输出文件前缀")
    parser.add_argument("--defects", help="缺陷清单 JSON 文件")
    args = parser.parse_args()

    defects = []
    if args.defects:
        defects = json.loads(Path(args.defects).read_text(encoding="utf-8"))
    build(args.run, args.out, defects)


if __name__ == "__main__":
    main()
