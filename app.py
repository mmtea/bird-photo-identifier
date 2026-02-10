import streamlit as st
import os
import io
import re
import json
import base64
import zipfile
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ExifTags
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from openai import OpenAI

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="Birdie · 鸟类智能识别",
    page_icon="🪶",
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

    /* 主标题区域 */
    .hero-section {
        text-align: center;
        padding: 3rem 1rem 2rem;
    }
    .hero-icon {
        font-size: 64px;
        margin-bottom: 8px;
        display: block;
    }
    .hero-title {
        font-size: 40px;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #1d1d1f;
        margin: 0;
        line-height: 1.1;
    }
    .hero-subtitle {
        font-size: 18px;
        font-weight: 400;
        color: #86868b;
        margin-top: 8px;
        letter-spacing: -0.01em;
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
        border-radius: 16px;
        padding: 20px;
        text-align: center;
    }
    .stat-value {
        font-size: 32px;
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
        font-size: 24px;
        font-weight: 700;
        color: #1d1d1f;
        letter-spacing: -0.02em;
        margin: 0 0 2px 0;
        line-height: 1.2;
    }
    .bird-name-en {
        font-size: 15px;
        font-weight: 400;
        color: #86868b;
        margin: 0 0 12px 0;
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
        margin: 24px 0;
    }

    /* 图片圆角 */
    .stImage img {
        border-radius: 14px;
    }

    /* 页脚 */
    .app-footer {
        text-align: center;
        padding: 32px 0 16px;
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
        font-size: 28px;
        font-weight: 700;
        color: #1d1d1f;
        letter-spacing: -0.02em;
        margin: 32px 0 16px;
    }
    .section-subtitle {
        font-size: 15px;
        color: #86868b;
        margin-top: -8px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 工具函数
# ============================================================
def encode_image_to_base64(image_bytes: bytes, max_size: int = 1024) -> str:
    """将图片字节编码为 base64 字符串，可选压缩"""
    if HAS_PIL:
        try:
            img = Image.open(io.BytesIO(image_bytes))
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


def extract_exif_info(image_bytes: bytes) -> dict:
    """从照片 EXIF 中提取拍摄时间和 GPS 坐标"""
    result = {"shoot_time": "", "gps_lat": None, "gps_lon": None}
    if not HAS_PIL:
        return result
    try:
        img = Image.open(io.BytesIO(image_bytes))
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
    """使用通义千问多模态模型识别鸟类、评分、判断地点"""
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 构建地理位置和时间的辅助信息
    context_hints = []
    geocoded_name = exif_info.get("geocoded_location", "")
    if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
        gps_text = f"GPS 坐标：纬度 {exif_info['gps_lat']:.6f}，经度 {exif_info['gps_lon']:.6f}"
        if geocoded_name:
            gps_text += f"，解析地名：{geocoded_name}"
        context_hints.append(gps_text)

    if exif_info.get("shoot_time"):
        raw_time = exif_info["shoot_time"]
        month_str = raw_time[4:6] if len(raw_time) >= 6 else ""
        season = ""
        if month_str:
            month = int(month_str)
            if month in (3, 4, 5):
                season = "春季（春迁期）"
            elif month in (6, 7, 8):
                season = "夏季（繁殖期）"
            elif month in (9, 10, 11):
                season = "秋季（秋迁期）"
            else:
                season = "冬季（越冬期）"
        date_text = f"拍摄时间：{raw_time}"
        if season:
            date_text += f"，季节：{season}"
        context_hints.append(date_text)

    context_block = ""
    if context_hints:
        context_block = (
            "\n\n【重要辅助信息 - 请结合以下信息缩小鸟种范围】\n"
            + "\n".join(context_hints)
            + "\n请根据该地区在该季节可能出现的鸟种来辅助判断。"
            "例如：某些鸟是候鸟，只在特定季节出现在特定地区；"
            "某些鸟是留鸟，全年可见但分布有地域限制。"
            "请优先考虑该地区该季节的常见鸟种和已记录鸟种。"
        )

    response = client.chat.completions.create(
        model="qwen-vl-max",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专业的鸟类学家和观鸟专家，拥有丰富的中国鸟类野外辨识经验。"
                    "你熟悉中国各地区各季节的鸟类分布，能够根据鸟的外形特征、"
                    "栖息环境、地理位置和季节来精确识别鸟种。"
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
                            "请作为专业鸟类学家，完成以下任务：\n\n"
                            "## 任务一：鸟种识别\n"
                            "请仔细观察照片中鸟的以下特征来精确识别鸟种：\n"
                            "- 体型大小（与常见鸟类对比）\n"
                            "- 喙的形状、长度和颜色\n"
                            "- 羽毛颜色和花纹（头部、背部、腹部、翅膀、尾羽）\n"
                            "- 眼睛颜色和眼圈特征\n"
                            "- 腿和脚的颜色\n"
                            "- 飞行姿态（如果是飞行照片）\n"
                            "- 栖息环境（水边、树林、草地、城市等）\n"
                            "结合拍摄地点和季节，判断该地区该时间最可能出现的鸟种。\n\n"
                            "## 任务二：摄影评分（满分100分）\n"
                            "- 清晰度与对焦（0-20分）\n"
                            "- 构图与美感（0-20分）\n"
                            "- 光线与曝光（0-15分）\n"
                            "- 背景与环境（0-15分）\n"
                            "- 鸟的姿态与行为（0-15分）\n"
                            "- 稀有度与难度（0-15分）\n\n"
                            "## 任务三：拍摄地点\n"
                            "根据照片环境和GPS信息判断拍摄地点。\n\n"
                            "只需要返回一个 JSON 对象，不要返回其他内容：\n"
                            "{\n"
                            '  "chinese_name": "中文种名",\n'
                            '  "english_name": "英文种名",\n'
                            '  "order_chinese": "目的中文名",\n'
                            '  "order_english": "目的英文名",\n'
                            '  "family_chinese": "科的中文名",\n'
                            '  "family_english": "科的英文名",\n'
                            '  "confidence": "high/medium/low",\n'
                            '  "identification_basis": "识别依据（30字以内）",\n'
                            '  "score": 85,\n'
                            '  "score_detail": "评分理由（30字以内）",\n'
                            '  "location": "拍摄地点"\n'
                            "}\n\n"
                            "要求：\n"
                            "1. 必须精确到具体鸟种\n"
                            "2. 目和科必须使用正确的鸟类分类学名称\n"
                            "3. 如果无法识别，chinese_name 填 \"未知鸟类\"\n"
                            "4. score 必须是 0-100 的整数，严格按标准打分\n"
                            "5. location 尽量精确；无法判断填 \"未知地点\""
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
        raw_score = parsed.get("score", 0)
        parsed["score"] = max(0, min(100, int(raw_score)))
        return parsed

    return {
        "chinese_name": "未知鸟类", "english_name": "unknown",
        "order_chinese": "未知目", "order_english": "Unknown",
        "family_chinese": "未知科", "family_english": "Unknown",
        "confidence": "low", "score": 0,
        "score_detail": "识别失败", "location": "未知地点",
        "identification_basis": "",
    }


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
    location = result.get("location", "")
    if location and location != "未知地点":
        parts.append(sanitize_filename(location))
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
    <span class="hero-icon">🪶</span>
    <h1 class="hero-title">Birdie</h1>
    <p class="hero-subtitle">智能鸟类识别 · 摄影评分 · 分类整理</p>
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
    f'<p class="section-subtitle">支持 JPG、PNG、HEIC、TIFF、BMP、WebP 格式，每次最多 {MAX_PHOTOS_PER_SESSION} 张</p>',
    unsafe_allow_html=True,
)

uploaded_files = st.file_uploader(
    "拖拽或点击上传鸟类照片",
    type=["jpg", "jpeg", "png", "tif", "tiff", "heic", "bmp", "webp"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files:
    if len(uploaded_files) > MAX_PHOTOS_PER_SESSION:
        st.warning(f"每次最多识别 {MAX_PHOTOS_PER_SESSION} 张照片，已自动截取前 {MAX_PHOTOS_PER_SESSION} 张。")
        uploaded_files = uploaded_files[:MAX_PHOTOS_PER_SESSION]

    st.markdown(
        f'<p style="font-size:15px; color:#86868b; margin:8px 0 16px;">已选择 <b style="color:#1d1d1f;">'
        f'{len(uploaded_files)}</b> 张照片</p>',
        unsafe_allow_html=True,
    )

    # 预览上传的照片 - 网格布局
    num_preview = min(len(uploaded_files), 8)
    preview_cols = st.columns(min(num_preview, 4))
    for idx in range(num_preview):
        with preview_cols[idx % 4]:
            try:
                img = Image.open(io.BytesIO(uploaded_files[idx].getvalue()))
                st.image(img, use_container_width=True)
            except Exception:
                st.text(uploaded_files[idx].name)
    if len(uploaded_files) > 8:
        st.caption(f"还有 {len(uploaded_files) - 8} 张照片未展示")

# ============================================================
# 识别按钮
# ============================================================
if uploaded_files and api_key:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("开始识别", type="primary", use_container_width=True):
        results_with_bytes = []
        progress_bar = st.progress(0, text="准备中...")

        for idx, uploaded_file in enumerate(uploaded_files):
            progress_text = f"正在识别 [{idx + 1}/{len(uploaded_files)}]: {uploaded_file.name}"
            progress_bar.progress((idx) / len(uploaded_files), text=progress_text)

            image_bytes = uploaded_file.getvalue()
            suffix = Path(uploaded_file.name).suffix.lower()

            # 提取 EXIF
            exif_info = extract_exif_info(image_bytes)

            # 逆地理编码
            geocoded_location = ""
            if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
                geocoded_location = reverse_geocode(exif_info["gps_lat"], exif_info["gps_lon"])
                if geocoded_location:
                    exif_info["geocoded_location"] = geocoded_location

            # AI 识别
            image_base64 = encode_image_to_base64(image_bytes)
            result = identify_bird(image_base64, api_key, exif_info)

            # 地点优先级：GPS逆地理编码 > AI识别
            ai_location = result.get("location", "未知地点")
            if geocoded_location:
                result["location"] = geocoded_location
                result["location_source"] = "GPS逆地理编码"
            elif ai_location and ai_location != "未知地点":
                result["location_source"] = "AI识别"
            else:
                result["location_source"] = "无法判断"

            # 拍摄日期
            shoot_date = ""
            if exif_info.get("shoot_time"):
                shoot_date = exif_info["shoot_time"][:8]
            result["shoot_date"] = shoot_date
            result["original_name"] = uploaded_file.name

            results_with_bytes.append({
                "result": result,
                "image_bytes": image_bytes,
                "suffix": suffix,
            })

        progress_bar.progress(1.0, text="✅ 识别完成！")

        # 保存到 session_state
        st.session_state["results_with_bytes"] = results_with_bytes


# ============================================================
# 展示结果
# ============================================================
if "results_with_bytes" in st.session_state:
    results_with_bytes = st.session_state["results_with_bytes"]
    results = [item["result"] for item in results_with_bytes]

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="section-title">识别结果</p>', unsafe_allow_html=True)

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

    # 逐张展示 - Apple 风格卡片
    for idx, item in enumerate(results_with_bytes):
        result = item["result"]
        image_bytes = item["image_bytes"]

        score = result.get("score", 0)
        score_color = get_score_color(score)
        score_emoji = get_score_emoji(score)
        confidence = result.get("confidence", "low")

        col_img, col_spacer, col_info = st.columns([1, 0.1, 2])

        with col_img:
            try:
                img = Image.open(io.BytesIO(image_bytes))
                st.image(img, use_container_width=True)
            except Exception:
                st.text("无法预览")

        with col_info:
            # 鸟种名称
            st.markdown(
                f'<p class="bird-name">{result.get("chinese_name", "未知")}</p>'
                f'<p class="bird-name-en">{result.get("english_name", "")}</p>',
                unsafe_allow_html=True,
            )

            # 分类标签 + 评分
            confidence_class = f"confidence-{confidence}"
            st.markdown(
                f'<span class="taxonomy-pill order-pill">{result.get("order_chinese", "")}</span>'
                f'<span class="taxonomy-pill family-pill">{result.get("family_chinese", "")}</span>'
                f'&nbsp;&nbsp;'
                f'<span class="score-pill score-{score_color}">{score_emoji} {score}</span>'
                f'&nbsp;&nbsp;'
                f'<span class="confidence-dot {confidence_class}"></span>'
                f'<span style="font-size:13px; color:#86868b;">{confidence}</span>',
                unsafe_allow_html=True,
            )

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # 信息行
            basis = result.get("identification_basis", "")
            if basis:
                st.markdown(
                    f'<div class="info-row">'
                    f'<span class="label">识别依据</span>'
                    f'<span class="value">{basis}</span></div>',
                    unsafe_allow_html=True,
                )

            location = result.get("location", "未知地点")
            source = result.get("location_source", "")
            source_text = f' <span style="font-size:11px; color:#aeaeb2;">({source})</span>' if source else ""
            st.markdown(
                f'<div class="info-row">'
                f'<span class="label">拍摄地点</span>'
                f'<span class="value">{location}{source_text}</span></div>',
                unsafe_allow_html=True,
            )

            shoot_date = result.get("shoot_date", "")
            if shoot_date and len(shoot_date) >= 8:
                formatted_date = f"{shoot_date[:4]}.{shoot_date[4:6]}.{shoot_date[6:8]}"
                st.markdown(
                    f'<div class="info-row">'
                    f'<span class="label">拍摄日期</span>'
                    f'<span class="value">{formatted_date}</span></div>',
                    unsafe_allow_html=True,
                )

            # 评分理由
            score_detail = result.get("score_detail", "")
            if score_detail:
                st.markdown(
                    f'<div class="score-detail">{score_detail}</div>',
                    unsafe_allow_html=True,
                )

            # 新文件名
            new_name = build_filename(result) + item["suffix"]
            st.markdown(
                f'<p style="font-size:12px; color:#aeaeb2; margin-top:8px;">'
                f'→ {new_name}</p>',
                unsafe_allow_html=True,
            )

        st.markdown("<hr>", unsafe_allow_html=True)

    # ============================================================
    # 下载区域
    # ============================================================
    st.markdown('<p class="section-title">下载整理</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-subtitle">'
        '照片将按 目 / 科 层级分文件夹整理，并重命名为 鸟名_地点_时间_评分 格式'
        '</p>',
        unsafe_allow_html=True,
    )

    dl_col_left, dl_col_center, dl_col_right = st.columns([1, 2, 1])
    with dl_col_center:
        if st.button("生成下载包", use_container_width=True):
            with st.spinner("正在打包整理..."):
                zip_bytes = create_organized_zip(results_with_bytes)
            st.session_state["zip_bytes"] = zip_bytes

        if "zip_bytes" in st.session_state:
            st.download_button(
                label="下载 ZIP",
                data=st.session_state["zip_bytes"],
                file_name="Birdie_鸟类照片整理.zip",
                mime="application/zip",
                use_container_width=True,
            )

    # 导出 JSON
    with st.expander("导出识别结果 (JSON)"):
        results_json = json.dumps(results, ensure_ascii=False, indent=2)
        st.code(results_json, language="json")
        st.download_button(
            label="下载 JSON",
            data=results_json,
            file_name="bird_identification_results.json",
            mime="application/json",
        )

# ============================================================
# 页脚
# ============================================================
st.markdown(
    '<div class="app-footer">'
    'Birdie · Powered by 通义千问 · '
    'Made with ❤️'
    '</div>',
    unsafe_allow_html=True,
)
