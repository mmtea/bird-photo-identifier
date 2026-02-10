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

    /* 主标题区域 - 带背景图 */
    .hero-section {
        text-align: center;
        padding: 4rem 1rem 3rem;
        position: relative;
        overflow: hidden;
        border-radius: 0 0 32px 32px;
        background:
            linear-gradient(180deg, rgba(245,245,247,0.85) 0%, rgba(255,255,255,0.92) 100%),
            url('https://images.unsplash.com/photo-1444464666168-49d633b86797?w=1920&q=80') center/cover no-repeat;
        margin-bottom: 8px;
    }
    .hero-icon {
        font-size: 96px;
        margin-bottom: 12px;
        display: block;
        filter: drop-shadow(0 4px 12px rgba(0,0,0,0.15));
    }
    .hero-title {
        font-size: 56px;
        font-weight: 700;
        letter-spacing: -0.03em;
        color: #1d1d1f;
        margin: 0;
        line-height: 1.1;
    }
    .hero-subtitle {
        font-size: 20px;
        font-weight: 400;
        color: #6e6e73;
        margin-top: 12px;
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
    """使用通义千问多模态模型识别鸟类并进行专业摄影评分"""
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 构建季节辅助信息
    context_block = ""
    if exif_info.get("shoot_time"):
        raw_time = exif_info["shoot_time"]
        month_str = raw_time[4:6] if len(raw_time) >= 6 else ""
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
            context_block = f"\n\n【辅助信息】拍摄时间：{raw_time}，季节：{season}"

    if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
        context_block += f"\nGPS 坐标：纬度 {exif_info['gps_lat']:.4f}，经度 {exif_info['gps_lon']:.4f}"
        context_block += "\n请结合该地区该季节的鸟种分布辅助判断。"

    response = client.chat.completions.create(
        model="qwen-vl-max",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专业的鸟类学家和鸟类摄影评审专家。"
                    "你不仅能精确识别鸟种，还精通鸟类摄影的评判标准。"
                    "你见过大量国际鸟类摄影大赛的获奖作品，对优秀鸟类摄影有极高的审美标准。"
                    "你的评分非常严格，只有真正出色的照片才能获得高分。"
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
                            "## 任务一：鸟种识别\n"
                            "观察鸟的体型、喙、羽毛花纹、眼圈、腿脚颜色等特征，精确识别鸟种。\n\n"
                            "## 任务二：专业摄影评分\n"
                            "以国际鸟类摄影大赛的标准严格评分，6个维度各自独立打分：\n\n"
                            "**1. 主体清晰度（0-20分）**\n"
                            "- 18-20：鸟眼锐利合焦，羽毛纤毫毕现，可见羽小枝细节\n"
                            "- 14-17：整体清晰，眼部合焦，但羽毛细节略有不足\n"
                            "- 10-13：基本清晰但有轻微跑焦或运动模糊\n"
                            "- 5-9：明显模糊，主体不够锐利\n"
                            "- 0-4：严重失焦，主体模糊不清\n\n"
                            "**2. 构图与美感（0-20分）**\n"
                            "- 18-20：构图精妙，主体位置完美，留白恰当，有强烈视觉冲击力\n"
                            "- 14-17：构图合理，主体突出，画面平衡\n"
                            "- 10-13：构图一般，主体居中或略偏，无明显美感\n"
                            "- 5-9：构图较差，主体过小/过偏/被裁切\n"
                            "- 0-4：构图混乱，主体难以辨认\n\n"
                            "**3. 光线与色彩（0-20分）**\n"
                            "- 18-20：光线完美（如黄金时段侧光/逆光轮廓光），色彩饱满自然\n"
                            "- 14-17：光线良好，曝光准确，色彩自然\n"
                            "- 10-13：光线平淡（如正午顶光/阴天），色彩一般\n"
                            "- 5-9：光线较差，过曝/欠曝，色彩失真\n"
                            "- 0-4：严重曝光问题，画面灰暗或过亮\n\n"
                            "**4. 背景与环境（0-15分）**\n"
                            "- 13-15：背景干净柔美（奶油般虚化/纯色），完美衬托主体\n"
                            "- 10-12：背景较好，虚化合理，无明显干扰\n"
                            "- 7-9：背景一般，有轻微杂乱元素\n"
                            "- 4-6：背景杂乱，干扰主体\n"
                            "- 0-3：背景极差，严重影响观感\n\n"
                            "**5. 姿态与瞬间（0-15分）**\n"
                            "- 13-15：捕捉到精彩瞬间（展翅、捕食、求偶、育雏等行为）\n"
                            "- 10-12：姿态优美自然，眼神有神\n"
                            "- 7-9：姿态普通，静立或常见动作\n"
                            "- 4-6：姿态不佳（背对、缩头、遮挡）\n"
                            "- 0-3：几乎看不到完整姿态\n\n"
                            "**6. 艺术性与故事感（0-10分）**\n"
                            "- 9-10：照片有强烈的情感共鸣或叙事性，堪称艺术品\n"
                            "- 7-8：有一定意境或氛围感\n"
                            "- 5-6：记录性照片，缺乏艺术表达\n"
                            "- 3-4：平淡无奇的记录\n"
                            "- 0-2：无任何艺术价值\n\n"
                            "**评分原则：严格按标准打分，拉开差距！**\n"
                            "- 90+分：大赛获奖级别，极为罕见\n"
                            "- 80-89：专业水准，各方面优秀\n"
                            "- 70-79：良好，有明显亮点但也有不足\n"
                            "- 60-69：中等，基本合格的鸟类照片\n"
                            "- 50-59：较差，有明显缺陷\n"
                            "- 50以下：质量很差\n"
                            "大多数普通照片应在 55-75 分之间，不要轻易给高分！\n\n"
                            "只返回一个 JSON 对象，不要返回其他内容：\n"
                            "{\n"
                            '  "chinese_name": "中文种名",\n'
                            '  "english_name": "英文种名",\n'
                            '  "order_chinese": "目的中文名",\n'
                            '  "order_english": "目的英文名",\n'
                            '  "family_chinese": "科的中文名",\n'
                            '  "family_english": "科的英文名",\n'
                            '  "confidence": "high/medium/low",\n'
                            '  "identification_basis": "识别依据（20字以内，说明通过哪些外观特征识别）",\n'
                            '  "bird_description": "该鸟种的详细介绍（100-150字），包括：外形特点（体长、羽色、显著特征）、生活习性（食性、活动规律、叫声特点）、栖息生境（偏好的生态环境类型）、全球分布范围（繁殖地、越冬地、迁徙路线）、在中国的分布和常见程度",\n'
                            '  "score": 72,\n'
                            '  "score_sharpness": 15,\n'
                            '  "score_composition": 14,\n'
                            '  "score_lighting": 13,\n'
                            '  "score_background": 10,\n'
                            '  "score_pose": 12,\n'
                            '  "score_artistry": 8,\n'
                            '  "score_comment": "一句话点评照片的最大亮点和最大不足（30字以内）"\n'
                            "}\n\n"
                            "要求：\n"
                            "1. 必须精确到具体鸟种，目和科使用正确分类学名称\n"
                            "2. 如果无法识别，chinese_name 填 \"未知鸟类\"\n"
                            "3. score 必须等于6个分项之和，严格按标准打分\n"
                            "4. 每个分项必须独立评判，不要所有分项都给相近的分数\n"
                            "5. bird_description 必须是专业准确的鸟类学知识，内容丰富有趣"
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
    f'<p class="section-subtitle">支持 JPG、PNG、HEIC、TIFF、BMP、WebP 格式，每次最多 {MAX_PHOTOS_PER_SESSION} 张</p>',
    unsafe_allow_html=True,
)

uploaded_files = st.file_uploader(
    "拖拽照片到此处，或点击选择文件",
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

    # 预览上传的照片 - 一行4个网格布局
    for row_start in range(0, len(uploaded_files), 4):
        row_files = uploaded_files[row_start:row_start + 4]
        preview_cols = st.columns(4)
        for col_idx, uploaded_file in enumerate(row_files):
            with preview_cols[col_idx]:
                try:
                    img = Image.open(io.BytesIO(uploaded_file.getvalue()))
                    st.image(img, use_container_width=True, caption=uploaded_file.name[:20])
                except Exception:
                    st.text(uploaded_file.name)

# ============================================================
# 上传后自动识别
# ============================================================
if uploaded_files and api_key:
    # 用上传文件的名称列表作为缓存 key，避免重复识别
    file_key = "_".join(sorted(f.name for f in uploaded_files))

    if st.session_state.get("last_file_key") != file_key:
        st.session_state["last_file_key"] = file_key
        st.session_state.pop("results_with_bytes", None)
        st.session_state.pop("zip_bytes", None)

        results_with_bytes = []
        progress_bar = st.progress(0, text="正在识别中...")

        for idx, uploaded_file in enumerate(uploaded_files):
            progress_text = f"正在识别 [{idx + 1}/{len(uploaded_files)}]: {uploaded_file.name}"
            progress_bar.progress((idx) / len(uploaded_files), text=progress_text)

            image_bytes = uploaded_file.getvalue()
            suffix = Path(uploaded_file.name).suffix.lower()

            # 提取 EXIF
            exif_info = extract_exif_info(image_bytes)

            # AI 识别
            image_base64 = encode_image_to_base64(image_bytes)
            result = identify_bird(image_base64, api_key, exif_info)

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

        progress_bar.progress(1.0, text="✅ 识别完成！正在打包...")

        # 自动生成 ZIP
        zip_bytes = create_organized_zip(results_with_bytes)
        st.session_state["results_with_bytes"] = results_with_bytes
        st.session_state["zip_bytes"] = zip_bytes

        progress_bar.progress(1.0, text="✅ 全部完成！")


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
                # 照片
                try:
                    img = Image.open(io.BytesIO(image_bytes))
                    st.image(img, use_container_width=True)
                except Exception:
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
