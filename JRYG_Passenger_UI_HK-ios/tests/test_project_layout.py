"""目录归档的离线回归：入口与公共封装分离，路径仍相对项目根。

仅静态读取文件或模拟pytest调用，不连接真机、不执行订单和历史接口工具。
覆盖运行器用例名单、报告路径、包引用及根目录不再散落业务脚本。
"""

import ast
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from ui_framework import JRYG_driver_ui, JRYG_order_flow
from ui_framework.JRYG_ios_ui_base import iOSBase
from runners import JRYG_run_main_ios, JRYG_run_driver_flow

ROOT = Path(__file__).resolve().parents[1]


def test_project_root_has_no_loose_python_or_shell_entrypoints():
    """根目录只保留配置清单和职责目录，不散放业务Python或Shell入口。"""
    assert list(ROOT.glob("*.py")) == []
    assert list(ROOT.glob("*.sh")) == []


def test_cases_use_one_public_order_flow():
    """所有真机场景引用唯一公共基类，cases内不保留基类实现副本。"""
    assert not (ROOT / "cases/JRYG_test_ios_order_base.py").exists()
    files = sorted((ROOT / "cases").glob("JRYG_test_ios_*.py"))
    assert len(files) == 7
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert any(node.module == "ui_framework.JRYG_order_flow" and
                   any(alias.name == "TestOrderBase" for alias in node.names)
                   for node in imports), path.name
    assert issubclass(JRYG_order_flow.TestOrderBase, iOSBase)


def test_driver_entrypoint_only_delegates_public_main():
    """运行入口只委托公共司机main，订单编排直接引用同一状态机。"""
    assert JRYG_run_driver_flow.main is JRYG_driver_ui.main
    assert JRYG_order_flow.DriverUIFlow is JRYG_driver_ui.DriverUIFlow
    tree = ast.parse((ROOT / "runners/JRYG_run_driver_flow.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.ClassDef, ast.FunctionDef)) for node in tree.body)


def test_driver_report_path_remains_at_project_root():
    """司机封装迁入包后报告仍写原report/driver_ui，而非公共代码目录。"""
    args = JRYG_driver_ui.parser().parse_args([])
    assert Path(args.report_dir) == ROOT / "report/driver_ui"


@pytest.mark.parametrize("collect_only", [True, False])
def test_main_runner_keeps_original_cases_and_config(monkeypatch, collect_only):
    """模拟pytest调用，核验六场景、配置位置、收集模式及报告路径。

    :param monkeypatch: 替换目录初始化及pytest执行，不创建真实订单。
    :param collect_only: 是否只收集；只有正式运行才配置HTML报告。
    """
    monkeypatch.setattr(JRYG_run_main_ios, "init_all_dirs", Mock())
    run = Mock(return_value=0)
    monkeypatch.setattr(JRYG_run_main_ios.pytest, "main", run)
    extra = ["--collect-only"] if collect_only else []
    assert JRYG_run_main_ios.run_tests(extra) == 0
    args = run.call_args.args[0]
    assert args[:2] == ["-c", str(ROOT / "pytest.ini")]
    cases = [Path(arg) for arg in args if arg.endswith(".py")]
    assert len(cases) == 6
    assert all(path.parent == ROOT / "cases" and path.is_file() for path in cases)
    assert not any(path.name == "JRYG_test_ios_meter_epayment_order.py" for path in cases)
    reports = [arg for arg in args if arg.startswith("--html=")]
    assert reports == ([] if collect_only else [f"--html={ROOT / 'report/JRYG_test_report_hk_ios.html'}"])


def test_shell_resolves_resources_from_project_root():
    """Shell从runners上一级定位WDA工程和日志，两种执行路径均调用新入口。"""
    text = (ROOT / "runners/JRYG_run_hk_ios.sh").read_text(encoding="utf-8")
    assert '$(dirname "${BASH_SOURCE[0]}")/..' in text
    assert text.count('"$BASE_DIR/runners/JRYG_run_main_ios.py"') == 2
    assert '"$BASE_DIR/iOS-Tagent/WebDriverAgent.xcodeproj"' in text


def test_legacy_tool_retains_original_config_and_output_location():
    """仅静态校验历史工具归档后的路径，不导入或执行其登录请求。"""
    text = (ROOT / "tools/legacy/JRYG_prepare_tokens.py").read_text(encoding="utf-8")
    assert "UI_DIR = Path(__file__).resolve().parents[2]" in text
    assert "BASE_DIR = UI_DIR.parent" in text
    assert 'tmp_dir = UI_DIR / "tmp"' in text
    assert (ROOT / "docs/JRYG_epayment_verified_flow.md").is_file()


@pytest.mark.parametrize("case_file", sorted((ROOT / "cases").glob("JRYG_test_ios_*.py")), ids=lambda path: path.stem)
def test_direct_case_entry_collects_without_device_initialization(case_file):
    """每个独立文件均在新进程中按用户方式仅收集，不提前加载Poco或探测Android。

    :param case_file: 真机场景入口，包含旧银行卡兼容文件；不执行测试方法。
    """
    result = subprocess.run(
        [sys.executable, str(case_file), "--collect-only", "-q"],
        cwd=ROOT.parent, capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "1 test collected" in output, output
    assert "_SixMetaPathImporter" not in output
    assert "Android Asset Packaging Tool" not in output


def test_public_ui_import_does_not_load_device_dependencies():
    """新进程导入公共基类不得加载Airtest/Poco或注册不支持find_spec的导入器。"""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from ui_framework.JRYG_ios_ui_base import iOSBase; "
         "assert not any(name == 'poco' or name.startswith('poco.') or "
         "name == 'airtest' or name.startswith('airtest.') for name in sys.modules); "
         "assert not any(type(finder).__name__ == '_SixMetaPathImporter' and "
         "not hasattr(finder, 'find_spec') for finder in sys.meta_path)"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
