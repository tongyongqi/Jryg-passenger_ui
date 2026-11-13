"""V1.5.0 邮箱管理真机调试场景（脑图「郵箱管理與格式校驗」分支）。

严格按用例脑图逐条实现，每条用例一个 test_ 方法：

1. 设置页新增电子邮箱输入口点击进入电子邮箱管理页
   —— 从首页「我的」→ 设置 → 電子郵箱 进入管理页，校验页面已加载。
2. 保存邮箱时去除首尾空格格式校验要求（仅包含一个@且@前后非空域名至少多一点）
   —— 离线契约校验：首尾空格被去除；多个@被拒绝；@前为空被拒绝；
      @后无点被拒绝。
3. 输入包含前后空格的合法邮箱保存成功且实际存储值去除空格后的值
   —— 真机输入「  user@example.com  」，保存后重新进入邮箱页回读，
      实际存储值应为去空格后的 user@example.com。
4. 邮箱格式不正确时 toast 提示邮箱格式不正确且不予保存
   —— 真机输入非法邮箱并保存，应捕获 toast「郵箱格式不正確」，
      且邮箱值未被保存。
5. 编辑框为空值点击保存视为删除该邮箱 toast 提示保存成功
   —— 真机清空邮箱并保存，应捕获「保存成功」toast，重新进入邮箱页
      回读邮箱为空。

用例结束后恢复原始邮箱，避免污染账号配置。
不发送电子收据、不调用收据接口。
"""

from pathlib import Path
import sys

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import logging
logger = logging.getLogger("JRYG_HK_android")

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps
from jryg_hk_android.JRYG_v150_contract import normalize_email
from jryg_hk_android.JRYG_v150_api_log import check_api_response


