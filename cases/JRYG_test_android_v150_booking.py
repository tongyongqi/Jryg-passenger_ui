"""V1.5.0 预约用车真机调试场景。

覆盖：
- 两轮分别选择预约时间、北角地铁站起点及香港大学终点
- 确认预约表单进入询价，确认呼叫进入呼叫中
- 第一轮主动取消订单，点击左上角返回首页
- 第二轮只读等待系统自然超时，等待期间不进行任何界面操作

出现问题（如取消后显示超时文案）时自动记录 Bug 证据，
不绕过检查也不阻塞后续用例，最终汇总所有 Bug。
会提交两笔预约订单；不调用司机端、不支付、不采集接口。
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps


class TestV150BookingDevice(V150DeviceSteps):
    __test__ = True
    DRIVER_REQUIRED = False

    def test_booking_entry_and_time_selection(self):
        """北角站→港大预约两轮：首轮取消返回首页，第二轮只读等待自然超时。

        出现 Bug 时不阻塞后续流程，最终汇总并断言所有 Bug。
        """
        for round_number in (1, 2):
            tag = f"v150_booking_round_{round_number}"
            page = self.v150_open_booking_entry(tag)
            assert page == "time_picker", f"时间选择器未出现：{page}"
            self.v150_select_booking_time(tag, minutes_ahead=35)
            self.v150_prepare_booking_route(tag)
            self.v150_submit_booking(tag)
            if round_number == 1:
                self.v150_cancel_booking_and_return_home(tag)
            else:
                result = self.v150_wait_booking_timeout(tag)
                assert result["timed_out"], "未观察到预约系统超时取消"

        # 汇总所有 Bug，有 Bug 时测试失败但已在之前步骤中继续执行
        bugs = self.v150_bug_summary()
        if bugs:
            summaries = "\n".join(f"  - {b['summary']} → {b['path']}" for b in bugs)
            raise AssertionError(f"本轮预约调试发现 {len(bugs)} 个 Bug：\n{summaries}")


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
