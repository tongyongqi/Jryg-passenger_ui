"""读取地图Canvas上的实际路线；无法唯一识别时拒绝继续呼叫。"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

BASE_DIR = Path(__file__).resolve().parents[1]


def recognize_map(image_path, map_bottom):
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        raise RuntimeError("Canvas路线核验需要macOS Vision及Xcode命令行工具，未跳过路线核验")
    cache = BASE_DIR / "data/vision_module_cache"
    cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["xcrun", "swift", "-module-cache-path", str(cache), str(BASE_DIR / "tools/JRYG_vision_ocr.swift"),
         str(image_path), str(map_bottom)], capture_output=True, text=True, timeout=30, check=True)
    observations = json.loads(result.stdout)
    if not isinstance(observations, list):
        raise RuntimeError("地图OCR结果格式错误，未继续呼叫")
    return observations


def recognize_markers(image_path, map_bottom):
    import cv2
    from PIL import Image
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError("地图截图无法读取")
    screen_height, screen_width = image.shape[:2]
    mask = cv2.inRange(image[:int(screen_height * map_bottom)], (242, 242, 242), (255, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    observations = []
    with Image.open(image_path) as original:
        for index, contour in enumerate(contours):
            x, y, width, height = cv2.boundingRect(contour)
            if not (0.15 * screen_width < width < 0.6 * screen_width
                    and 0.015 * screen_height < height < 0.08 * screen_height
                    and cv2.contourArea(contour) > 0.45 * width * height):
                continue
            left, top = x + int(height * 0.25), y + int(height * 0.15)
            right, bottom = x + width - int(height * 0.9), y + int(height * 0.85)
            if right <= left:
                continue
            label = original.crop((left, top, right, bottom))
            label = label.resize((label.width * 2, label.height * 2))
            with tempfile.TemporaryDirectory(prefix="jryg-marker-") as directory:
                path = Path(directory) / f"marker-{index}.png"
                label.save(path)
                recognized = recognize_map(path, 1)
            for item in recognized:
                observations.append({**item, "x": (left + item["x"] * (right - left)) / screen_width,
                                     "y": (top + item["y"] * (bottom - top)) / screen_height,
                                     "width": item["width"] * (right - left) / screen_width,
                                     "height": item["height"] * (bottom - top) / screen_height})
    return observations


def map_route(observations, map_bottom):
    starts, ends = [], []
    for item in observations:
        confidence = item.get("confidence", 0)
        x, y = item.get("x", -1), item.get("y", -1)
        width, height = item.get("width", 0), item.get("height", 0)
        if (not isinstance(item.get("text"), str) or confidence < 0.5
                or not 0 <= x < 1 or width <= 0 or x + width > 1.01
                or not 0 <= y < map_bottom or height <= 0 or y + height > map_bottom):
            continue
        text = re.sub(r"\s+", "", item["text"]).translate(str.maketrans({"铁": "鐵", "学": "學", "（": "(", "）": ")"})).rstrip("，,。〉>＞")
        if re.fullmatch(r"北角(?:\(地鐵站\)|地鐵站)A1(?:出入口)?", text):
            starts.append("北角(地鐵站) A1出入口")
        if text == "香港大學":
            ends.append("香港大學")
    if len(starts) != 1 or len(ends) != 1:
        return None
    return starts[0], ends[0]


def current_map_route(client, map_bottom):
    expected_package = "com.sunlightmobility.client"
    if client.driver.current_package != expected_package:
        raise RuntimeError("截图前乘客App不在前台，未核验路线")
    import time
    for attempt in range(2):
        with tempfile.TemporaryDirectory(prefix="jryg-route-") as directory:
            path = Path(directory) / "route.png"
            client.screenshot(str(path))
            observations = recognize_markers(path, map_bottom)
        if client.driver.current_package != expected_package:
            raise RuntimeError("截图核验期间乘客App已离开前台，未继续呼叫")
        route = map_route(observations, map_bottom)
        if route is not None:
            return route
        if attempt == 0:
            time.sleep(1)
    return None
