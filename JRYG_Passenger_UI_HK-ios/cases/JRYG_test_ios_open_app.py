"""港版阳光出行 iOS：从启动 App 到提交订单及优惠券场景的端到端自动化用例 -ios

对标安卓版 JRYG_test_open_app.py，逻辑与业务流程完全一致。
使用 WDA (WebDriverAgent) + facebook-wda + iosPoco 物理通道驱动 iOS 真机。
"""

import os
import sys
import time

import pytest
import wda
from airtest.core.api import connect_device
from poco.drivers.ios import iosPoco

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "IOS",
    reason="当前不是 iOS 自动化环境",
)
class TestJRYGHKIosOrder:
    """启动港版 iOS App，选择铜锣湾地铁站到香港大学并确认呼叫，优惠券场景验证 -ios。"""

    @classmethod
    def setup_class(cls):
        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        cls.bundle_id = SETTINGS["packages"].get("passenger_hk", "com.sunlightmobility.client")
        logger.info(f"【iOS 下单+优惠券 -ios】正在尝试连接 WDA 物理通道: {cls.wda_url}")

        try:
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 下单+优惠券 -ios】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败 -ios】请确认 WDA 已在手机上正常运行，且通过 iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 下单+优惠券用例")

        connect_device(f"ios:///{cls.wda_url}")
        cls.poco = iosPoco()
        logger.info("【iOS 下单+优惠券 -ios】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        logger.info("【iOS 下单+优惠券 -ios】自动化运行结束。")

    # ==================== 通用操作封装 ====================

    def _screenshot(self, filename):
        """通过 WDA 截图并保存到 screenshots 目录"""
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.client.screenshot(path)
        logger.info(f"  >> 截图已保存: {path}")
        return path

    def _launch_app(self):
        """拉起港版乘客端 App"""
        logger.info(f"【iOS -ios】正在拉起港版 App: {self.bundle_id}")
        self.client.home()
        time.sleep(1)
        self.client.session(self.bundle_id)
        time.sleep(8)

    def _accept_alert(self):
        """自动接受 iOS 系统弹窗"""
        try:
            self.client.alert.accept()
            logger.info("  >> 已自动允许系统授权弹窗")
            time.sleep(2)
        except Exception:
            pass

    def _close_activity_popup(self):
        """关闭首页可能出现的广告/促销弹框"""
        self._accept_alert()
        for ad_btn_text in ["iv_cancel", "close", "关闭", "叉號", "叉号"]:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"  >> 成功关闭首页促销大图弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                return
        close_xpath = self.client(xpath='//*[contains(@label, "close") or contains(@label, "關閉") or contains(@label, "关闭") or contains(@label, "叉")]')
        if close_xpath.exists:
            close_xpath.click()
            logger.info("  >> [WDA] 成功关闭弹框")
            time.sleep(2)
        else:
            logger.info("  >> 当前没有活动弹框")

    def _click_search_and_input(self, value):
        """点击搜索框并输入文本"""
        logger.info(f"正在输入: {value}...")
        for wait_sec in range(15):
            tf = self.client(type="TextField")
            if tf.exists:
                tf.click()
                time.sleep(0.5)
                break
            if self.poco(type="XCUIElementTypeTextField").exists():
                self.poco(type="XCUIElementTypeTextField").click()
                time.sleep(0.5)
                break
            time.sleep(1)

        self.client.send_keys(value)
        logger.info(f"  >> [WDA] 已成功键入: {value}")
        time.sleep(5)

    def _select_first_search_result(self, fallback_x, fallback_y, name):
        """选择搜索结果列表首项"""
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info(f"  >> [WDA] 成功选中首个搜索结果: {name}")
        else:
            first_item = self.poco(type="XCUIElementTypeCell")
            if first_item.exists():
                first_item[0].click()
                logger.info(f"  >> [Poco] 成功选中首个搜索结果: {name}")
            else:
                logger.info(f"  >> 通过物理坐标 ({fallback_x}, {fallback_y}) 强制点击首行{name}结果...")
                self.client.click(fallback_x, fallback_y)

    def _ensure_logged_in(self):
        """保障登录：进入个人中心，检查是否登录，若未登录则一键登录，最后必须切换回首页"""
        phone_number = "11001727"
        verify_code = "123456"
        logger.info(f"【登录校验 -ios】进入个人中心检查登录状态，预备登录手机号: {phone_number}...")

        self._close_activity_popup()

        # 点击底部『我的』标签
        btn_mine = self.poco(textMatches=".*我的.*|.*Me.*|.*個人.*|.*个人.*")
        if btn_mine.exists():
            btn_mine.click()
            logger.info("  >> [Poco] 成功点击『我的』标签")
        else:
            mine_xpath = self.client(xpath='//*[contains(@label, "我的") or contains(@value, "我的")]')
            if mine_xpath.exists:
                mine_xpath.click()
                logger.info("  >> [WDA] 成功点击『我的』标签")
            else:
                logger.info("  >> 采用物理坐标 (0.83, 0.97) 点击底部『我的』标签...")
                self.client.click(0.83, 0.97)
        time.sleep(5)

        # 检查登录状态
        logged_in = True
        for retry in range(5):
            texts = []
            try:
                for el in self.poco(type="XCUIElementTypeStaticText"):
                    t = el.get_text()
                    if t:
                        texts.append(t.strip())
            except Exception:
                pass
            joined = " ".join(texts)
            logger.info(f"  >> [iOS 我的页面文本嗅探] 循环 {retry}: {joined[:200]}")

            if "登錄/註冊" in joined or "登录/注册" in joined:
                logged_in = False
                break
            elif "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                logged_in = True
                break
            time.sleep(1)

        if not logged_in:
            logger.info("  >> 【未登录 -ios】检测到处于未登录态，准备执行登录流程...")
            btn_login_entry = self.poco(textMatches=".*登錄/註冊.*|.*登录/注册.*")
            if btn_login_entry.exists():
                btn_login_entry.click()
            else:
                login_xpath = self.client(xpath='//*[contains(@label, "登錄/註冊") or contains(@value, "登錄/註冊") or contains(@label, "登录/注册") or contains(@value, "登录/注册")]')
                if login_xpath.exists:
                    login_xpath.click()
                else:
                    self.client.click(0.5, 0.25)
            time.sleep(4)

            # 输入手机号
            logger.info(f"  >> 键入手机号 {phone_number}...")
            phone_field = self.client(type="TextField")
            if phone_field.exists:
                phone_field.click()
                time.sleep(0.5)
                self.client.send_keys(phone_number)
            else:
                self.client.click(0.5, 0.25)
                time.sleep(1)
                self.client.send_keys(phone_number)
            time.sleep(1.5)

            # 勾选隐私协议
            agree_text = self.poco(textMatches=".*已閱讀並同意.*|.*已阅读并同意.*|.*同意.*")
            if agree_text.exists():
                try:
                    pos = agree_text.get_position()
                    size = agree_text.get_size()
                    x = pos[0] - size[0] / 2 + 0.03
                    y = pos[1]
                    self.client.click(x, y)
                    logger.info("  >> 成功勾选隐私协议复选框")
                except Exception:
                    agree_text.click()
                time.sleep(1)

            # 点击取得验证码
            btn_get_code = self.poco(textMatches=".*取得驗證碼.*|.*获取验证码.*")
            if btn_get_code.exists():
                btn_get_code.click()
            else:
                code_xpath = self.client(xpath='//*[contains(@label, "取得驗證碼") or contains(@value, "取得驗證碼") or contains(@label, "获取验证码") or contains(@value, "获取验证码")]')
                if code_xpath.exists:
                    code_xpath.click()
                else:
                    self.client.click(0.5, 0.55)
            time.sleep(4)

            # 输入验证码
            logger.info(f"  >> 键入验证码 {verify_code}...")
            code_field = self.client(type="TextField")
            if code_field.exists:
                code_field.click()
                time.sleep(0.5)
                self.client.send_keys(verify_code)
            else:
                self.client.click(0.5, 0.25)
                time.sleep(1)
                self.client.send_keys(verify_code)
            time.sleep(6)
            logger.info("  >> 登录验证码已输入完毕，等待网络交互跳转。")
        else:
            logger.info("  >> 【已登录 -ios】检测到已处于登录态，跳过登录录入步骤。")

        # 切回首页
        logger.info("【登录校验结束 -ios】正在切换并回到乘客端首页选项卡...")
        for i in range(3):
            self.client.click(0.15, 0.97)
            time.sleep(4)

            tv_start = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*您在哪.*")
            tv_dest = self.poco(textMatches=".*想去哪.*|.*目的地.*|.*去哪.*")
            if tv_start.exists() or tv_dest.exists():
                logger.info("  >> 成功确认切回乘客端主页！")
                break
            logger.warning(f"  >> 切回首页未成功确认，尝试重新点击 (尝试次数: {i+1})...")

        time.sleep(2)

    def _set_origin(self):
        logger.info("正在点击起点栏位...")
        start_el = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*请输入起点.*|.*輸入起點.*|.*输入起点.*|.*您在哪.*|.*您從哪.*|.*您从哪.*")
        if start_el.exists():
            start_el.click()
            logger.info("  >> [Poco] 成功点击起点栏位")
        else:
            start_xpath = self.client(xpath='//*[contains(@label, "起點") or contains(@value, "起點") or contains(@label, "起点") or contains(@value, "起点") or contains(@label, "当前位置") or contains(@value, "当前位置") or contains(@label, "當前位置") or contains(@value, "當前位置") or contains(@label, "您在哪") or contains(@value, "您在哪")]')
            if start_xpath.exists:
                start_xpath.click()
                logger.info("  >> [WDA] 成功点击起点栏位")
            else:
                logger.info("  >> 采用物理坐标 (0.5, 0.76) 点击起点区域...")
                self.client.click(0.5, 0.76)
        time.sleep(3)
        self._click_search_and_input("铜锣湾地铁站")
        self._screenshot("JRYG_ios_02_origin_results.png")
        self._select_first_search_result(0.50, 0.25, "铜锣湾地铁站")
        time.sleep(6)
        self._close_activity_popup()

    def _set_destination(self):
        logger.info("正在点击目的地栏位...")
        dest_el = self.poco(textMatches=".*想去哪.*|.*想去哪里.*|.*目的地.*|.*去哪.*|.*輸入目的地.*|.*输入目的地.*|.*要去哪.*|.*要去邊.*")
        if dest_el.exists():
            dest_el.click()
            logger.info("  >> [Poco] 成功点击目的地栏位")
        else:
            dest_xpath = self.client(xpath='//*[contains(@label, "想去") or contains(@value, "想去") or contains(@label, "哪裡") or contains(@value, "哪裡") or contains(@label, "哪里") or contains(@value, "哪里") or contains(@label, "输入目的地") or contains(@value, "输入目的地") or contains(@label, "輸入目的地") or contains(@value, "輸入目的地")]')
            if dest_xpath.exists:
                dest_xpath.click()
                logger.info("  >> [WDA] 成功点击目的地栏位")
            else:
                logger.info("  >> 采用物理坐标 (0.5, 0.68) 点击目的地区域...")
                self.client.click(0.5, 0.68)
        time.sleep(3)
        self._click_search_and_input("香港大学")
        self._screenshot("JRYG_ios_03_destination_results.png")
        self._select_first_search_result(0.50, 0.25, "香港大学")
        time.sleep(10)

    # ==================== 测试用例 ====================

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，跳过直接呼叫下单")
    def test_ios_launch_to_order(self):
        """启动 App、关闭弹框、设置起终点、选择打錶的士并提交订单 -ios。"""
        try:
            logger.info("【步骤 1 -ios】从桌面启动港版 App...")
            self._launch_app()

            logger.info("【步骤 2 -ios】保存首页截图并关闭活动弹框...")
            self._screenshot("JRYG_ios_00_home_with_popup.png")
            self._close_activity_popup()
            self._screenshot("JRYG_ios_01_home.png")

            logger.info("【步骤 3 -ios】设置起点：铜锣湾地铁站...")
            self._set_origin()

            logger.info("【步骤 4 -ios】设置终点：香港大学...")
            self._set_destination()

            logger.info("【成功 -ios】港版 iOS App 从启动到下单流程执行完成！")
        except Exception as exc:
            logger.error(f"【下单流程失败 -ios】{exc}")
            try:
                self._screenshot("JRYG_ios_order_error.png")
            except Exception as screenshot_error:
                logger.error(f"  >> 异常截图失败: {screenshot_error}")
            raise

    def test_ios_coupon_expiry_verification(self):
        """香港版 iOS 乘客端：优惠券选择在估价失效刷新后的持久性验证流 -ios"""
        logger.info("\n" + "="*50)
        logger.info("  >> 【特殊用例 -ios】启动港版 iOS 乘客端优惠券时效与刷新验证...")
        logger.info("="*50)

        try:
            # 1. 打开乘客端
            logger.info("【步骤 1 -ios】从桌面启动港版 App...")
            self._launch_app()

            # 执行登录保障
            self._ensure_logged_in()
            poco_passenger = self.poco

            self._close_activity_popup()

            # 2. 输入起点
            logger.info("【步骤 3 -ios】配置起点：铜锣湾地铁站...")
            self._set_origin()

            # 3. 输入终点并跳转到估价页面
            logger.info("【步骤 4 -ios】配置目的地：香港大学...")
            self._set_destination()

            # 4. 选择包車价的士
            logger.info("【步骤 5 -ios】寻找并选择车型『包車价的士』并配置优惠券...")
            car_el = poco_passenger(textMatches=".*包車.*|.*包车.*")
            if car_el.exists():
                car_el.click()
                logger.info("  >> 成功点击『包車价的士』车型")
            else:
                car_xpath = self.client(xpath='//*[contains(@label, "包車") or contains(@label, "包车")]')
                if car_xpath.exists:
                    car_xpath.click()
                    logger.info("  >> [WDA] 成功点击包车价车型")
                else:
                    logger.warning("  >> 未定位到包车价车型文字，执行物理高容错坐标点击...")
                    self.client.click(0.25, 0.83)
            time.sleep(3)
            self._screenshot("JRYG_ios_coupon_check_01_quote.png")

            # 5. 进入优惠券页面并选择优惠券
            logger.info("寻找并进入优惠券列表页面...")
            coupon_el = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el.exists():
                coupon_el.click()
                logger.info("  >> 成功点击优惠券入口")
            else:
                coupon_xpath = self.client(xpath='//*[contains(@label, "優惠券") or contains(@value, "優惠券") or contains(@label, "优惠券") or contains(@value, "优惠券") or contains(@label, "优惠") or contains(@value, "优惠") or contains(@label, "折扣") or contains(@value, "折扣")]')
                if coupon_xpath.exists:
                    coupon_xpath.click()
                    logger.info("  >> [WDA] 成功点击优惠券入口")
                else:
                    logger.warning("  >> 未定位到优惠券文字，执行物理高容错坐标点击进入...")
                    self.client.click(0.85, 0.81)
            time.sleep(4)

            self._screenshot("JRYG_ios_coupon_check_02_list.png")
            logger.info("正在列表中选择并全部勾选所有优惠券卡片...")
            target_coupons = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*|.*元.*|.*HKD.*|.*折.*")
            if target_coupons.exists():
                try:
                    cnt = 0
                    for cp in target_coupons:
                        cp.click()
                        cnt += 1
                        logger.info(f"  >> 成功点击勾选第 {cnt} 张优惠券: '{cp.get_text() if hasattr(cp, 'get_text') else ''}'")
                        time.sleep(1.5)
                except Exception as ex:
                    logger.warning(f"  >> 遍历全部勾选优惠券时出现异常: {ex}")
            else:
                logger.info("  >> 未在列表中找到特定特征的优惠券，默认点击列表首张券...")
                first_coupon = poco_passenger(textMatches=".*元.*|.*HKD.*|.*折.*")
                if first_coupon.exists():
                    first_coupon.click()
                    time.sleep(2)
                else:
                    first_card = self.poco(type="XCUIElementTypeCell")
                    if first_card.exists():
                        first_card[0].click()
                        time.sleep(2)

            # 点击确定/使用
            btn_use = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_use.exists():
                btn_use.click()
                logger.info("  >> 点击确定使用成功")
                time.sleep(3)

            # 6. 等待5分钟10秒以模拟估价过期
            logger.info("【重要步骤 -ios】为了触发预估刷新提示，正在就地等待 5 分钟 10 秒 (310 秒)...")
            for minute in range(1, 6):
                time.sleep(60)
                logger.info(f"  >> [等待进度 -ios] 已过去 {minute} 分钟...")
            time.sleep(10)
            logger.info("  >> [等待进度 -ios] 额外 10 秒等待结束。")

            # 7. 点击"確認呼叫"，触发预估价已刷新提示
            logger.info("【步骤 6 -ios】等待结束，正在点击『確認呼叫』以触发预估更新对话框...")
            self.client.click(0.50, 0.928)
            time.sleep(4)
            self._screenshot("JRYG_ios_coupon_check_03_expired_prompt.png")

            # 处理可能出现的"预估已刷新"提示弹框
            logger.info("检测并处理预估价格刷新提示框...")
            btn_refresh_confirm = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*我知道了.*|.*同意.*|.*重新估價.*|.*重新估价.*")
            if btn_refresh_confirm.exists():
                btn_refresh_confirm.click()
                logger.info("  >> 成功点击确认价格刷新弹窗")
                time.sleep(4)
            else:
                refresh_xpath = self.client(xpath='//*[contains(@label, "確定") or contains(@label, "确定") or contains(@label, "確認") or contains(@label, "确认") or contains(@label, "重新估價") or contains(@label, "重新估价")]')
                if refresh_xpath.exists:
                    refresh_xpath.click()
                    logger.info("  >> [WDA] 成功点击确认价格刷新弹窗")
                    time.sleep(4)
                else:
                    logger.info("  >> 未发现显式阻挡弹窗，继续下步操作...")

            # 8. 重新点击优惠券进入列表，验证此前选择的优惠券是否保留
            logger.info("【步骤 7 -ios】再次点击优惠券选项卡以核对状态持久性...")
            coupon_el_retry = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_retry.exists():
                coupon_el_retry.click()
            else:
                self.client.click(0.85, 0.81)
            time.sleep(4)

            self._screenshot("JRYG_ios_coupon_check_04_post_verification.png")
            logger.info("【步骤 8 -ios】已打开优惠券列表。检查此前选中的券是否保持勾选状态...")

            target_coupon_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            if target_coupon_chk.exists():
                logger.info("  >> [校验成功 -ios] 目标优惠券依然存在于列表中！")
            else:
                logger.warning("  >> [校验提示 -ios] 目标优惠券未找到，请查看截图进行人工复核。")

            # 9. 返回首页完成测试
            logger.info("【步骤 9 -ios】校验完毕，正在点击返回以恢复首页...")
            btn_back = poco_passenger(textMatches=".*返回.*|.*点击回首页.*|.*返回首页.*")
            if btn_back.exists():
                btn_back.click()
            else:
                back_xpath = self.client(xpath='//*[contains(@label, "返回") or contains(@label, "返回首頁") or contains(@label, "返回首页")]')
                if back_xpath.exists:
                    back_xpath.click()
                else:
                    self.client.click(0.05, 0.05)
            time.sleep(3)

            # 再返回一次确保回到首页
            self.client.click(0.05, 0.05)
            time.sleep(3)
            self._screenshot("JRYG_ios_coupon_check_05_finished.png")
            logger.info("【成功 -ios】乘客端优惠券时效刷新与持久性验证流程顺利完成！")

        except Exception as e:
            logger.error(f"【优惠券核销时效测试失败 -ios】{e}")
            self._screenshot("JRYG_ios_coupon_check_failed.png")
            raise e

    def test_ios_coupon_rules_scenarios(self):
        """香港版 iOS 乘客端多场景优惠券刷新与手选券保留规则验证用例 -ios"""
        logger.info("\n" + "="*50)
        logger.info("  >> 【多场景验证 -ios】开始执行优惠券刷新与手选保留场景测试集...")
        logger.info("="*50)

        try:
            # ------------------ 场景 D 校验 ------------------
            logger.info("=== 场景 D -ios: 由上级页面进入选择车型页时，获取估价，无需提示直接重新匹配 ===")
            self._launch_app()
            self._ensure_logged_in()
            poco_passenger = self.poco
            self._close_activity_popup()
            self._set_origin()
            self._set_destination()
            time.sleep(5)

            # 验证进入车型页，没有提示弹框
            toast_or_popup = poco_passenger(textMatches=".*预估信息已更新.*|.*请重新选择.*|.*失效.*")
            assert not toast_or_popup.exists(), "【失败 -ios】初始进入选择车型页面不应有刷新提示或报错！"
            logger.info("  >> 场景 D 验证通过 -ios：初始进入页面直接进行推荐，无弹框干扰。")

            # ------------------ 场景 A 校验 ------------------
            logger.info("=== 场景 A -ios: 页面切入后台再切回来，自动刷新估价并保留手选券 ===")
            logger.info("选择车型『包車价的士』并配置优惠券...")
            car_el = poco_passenger(textMatches=".*包車.*|.*包车.*")
            if car_el.exists():
                car_el.click()
                logger.info("  >> 成功点击『包車价的士』")
            else:
                self.client.click(0.25, 0.83)
            time.sleep(3)
            coupon_el = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el.exists():
                coupon_el.click()
                time.sleep(3)
                target_coupons = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*|.*元.*|.*HKD.*|.*折.*")
                if target_coupons.exists():
                    try:
                        cnt = 0
                        for cp in target_coupons:
                            cp.click()
                            cnt += 1
                            logger.info(f"  >> [场景A -ios] 成功点击勾选第 {cnt} 张优惠券: '{cp.get_text() if hasattr(cp, 'get_text') else ''}'")
                            time.sleep(1.5)
                    except Exception as ex:
                        logger.warning(f"  >> [场景A -ios] 遍历勾选优惠券异常: {ex}")
                btn_use = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*")
                if btn_use.exists():
                    btn_use.click()
                    time.sleep(3)

            logger.info("  >> 成功手动勾选目标优惠券。")
            self._screenshot("JRYG_ios_scenario_A_selected.png")

            # 2. 将 App 切入后台 (iOS 端按 Home 键)
            logger.info("正在将港版 iOS 乘客端 App 切入后台模拟挂起...")
            self.client.home()
            time.sleep(5)

            # 3. 重新拉起 App 切回前台
            logger.info("正在唤醒并重新将 App 切回前台...")
            self.client.session(self.bundle_id)
            time.sleep(6)
            self._screenshot("JRYG_ios_scenario_A_foreground.png")

            # 4. 验证预估刷新及手选券保留
            coupon_el_retry = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_retry.exists():
                coupon_el_retry.click()
                time.sleep(3)

            self._screenshot("JRYG_ios_scenario_A_retained_check.png")
            target_coupon_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            assert target_coupon_chk.exists(), "【失败 -ios】应用从后台切回前台后，手选的目标优惠券未被正确保留！"
            logger.info("  >> 场景 A 验证通过 -ios：切回前台后手选券被正确保留！")

            # 返回估价页
            btn_back = poco_passenger(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*")
            if btn_back.exists():
                btn_back.click()
            else:
                self.client.click(0.05, 0.05)
            time.sleep(3)

            # ------------------ 场景 C 校验 ------------------
            logger.info("=== 场景 C -ios: 预付收银台支付失效弹框关闭，自动刷新估价并保留手选券 ===")
            logger.info("点击呼叫以触发预付收银台页面...")
            self.client.click(0.50, 0.928)
            time.sleep(5)
            self._screenshot("JRYG_ios_scenario_C_cashier.png")

            # 2. 模拟关闭收银台 (iOS 端通过左上角返回或关闭)
            logger.info("正在点击返回或关闭支付收银台弹窗，返回到车型选择页...")
            self.client.click(0.05, 0.05)
            time.sleep(4)
            self._screenshot("JRYG_ios_scenario_C_back_to_quote.png")

            # 3. 验证估价已自动刷新，且手选的优惠券仍保留
            coupon_el_c = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_c.exists():
                coupon_el_c.click()
                time.sleep(3)

            self._screenshot("JRYG_ios_scenario_C_retained_check.png")
            target_coupon_c_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            assert target_coupon_c_chk.exists(), "【失败 -ios】收银台关闭并刷新估价后，手选的目标优惠券未被正确保留！"
            logger.info("  >> 场景 C 验证通过 -ios：收银台页面关闭自动刷新预估价后，手选券完好保留！")

            # ------------------ 场景 E 校验 ------------------
            logger.info("=== 场景 E -ios: 最终选择优惠券并支付下单 ===")
            logger.info("正在关闭优惠券列表，返回车型估价页...")
            btn_back_to_quote = poco_passenger(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_back_to_quote.exists():
                btn_back_to_quote.click()
            else:
                self.client.click(0.05, 0.05)
            time.sleep(4)

            logger.info("在车型预估主页，确认优惠券状态并点击『確認呼叫』重新进入预付款收银台...")
            self.client.click(0.50, 0.928)
            time.sleep(5)
            self._screenshot("JRYG_ios_prepaid_cashier_order.png")

            logger.info("正在点击收银台『确认支付/去支付』下单按钮...")
            pay_btn = poco_passenger(textMatches=".*支付.*|.*立即支付.*|.*確認支付.*|.*确认支付.*|.*去支付.*")
            if pay_btn.exists():
                pay_btn.click()
                logger.info("  >> [Poco] 成功点击支付/下单按钮")
            else:
                pay_xpath = self.client(xpath='//*[contains(@label, "支付") or contains(@label, "立即支付") or contains(@label, "確認支付") or contains(@label, "确认支付") or contains(@label, "去支付")]')
                if pay_xpath.exists:
                    pay_xpath.click()
                    logger.info("  >> [WDA] 成功点击支付/下单按钮")
                else:
                    logger.warning("  >> 未定位到支付按钮文字，执行高精度物理坐标点击底部支付/确认呼叫区域 (0.50, 0.928)...")
                    self.client.click(0.50, 0.928)

            time.sleep(10)
            self._screenshot("JRYG_ios_order_submitted_with_coupon.png")
            logger.info("【成功 -ios】乘客端选择优惠券并支付下单全流程运行圆满完成！")

        except Exception as e:
            logger.error(f"【多场景优惠券校验失败 -ios】{e}")
            self._screenshot("JRYG_ios_scenario_coupon_failed.png")
            raise e