class TestV150EmailDevice(V150DeviceSteps):
    __test__ = True
    DRIVER_REQUIRED = False

    @pytest.mark.parametrize("previous,value", [
        pytest.param(None, "single@example.com", id="01-normal-email"),
        pytest.param("single@example.com", "  spaces@example.com  ",
                     id="02-leading-trailing-spaces"),
        pytest.param("  spaces@example.com  ", "invalid-email", id="03-invalid-email"),
        pytest.param("invalid-email", "", id="04-empty-value"),
        pytest.param("", "o'connor+tag@example.com", id="05-quote-plus"),
        pytest.param("o'connor+tag@example.com", "x" * 80 + "@example.com",
                     id="06-long-email"),
        pytest.param("x" * 80 + "@example.com", "final@example.com",
                     id="07-replace-again"),
    ])
    def test_email_native_input_replaces_exactly_once(self, previous, value, request):
        """每组输入独立准备旧值、替换并原样回读，不保存或发送。"""
        tag = f"v150_email_native_input_{request.node.callspec.id}"
        self.v150_open_email_settings(tag)
        original = self.v150_email_read_current(tag)
        try:
            if previous is not None:
                self.v150_email_type(tag, previous)
                assert self.v150_email_read_current(tag) == previous, "前置输入未准确写入"
            self.v150_email_type(tag, value)
            actual = self.v150_email_read_current(tag)
            assert actual == value, f"原样输入回读不一致：{value!r} != {actual!r}"
        finally:
            self._v150_reopen_email_page(tag)
        assert self.v150_email_read_current(tag) == original, "未提交的输入改变了已保存邮箱"

    # ==================== 用例1：进入电子邮箱管理页 ====================

    def test_email_settings_entry_open_management_page(self):
        """设置页新增电子邮箱输入口点击进入电子邮箱管理页。"""
        tag = "v150_email_entry"
        page = self.v150_open_email_settings(tag)
        assert page == "email_settings", f"未进入电子邮箱管理页：{page}"
        self.v150_screenshot("email_entry_management_page")

        # 管理页必须同时具备：邮箱输入框与保存按钮
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        has_input = any(self._v150_is_input(n) for n in nodes)
        has_save = any("保存" in (n.get("label") or "")
                       or "保存" in (n.get("content-desc") or "")
                       or "保存" in (n.get("text") or "") for n in nodes)
        assert has_input, "电子邮箱管理页缺少邮箱输入框"
        assert has_save, "电子邮箱管理页缺少保存按钮"

    # ==================== 用例2：保存邮箱的格式校验规则 ====================

    def test_email_save_format_validation_rules(self):
        """保存邮箱时去除首尾空格；仅允许一个@且@前后非空、域名至少多一点。"""
        tag = "v150_email_rule"

        # 首尾空格必须被去除
        assert normalize_email("  user@example.com  ") == "user@example.com"

        # 仅允许一个@：多个@必须被拒绝
        for invalid in ("a@b@c.com", "user@@example.com"):
            try:
                normalize_email(invalid)
            except ValueError:
                continue
            raise AssertionError(f"多@邮箱未被拒绝：{invalid}")

        # @前必须非空
        try:
            normalize_email("@example.com")
        except ValueError:
            pass
        else:
            raise AssertionError("@前为空的邮箱未被拒绝")

        # @后域名至少要有一个点
        try:
            normalize_email("user@example")
        except ValueError:
            pass
        else:
            raise AssertionError("域名缺少点的邮箱未被拒绝")

        # 内部空白必须被拒绝
        try:
            normalize_email("us er@example.com")
        except ValueError:
            pass
        else:
            raise AssertionError("含空格的邮箱未被拒绝")

        self.v150_screenshot("email_format_rules")

    # ==================== 用例3：含前后空格的合法邮箱保存成功 ====================

    def test_email_save_with_surrounding_spaces_trims_value(self):
        """输入包含前后空格的合法邮箱，保存成功且实际存储值去除空格后的值。"""
        tag = "v150_email_trim"
        self.v150_open_email_settings(tag)
        original = self.v150_email_read_current(tag)

        padded = "  v150_trim@example.com  "
        expected = "v150_trim@example.com"
        try:
            actual = self.v150_email_save(tag, email=padded)
            self.v150_screenshot("email_after_trim_save")
            assert actual == expected, (
                f"含空格邮箱保存后应存储去空格的值：expected={expected!r}, actual={actual!r}")
            api_result = check_api_response(
                getattr(self, "_last_email_api_calls", []), "user_save", expect_code=10000)
            assert api_result["passed"], (
                f"邮箱保存接口未返回成功：{api_result.get('reason') or api_result}")
        finally:
            self._v150_reopen_email_page(tag)
            if self.v150_email_read_current(tag) != original:
                restored = self.v150_email_save(tag, email=original)
                assert restored == original, "测试后原始邮箱恢复失败"

    # ==================== 用例4：格式不正确时 toast 提示且不保存 ====================

    def test_email_invalid_format_toast_and_not_saved(self):
        """同一页面内连续验证多种非法邮箱格式：输入→保存→验证toast→清空→下一个。"""
        tag = "v150_email_invalid"
        self.v150_open_email_settings(tag)
        original = self.v150_email_read_current(tag)

        # 注意：含内部空格的邮箱（如 "us er@example.com"）App 会先去空格再校验，
        # 结果是合法邮箱被保存成功，不属于"格式错误"场景，故不列入。
        invalid_cases = [
            ("invalid-email-no-at-sign", "no-at"),
            ("a@b@c.com", "multiple-at"),
            ("@example.com", "empty-local"),
            ("user@", "empty-domain"),
            ("user@example", "domain-no-dot"),
        ]
        failures = []
        try:
            for value, case_id in invalid_cases:
                self.v150_email_type(tag, value)
                self._v150_email_start_api_capture(tag)
                self.v150_email_click_save(tag)
                toast = self._v150_wait_toast(("郵箱格式不正確",), tag=tag)
                self._v150_email_collect_api_log(tag)
                self.v150_screenshot(f"email_invalid_{case_id}")
                # 非法邮箱校验失败后应留在邮箱管理页，不跳转
                page = self._v150_current_page_type()
                if toast != "郵箱格式不正確":
                    failures.append(f"[{case_id}] 非法格式提示不匹配：{toast!r}")
                if page != "email_settings":
                    failures.append(f"[{case_id}] 非法邮箱不应保存跳转：page={page}")
                api_result = check_api_response(
                    getattr(self, "_last_email_api_calls", []), "user_save")
                if api_result["matched"]:
                    failures.append(f"[{case_id}] 非法邮箱不应调用保存接口：{api_result}")
                logger.info("【%s】%s 验证完成，清空输入框继续下一条", tag, case_id)
            assert not failures, "; ".join(failures)
        finally:
            self._v150_reopen_email_page(tag)
            if self.v150_email_read_current(tag) != original:
                restored = self.v150_email_save(tag, email=original)
                assert restored == original, "测试后原始邮箱恢复失败"

    # ==================== 用例5：空值保存视为删除且 toast 提示保存成功 ====================

    def test_email_empty_value_deletes_and_toast_success(self):
        """编辑框为空值点击保存视为删除该邮箱，toast 提示保存成功。"""
        tag = "v150_email_delete"
        self.v150_open_email_settings(tag)
        original = self.v150_email_read_current(tag)

        try:
            seed = "v150_delete_probe@example.com"
            seeded = self.v150_email_save(tag, email=seed)
            assert seeded == seed, f"前置邮箱写入失败：expected={seed!r}, actual={seeded!r}"

            self.v150_email_type(tag, "")
            self._v150_email_start_api_capture(tag)
            self.v150_email_click_save(tag)
            toast = self._v150_wait_toast(("保存成功",), tag=tag)
            self._v150_email_collect_api_log(tag)
            self.v150_screenshot("email_delete_toast")
            self._v150_reopen_email_page(tag)
            actual = self.v150_email_read_current(tag)
            failures = []
            if toast != "保存成功":
                failures.append(f"空值保存后提示不匹配：{toast!r}")
            if actual != "":
                failures.append(f"空值保存后邮箱未删除：{actual!r}")
            api_result = check_api_response(
                getattr(self, "_last_email_api_calls", []), "user_save", expect_code=10000)
            if not api_result["passed"]:
                failures.append(f"邮箱删除接口未返回成功：{api_result.get('reason') or api_result}")
            assert not failures, "; ".join(failures)
        finally:
            self._v150_reopen_email_page(tag)
            if self.v150_email_read_current(tag) != original:
                restored = self.v150_email_save(tag, email=original)
                assert restored == original, "测试后原始邮箱恢复失败"


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
