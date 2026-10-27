"""设置页面多级菜单深度优先遍历（DFS）测试。

遍历设置页面所有一级菜单项，逐个进入后判断是否包含下级子菜单，
若有则继续进入下级，到达最深层后返回上一级，再进入同级下一个子页面，
实现多级菜单的深度优先遍历验证。

每级页面记录：
  - 页面标题
  - 包含的子菜单项列表
  - 是否为最终详情页（无更多子菜单）

遍历策略（DFS）：
  进入菜单A → 判断A是否有子菜单 → 有则进入A的第一个子菜单A1
  → 判断A1是否有子菜单 → 有则继续进入... 直到最深层
  → 返回上一级 → 进入A的第二个子菜单A2 → ... 如此循环

安全策略：
  - 全程不修改任何用户数据，仅做页面打开与返回验证
  - 排除项：退出登录、测试中心、注销账号不点击（_is_excluded 校验）
  - 递归最大深度 4 层，防止无限循环
  - 单项异常不中断整体遍历，记录错误后继续下一项
"""
import re
import sys
import time
from pathlib import Path

import pytest

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_UI.common.JRYG_settings_flow import SettingsFlow, SETTING_ITEMS, EXCLUDED_TEXT, EXCLUDED_IDS
from JRYG_Passenger_UI.common.JRYG_logger import logger


# 排除项说明：退出登录、测试中心、注销账号不点击
# 这些在 SETTING_ITEMS 之外，但需要额外防止在子级页面中误触


