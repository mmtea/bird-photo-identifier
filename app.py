import streamlit as st
import os
import io
import re
import json
import base64
import hashlib
import zipfile
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ExifTags
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* 全局字体和背景 */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display',
                     'SF Pro Text', 'Helvetica Neue', Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
    }
    .stApp {
        background: linear-gradient(180deg, #f5f5f7 0%, #ffffff 100%);
    }

    /* 隐藏 Streamlit 默认元素 */
    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none; }

    /* 主标题区域 - 左文字右猛禽 */
    .hero-section {
        text-align: left;
        padding: 2rem 3rem 1.5rem;
        position: relative;
        overflow: hidden;
        border-radius: 0 0 32px 32px;
        background: linear-gradient(135deg, #f5f5f7 0%, #e8e8ed 50%, rgba(200,200,210,0.6) 100%);
        margin-bottom: 4px;
        min-height: 160px;
    }
    .hero-section::after {
        content: '';
        position: absolute;
        right: -20px;
        top: 50%;
        transform: translateY(-50%);
        width: 300px;
        height: 300px;
        background: url('https://images.unsplash.com/photo-1611689342806-0f0e9395e0e1?w=800&q=80') center/cover no-repeat;
        border-radius: 50%;
        opacity: 0.35;
        mask-image: radial-gradient(circle, black 40%, transparent 75%);
        -webkit-mask-image: radial-gradient(circle, black 40%, transparent 75%);
        pointer-events: none;
    }
    .hero-icon {
        font-size: 56px;
        margin-bottom: 4px;
        display: block;
        filter: drop-shadow(0 4px 12px rgba(0,0,0,0.15));
    }
    .hero-title {
        font-size: 42px;
        font-weight: 700;
        letter-spacing: -0.03em;
        color: #1d1d1f;
        margin: 0;
        line-height: 1.1;
        position: relative;
        z-index: 1;
    }
    .hero-subtitle {
        font-size: 16px;
        font-weight: 400;
        color: #6e6e73;
        margin-top: 6px;
        letter-spacing: -0.01em;
        position: relative;
        z-index: 1;
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
        padding: 12px 0 8px;
        color: #86868b;
        font-size: 13px;
        letter-spacing: -0.01em;
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


def identify_bird(image_base64: str, api_key: str, exif_info: dict) -> dict:
    """使用通义千问多模态模型识别鸟类并进行专业摄影评分"""
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 构建地理位置和季节辅助信息
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

    # 构建详细的地理+季节约束
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
            "例如：如果拍摄于冬季的杭州，则排除仅在东北繁殖且不在华东越冬的鸟种；"
            "如果拍摄于夏季的北京，则排除仅在南方分布的留鸟。\n"
            "候鸟的季节性分布尤其重要：夏候鸟只在繁殖季出现，冬候鸟只在越冬季出现，"
            "旅鸟只在迁徙季短暂停留。"
        )

    response = client.chat.completions.create(
        model="qwen-vl-max",
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
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "请完成以下两个任务：\n\n"
                            "## 任务一：鸟种识别（聚焦中国鸟类）\n"
                            "这些照片均拍摄于中国境内，请在中国有分布记录的鸟种范围内进行识别。\n"
                            "仔细观察以下特征来精确识别：\n"
                            "- 体型大小和比例（与麻雀/鸽子/乌鸦等常见鸟对比）\n"
                            "- 喙的形状、长度、粗细和颜色\n"
                            "- 头部特征（冠羽、眉纹、贯眼纹、眼圈颜色）\n"
                            "- 上体和下体羽色、翼斑、腰色、尾羽形状和颜色\n"
                            "- 腿脚颜色\n"
                            "- 注意区分中国常见的易混淆种（如各种柳莺、鹀、鸫、鹟等）\n"
                            "- 结合栖息环境（水域/林地/草地/城市等）辅助判断\n\n"
                            "## 任务二：鸟的位置标注\n"
                            "请估算鸟在图片中的位置，用百分比坐标表示边界框 [x1, y1, x2, y2]：\n"
                            "- x1, y1 是鸟所在区域左上角的坐标（占图片宽高的百分比，0-100）\n"
                            "- x2, y2 是鸟所在区域右下角的坐标（占图片宽高的百分比，0-100）\n"
                            "- 边界框应紧密包围整只鸟（包括尾羽和脚），但不要留太多空白\n"
                            "- 如果图片中有多只鸟，标注最显眼/最大的那只\n\n"
                            "## 任务三：专业摄影评分\n"
                            "以国际鸟类摄影大赛的标准严格评分。\n\n"
                            "**【核心评分方法 - 必须严格遵守】**\n"
                            "每个维度从该维度满分的50%（即中位数）开始，然后根据优缺点加减分：\n"
                            "- 有明显优点：+1到+3分\n"
                            "- 有明显缺点：-1到-5分\n"
                            "- 有严重缺陷：直接降到该维度满分的20%以下\n"
                            "- 只有极其出色才能超过该维度满分的80%\n\n"
                            "**各维度起始分和评判标准：**\n\n"
                            "**1. 主体清晰度（0-20分，起始10分）**\n"
                            "- 鸟眼是否锐利合焦？是+2，否-3\n"
                            "- 羽毛细节是否可见？纤毫毕现+3，模糊-3\n"
                            "- 有无运动模糊？无+1，有-2到-4\n"
                            "- 16分以上要求：鸟眼极锐+羽毛纤维可见+零噪点\n\n"
                            "**2. 构图与美感（0-20分，起始10分）**\n"
                            "- 主体是否居中无变化？是-2（构图平庸）\n"
                            "- 是否运用三分法/黄金分割？是+2\n"
                            "- 留白是否恰当？恰当+1，过多/过少-2\n"
                            "- 主体是否被裁切？是-3到-5\n"
                            "- 16分以上要求：构图有创意+视觉冲击力强\n\n"
                            "**3. 光线与色彩（0-20分，起始10分）**\n"
                            "- 是否黄金时段光线？是+3，正午顶光-2，阴天平光-1\n"
                            "- 曝光是否准确？准确+1，过曝/欠曝-3\n"
                            "- 色彩是否自然饱满？是+1，偏色-2\n"
                            "- 16分以上要求：完美光线+眼神光+色彩层次丰富\n\n"
                            "**4. 背景与环境（0-15分，起始7分）**\n"
                            "- 背景是否干净虚化？奶油虚化+3，轻微杂乱-1，严重杂乱-3\n"
                            "- 有无干扰元素（电线/垃圾/人工物）？有-2到-4\n"
                            "- 12分以上要求：背景完美虚化+色调和谐+衬托主体\n\n"
                            "**5. 姿态与瞬间（0-15分，起始7分）**\n"
                            "- 是否捕捉到行为瞬间（展翅/捕食/求偶）？是+3到+5\n"
                            "- 普通静立？维持7分不加分\n"
                            "- 背对/缩头/遮挡？-2到-4\n"
                            "- 12分以上要求：精彩行为瞬间+眼神交流\n\n"
                            "**6. 艺术性与故事感（0-10分，起始3分）**\n"
                            "- 注意：大多数照片艺术性只有2-4分！\n"
                            "- 纯记录照：2-3分\n"
                            "- 有一定氛围感：4-5分\n"
                            "- 有意境和情感：6-7分\n"
                            "- 8分以上要求：强烈情感共鸣+叙事性+可作为艺术品\n\n"
                            "**总分分布预期（你必须遵守）：**\n"
                            "- 90+：百里挑一的杰作，你每100张照片最多给1张90+\n"
                            "- 75-89：优秀作品，约占10%\n"
                            "- 55-74：普通到良好，大多数照片应在此区间\n"
                            "- 40-54：有明显不足\n"
                            "- 40以下：质量很差\n\n"
                            "**反作弊检查：打分完成后自查，如果总分>80，请重新审视每个分项，"
                            "确认是否每个维度都真的达到了该分数对应的严格标准。"
                            "如果不确定，宁可降低2-3分。**\n\n"
                            "只返回一个 JSON 对象，不要返回其他内容。\n"
                            "【重要】下面是 JSON 格式模板，其中的数值仅为格式示意，"
                            "你必须根据实际照片独立评判每个分项，严禁照抄模板中的数值！\n"
                            "{\n"
                            '  "chinese_name": "填写实际识别的中文种名",\n'
                            '  "english_name": "填写实际识别的英文种名",\n'
                            '  "order_chinese": "填写实际的目中文名",\n'
                            '  "order_english": "填写实际的目英文名",\n'
                            '  "family_chinese": "填写实际的科中文名",\n'
                            '  "family_english": "填写实际的科英文名",\n'
                            '  "confidence": "根据实际判断填 high/medium/low",\n'
                            '  "identification_basis": "根据实际观察填写识别依据（20字以内）",\n'
                            '  "bird_description": "根据识别出的鸟种填写详细介绍（100-150字），包括外形特点、生活习性、栖息生境、全球分布、在中国的常见程度",\n'
                            '  "bird_bbox": [x1, y1, x2, y2],\n'
                            '  "score": 0,\n'
                            '  "score_sharpness": 0,\n'
                            '  "score_composition": 0,\n'
                            '  "score_lighting": 0,\n'
                            '  "score_background": 0,\n'
                            '  "score_pose": 0,\n'
                            '  "score_artistry": 0,\n'
                            '  "score_comment": "根据实际照片填写点评（30字以内）"\n'
                            "}\n\n"
                            "要求：\n"
                            "1. 必须精确到具体鸟种，目和科使用正确分类学名称\n"
                            "2. 如果无法识别，chinese_name 填 \"未知鸟类\"\n"
                            "3. score 必须等于6个分项之和\n"
                            "4. 每个分项必须根据照片实际情况独立评判，不同照片的分数应有明显差异\n"
                            "5. 严禁所有分项都给相同或相近的分数，必须体现照片各维度的真实差异\n"
                            "6. bird_description 必须是专业准确的鸟类学知识，内容丰富有趣"
                            f"{context_block}"
                        ),
                    },
                ],
            }
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
# 主界面 - Hero Section
# ============================================================
st.markdown("""
<div class="hero-section">
    <span class="hero-icon">🦅</span>
    <h1 class="hero-title">影禽</h1>
    <p class="hero-subtitle">BirdEye · 智能鸟类识别 · 摄影评分 · 分类整理</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# API Key（从 Streamlit Secrets 或环境变量读取，用户无需输入）
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

# ============================================================
# 上传区域
# ============================================================
st.markdown('<p class="section-title">上传照片</p>', unsafe_allow_html=True)
st.markdown(
    f'<p class="section-subtitle">支持 JPG、PNG、HEIC、TIFF、BMP、WebP 及 RAW 格式（ARW/CR2/NEF/DNG 等），每次最多 {MAX_PHOTOS_PER_SESSION} 张</p>',
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
        st.warning(f"每次最多识别 {MAX_PHOTOS_PER_SESSION} 张照片，已自动截取前 {MAX_PHOTOS_PER_SESSION} 张。")
        uploaded_files = uploaded_files[:MAX_PHOTOS_PER_SESSION]

    st.markdown(
        f'<p style="font-size:15px; color:#86868b; margin:8px 0 16px;">已选择 <b style="color:#1d1d1f;">'
        f'{len(uploaded_files)}</b> 张照片，上传完成后将自动开始识别</p>',
        unsafe_allow_html=True,
    )

# ============================================================
# 上传后自动识别
# ============================================================
if uploaded_files and api_key:
    # 初始化单文件级别的缓存字典：file_unique_key -> result item
    if "identified_cache" not in st.session_state:
        st.session_state["identified_cache"] = {}

    # 用文件名+大小作为轻量级唯一标识（避免对大文件算 MD5 导致卡顿）
    def make_file_key(uploaded_file):
        return f"{uploaded_file.name}_{uploaded_file.size}"

    # 找出本次上传中尚未识别的新文件
    current_file_keys = set()
    new_files = []
    for uploaded_file in uploaded_files:
        fkey = make_file_key(uploaded_file)
        current_file_keys.add(fkey)
        if fkey not in st.session_state["identified_cache"]:
            new_files.append(uploaded_file)

    # 只对新文件进行识别（增量识别）
    if new_files:
        progress_bar = st.progress(0, text="正在识别新照片...")

        for idx, uploaded_file in enumerate(new_files):
            fkey = make_file_key(uploaded_file)
            progress_text = f"正在识别 [{idx + 1}/{len(new_files)}]: {uploaded_file.name}"
            progress_bar.progress(idx / len(new_files), text=progress_text)

            image_bytes = uploaded_file.getvalue()
            suffix = Path(uploaded_file.name).suffix.lower()

            # 提取 EXIF（传入文件名以支持 RAW 格式）
            exif_info = extract_exif_info(image_bytes, uploaded_file.name)

            # 逆地理编码：将 GPS 坐标转换为地名，帮助 AI 更准确识别
            if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
                geocoded_location = reverse_geocode(exif_info["gps_lat"], exif_info["gps_lon"])
                if geocoded_location:
                    exif_info["geocoded_location"] = geocoded_location

            # AI 识别（传入文件名以支持 RAW 格式）
            image_base64 = encode_image_to_base64(image_bytes, filename=uploaded_file.name)
            result = identify_bird(image_base64, api_key, exif_info)

            # 拍摄日期
            shoot_date = ""
            if exif_info.get("shoot_time"):
                shoot_date = exif_info["shoot_time"][:8]
            result["shoot_date"] = shoot_date
            result["original_name"] = uploaded_file.name

            # 缓存到 session_state，下次不再重复识别
            st.session_state["identified_cache"][fkey] = {
                "result": result,
                "image_bytes": image_bytes,
                "suffix": suffix,
            }

        progress_bar.progress(1.0, text=f"✅ 新增 {len(new_files)} 张识别完成！")

    # 按当前上传文件的顺序，从缓存中组装完整结果列表
    results_with_bytes = []
    for uploaded_file in uploaded_files:
        fkey = make_file_key(uploaded_file)
        if fkey in st.session_state["identified_cache"]:
            results_with_bytes.append(st.session_state["identified_cache"][fkey])

    # 生成 ZIP（每次都重新生成，因为文件组合可能变化）
    if results_with_bytes:
        zip_bytes = create_organized_zip(results_with_bytes)
        st.session_state["results_with_bytes"] = results_with_bytes
        st.session_state["zip_bytes"] = zip_bytes


# ============================================================
# 展示结果
# ============================================================
if "results_with_bytes" in st.session_state:
    results_with_bytes = st.session_state["results_with_bytes"]
    results = [item["result"] for item in results_with_bytes]

    st.markdown('<div id="results-anchor"></div>', unsafe_allow_html=True)
    st.markdown('<p class="section-title">识别结果</p>', unsafe_allow_html=True)

    # 自动滚动到结果区域
    import streamlit.components.v1 as components
    components.html(
        '<script>parent.document.getElementById("results-anchor").scrollIntoView({behavior:"smooth"});</script>',
        height=0,
    )

    # 汇总统计 - Apple 风格卡片
    scores = [r["score"] for r in results if r.get("score")]
    if scores:
        species_set = set(r["chinese_name"] for r in results)
        avg_score = sum(scores) / len(scores)
        best_score = max(scores)

        stat_cols = st.columns(4, gap="medium")
        stat_data = [
            (str(len(results)), "照片"),
            (f"{len(species_set)}", "鸟种"),
            (f"{avg_score:.1f}", "平均分"),
            (f"{best_score}", "最高分"),
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

    st.markdown("<br>", unsafe_allow_html=True)

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

    st.markdown("<br>", unsafe_allow_html=True)

    # 逐张展示 - 一行4个卡片网格
    for row_start in range(0, len(results_with_bytes), 4):
        row_items = results_with_bytes[row_start:row_start + 4]
        card_cols = st.columns(4)

        for col_idx, item in enumerate(row_items):
            result = item["result"]
            image_bytes = item["image_bytes"]

            score = result.get("score", 0)
            score_color = get_score_color(score)
            score_emoji = get_score_emoji(score)
            confidence = result.get("confidence", "low")

            with card_cols[col_idx]:
                # 照片（支持 RAW 格式预览 + 聚焦到鸟）
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

                # 鸟种名称 + 评分
                st.markdown(
                    f'<p class="bird-name">{result.get("chinese_name", "未知")}</p>'
                    f'<p class="bird-name-en">{result.get("english_name", "")}</p>',
                    unsafe_allow_html=True,
                )

                # 分类标签 + 评分徽章
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

                # 识别依据
                basis = result.get("identification_basis", "")
                if basis:
                    st.markdown(
                        f'<div style="font-size:12px; color:#6e6e73; margin-top:6px;">'
                        f'<b style="color:#86868b;">识别依据</b> {basis}</div>',
                        unsafe_allow_html=True,
                    )

                # 鸟类介绍（折叠展示，避免卡片过长）
                bird_desc = result.get("bird_description", "")
                if bird_desc:
                    with st.expander("🐦 鸟类介绍"):
                        st.markdown(
                            f'<div style="font-size:12px; color:#3a3a3c; line-height:1.7;">'
                            f'{bird_desc}</div>',
                            unsafe_allow_html=True,
                        )

                # 拍摄日期
                shoot_date = result.get("shoot_date", "")
                if shoot_date and len(shoot_date) >= 8:
                    formatted_date = f"{shoot_date[:4]}.{shoot_date[4:6]}.{shoot_date[6:8]}"
                    st.markdown(
                        f'<div style="font-size:12px; color:#86868b; margin-top:4px;">'
                        f'📅 {formatted_date}</div>',
                        unsafe_allow_html=True,
                    )

                # 分项评分条形图（紧凑版）
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

                # 点评
                score_comment = result.get("score_comment", "")
                if score_comment:
                    st.markdown(
                        f'<div style="font-size:12px; color:#6e6e73; font-style:italic; '
                        f'margin-top:6px; padding:6px 8px; background:rgba(0,0,0,0.03); '
                        f'border-radius:8px;">💬 {score_comment}</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown("<hr>", unsafe_allow_html=True)

    # ============================================================
    # 下载区域
    # ============================================================
    st.markdown('<p class="section-title">下载整理</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-subtitle">'
        '照片已按 目 / 科 层级分文件夹整理，并重命名为 鸟名_时间_评分 格式'
        '</p>',
        unsafe_allow_html=True,
    )

    dl_col_left, dl_col_center, dl_col_right = st.columns([1, 2, 1])
    with dl_col_center:
        if "zip_bytes" in st.session_state:
            st.download_button(
                label="下载整理后的照片",
                data=st.session_state["zip_bytes"],
                file_name="BirdEye_影禽_鸟类照片整理.zip",
                mime="application/zip",
                use_container_width=True,
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
