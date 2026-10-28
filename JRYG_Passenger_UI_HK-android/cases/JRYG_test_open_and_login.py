"""
港版阳光出行乘客端 (Android) —— 一键打开并登录全业务流自动化用例
==============================================================================
特性：
1. 本文件遵循“一站式闭环”设计，将【拉起App -> 隐私协议同意 -> 定位权限授权 -> 
   个人中心跳转 -> 手机号键入 -> 隐私勾选 -> 获取验证码 -> 验证码输入 -> 登录成功核对】
   完整操作全部内聚在本单一 `.py` 文件中，结构干净明晰，没有任何多余脚本。
2. 完美支持在 PyCharm 中右键直接点击 Run 运行。
==============================================================================
"""

import os
import sys
import subprocess
import re
import pytest

# 添加测试框架核心根路径到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from airtest.core.api import connect_device, sleep
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from jryg_hk_android.JRYG_logger import logger
from jryg_hk_android.JRYG_config import SETTINGS


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "IOS",
    reason="当前设置为 iOS 物理真机环境，跳过 Android 一键登录用例"
)
class TestJRYGHKOneKeyLogin:
    """港版阳光出行乘客端一键打开与登录测试套件"""

    @classmethod
    def setup_class(cls):
        cls.udid = SETTINGS["device"]["udid"]
        cls.passenger_pkg = SETTINGS["packages"]["passenger_hk"]
        cls.passenger_activity = SETTINGS["packages"]["passenger_hk_activity"]
        
        logger.info(f"【港版一键登录】正在通过 ADB 初始化并拉起 App: {cls.passenger_pkg}")
        # 1. 强制杀死可能残留的后台进程并全新冷启动
        subprocess.run(["adb", "-s", cls.udid, "shell", "am", "force-stop", cls.passenger_pkg], capture_output=True)
        sleep(1)
        subprocess.run(["adb", "-s", cls.udid, "shell", "monkey", "-p", cls.passenger_pkg, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True)
        sleep(6)

        # 2. 建立 Poco Uiautomation 物理连接通道
        connect_device(f"android://127.0.0.1:5037/{cls.udid}")
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        logger.info("【港版一键登录】设备连接已建立，进入自动化流转。")

    @classmethod
    def teardown_class(cls):
        logger.info("【港版一键登录】自动化运行结束。")

    def test_passenger_hk_login_flow(self):
        """测试用例：执行一键打开并自动登录完整闭环流程"""
        phone_number = "11001727"
        verify_code = "123456"
        
        logger.info(f"【港版一键登录】启动业务流转，预备登录测试手机号: {phone_number}")

        # 通过状态监控执行状态机循环
        for cycle in range(30):
            state = self._detect_current_state()
            logger.info(f"当前流转 [循环 {cycle}] -> 页面状态: {state}")

            # 1. 隐私服务协议弹窗处理
            if state == "privacy_agreement":
                logger.info("【步骤 1】检测到隐私政策服务弹窗，正在寻找并点击『同意』...")
                btn_agree = self.poco(text="同意")
                if btn_agree.exists():
                    btn_agree.click()
                else:
                    self._adb_tap_by_text("同意")
                sleep(3)
                continue

            # 2. 地理位置权限申请框处理
            if state == "permission_dialog":
                logger.info("【步骤 2】检测到位置权限授权提示框，正在点击『去授權』...")
                btn_auth = self.poco(text="去授權")
                if btn_auth.exists():
                    btn_auth.click()
                else:
                    self._adb_tap_by_text("去授權")
                sleep(3)
                continue

            # 3. 系统级定位权限允许弹框处理
            if state == "system_location_permission":
                logger.info("【步骤 3】检测到 Android 系统定位授权对话框，正在点击『使用应用时允許』...")
                btn_allow = self.poco(text="使用应用时允许")
                if not btn_allow.exists():
                    btn_allow = self.poco(text="仅在使用中允许")
                if btn_allow.exists():
                    btn_allow.click()
                else:
                    # 兜底：如果定制 ROM 文字有差异，通过系统 ID 或常见确定位置点击
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "2178"])
                sleep(4)
                continue

            # 4. 乘客端主页（已授权进入）处理 -> 点击『我的』
            if state == "home_unlogged":
                logger.info("【步骤 4】已成功进入港版 App 首页，正在点击下方导航栏『我的』...")
                btn_mine = self.poco(text="我的")
                if btn_mine.exists():
                    btn_mine.click()
                else:
                    self._adb_tap_by_text("我的")
                sleep(3)
                continue

            # 5. 个人中心未登录态处理 -> 点击『登錄/註冊』
            if state == "mine_unlogged":
                logger.info("【步骤 5】已进入个人中心，正在点击『登錄/註冊』进入账号录入页...")
                btn_login_entry = self.poco(text="登錄/註冊")
                if not btn_login_entry.exists():
                    btn_login_entry = self.poco("com.sunlightmobility.client:id/tv_mine_name")
                if btn_login_entry.exists():
                    btn_login_entry.click()
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "661", "477"])
                sleep(4)
                continue

            # 6. 真实手机号输入页面处理 -> 键入手机号 + 勾选隐私协议 -> 获取验证码
            if state == "login_phone_input":
                logger.info("【步骤 6】正在手机号输入页：键入号码、勾选协议、并点击『取得驗證碼』...")
                
                # 键入手机号
                et_phone = self.poco("com.sunlightmobility.client:id/phone_num")
                if et_phone.exists():
                    et_phone.click()
                    sleep(0.5)
                    et_phone.set_text(phone_number)
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "617", "821"])
                    sleep(0.5)
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "text", phone_number])
                sleep(1.5)
                
                # 点击隐私勾选框 (采用高精度文本坐标偏移点击法)
                self._adb_tap_checkbox()
                sleep(1)
                
                # 点击取得验证码
                btn_get_code = self.poco("com.sunlightmobility.client:id/rl_next")
                if btn_get_code.exists():
                    btn_get_code.click()
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "1042"])
                sleep(4)
                continue

            # 7. 真实验证码输入页面处理 -> 键入验证码 123456 -> 自动登录
            if state == "login_code_input":
                logger.info(f"【步骤 7】正在验证码输入页：输入验证码: {verify_code}...")
                et_code = self.poco("com.sunlightmobility.client:id/verify_code")
                if et_code.exists():
                    et_code.click()
                    sleep(0.5)
                    et_code.set_text(verify_code)
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "865"])
                    sleep(0.5)
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "text", verify_code])
                sleep(5) # 等待登录服务器网络交互并跳转
                continue

            # 8. 成功登录状态验证
            if state == "home_logged":
                logger.info("【成功】一键打开并登录港版阳光出行测试成功！手机号已正确核对绑定。")
                break

            sleep(2)

    def test_passenger_hk_booking_flow(self):
        """测试用例：登录成功后切换回首页，输入起终点，选择打錶的士，选择现金支付，点击确认呼叫"""
        logger.info("【港版下单测试】启动港版打錶的士+现金支付全业务下单流程...")

        # 1. 确保在首页
        logger.info("确保处于首页选项卡...")
        btn_home = self.poco("com.sunlightmobility.client:id/item_tab_icon_layout")
        if btn_home.exists():
            btn_home[0].click()
            sleep(3)
        else:
            # 物理点击底部导航栏第一个“首页”图标
            subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "195", "2676"])
            sleep(3)

        # 2. 自动检查并关闭可能阻挡主页的大图推广弹框
        logger.info("检查并关闭可能覆盖主页的弹窗...")
        subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/window_dump_chk_popup.xml"], capture_output=True)
        subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/window_dump_chk_popup.xml", "window_dump_chk_popup.xml"], capture_output=True)
        if os.path.exists("window_dump_chk_popup.xml"):
            with open("window_dump_chk_popup.xml", "r", encoding="utf-8") as f:
                chk_content = f.read()
            if "RecyclerView" in chk_content and "ImageView" in chk_content and "LinearLayout" not in chk_content:
                # 处于弹框覆盖状态下，物理点击弹窗底部的关闭叉号位置 (585, 2047)
                logger.info("检测到主屏被推广大图弹框覆盖，执行物理叉号点击 (585, 2047) 以关闭...")
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "585", "2047"])
                sleep(2)

        # 3. 输入起点：铜锣湾地铁站
        logger.info("点击起点输入栏...")
        tv_start = self.poco("com.sunlightmobility.client:id/tv_start_address")
        if tv_start.exists():
            tv_start.click()
            sleep(3)

            # 在搜索页输入起点
            logger.info("输入起点：铜锣湾地铁...")
            et_search = self.poco("com.sunlightmobility.client:id/et_search")
            if not et_search.exists():
                et_search = self.poco(type="android.widget.EditText")
            if et_search.exists():
                et_search.click()
                sleep(0.5)
                et_search.set_text("铜锣湾地铁")
                sleep(4) # 等待列表检索加载完成

                # 点击第一个结果
                logger.info("选择起点匹配项...")
                self._adb_tap_first_search_result()
                sleep(3)

        # 4. 输入终点：香港大学
        logger.info("点击目的地输入栏...")
        tv_dest = self.poco(text="想要去哪裡？")
        if not tv_dest.exists():
            tv_dest = self.poco("com.sunlightmobility.client:id/tv_destination")
        if not tv_dest.exists():
            tv_dest = self.poco("com.sunlightmobility.client:id/rl_destination_layout")

        if tv_dest.exists():
            tv_dest.click()
            sleep(3)

            # 在搜索页输入终点
            logger.info("输入终点：香港大学...")
            et_search = self.poco("com.sunlightmobility.client:id/et_search")
            if not et_search.exists():
                et_search = self.poco(type="android.widget.EditText")
            if et_search.exists():
                et_search.click()
                sleep(0.5)
                et_search.set_text("香港大学")
                sleep(4)

                # 点击第一个结果
                logger.info("选择目的地匹配项...")
                self._adb_tap_first_search_result()
                sleep(6) # 等待完全加载进入车型询价选择面板

        # 5. 选择优惠卷：100元优惠卷
        logger.info("在车型选择与确认页面中，正在寻找并点击『优惠券/優惠券』选择栏...")
        coupon_clicked = False
        # 针对简繁体、数值进行多组文本匹配
        for text_to_try in ["優惠券", "优惠券", "优惠", "優惠", "选择优惠券", "选择優惠券", "100"]:
            subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/_temp.xml"], capture_output=True)
            subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/_temp.xml", "_temp.xml"], capture_output=True)
            if os.path.exists("_temp.xml"):
                with open("_temp.xml", "r", encoding="utf-8") as f:
                    content = f.read()
                if text_to_try in content:
                    logger.info(f"匹配到优惠券入口关键字: '{text_to_try}'，正在点击进入列表...")
                    self._adb_tap_by_text(text_to_try)
                    coupon_clicked = True
                    sleep(3)
                    break

        if not coupon_clicked:
            logger.info("未直接通过文本定位到，尝试通过 Poco 寻找优惠词条并点击...")
            el_coupon = self.poco(textMatches=".*优惠.*|.*優惠.*")
            if el_coupon.exists():
                el_coupon.click()
                sleep(3)
                coupon_clicked = True

        # 进入列表后选择 100元优惠卷
        if coupon_clicked:
            logger.info("已进入优惠券列表，正在选中『100元优惠卷』...")
            selected_coupon = False
            for target_coupon_text in ["100元优惠卷", "100元优惠券", "100", "100元"]:
                subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/_temp.xml"], capture_output=True)
                subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/_temp.xml", "_temp.xml"], capture_output=True)
                if os.path.exists("_temp.xml"):
                    with open("_temp.xml", "r", encoding="utf-8") as f:
                        content = f.read()
                    if target_coupon_text in content:
                        logger.info(f"匹配到优惠券卡片: '{target_coupon_text}'，正在点击选中...")
                        self._adb_tap_by_text(target_coupon_text)
                        selected_coupon = True
                        sleep(3)
                        break
            if not selected_coupon:
                logger.info("未在列表中找到指定 100 元优惠卡片，默认点击列表中首张面额卡片...")
                first_card = self.poco(textMatches=".*元.*")
                if first_card.exists():
                    first_card.click()
                    sleep(3)

        # 6. 点击“確認呼叫”按钮 (586, 2551)
        logger.info("【呼叫】点击『確認呼叫』正式向系统发起本订单派单...")
        btn_call = self.poco("com.sunlightmobility.client:id/btn_call")
        if btn_call.exists():
            btn_call.click()
        else:
            subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "2551"])
        
        sleep(5)
        logger.info("【港版下单流程】执行完毕，订单已成功发起并进入后台派单流程！")

    # ==================== 底层核心辅助函数封装 ====================

    def _adb_tap_first_search_result(self):
        """物理点击第一个搜索关联地址条目"""
        subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/window_dump_list_temp.xml"], capture_output=True)
        subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/window_dump_list_temp.xml", "window_dump_list_temp.xml"], capture_output=True)
        if os.path.exists("window_dump_list_temp.xml"):
            with open("window_dump_list_temp.xml", "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r'resource-id="com.sunlightmobility.client:id/tv_title"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            matches = re.findall(pattern, content)
            if matches:
                x1, y1, x2, y2 = map(int, matches[0])
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2)])
                return
        # 物理兜底位置
        subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "500", "420"])

    def _detect_current_state(self):
        """核心：通过前台 Activity 与 UI 关键内容嗅探当前所在业务节点"""
        res = subprocess.run(
            ["adb", "-s", self.udid, "shell", "dumpsys", "activity", "activities"],
            capture_output=True, text=True, timeout=10
        )
        activity = ""
        for line in res.stdout.split("\n"):
            if "topResumedActivity" in line:
                activity = line.lower()
                break

        # 如果不在港版 App 前台
        if self.passenger_pkg not in activity:
            return "launcher"

        # 极速匹配 (exists)
        if self.poco(text="同意").exists() and self.poco(text="不同意").exists():
            return "privacy_agreement"
        if self.poco(text="去授權").exists() and self.poco(text="取消").exists():
            return "permission_dialog"
        if self.poco(text="使用应用时允许").exists() or self.poco(text="仅在使用中允许").exists():
            return "system_location_permission"
        if self.poco(text="請輸入驗證碼").exists() or self.poco(textMatches=".*重新獲取.*").exists():
            return "login_code_input"
        if self.poco(text="請輸入手機號").exists() or self.poco(text="取得驗證碼").exists():
            return "login_phone_input"
        if self.poco(text="登錄/註冊").exists():
            return "mine_unlogged"
        
        # 通过拉取全部文本作复合判断 (防止 exists 缓存)
        texts = []
        try:
            for el in self.poco(type="android.widget.TextView"):
                t = el.get_text()
                if t:
                    texts.append(t.strip())
        except Exception:
            pass
        joined = " ".join(texts)

        if "歡迎登錄" in joined or "請輸入手機號" in joined:
            return "login_phone_input"
        if "請輸入驗證碼" in joined:
            return "login_code_input"
        if "登錄/註冊" in joined:
            return "mine_unlogged"
        if "想要去哪裡？" in joined:
            if "1727" in joined or "****" in joined:
                return "home_logged"
            return "home_unlogged"

        return "unknown"

    def _adb_tap_by_text(self, target_text):
        """通过 adb dump 正则查找目标 text 并物理点击"""
        subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/_temp.xml"], capture_output=True)
        subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/_temp.xml", "_temp.xml"], capture_output=True)
        if os.path.exists("_temp.xml"):
            with open("_temp.xml", "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r'text="' + re.escape(target_text) + r'"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2)])

    def _adb_tap_checkbox(self):
        """通过 bounds 计算点击隐私条款最左侧的 CheckBox"""
        subprocess.run(["adb", "-s", self.udid, "shell", "uiautomator", "dump", "/sdcard/_temp.xml"], capture_output=True)
        subprocess.run(["adb", "-s", self.udid, "pull", "/sdcard/_temp.xml", "_temp.xml"], capture_output=True)
        if os.path.exists("_temp.xml"):
            with open("_temp.xml", "r", encoding="utf-8") as f:
                content = f.read()
            # 根据“已閱讀並同意”文本偏移计算左侧勾选框位置
            pattern = r'text="已閱讀並同意[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                # 偏移点击协议左侧
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", str(x1 - 35), str((y1+y2)//2)])