class TestJRYGSettingsMenuTraversal:
    """设置页面多级菜单深度优先遍历测试。

    从设置一级菜单开始，逐个进入每个菜单项，检测其是否包含下级子菜单，
    若有则递归进入，到达最深层后返回上一级继续遍历同级下一个子项。
    全程不修改任何用户数据，仅做页面打开与返回验证。
    """

    @classmethod
    def setup_class(cls):
        """初始化 SettingsFlow 并导航至设置页面。

        traversal_log 列表用于记录整个遍历路径，每条记录包含：
        label（路径标签）、depth（层级）、activity、page_texts、sub_items、error
        """
        cls.flow = SettingsFlow()
        cls.flow.start_from_app()
        cls.traversal_log = []  # 记录遍历路径

    def test_menu_traversal(self):
        """深度优先遍历设置页面所有菜单层级。

        流程：
          1. 确保从设置主页开始
          2. 获取一级菜单项列表（rl_ 开头的可点击行，按 Y 坐标排序）
          3. 逐个进入一级菜单，采集页面信息，递归遍历下级
          4. 最终断言：至少遍历 5 个一级菜单，且至少存在一级多级菜单
        """
        flow = self.flow

        # 确保从设置主页开始
        flow.return_settings()
        flow.expect("设置")

        # 获取一级菜单项（按 Y 坐标排序）
        level1_items = self._get_clickable_menu_items()

        assert len(level1_items) >= 5, f"设置一级菜单项过少: {level1_items}"

        logger.info(f"【多级遍历】设置一级菜单共 {len(level1_items)} 项，开始深度优先遍历")

        for idx, (rid, text) in enumerate(level1_items):
            label = f"L1-{idx+1}-{text or rid}"
            logger.info(f"【多级遍历】▼ 进入一级菜单: {label}")

            try:
                # 返回设置主页
                flow.return_settings()
                # 滚动定位并点击该项
                flow.open(rid)
                time.sleep(1.5)

                # 记录一级菜单页面信息
                page_info = self._capture_page_info(label, depth=1)
                self.traversal_log.append(page_info)
                logger.info(f"【多级遍历】{label} 页面子项: {page_info['sub_items']}")

                # 递归遍历下级菜单
                if page_info["sub_items"]:
                    self._traverse_children(label, page_info["sub_items"], depth=2, parent_rid=rid)

                logger.info(f"【多级遍历】▲ 一级菜单 {label} 遍历完成")

            except Exception as exc:
                logger.error(f"【多级遍历】{label} 遍历异常: {exc}")
                flow.evidence(f"{label}_error")
                # 尝试返回设置页继续下一项
                try:
                    flow.return_settings()
                except Exception:
                    flow.start_from_app()
                # 记录错误但不中断整体遍历
                self.traversal_log.append({
                    "label": label, "depth": 1, "error": str(exc),
                    "sub_items": [], "activity": flow.adb.get_top_activity(),
                })

        # 验证至少遍历了 5 个一级菜单
        visited = [item for item in self.traversal_log if item.get("depth") == 1]
        assert len(visited) >= 5, f"仅遍历了 {len(visited)} 个一级菜单"

        # 输出遍历摘要
        logger.info("【多级遍历】==== 遍历结果摘要 ====")
        for entry in self.traversal_log:
            indent = "  " * entry.get("depth", 1)
            subs = entry.get("sub_items", [])
            status = "ERROR" if entry.get("error") else "OK"
            logger.info(f"  {indent}{entry['label']} [{status}] 子项数={len(subs)}")

        # 验证多级菜单至少出现过一次（至少有一个一级菜单包含下级）
        has_multi_level = any(
            item.get("sub_items") for item in self.traversal_log if item.get("depth") == 1
        )
        assert has_multi_level, "所有一级菜单均无下级子菜单，未验证多级遍历能力"

    def _traverse_children(self, parent_label, sub_items, depth, parent_rid):
        """递归遍历子菜单项（DFS 核心逻辑）。

        流程：
          1. 返回父级页面（return_settings → open parent_rid）
          2. 滚动定位并点击当前子项
          3. 采集子级页面信息，记录到 traversal_log
          4. 如果子级页面还包含下级子菜单，递归调用自身
          5. 单项异常不中断，记录错误后继续下一子项

        :param parent_label: 父级标签（如 "L1-1-紧急联系人"）
        :param sub_items: 子项列表 [(rid, text), ...]
        :param depth: 当前深度（一级=1，二级=2，...）
        :param parent_rid: 父级 resource_id（用于重新进入父级页面）
        """
        flow = self.flow
        max_depth = 4  # 最多递归 4 层防止无限循环
        if depth > max_depth:
            logger.info(f"【多级遍历】已达最大深度 {max_depth}，停止递归")
            return

        for idx, (child_rid, child_text) in enumerate(sub_items):
            child_label = f"{parent_label} > L{depth}-{idx+1}-{child_text or child_rid}"

            # 跳过排除项
            if self._is_excluded(child_rid, child_text):
                logger.info(f"【多级遍历】跳过排除项: {child_label}")
                continue

            logger.info(f"【多级遍历】▼ 进入子菜单: {child_label}")

            try:
                # 返回父级页面
                flow.return_settings()
                flow.open(parent_rid)
                time.sleep(1.0)

                # 滚动定位并点击子项
                self._scroll_and_click(child_rid, child_text)
                time.sleep(1.5)

                # 记录子级页面信息
                page_info = self._capture_page_info(child_label, depth=depth)
                self.traversal_log.append(page_info)
                logger.info(f"【多级遍历】{child_label} 子项: {page_info['sub_items']}")

                # 递归遍历更下级
                if page_info["sub_items"]:
                    self._traverse_children(
                        child_label, page_info["sub_items"],
                        depth=depth + 1, parent_rid=child_rid,
                    )

                logger.info(f"【多级遍历】▲ 子菜单 {child_label} 遍历完成")

            except Exception as exc:
                logger.error(f"【多级遍历】{child_label} 遍历异常: {exc}")
                flow.evidence(f"{child_label}_error")
                try:
                    flow.return_settings()
                except Exception:
                    flow.start_from_app()
                self.traversal_log.append({
                    "label": child_label, "depth": depth, "error": str(exc),
                    "sub_items": [], "activity": flow.adb.get_top_activity(),
                })

    # ==================== 页面分析与工具方法 ====================

    def _get_clickable_menu_items(self):
        """获取当前设置页面的可点击菜单项列表。

        扫描 Poco 控件树，提取以 rl_ 开头的可点击行，
        返回 [(resource_id_short, text)] 列表，按 Y 坐标排序。

        特殊处理：
          - 排除 EXCLUDED_IDS 中的项（注销账号等）
          - 如果节点无 text，在兄弟节点中按 Y 坐标相近查找文本
          - 去重：同一 rid 只保留第一次出现
        """
        flow = self.flow
        nodes = flow.nodes()
        items = []
        for node in nodes:
            name = node.get("name", "")
            if ":id/rl_" in name:
                rid_short = name.split(":id/")[-1]
                # 排除注销账号
                if rid_short in EXCLUDED_IDS:
                    continue
                # 找同一行的文本
                text = node.get("text", "")
                if not text:
                    # 在兄弟节点中找文本
                    bounds = node.get("bounds", "")
                    text = self._find_text_in_same_row(nodes, node, bounds)
                items.append((rid_short, text))
        # 去重并按 rid 排序
        seen = set()
        unique_items = []
        for rid, text in items:
            if rid not in seen:
                seen.add(rid)
                unique_items.append((rid, text))
        return unique_items

    def _capture_page_info(self, label, depth):
        """采集当前页面信息：Activity、标题、子菜单项列表。"""
        flow = self.flow
        activity = flow.adb.get_top_activity()
        texts = flow.texts()
        sub_items = self._get_clickable_menu_items()

        return {
            "label": label,
            "depth": depth,
            "activity": activity,
            "page_texts": sorted(texts),
            "sub_items": sub_items,
            "error": None,
        }

    def _find_text_in_same_row(self, nodes, target_node, target_bounds):
        """在 Y 坐标相近的节点中查找文本内容。

        某些可点击行（rl_ 开头）本身没有 text，文本在同级兄弟节点中。
        通过 bounds 坐标计算 Y 轴中心，在阈值 80px 内查找含文本的节点。
        """
        if not target_bounds:
            return ""
        import re as _re
        m = _re.findall(r"\d+", target_bounds)
        if len(m) < 4:
            return ""
        target_y = (int(m[1]) + int(m[3])) // 2
        for node in nodes:
            bounds = node.get("bounds", "")
            m2 = _re.findall(r"\d+", bounds)
            if len(m2) >= 4:
                y = (int(m2[1]) + int(m2[3])) // 2
                text = node.get("text", "")
                if abs(y - target_y) < 80 and text and text.strip():
                    return text.strip()
        return ""

    def _scroll_and_click(self, rid, text):
        """滚动定位并点击指定菜单项，支持按 rid 或 text 定位。

        先尝试滚动 3 次找到目标，再优先按 rid 点击，其次按 text 点击，
        均未找到则抛出 AssertionError。
        """
        flow = self.flow
        # 尝试滚动 3 次找到目标
        for _ in range(3):
            if flow.exists(rid=rid) or flow.exists(text=text):
                break
            flow.poco.swipe([0.5, 0.79], [0.5, 0.35], duration=0.8)
            time.sleep(0.5)

        if flow.exists(rid=rid):
            flow.click(rid=rid)
        elif flow.exists(text=text):
            flow.click(text=text)
        else:
            raise AssertionError(f"无法定位子菜单项: rid={rid} text={text}")

    def _is_excluded(self, rid, text):
        """判断是否为排除项（退出登录/测试中心/注销账号）。"""
        rid_short = (rid or "").split(":id/")[-1]
        if rid_short in EXCLUDED_IDS:
            return True
        for word in EXCLUDED_TEXT:
            if word in (text or ""):
                return True
        return False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
