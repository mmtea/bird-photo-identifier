i额mport streamlit as st
import os
import io
import re
import json
import base64
import hashlib
import zipfile
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

try:
    from PIL import Image, ExifTags
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from datetime import datetime

from openai import OpenAI

# RAW 格式后缀集合（索尼 ARW、佳能 CR2/CR3、尼康 NEF 等）
RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw"}


def is_raw_file(filename: str) -> bool:
    """判断文件是否为 RAW 格式"""
    return Path(filename).suffix.lower() in RAW_EXTENSIONS


def extract_jpeg_from_raw(raw_bytes: bytes) -> bytes:
    """从 RAW 文件中提取内嵌的 JPEG 预览图（纯 Python，无需额外依赖）。

    大多数相机 RAW 格式（ARW/CR2/NEF/DNG 等）都基于 TIFF 结构，
    内部嵌有一张全尺寸或接近全尺寸的 JPEG 预览图。
    本函数通过扫描 JPEG SOI (FFD8) 标记来定位并提取最大的那张 JPEG。
    """
    jpeg_candidates = []
    search_start = 0

    while True:
        soi_pos = raw_bytes.find(b'\xff\xd8', search_start)
        if soi_pos == -1:
            break

        # 从 SOI 开始找对应的 EOI (FFD9)
        eoi_pos = raw_bytes.find(b'\xff\xd9', soi_pos + 2)
        if eoi_pos == -1:
            break

        jpeg_data = raw_bytes[soi_pos:eoi_pos + 2]
        # 只保留大于 50KB 的 JPEG（过滤缩略图）
        if len(jpeg_data) > 50 * 1024:
            jpeg_candidates.append(jpeg_data)

        search_start = eoi_pos + 2

    if jpeg_candidates:
        # 返回最大的那张（通常是全尺寸预览）
        return max(jpeg_candidates, key=len)

    return b""

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="影禽 BirdEye",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Apple 风格样式
# ============================================================
st.markdown("""
<style>
    /* 全局字体和背景 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display',
                     'SF Pro Text', 'Helvetica Neue', 'Inter', Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
    }
    .stApp {
        background: linear-gradient(180deg, #f5f5f7 0%, #ffffff 100%);
    }

    /* 隐藏 Streamlit 默认元素 */
    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none; }

    /* 减少顶部空白 */
    .block-container {
        padding-top: 1rem !important;
    }

    /* 主标题区域 - 紧凑竖向 */
    .hero-section {
        text-align: center;
        padding: 1.5rem 1rem;
        position: relative;
        overflow: hidden;
        border-radius: 16px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        margin-bottom: 0;
    }
    .hero-icon {
        font-size: 40px;
        margin-bottom: 6px;
        display: block;
        filter: drop-shadow(0 4px 12px rgba(0,0,0,0.2));
    }
    .hero-title {
        font-size: 28px;
        font-weight: 700;
        letter-spacing: -0.03em;
        color: #ffffff;
        margin: 0;
        line-height: 1.1;
    }
    .hero-subtitle {
        font-size: 11px;
        font-weight: 400;
        color: rgba(255,255,255,0.75);
        margin-top: 4px;
        letter-spacing: -0.01em;
    }
    .hero-features {
        margin-top: 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .hero-feature-item {
        font-size: 11px;
        color: rgba(255,255,255,0.9);
        padding: 5px 8px;
        background: rgba(255,255,255,0.15);
        backdrop-filter: blur(10px);
        border-radius: 8px;
        letter-spacing: -0.01em;
        text-align: left;
    }

    /* 登录卡片 */
    .login-card {
        text-align: center;
        padding: 16px 0 8px;
    }
    .login-title {
        font-size: 20px;
        font-weight: 700;
        color: #1d1d1f;
        margin: 0 0 4px;
    }
    .login-subtitle {
        font-size: 14px;
        color: #86868b;
        margin: 0;
    }

    /* 识别进度 - 仪式感 */
    .progress-banner {
        text-align: center;
        padding: 12px 16px;
        margin: 8px 0;
        border-radius: 12px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.02em;
        animation: pulse-glow 2s ease-in-out infinite;
    }
    @keyframes pulse-glow {
        0%, 100% { box-shadow: 0 0 8px rgba(102,126,234,0.3); }
        50% { box-shadow: 0 0 20px rgba(102,126,234,0.6); }
    }
    .progress-done {
        text-align: center;
        padding: 10px 16px;
        margin: 8px 0;
        border-radius: 12px;
        background: linear-gradient(135deg, #34c759 0%, #30d158 100%);
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
    }
    .results-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(102,126,234,0.3), transparent);
        margin: 16px 0;
    }

    /* 排行榜区域 - 与 hero 同色系 */
    .leaderboard-header {
        text-align: center;
        padding: 12px;
        border-radius: 16px 16px 0 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        margin-bottom: 0;
    }
    .leaderboard-header-title {
        font-size: 16px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
    }
    .leaderboard-body {
        background: rgba(255,255,255,0.85);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(0,0,0,0.06);
        border-top: none;
        border-radius: 0 0 16px 16px;
        padding: 8px;
    }
    .leaderboard-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border-radius: 10px;
        margin-bottom: 4px;
        transition: background 0.2s;
    }
    .leaderboard-item:hover {
        background: rgba(0,0,0,0.03);
    }
    .leaderboard-item-current {
        background: rgba(102,126,234,0.08);
        border: 1.5px solid rgba(102,126,234,0.25);
    }
    .leaderboard-rank {
        font-size: 16px;
        width: 24px;
        text-align: center;
        flex-shrink: 0;
    }
    .leaderboard-rank-num {
        font-size: 12px;
        color: #86868b;
        font-weight: 600;
        width: 24px;
        text-align: center;
        flex-shrink: 0;
    }
    .leaderboard-name {
        font-size: 13px;
        font-weight: 600;
        color: #1d1d1f;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin: 0;
    }
    .leaderboard-name-current {
        color: #667eea;
    }
    .leaderboard-stats {
        font-size: 10px;
        color: #86868b;
        margin: 1px 0 0;
    }

    /* 毛玻璃卡片 */
    .glass-card {
        background: rgba(255, 255, 255, 0.72);
        backdrop-filter: blur(20px) saturate(180%);
        -webkit-backdrop-filter: blur(20px) saturate(180%);
        border: 1px solid rgba(0, 0, 0, 0.08);
        border-radius: 20px;
        padding: 24px;
        margin-bottom: 20px;
        transition: all 0.3s cubic-bezier(0.25, 0.1, 0.25, 1);
    }
    .glass-card:hover {
        box-shadow: 0 8px 40px rgba(0, 0, 0, 0.08);
        transform: translateY(-2px);
    }

    /* 统计卡片 */
    .stat-card {
        background: rgba(255, 255, 255, 0.8);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 12px;
        padding: 12px;
        text-align: center;
    }
    .stat-value {
        font-size: 26px;
        font-weight: 700;
        color: #1d1d1f;
        letter-spacing: -0.02em;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 13px;
        font-weight: 500;
        color: #86868b;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.02em;
    }

    /* 鸟类结果卡片 */
    .bird-result-card {
        background: rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(20px) saturate(180%);
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 20px;
        padding: 0;
        margin-bottom: 24px;
        overflow: hidden;
        transition: all 0.3s cubic-bezier(0.25, 0.1, 0.25, 1);
    }
    .bird-result-card:hover {
        box-shadow: 0 12px 48px rgba(0, 0, 0, 0.1);
        transform: translateY(-3px);
    }

    /* 评分徽章 */
    .score-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 16px;
        border-radius: 100px;
        font-weight: 600;
        font-size: 15px;
        letter-spacing: -0.01em;
    }
    .score-excellent {
        background: linear-gradient(135deg, #34c759, #30d158);
        color: white;
    }
    .score-good {
        background: linear-gradient(135deg, #007aff, #0a84ff);
        color: white;
    }
    .score-fair {
        background: linear-gradient(135deg, #ff9500, #ff9f0a);
        color: white;
    }
    .score-poor {
        background: linear-gradient(135deg, #ff3b30, #ff453a);
        color: white;
    }

    /* 分类标签 */
    .taxonomy-pill {
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 100px;
        font-size: 12px;
        font-weight: 500;
        margin-right: 6px;
        letter-spacing: -0.01em;
    }
    .order-pill {
        background: rgba(0, 122, 255, 0.1);
        color: #007aff;
    }
    .family-pill {
        background: rgba(52, 199, 89, 0.1);
        color: #34c759;
    }

    /* 置信度指示器 */
    .confidence-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
    }
    .confidence-high { background: #34c759; }
    .confidence-medium { background: #ff9500; }
    .confidence-low { background: #ff3b30; }

    /* 信息行 */
    .info-row {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 14px;
        color: #6e6e73;
        margin: 4px 0;
        letter-spacing: -0.01em;
    }
    .info-row .label {
        color: #86868b;
        font-weight: 500;
    }
    .info-row .value {
        color: #1d1d1f;
    }

    /* 鸟名标题 */
    .bird-name {
        font-size: 18px;
        font-weight: 700;
        color: #1d1d1f;
        letter-spacing: -0.02em;
        margin: 0 0 2px 0;
        line-height: 1.2;
    }
    .bird-name-en {
        font-size: 13px;
        font-weight: 400;
        color: #86868b;
        margin: 0 0 8px 0;
        letter-spacing: -0.01em;
    }

    /* 评分详情 */
    .score-detail {
        font-size: 14px;
        color: #6e6e73;
        font-style: italic;
        margin-top: 8px;
        padding: 8px 12px;
        background: rgba(0, 0, 0, 0.03);
        border-radius: 10px;
    }

    /* 上传区域 */
    .stFileUploader > div {
        border-radius: 16px !important;
        border: 2px dashed rgba(0, 0, 0, 0.1) !important;
        background: rgba(255, 255, 255, 0.6) !important;
    }
    .stFileUploader > div:hover {
        border-color: #007aff !important;
        background: rgba(0, 122, 255, 0.03) !important;
    }

    /* 按钮样式 */
    .stButton > button {
        border-radius: 14px !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em !important;
        padding: 12px 24px !important;
        transition: all 0.2s ease !important;
        border: none !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #007aff, #0a84ff) !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        box-shadow: 0 4px 16px rgba(0, 122, 255, 0.4) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"] {
        background: rgba(0, 0, 0, 0.05) !important;
        color: #1d1d1f !important;
    }

    /* 下载按钮 */
    .stDownloadButton > button {
        border-radius: 14px !important;
        font-weight: 600 !important;
        background: linear-gradient(135deg, #34c759, #30d158) !important;
        color: white !important;
        border: none !important;
        padding: 12px 24px !important;
    }
    .stDownloadButton > button:hover {
        box-shadow: 0 4px 16px rgba(52, 199, 89, 0.4) !important;
    }

    /* 输入框 */
    .stTextInput > div > div {
        border-radius: 12px !important;
        border: 1px solid rgba(0, 0, 0, 0.1) !important;
    }

    /* 进度条 */
    .stProgress > div > div {
        border-radius: 100px !important;
        background: linear-gradient(90deg, #007aff, #5ac8fa) !important;
    }

    /* Expander */
    .streamlit-expanderHeader {
        border-radius: 12px !important;
        font-weight: 600 !important;
    }

    /* 分割线 */
    hr {
        border: none;
        height: 1px;
        background: rgba(0, 0, 0, 0.06);
        margin: 10px 0;
    }

    /* 图片圆角 */
    .stImage img {
        border-radius: 14px;
    }

    /* 页脚 */
    .app-footer {
        text-align: center;
        padding: 24px 0 12px;
        color: #86868b;
        font-size: 13px;
        letter-spacing: -0.01em;
        border-top: 1px solid rgba(0,0,0,0.06);
        margin-top: 24px;
    }
    .app-footer a {
        color: #007aff;
        text-decoration: none;
    }

    /* Section 标题 */
    .section-title {
        font-size: 22px;
        font-weight: 700;
        color: #1d1d1f;
        letter-spacing: -0.02em;
        margin: 12px 0 8px;
    }
    .section-subtitle {
        font-size: 13px;
        color: #86868b;
        margin-top: -4px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 工具函数
# ============================================================
def image_bytes_to_pil(image_bytes: bytes, filename: str = "") -> "Image.Image | None":
    """将图片字节转为 PIL Image，支持 RAW 格式（自动提取内嵌 JPEG）"""
    if not HAS_PIL:
        return None

    # 如果是 RAW 格式，先提取内嵌 JPEG
    actual_bytes = image_bytes
    if is_raw_file(filename):
        jpeg_data = extract_jpeg_from_raw(image_bytes)
        if jpeg_data:
            actual_bytes = jpeg_data
        else:
            return None

    try:
        img = Image.open(io.BytesIO(actual_bytes))
        return img
    except Exception:
        return None


def encode_image_to_base64(image_bytes: bytes, max_size: int = 1024, filename: str = "") -> str:
    """将图片字节编码为 base64 字符串，可选压缩。支持 RAW 格式。"""
    img = image_bytes_to_pil(image_bytes, filename)
    if img is not None:
        try:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            width, height = img.size
            if max(width, height) > max_size:
                ratio = max_size / max(width, height)
                new_size = (int(width * ratio), int(height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception:
            pass
    return base64.b64encode(image_bytes).decode("utf-8")


def extract_exif_info(image_bytes: bytes, filename: str = "") -> dict:
    """从照片 EXIF 中提取拍摄时间和 GPS 坐标。支持 RAW 格式。"""
    result = {"shoot_time": "", "gps_lat": None, "gps_lon": None}
    if not HAS_PIL:
        return result

    # RAW 格式：先提取内嵌 JPEG 再读 EXIF
    actual_bytes = image_bytes
    if is_raw_file(filename):
        jpeg_data = extract_jpeg_from_raw(image_bytes)
        if jpeg_data:
            actual_bytes = jpeg_data
        else:
            return result

    try:
        img = Image.open(io.BytesIO(actual_bytes))
        exif_data = img._getexif()
        if not exif_data:
            return result

        for tag_id in (36867, 36868, 306):
            if tag_id in exif_data:
                raw_time = exif_data[tag_id]
                try:
                    cleaned = raw_time.replace(":", "").replace(" ", "_")[:13]
                    result["shoot_time"] = cleaned
                except (ValueError, AttributeError):
                    pass
                break

        gps_info_tag = 34853
        if gps_info_tag in exif_data:
            gps_data = exif_data[gps_info_tag]

            def gps_to_decimal(gps_coords, gps_ref):
                degrees = float(gps_coords[0])
                minutes = float(gps_coords[1])
                seconds = float(gps_coords[2])
                decimal = degrees + minutes / 60.0 + seconds / 3600.0
                if gps_ref in ("S", "W"):
                    decimal = -decimal
                return decimal

            if 2 in gps_data and 1 in gps_data:
                result["gps_lat"] = gps_to_decimal(gps_data[2], gps_data[1])
            if 4 in gps_data and 3 in gps_data:
                result["gps_lon"] = gps_to_decimal(gps_data[4], gps_data[3])
    except Exception:
        pass
    return result


def reverse_geocode(latitude: float, longitude: float) -> str:
    """使用 Nominatim 逆地理编码将 GPS 坐标转换为地名"""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?"
            f"lat={latitude}&lon={longitude}&format=json&accept-language=zh-CN&zoom=14"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "BirdPhotoApp/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            address = data.get("address", {})
            city = address.get("city", address.get("town", address.get("county", "")))
            district = address.get("suburb", address.get("district", address.get("village", "")))
            state = address.get("state", address.get("province", ""))
            poi_name = data.get("name", "")
            if poi_name and city:
                return f"{city}{poi_name}"
            elif city and district:
                return f"{city}{district}"
            elif city:
                return city
            elif state:
                return state
    except Exception:
        pass
    return ""


def _build_context_block(exif_info: dict) -> tuple:
    """构建地理位置和季节辅助信息，返回 (context_block, season)"""
    context_block = ""
    season = ""
    location_name = exif_info.get("geocoded_location", "")

    if exif_info.get("shoot_time"):
        raw_time = exif_info["shoot_time"]
        month_str = raw_time[4:6] if len(raw_time) >= 6 else ""
        if month_str:
            month = int(month_str)
            if month in (3, 4, 5):
                season = "春季（春迁期，3-5月）"
            elif month in (6, 7, 8):
                season = "夏季（繁殖期，6-8月）"
            elif month in (9, 10, 11):
                season = "秋季（秋迁期，9-11月）"
            else:
                season = "冬季（越冬期，12-2月）"

    if location_name or season or (exif_info.get("gps_lat") and exif_info.get("gps_lon")):
        context_block = "\n\n【关键约束 - 必须结合以下信息缩小候选鸟种范围】\n"
        if location_name:
            context_block += f"拍摄地点：{location_name}\n"
        if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
            context_block += f"GPS坐标：北纬{abs(exif_info['gps_lat']):.4f}°，东经{abs(exif_info['gps_lon']):.4f}°\n"
        if exif_info.get("shoot_time"):
            context_block += f"拍摄时间：{exif_info['shoot_time']}\n"
        if season:
            context_block += f"季节：{season}\n"
        context_block += (
            "\n你必须严格按照以下逻辑进行识别：\n"
            "1. 先根据外形特征初步判断可能的鸟种（列出2-3个候选种）\n"
            "2. 然后逐一检查每个候选种在该地区、该季节是否有分布记录\n"
            "3. 排除在该地区该季节不可能出现的鸟种\n"
            "4. 从剩余候选种中选择最匹配的\n"
            "候鸟的季节性分布尤其重要：夏候鸟只在繁殖季出现，冬候鸟只在越冬季出现，"
            "旅鸟只在迁徙季短暂停留。"
        )

    return context_block, season


def _phase1_candidates(client, image_base64: str, context_block: str) -> list:
    """第一阶段：快速识别 top-3 候选鸟种"""
    response = client.chat.completions.create(
        model="qwen-vl-max-latest",
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专精中国鸟类的顶级鸟类学家。"
                    "你熟悉《中国鸟类野外手册》中记录的所有鸟种，"
                    "精通中国境内1400余种鸟类的辨识要点、分布范围和季节性变化。"
                    "你能根据细微的羽色差异区分易混淆种。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "请仔细观察这张鸟类照片，给出最可能的 3 个候选鸟种。\n\n"
                            "对每个候选种，请说明：\n"
                            "1. 中文名和英文名\n"
                            "2. 你从照片中观察到的支持该种的关键特征（具体描述喙、眉纹、羽色等）\n"
                            "3. 与其他候选种的关键区分点是什么\n"
                            "4. 该种在中国的分布范围和季节性\n"
                            "5. 置信度（0-100%）\n\n"
                            "同时列出你排除的易混淆种（至少2个），说明排除理由。\n\n"
                            "只返回 JSON，格式如下：\n"
                            "{\n"
                            '  "candidates": [\n'
                            '    {"chinese_name": "种名", "english_name": "name", '
                            '"key_features": "从照片观察到的支持特征", '
                            '"distinguishing_marks": "与其他候选种的区分点", '
                            '"distribution": "分布和季节性", "confidence": 80},\n'
                            '    ...\n'
                            '  ],\n'
                            '  "excluded_species": [\n'
                            '    {"chinese_name": "种名", "reason": "排除理由"}\n'
                            '  ],\n'
                            '  "observed_features": "照片中鸟的整体特征描述（体型、喙、羽色、环境等）"\n'
                            "}\n"
                            f"{context_block}"
                        ),
                    },
                ],
            },
        ],
    )

    result_text = response.choices[0].message.content.strip()
    json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            return parsed.get("candidates", []), parsed.get("excluded_species", []), parsed.get("observed_features", "")
        except (json.JSONDecodeError, ValueError):
            pass
    return [], [], ""


def identify_bird(image_base64: str, api_key: str, exif_info: dict) -> dict:
    """两阶段鸟类识别 + 摄影评分（使用 qwen-vl-max-latest）

    第一阶段：快速给出 top-3 候选鸟种及区分特征
    第二阶段：基于候选信息做最终精确判断 + 摄影评分
    """
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    context_block, season = _build_context_block(exif_info)

    # ---- 第一阶段：获取 top-3 候选种 ----
    candidates, excluded, observed_features = _phase1_candidates(client, image_base64, context_block)

    # 构建候选信息供第二阶段使用
    candidates_block = ""
    if candidates:
        candidates_block = "\n\n【第一阶段候选结果 - 请在此基础上做最终判断】\n"
        candidates_block += f"照片特征概述：{observed_features}\n\n"
        for idx, cand in enumerate(candidates, 1):
            candidates_block += (
                f"候选{idx}：{cand.get('chinese_name', '?')} ({cand.get('english_name', '?')})\n"
                f"  支持特征：{cand.get('key_features', '')}\n"
                f"  区分要点：{cand.get('distinguishing_marks', '')}\n"
                f"  分布：{cand.get('distribution', '')}\n"
                f"  初步置信度：{cand.get('confidence', '?')}%\n\n"
            )
        if excluded:
            candidates_block += "已排除的易混淆种：\n"
            for exc in excluded:
                candidates_block += f"  ✗ {exc.get('chinese_name', '?')}：{exc.get('reason', '')}\n"
        candidates_block += (
            "\n请基于以上候选信息，重新仔细审视照片，做出最终判断。\n"
            "你可以选择候选种之一，也可以推翻候选给出新的判断（需说明理由）。\n"
            "必须在 identification_basis 中说明你最终选择该种而非其他候选种的关键依据。"
        )

    # ---- 第二阶段：精确判断 + 评分 ----
    response = client.chat.completions.create(
        model="qwen-vl-max-latest",
        temperature=0.3,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专精中国鸟类的顶级鸟类学家和鸟类摄影评审专家。"
                    "你熟悉《中国鸟类野外手册》《中国鸟类分类与分布名录》中记录的所有鸟种，"
                    "精通中国境内1400余种鸟类的辨识要点、分布范围和季节性变化。"
                    "你能根据细微的羽色差异区分中国常见的易混淆种（如柳莺类、鹀类、鸫类等）。"
                    "同时你精通鸟类摄影的评判标准，评分非常严格，只有真正出色的照片才能获得高分。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "请完成以下任务：\n\n"
                            "## 任务一：鸟种最终判定\n"
                            "这张照片拍摄于中国境内，请在中国有分布记录的鸟种范围内做最终识别。\n"
                            "仔细观察以下特征来精确识别：\n"
                            "- 体型大小和比例（与麻雀/鸽子/乌鸦等常见鸟对比）\n"
                            "- 喙的形状、长度、粗细和颜色\n"
                            "- 头部特征（冠羽、眉纹、贯眼纹、眼圈颜色）\n"
                            "- 上体和下体羽色、翼斑、腰色、尾羽形状和颜色\n"
                            "- 腿脚颜色\n"
                            "- 结合栖息环境（水域/林地/草地/城市等）辅助判断\n\n"
                            "## 任务二：鸟的位置标注\n"
                            "估算鸟在图片中的位置，用百分比坐标 [x1, y1, x2, y2]（0-100）。\n"
                            "边界框应紧密包围整只鸟。多只鸟时标注最显眼的。\n\n"
                            "## 任务三：专业摄影评分\n"
                            "以国际鸟类摄影大赛的标准严格评分。\n\n"
                            "**【核心评分方法 - 必须严格遵守】**\n"
                            "每个维度从该维度满分的50%开始，根据优缺点加减分：\n"
                            "- 有明显优点：+1到+3分\n"
                            "- 有明显缺点：-1到-5分\n"
                            "- 有严重缺陷：直接降到该维度满分的20%以下\n"
                            "- 只有极其出色才能超过该维度满分的80%\n\n"
                            "**1. 主体清晰度（0-20分，起始10分）**\n"
                            "鸟眼锐利+2/模糊-3；羽毛纤毫毕现+3/模糊-3；运动模糊-2到-4\n\n"
                            "**2. 构图与美感（0-20分，起始10分）**\n"
                            "三分法/黄金分割+2；居中平庸-2；主体裁切-3到-5\n\n"
                            "**3. 光线与色彩（0-20分，起始10分）**\n"
                            "黄金时段+3；正午顶光-2；过曝/欠曝-3\n\n"
                            "**4. 背景与环境（0-15分，起始7分）**\n"
                            "奶油虚化+3；杂乱-3；干扰元素-2到-4\n\n"
                            "**5. 姿态与瞬间（0-15分，起始7分）**\n"
                            "行为瞬间+3到+5；普通静立不加分；背对/遮挡-2到-4\n\n"
                            "**6. 艺术性与故事感（0-10分，起始3分）**\n"
                            "纯记录照2-3分；有氛围4-5分；有意境6-7分；8+需强烈共鸣\n\n"
                            "**总分分布：** 90+百里挑一；75-89优秀约10%；55-74大多数；40-54有不足；<40很差\n\n"
                            "**反作弊：总分>80时重新审视每个分项，不确定则降2-3分。**\n\n"
                            "只返回一个 JSON 对象，不要返回其他内容。\n"
                            "{\n"
                            '  "chinese_name": "最终确定的中文种名",\n'
                            '  "english_name": "英文种名",\n'
                            '  "order_chinese": "目中文名",\n'
                            '  "order_english": "目英文名",\n'
                            '  "family_chinese": "科中文名",\n'
                            '  "family_english": "科英文名",\n'
                            '  "confidence": "high/medium/low",\n'
                            '  "identification_basis": "最终选择该种的关键依据，以及排除其他候选种的理由（30字以内）",\n'
                            '  "excluded_similar_species": "排除的易混淆种及理由（如：非白头鹎，因缺少红色臀部）",\n'
                            '  "bird_description": "该鸟种详细介绍（100-150字），含外形、习性、生境、分布、常见程度",\n'
                            '  "bird_bbox": [x1, y1, x2, y2],\n'
                            '  "score": 0,\n'
                            '  "score_sharpness": 0,\n'
                            '  "score_composition": 0,\n'
                            '  "score_lighting": 0,\n'
                            '  "score_background": 0,\n'
                            '  "score_pose": 0,\n'
                            '  "score_artistry": 0,\n'
                            '  "score_comment": "照片点评（30字以内）"\n'
                            "}\n\n"
                            "要求：\n"
                            "1. 必须精确到具体鸟种，目和科使用正确分类学名称\n"
                            "2. 如果无法识别，chinese_name 填 \"未知鸟类\"\n"
                            "3. score 必须等于6个分项之和\n"
                            "4. 每个分项必须根据照片实际情况独立评判\n"
                            "5. identification_basis 必须说明为何选择该种而非其他候选种\n"
                            "6. excluded_similar_species 必须列出至少1个排除的易混淆种及理由"
                            f"{context_block}"
                            f"{candidates_block}"
                        ),
                    },
                ],
            },
        ],
    )

    result_text = response.choices[0].message.content.strip()
    json_match = re.search(r'\{[^{}]*\}', result_text, re.DOTALL)
    if json_match:
        parsed = json.loads(json_match.group())
        # 确保分项分数在合理范围内
        dimension_keys = [
            ("score_sharpness", 20), ("score_composition", 20),
            ("score_lighting", 20), ("score_background", 15),
            ("score_pose", 15), ("score_artistry", 10),
        ]
        total = 0
        for key, max_val in dimension_keys:
            val = max(0, min(max_val, int(parsed.get(key, 0))))
            parsed[key] = val
            total += val
        parsed["score"] = total
        return parsed

    return {
        "chinese_name": "未知鸟类", "english_name": "unknown",
        "order_chinese": "未知目", "order_english": "Unknown",
        "family_chinese": "未知科", "family_english": "Unknown",
        "confidence": "low", "score": 0,
        "score_sharpness": 0, "score_composition": 0,
        "score_lighting": 0, "score_background": 0,
        "score_pose": 0, "score_artistry": 0,
        "score_comment": "识别失败",
        "identification_basis": "",
        "bird_description": "",
    }


def crop_to_bird(img: "Image.Image", bbox: list, padding_ratio: float = 0.15) -> "Image.Image":
    """根据 AI 返回的百分比 bounding box 裁剪图片，聚焦到鸟的区域。

    bbox 格式: [x1, y1, x2, y2]，值为 0-100 的百分比。
    padding_ratio: 在 bbox 外围额外保留的比例（避免裁太紧）。
    """
    if not bbox or len(bbox) != 4:
        return img

    width, height = img.size
    x1_pct, y1_pct, x2_pct, y2_pct = bbox

    # 百分比转像素
    x1 = int(width * x1_pct / 100)
    y1 = int(height * y1_pct / 100)
    x2 = int(width * x2_pct / 100)
    y2 = int(height * y2_pct / 100)

    # 确保坐标有效
    if x2 <= x1 or y2 <= y1:
        return img

    # 添加 padding（让鸟不要贴边）
    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = int(box_width * padding_ratio)
    pad_y = int(box_height * padding_ratio)

    crop_x1 = max(0, x1 - pad_x)
    crop_y1 = max(0, y1 - pad_y)
    crop_x2 = min(width, x2 + pad_x)
    crop_y2 = min(height, y2 + pad_y)

    # 如果裁剪区域太小（鸟已经占满画面），就不裁剪
    crop_area = (crop_x2 - crop_x1) * (crop_y2 - crop_y1)
    total_area = width * height
    if crop_area > total_area * 0.85:
        return img

    return img.crop((crop_x1, crop_y1, crop_x2, crop_y2))


# ============================================================
# 数据库相关函数（通过 Supabase REST API，无需额外依赖）
# ============================================================
def _supabase_config():
    """获取 Supabase 配置，返回 (url, key) 或 (None, None)"""
    try:
        return st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    except (KeyError, FileNotFoundError):
        return None, None


def _supabase_request(method: str, endpoint: str, body: dict = None,
                      params: str = ""):
    """通用 Supabase REST API 请求"""
    base_url, api_key = _supabase_config()
    if not base_url or not api_key:
        return None

    url = f"{base_url}/rest/v1/{endpoint}"
    if params:
        url += f"?{params}"

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
            if response_body:
                return json.loads(response_body)
            return None
    except urllib.error.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        st.toast(f"⚠️ 数据库请求失败: {http_err.code} {error_body[:100]}", icon="⚠️")
        return None
    except Exception:
        return None


def get_supabase_client():
    """检查 Supabase 是否可用，返回 True/False（兼容原有调用方式）"""
    base_url, api_key = _supabase_config()
    return True if (base_url and api_key) else None


def generate_thumbnail_base64(image_bytes: bytes, filename: str = "",
                              bird_bbox: list = None, max_width: int = 480) -> str:
    """生成缩略图的 base64 字符串（保留完整画面，压缩到 480px 宽）"""
    img = image_bytes_to_pil(image_bytes, filename)
    if img is None:
        return ""
    try:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # 不裁剪，保留完整的鸟的形象
        width, height = img.size
        if width > max_width:
            ratio = max_width / width
            new_size = (max_width, int(height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        return ""


def save_record_to_db(supabase_client, user_nickname: str, result: dict,
                      thumbnail_b64: str) -> bool:
    """将一条识别记录保存到 Supabase 数据库"""
    if not supabase_client:
        return False
    try:
        record = {
            "user_nickname": user_nickname,
            "chinese_name": result.get("chinese_name", "未知鸟类"),
            "english_name": result.get("english_name", ""),
            "order_chinese": result.get("order_chinese", ""),
            "family_chinese": result.get("family_chinese", ""),
            "confidence": result.get("confidence", "low"),
            "score": result.get("score", 0),
            "score_sharpness": result.get("score_sharpness", 0),
            "score_composition": result.get("score_composition", 0),
            "score_lighting": result.get("score_lighting", 0),
            "score_background": result.get("score_background", 0),
            "score_pose": result.get("score_pose", 0),
            "score_artistry": result.get("score_artistry", 0),
            "score_comment": result.get("score_comment", ""),
            "identification_basis": result.get("identification_basis", ""),
            "bird_description": result.get("bird_description", ""),
            "shoot_date": result.get("shoot_date", ""),
            "thumbnail_base64": thumbnail_b64,
        }
        result_data = _supabase_request("POST", "bird_records", body=record)
        return result_data is not None
    except Exception:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def fetch_user_history(_supabase_client, user_nickname: str, limit: int = 50) -> list:
    """查询用户的历史识别记录（缓存 30 秒）"""
    if not _supabase_client:
        return []
    try:
        encoded_nickname = urllib.parse.quote(user_nickname)
        params = (
            f"user_nickname=eq.{encoded_nickname}"
            f"&order=created_at.desc"
            f"&limit={limit}"
            f"&select=id,chinese_name,score,created_at,thumbnail_base64"
        )
        result = _supabase_request("GET", "bird_records", params=params)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def delete_record_from_db(record_id: int) -> bool:
    """从数据库中删除一条识别记录"""
    base_url, api_key = _supabase_config()
    if not base_url or not api_key:
        return False
    try:
        import http.client
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        conn = http.client.HTTPSConnection(parsed.hostname, timeout=15)
        path = f"/rest/v1/bird_records?id=eq.{record_id}"
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Prefer": "return=minimal",
        }
        conn.request("DELETE", path, body=None, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        body = resp.read().decode("utf-8", errors="replace")
        conn.close()
        if status in (200, 204):
            return True
        st.error(f"删除失败 ({status}): {body[:200]}")
        return False
    except Exception as exc:
        st.error(f"删除失败: {exc}")
        return False


def fetch_user_stats_from_records(records: list) -> dict:
    """从已有的历史记录中计算统计数据（避免额外的数据库请求）"""
    if not records:
        return {"total": 0, "species": 0, "avg_score": 0, "best_score": 0}
    species_set = set(r["chinese_name"] for r in records if r.get("chinese_name"))
    scores = [r["score"] for r in records if r.get("score")]
    avg_score = sum(scores) / len(scores) if scores else 0
    best_score = max(scores) if scores else 0
    return {
        "total": len(records),
        "species": len(species_set),
        "avg_score": round(avg_score, 1),
        "best_score": best_score,
    }


@st.cache_data(ttl=60, show_spinner=False)
def fetch_top_photos(limit: int = 10) -> list:
    """查询全局评分最高的照片（缓存 60 秒）"""
    try:
        params = (
            f"select=id,user_nickname,chinese_name,score,thumbnail_base64"
            f"&order=score.desc"
            f"&limit={limit}"
            f"&score=gt.0"
        )
        result = _supabase_request("GET", "bird_records", params=params)
        return result if isinstance(result, list) else []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def fetch_leaderboard(limit: int = 20) -> list:
    """查询所有用户的排行榜数据，按鸟种数降序排列（缓存 60 秒）"""
    try:
        params = "select=user_nickname,chinese_name,score&limit=2000"
        result = _supabase_request("GET", "bird_records", params=params)
        records = result if isinstance(result, list) else []
        if not records:
            return []
        # 按用户聚合统计
        user_data = {}
        for record in records:
            nickname = record.get("user_nickname", "")
            if not nickname:
                continue
            if nickname not in user_data:
                user_data[nickname] = {"species": set(), "total": 0, "scores": []}
            user_data[nickname]["total"] += 1
            chinese_name = record.get("chinese_name", "")
            if chinese_name and chinese_name != "未知鸟类":
                user_data[nickname]["species"].add(chinese_name)
            score = record.get("score", 0)
            if score:
                user_data[nickname]["scores"].append(score)
        # 转为列表并排序
        leaderboard = []
        for nickname, data in user_data.items():
            scores = data["scores"]
            avg_score = round(sum(scores) / len(scores), 1) if scores else 0
            best_score = max(scores) if scores else 0
            leaderboard.append({
                "nickname": nickname,
                "species": len(data["species"]),
                "total": data["total"],
                "avg_score": avg_score,
                "best_score": best_score,
            })
        leaderboard.sort(key=lambda x: (x["species"], x["total"], x["avg_score"]), reverse=True)
        return leaderboard[:limit]
    except Exception:
        return []


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    sanitized = sanitized.strip('. ')
    return sanitized if sanitized else "unknown"


def get_score_color(score: int) -> str:
    if score >= 90:
        return "excellent"
    elif score >= 75:
        return "good"
    elif score >= 60:
        return "fair"
    return "poor"


def get_score_emoji(score: int) -> str:
    if score >= 90:
        return "🌟"
    elif score >= 75:
        return "⭐"
    elif score >= 60:
        return "👍"
    return "📷"


def get_confidence_emoji(confidence: str) -> str:
    return {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(confidence, "⚪")


def build_filename(result: dict) -> str:
    """根据识别结果构建文件名"""
    parts = [sanitize_filename(result.get("chinese_name", "未知鸟类"))]
    shoot_date = result.get("shoot_date", "")
    if shoot_date:
        parts.append(shoot_date)
    parts.append(f"{result.get('score', 0)}分")
    return "_".join(parts)


def create_organized_zip(results_with_bytes: list) -> bytes:
    """创建按 目/科 分类整理的 zip 文件"""
    zip_buffer = io.BytesIO()
    name_counters = {}

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in results_with_bytes:
            result = item["result"]
            image_bytes = item["image_bytes"]
            original_suffix = item["suffix"]

            order_folder = sanitize_filename(
                f"{result.get('order_chinese', '未知目')}({result.get('order_english', 'Unknown')})"
            )
            family_folder = sanitize_filename(
                f"{result.get('family_chinese', '未知科')}({result.get('family_english', 'Unknown')})"
            )

            filename = build_filename(result)
            full_name = f"{filename}{original_suffix}"
            zip_path = f"{order_folder}/{family_folder}/{full_name}"

            # 处理重名
            if zip_path in name_counters:
                name_counters[zip_path] += 1
                full_name = f"{filename}_{name_counters[zip_path]}{original_suffix}"
                zip_path = f"{order_folder}/{family_folder}/{full_name}"
            else:
                name_counters[zip_path] = 1

            zip_file.writestr(zip_path, image_bytes)

        # 写入识别结果 JSON
        results_json = [item["result"] for item in results_with_bytes]
        zip_file.writestr(
            "bird_identification_results.json",
            json.dumps(results_json, ensure_ascii=False, indent=2)
        )

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


# ============================================================
# API Key & Supabase 初始化
# ============================================================
MAX_PHOTOS_PER_SESSION = 10

api_key = ""
try:
    api_key = st.secrets["DASHSCOPE_API_KEY"]
except (KeyError, FileNotFoundError):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")

if not api_key:
    st.error("服务暂不可用，请联系管理员配置 API Key。")
    st.stop()

supabase_client = get_supabase_client()

# ============================================================
# 用户昵称 session 初始化（从 URL 参数恢复）
# ============================================================
if "user_nickname" not in st.session_state:
    saved_nick = st.query_params.get("nick", "")
    st.session_state["user_nickname"] = saved_nick

# ============================================================
# 顶部区域：左边 Logo+介绍 | 右边 登录+上传
# ============================================================
hero_left, hero_right = st.columns([1, 3], gap="medium")

with hero_left:
    st.markdown("""
    <div class="hero-section">
        <span class="hero-icon">🦅</span>
        <h1 class="hero-title">影禽</h1>
        <p class="hero-subtitle">BirdEye · AI 鸟类识别与摄影评分平台</p>
        <div class="hero-features">
            <div class="hero-feature-item">🔍 <b>智能识别</b> 覆盖中国 1400+ 鸟种</div>
            <div class="hero-feature-item">📸 <b>专业评分</b> 六维度摄影评价体系</div>
            <div class="hero-feature-item">📂 <b>自动整理</b> 按目/科分类归档照片</div>
            <div class="hero-feature-item">☁️ <b>云端记录</b> 永久保存你的观鸟足迹</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with hero_right:
    # ---- 佳作榜：横向滚动展示评分最高的 top10 照片 ----
    top_photos = fetch_top_photos()
    if top_photos:
        cards_html = ""
        for rank, photo in enumerate(top_photos, 1):
            thumb_b64 = photo.get("thumbnail_base64", "")
            photo_nickname = photo.get("user_nickname", "匿名")
            bird_name = photo.get("chinese_name", "未知")
            photo_score = photo.get("score", 0)
            score_color = get_score_color(photo_score)
            score_emoji_str = get_score_emoji(photo_score)

            if rank == 1:
                rank_label = "🥇"
            elif rank == 2:
                rank_label = "🥈"
            elif rank == 3:
                rank_label = "🥉"
            else:
                rank_label = f"#{rank}"

            if thumb_b64:
                img_html = (
                    f'<img src="data:image/jpeg;base64,{thumb_b64}" '
                    f'style="width:100%;height:140px;object-fit:cover;border-radius:10px 10px 0 0;" '
                    f'loading="lazy" alt="{bird_name}">'
                )
                full_img_html = (
                    f'<img src="data:image/jpeg;base64,{thumb_b64}" '
                    f'style="width:100%;border-radius:8px;object-fit:contain;" alt="{bird_name}">'
                )
            else:
                img_html = (
                    '<div style="width:100%;height:140px;background:rgba(0,0,0,0.04);'
                    'border-radius:10px 10px 0 0;display:flex;align-items:center;'
                    'justify-content:center;font-size:32px;">🐦</div>'
                )
                full_img_html = ""

            if photo_score >= 80:
                pill_color = "#34c759"
            elif photo_score >= 60:
                pill_color = "#007aff"
            else:
                pill_color = "#ff9500"

            cards_html += (
                f'<div style="min-width:160px;max-width:160px;background:#fff;'
                f'border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);'
                f'flex-shrink:0;overflow:hidden;">'
                f'{img_html}'
                f'<div style="padding:8px 10px;">'
                f'<div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;">'
                f'<span style="font-size:14px;">{rank_label}</span>'
                f'<span style="font-size:13px;font-weight:600;color:#1d1d1f;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{bird_name}</span>'
                f'</div>'
                f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                f'<span style="font-size:11px;color:#86868b;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;max-width:70px;">👤 {photo_nickname}</span>'
                f'<span style="font-size:11px;font-weight:600;color:{pill_color};'
                f'background:rgba(0,0,0,0.04);padding:1px 6px;border-radius:8px;">'
                f'{score_emoji_str} {photo_score}</span>'
                f'</div>'
                f'</div>'
                f'</div>'
            )

        st.markdown(
            f'<div style="margin-bottom:12px;">'
            f'<p style="font-size:15px;font-weight:700;color:#1d1d1f;margin:0 0 8px;">'
            f'📸 佳作榜 · Top 10</p>'
            f'<div style="display:flex;gap:12px;overflow-x:auto;padding:4px 0 12px;'
            f'-webkit-overflow-scrolling:touch;">'
            f'{cards_html}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # 用户登录区
    if not st.session_state["user_nickname"]:
        st.markdown(
            '<div class="login-card">'
            '<p class="login-title">👋 欢迎来到影禽</p>'
            '<p class="login-subtitle">输入昵称，开启你的观鸟之旅</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        entered_nickname = st.text_input(
            "你的昵称",
            placeholder="例如：观鸟达人小明",
            label_visibility="collapsed",
            max_chars=20,
        )
        if entered_nickname and entered_nickname.strip():
            st.session_state["user_nickname"] = entered_nickname.strip()
            st.query_params["nick"] = entered_nickname.strip()
            st.rerun()
        if not entered_nickname:
            st.stop()
    else:
        nickname_display = st.session_state["user_nickname"]
        if st.query_params.get("nick", "") != nickname_display:
            st.query_params["nick"] = nickname_display

        col_greeting, col_switch = st.columns([3, 1])
        with col_greeting:
            st.markdown(
                f'<p style="font-size:15px; color:#86868b; margin:8px 0 4px;">'
                f'🐦 <b style="color:#1d1d1f; font-size:17px;">{nickname_display}</b></p>',
                unsafe_allow_html=True,
            )
        with col_switch:
            if st.button("切换", type="secondary", use_container_width=True):
                st.session_state["user_nickname"] = ""
                st.query_params.pop("nick", None)
                st.session_state.pop("identified_cache", None)
                st.session_state.pop("results_with_bytes", None)
                st.session_state.pop("zip_bytes", None)
                st.rerun()
        # 上传区域（紧跟在登录下方）
        st.markdown(
            f'<p class="section-subtitle" style="margin-top:8px;">'
            f'支持 JPG、PNG、RAW 等格式，每次最多 {MAX_PHOTOS_PER_SESSION} 张</p>',
            unsafe_allow_html=True,
        )

        uploaded_files = st.file_uploader(
            "拖拽照片到此处，或点击选择文件",
            type=["jpg", "jpeg", "png", "tif", "tiff", "heic", "bmp", "webp",
                  "arw", "cr2", "cr3", "nef", "nrw", "dng", "raf", "orf", "rw2", "pef", "srw"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if uploaded_files:
            if len(uploaded_files) > MAX_PHOTOS_PER_SESSION:
                st.warning(f"每次最多 {MAX_PHOTOS_PER_SESSION} 张，已自动截取。")
                uploaded_files = uploaded_files[:MAX_PHOTOS_PER_SESSION]
            st.markdown(
                f'<p style="font-size:14px; color:#86868b; margin:4px 0;">已选择 '
                f'<b style="color:#1d1d1f;">{len(uploaded_files)}</b> 张照片</p>',
                unsafe_allow_html=True,
            )

        # ============================================================
        # 上传后自动识别（在右栏内）
        # ============================================================
        if uploaded_files and api_key:
            if "identified_cache" not in st.session_state:
                st.session_state["identified_cache"] = {}

            def make_file_key(uploaded_file):
                return f"{uploaded_file.name}_{uploaded_file.size}"

            current_file_keys = set()
            new_files = []
            for uploaded_file in uploaded_files:
                fkey = make_file_key(uploaded_file)
                current_file_keys.add(fkey)
                if fkey not in st.session_state["identified_cache"]:
                    new_files.append(uploaded_file)

            if new_files:
                # 仪式感进度提示
                st.markdown(
                    '<div class="progress-banner">'
                    '✨ AI 正在分析你的照片…'
                    '</div>',
                    unsafe_allow_html=True,
                )
                progress_bar = st.progress(0)

                for idx, uploaded_file in enumerate(new_files):
                    fkey = make_file_key(uploaded_file)
                    progress_bar.progress(
                        (idx + 0.5) / len(new_files),
                        text=f"🔍 识别中 ({idx + 1}/{len(new_files)}) {uploaded_file.name}",
                    )

                    image_bytes = uploaded_file.getvalue()
                    suffix = Path(uploaded_file.name).suffix.lower()
                    exif_info = extract_exif_info(image_bytes, uploaded_file.name)

                    if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
                        geocoded_location = reverse_geocode(exif_info["gps_lat"], exif_info["gps_lon"])
                        if geocoded_location:
                            exif_info["geocoded_location"] = geocoded_location

                    image_base64 = encode_image_to_base64(image_bytes, filename=uploaded_file.name)
                    result = identify_bird(image_base64, api_key, exif_info)

                    shoot_date = ""
                    if exif_info.get("shoot_time"):
                        shoot_date = exif_info["shoot_time"][:8]
                    result["shoot_date"] = shoot_date
                    result["original_name"] = uploaded_file.name

                    st.session_state["identified_cache"][fkey] = {
                        "result": result,
                        "image_bytes": image_bytes,
                        "suffix": suffix,
                    }

                # 新增记录后清除缓存，确保历史记录和排行榜刷新
                fetch_user_history.clear()
                fetch_leaderboard.clear()
                fetch_top_photos.clear()

            results_with_bytes = []
            for uploaded_file in uploaded_files:
                fkey = make_file_key(uploaded_file)
                if fkey in st.session_state["identified_cache"]:
                    results_with_bytes.append(st.session_state["identified_cache"][fkey])

            if results_with_bytes:
                zip_bytes = create_organized_zip(results_with_bytes)
                st.session_state["results_with_bytes"] = results_with_bytes
                st.session_state["zip_bytes"] = zip_bytes

        # ============================================================
        # 展示结果（在右栏内）
        # ============================================================
        if "results_with_bytes" in st.session_state:
            results_with_bytes = st.session_state["results_with_bytes"]
            results = [item["result"] for item in results_with_bytes]

            st.markdown(
                '<div class="results-divider"></div>',
                unsafe_allow_html=True,
            )

            # 汇总统计
            scores = [r["score"] for r in results if r.get("score")]
            if scores:
                species_set = set(r["chinese_name"] for r in results)
                avg_score = sum(scores) / len(scores)
                best_score = max(scores)

                stat_cols = st.columns(4, gap="small")
                stat_data = [
                    (str(len(results)), "照片"),
                    (f"{len(species_set)}", "鸟种"),
                    (f"{avg_score:.1f}", "均分"),
                    (f"{best_score}", "最高"),
                ]
                for col, (value, label) in zip(stat_cols, stat_data):
                    with col:
                        st.markdown(
                            f'<div class="stat-card">'
                            f'<div class="stat-value">{value}</div>'
                            f'<div class="stat-label">{label}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

            # 分类统计
            taxonomy = {}
            for result in results:
                order = result.get("order_chinese", "未知目")
                family = result.get("family_chinese", "未知科")
                species_name = result["chinese_name"]
                taxonomy.setdefault(order, {}).setdefault(family, set())
                taxonomy[order][family].add(species_name)

            with st.expander("分类学概览"):
                for order, families in sorted(taxonomy.items()):
                    st.markdown(f"**{order}**")
                    for family, species_set in sorted(families.items()):
                        species_list = " · ".join(sorted(species_set))
                        st.markdown(
                            f'&nbsp;&nbsp;&nbsp;&nbsp;'
                            f'<span class="taxonomy-pill family-pill">{family}</span> '
                            f'<span style="color:#6e6e73; font-size:14px;">{species_list}</span>',
                            unsafe_allow_html=True,
                        )

            # 逐张展示 - 一行3个卡片网格（右栏空间适配）
            for row_start in range(0, len(results_with_bytes), 3):
                row_items = results_with_bytes[row_start:row_start + 3]
                card_cols = st.columns(3)

                for col_idx, item in enumerate(row_items):
                    result = item["result"]
                    image_bytes = item["image_bytes"]

                    score = result.get("score", 0)
                    score_color = get_score_color(score)
                    score_emoji = get_score_emoji(score)
                    confidence = result.get("confidence", "low")

                    with card_cols[col_idx]:
                        original_name = result.get("original_name", "")
                        preview_img = image_bytes_to_pil(image_bytes, original_name)
                        if preview_img is not None:
                            bird_bbox = result.get("bird_bbox")
                            if bird_bbox and len(bird_bbox) == 4:
                                try:
                                    cropped_img = crop_to_bird(preview_img.copy(), bird_bbox)
                                    st.image(cropped_img, use_container_width=True)
                                except Exception:
                                    st.image(preview_img, use_container_width=True)
                            else:
                                st.image(preview_img, use_container_width=True)
                        else:
                            st.text("无法预览")

                        st.markdown(
                            f'<p class="bird-name">{result.get("chinese_name", "未知")}</p>'
                            f'<p class="bird-name-en">{result.get("english_name", "")}</p>',
                            unsafe_allow_html=True,
                        )

                        confidence_class = f"confidence-{confidence}"
                        st.markdown(
                            f'<span class="taxonomy-pill order-pill">{result.get("order_chinese", "")}</span>'
                            f'<span class="taxonomy-pill family-pill">{result.get("family_chinese", "")}</span>'
                            f'<br>'
                            f'<span class="score-pill score-{score_color}" style="margin-top:6px;">'
                            f'{score_emoji} {score}</span>'
                            f'&nbsp;'
                            f'<span class="confidence-dot {confidence_class}"></span>'
                            f'<span style="font-size:12px; color:#86868b;">{confidence}</span>',
                            unsafe_allow_html=True,
                        )

                        basis = result.get("identification_basis", "")
                        if basis:
                            st.markdown(
                                f'<div style="font-size:12px; color:#6e6e73; margin-top:6px;">'
                                f'<b style="color:#86868b;">识别依据</b> {basis}</div>',
                                unsafe_allow_html=True,
                            )

                        bird_desc = result.get("bird_description", "")
                        if bird_desc:
                            with st.expander("🐦 鸟类介绍"):
                                st.markdown(
                                    f'<div style="font-size:12px; color:#3a3a3c; line-height:1.7;">'
                                    f'{bird_desc}</div>',
                                    unsafe_allow_html=True,
                                )

                        shoot_date = result.get("shoot_date", "")
                        if shoot_date and len(shoot_date) >= 8:
                            formatted_date = f"{shoot_date[:4]}.{shoot_date[4:6]}.{shoot_date[6:8]}"
                            st.markdown(
                                f'<div style="font-size:12px; color:#86868b; margin-top:4px;">'
                                f'📅 {formatted_date}</div>',
                                unsafe_allow_html=True,
                            )

                        dimensions = [
                            ("清晰", result.get("score_sharpness", 0), 20),
                            ("构图", result.get("score_composition", 0), 20),
                            ("光线", result.get("score_lighting", 0), 20),
                            ("背景", result.get("score_background", 0), 15),
                            ("姿态", result.get("score_pose", 0), 15),
                            ("艺术", result.get("score_artistry", 0), 10),
                        ]
                        bars_html = ""
                        for dim_name, dim_score, dim_max in dimensions:
                            percentage = (dim_score / dim_max * 100) if dim_max > 0 else 0
                            if percentage >= 85:
                                bar_color = "#34c759"
                            elif percentage >= 70:
                                bar_color = "#007aff"
                            elif percentage >= 50:
                                bar_color = "#ff9500"
                            else:
                                bar_color = "#ff3b30"
                            bars_html += (
                                f'<div style="display:flex; align-items:center; margin:2px 0; font-size:11px;">'
                                f'<span style="width:28px; color:#86868b; font-weight:500; flex-shrink:0;">{dim_name}</span>'
                                f'<div style="flex:1; height:6px; background:rgba(0,0,0,0.06); border-radius:3px; margin:0 4px; overflow:hidden;">'
                                f'<div style="width:{percentage}%; height:100%; background:{bar_color}; border-radius:3px;"></div></div>'
                                f'<span style="width:32px; text-align:right; color:#1d1d1f; font-weight:600; font-size:11px;">{dim_score}/{dim_max}</span>'
                                f'</div>'
                            )
                        st.markdown(
                            f'<div style="background:rgba(0,0,0,0.02); border-radius:10px; padding:8px 10px; margin-top:6px;">'
                            f'{bars_html}</div>',
                            unsafe_allow_html=True,
                        )

                        score_comment = result.get("score_comment", "")
                        if score_comment:
                            st.markdown(
                                f'<div style="font-size:12px; color:#6e6e73; font-style:italic; '
                                f'margin-top:6px; padding:6px 8px; background:rgba(0,0,0,0.03); '
                                f'border-radius:8px;">💬 {score_comment}</div>',
                                unsafe_allow_html=True,
                            )

            # 下载区域
            if "zip_bytes" in st.session_state:
                st.markdown('<div class="results-divider"></div>', unsafe_allow_html=True)
                st.download_button(
                    label="📦 下载整理后的照片",
                    data=st.session_state["zip_bytes"],
                    file_name="BirdEye_影禽_鸟类照片整理.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

user_nickname = st.session_state["user_nickname"]

# ============================================================
# 历史记录
# ============================================================
if supabase_client and user_nickname:
    st.markdown("<br>", unsafe_allow_html=True)

    # 先处理待删除的记录（确保统计数据和列表都是最新的）
    pending_delete_key = "_pending_delete_record_id"
    if pending_delete_key in st.session_state:
        delete_id = st.session_state.pop(pending_delete_key)
        if delete_record_from_db(delete_id):
            # 清除缓存，确保下次查询拿到最新数据
            fetch_user_history.clear()
            fetch_leaderboard.clear()
            fetch_top_photos.clear()
            st.toast("✅ 已删除", icon="✅")
        else:
            st.toast("⚠️ 删除失败，请检查数据库权限", icon="⚠️")

    # 左右两栏布局：左边排行榜，右边观鸟记录
    leaderboard_col, history_col = st.columns([1, 3], gap="medium")

    # ---- 右栏：我的观鸟记录 ----
    with history_col:
        st.markdown('<p class="section-title">📚 我的观鸟记录</p>', unsafe_allow_html=True)

        # 先查历史记录（一次请求），再从中计算统计数据（省掉一次请求）
        history_records = fetch_user_history(supabase_client, user_nickname)
        user_stats = fetch_user_stats_from_records(history_records)
        if user_stats and user_stats.get("total", 0) > 0:
            hist_stat_cols = st.columns(4, gap="medium")
            hist_stat_data = [
                (str(user_stats["total"]), "累计识别"),
                (str(user_stats["species"]), "鸟种数"),
                (str(user_stats["avg_score"]), "平均分"),
                (str(user_stats["best_score"]), "最高分"),
            ]
            for col, (value, label) in zip(hist_stat_cols, hist_stat_data):
                with col:
                    st.markdown(
                        f'<div class="stat-card">'
                        f'<div class="stat-value">{value}</div>'
                        f'<div class="stat-label">{label}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("<br>", unsafe_allow_html=True)

        # 历史记录列表（已在上方查询过）
        if history_records:
            with st.expander(f"查看全部历史记录（{len(history_records)} 条）", expanded=True):
                for row_start in range(0, len(history_records), 4):
                    row_items = history_records[row_start:row_start + 4]
                    hist_cols = st.columns(4)
                    for col_idx, record in enumerate(row_items):
                        with hist_cols[col_idx]:
                            # 缩略图（直接用 HTML img 渲染 base64，避免 st.image 开销）
                            thumb_b64 = record.get("thumbnail_base64", "")
                            if thumb_b64:
                                st.markdown(
                                    f'<img src="data:image/jpeg;base64,{thumb_b64}" '
                                    f'style="width:100%; border-radius:10px; object-fit:contain;" '
                                    f'loading="lazy" alt="bird">',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    '<div style="height:80px; background:rgba(0,0,0,0.04); '
                                    'border-radius:10px; display:flex; align-items:center; '
                                    'justify-content:center; color:#86868b; font-size:20px;">🐦</div>',
                                    unsafe_allow_html=True,
                                )

                            # 鸟名和评分
                            hist_score = record.get("score", 0)
                            hist_score_color = get_score_color(hist_score)
                            st.markdown(
                                f'<p style="font-size:13px; font-weight:600; color:#1d1d1f; '
                                f'margin:4px 0 2px; line-height:1.2;">{record.get("chinese_name", "未知")}</p>'
                                f'<span class="score-pill score-{hist_score_color}" '
                                f'style="font-size:11px; padding:2px 8px;">'
                                f'{get_score_emoji(hist_score)} {hist_score}</span>',
                                unsafe_allow_html=True,
                            )

                            # 日期
                            created_at = record.get("created_at", "")
                            if created_at:
                                try:
                                    date_display = created_at[:10]
                                    st.markdown(
                                        f'<p style="font-size:11px; color:#86868b; margin:2px 0 8px;">'
                                        f'📅 {date_display}</p>',
                                        unsafe_allow_html=True,
                                    )
                                except Exception:
                                    pass

                            # 删除按钮
                            record_id = record.get("id")
                            if record_id:
                                if st.button("🗑️", key=f"del_{record_id}",
                                             help="删除这条记录",
                                             use_container_width=True):
                                    st.session_state[pending_delete_key] = record_id
                                    st.rerun()
        else:
            st.markdown(
                '<p style="text-align:center; color:#86868b; font-size:14px; padding:20px 0;">'
                '还没有识别记录，上传照片开始你的观鸟之旅吧 🐦</p>',
                unsafe_allow_html=True,
            )

    # ---- 左栏：观鸟排行榜 ----
    with leaderboard_col:
        # 排行榜头部（与 hero 同色系渐变）
        st.markdown(
            '<div class="leaderboard-header">'
            '<p class="leaderboard-header-title">🏆 排行榜</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        leaderboard = fetch_leaderboard()
        if leaderboard:
            items_html = ""
            for rank, entry in enumerate(leaderboard, 1):
                if rank == 1:
                    rank_html = '<span class="leaderboard-rank">🥇</span>'
                elif rank == 2:
                    rank_html = '<span class="leaderboard-rank">🥈</span>'
                elif rank == 3:
                    rank_html = '<span class="leaderboard-rank">🥉</span>'
                else:
                    rank_html = f'<span class="leaderboard-rank-num">{rank}</span>'

                is_current_user = entry["nickname"] == user_nickname
                item_class = "leaderboard-item leaderboard-item-current" if is_current_user else "leaderboard-item"
                name_class = "leaderboard-name leaderboard-name-current" if is_current_user else "leaderboard-name"

                items_html += (
                    f'<div class="{item_class}">'
                    f'{rank_html}'
                    f'<div style="flex:1;min-width:0;">'
                    f'<p class="{name_class}">{entry["nickname"]}</p>'
                    f'<p class="leaderboard-stats">'
                    f'🐦 {entry["species"]}种 · 📷 {entry["total"]}张 · ⭐ {entry["avg_score"]}</p>'
                    f'</div>'
                    f'</div>'
                )

            st.markdown(
                f'<div class="leaderboard-body">{items_html}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="leaderboard-body">'
                '<p style="text-align:center; color:#86868b; font-size:13px; padding:20px 0;">'
                '暂无排行数据</p>'
                '</div>',
                unsafe_allow_html=True,
            )


# ============================================================
# 页脚
# ============================================================
st.markdown(
    '<div class="app-footer">'
    '影禽 BirdEye · Powered by 通义千问 · '
    'Made with ❤️'
    '</div>',
    unsafe_allow_html=True,
)
