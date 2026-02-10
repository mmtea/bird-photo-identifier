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
    page_title="🐦 鸟类照片智能识别",
    page_icon="🐦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 自定义样式
# ============================================================
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
    }
    .score-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        color: white;
        font-size: 14px;
    }
    .score-excellent { background-color: #10b981; }
    .score-good { background-color: #3b82f6; }
    .score-fair { background-color: #f59e0b; }
    .score-poor { background-color: #ef4444; }
    .bird-card {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 16px;
        background: white;
    }
    .taxonomy-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        margin-right: 4px;
    }
    .order-tag { background-color: #dbeafe; color: #1e40af; }
    .family-tag { background-color: #dcfce7; color: #166534; }
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
# 主界面
# ============================================================
st.markdown('<div class="main-header">', unsafe_allow_html=True)
st.title("🐦 鸟类照片智能识别与分类整理")
st.caption("上传鸟类照片，AI 自动识别鸟种、评分、按分类学整理")
st.markdown('</div>', unsafe_allow_html=True)

# ============================================================
# 侧边栏 - 设置
# ============================================================
with st.sidebar:
    st.header("⚙️ 设置")

    api_key = st.text_input(
        "DashScope API Key",
        type="password",
        placeholder="sk-xxxxxxxxxxxxxxxx",
        help="前往 https://dashscope.console.aliyun.com/apiKey 获取",
    )

    if not api_key:
        env_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if env_key:
            api_key = env_key
            st.success("✅ 已从环境变量读取 API Key")

    st.divider()
    st.header("📖 使用说明")
    st.markdown("""
    1. 在上方输入 **DashScope API Key**
    2. 上传鸟类照片（支持批量）
    3. 点击 **开始识别**
    4. 查看识别结果和评分
    5. 下载按「目/科」分类整理的照片
    """)

    st.divider()
    st.markdown("""
    ### 📊 评分标准
    | 维度 | 分值 |
    |------|------|
    | 清晰度与对焦 | 20分 |
    | 构图与美感 | 20分 |
    | 光线与曝光 | 15分 |
    | 背景与环境 | 15分 |
    | 鸟的姿态行为 | 15分 |
    | 稀有度与难度 | 15分 |
    """)

# ============================================================
# 上传区域
# ============================================================
st.header("📤 上传照片")

uploaded_files = st.file_uploader(
    "拖拽或点击上传鸟类照片（支持 JPG/PNG/HEIC/TIFF/BMP/WebP）",
    type=["jpg", "jpeg", "png", "tif", "tiff", "heic", "bmp", "webp"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"📷 已选择 **{len(uploaded_files)}** 张照片")

    # 预览上传的照片
    preview_cols = st.columns(min(len(uploaded_files), 6))
    for idx, uploaded_file in enumerate(uploaded_files[:6]):
        with preview_cols[idx % 6]:
            try:
                img = Image.open(io.BytesIO(uploaded_file.getvalue()))
                st.image(img, caption=uploaded_file.name, use_container_width=True)
            except Exception:
                st.text(uploaded_file.name)
    if len(uploaded_files) > 6:
        st.caption(f"... 还有 {len(uploaded_files) - 6} 张照片")

# ============================================================
# 识别按钮
# ============================================================
if uploaded_files and api_key:
    if st.button("🚀 开始识别", type="primary", use_container_width=True):
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

elif uploaded_files and not api_key:
    st.warning("⚠️ 请先在左侧边栏输入 DashScope API Key")

# ============================================================
# 展示结果
# ============================================================
if "results_with_bytes" in st.session_state:
    results_with_bytes = st.session_state["results_with_bytes"]
    results = [item["result"] for item in results_with_bytes]

    st.divider()
    st.header("📊 识别结果")

    # 汇总统计
    scores = [r["score"] for r in results if r.get("score")]
    if scores:
        stat_cols = st.columns(4)
        with stat_cols[0]:
            st.metric("📷 照片总数", len(results))
        with stat_cols[1]:
            species = set(r["chinese_name"] for r in results)
            st.metric("🐦 识别鸟种", f"{len(species)} 种")
        with stat_cols[2]:
            avg_score = sum(scores) / len(scores)
            st.metric("📊 平均评分", f"{avg_score:.1f}")
        with stat_cols[3]:
            best = max(scores)
            st.metric("🌟 最高评分", f"{best}")

    # 评分分布
    if scores:
        with st.expander("📈 评分分布", expanded=False):
            excellent = sum(1 for s in scores if s >= 90)
            good = sum(1 for s in scores if 75 <= s < 90)
            fair = sum(1 for s in scores if 60 <= s < 75)
            poor = sum(1 for s in scores if s < 60)

            dist_cols = st.columns(4)
            with dist_cols[0]:
                st.metric("🌟 优秀 (≥90)", excellent)
            with dist_cols[1]:
                st.metric("⭐ 良好 (75-89)", good)
            with dist_cols[2]:
                st.metric("👍 一般 (60-74)", fair)
            with dist_cols[3]:
                st.metric("📷 待提升 (<60)", poor)

    # 分类统计
    taxonomy = {}
    for result in results:
        order = result.get("order_chinese", "未知目")
        family = result.get("family_chinese", "未知科")
        species = result["chinese_name"]
        taxonomy.setdefault(order, {}).setdefault(family, set())
        taxonomy[order][family].add(species)

    with st.expander("🔬 分类学统计", expanded=False):
        for order, families in sorted(taxonomy.items()):
            st.markdown(f"**📗 {order}**")
            for family, species_set in sorted(families.items()):
                species_list = ", ".join(sorted(species_set))
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;📘 {family}: {species_list}")

    st.divider()

    # 逐张展示
    for idx, item in enumerate(results_with_bytes):
        result = item["result"]
        image_bytes = item["image_bytes"]

        score = result.get("score", 0)
        score_color = get_score_color(score)
        score_emoji = get_score_emoji(score)
        confidence = result.get("confidence", "low")
        confidence_emoji = get_confidence_emoji(confidence)

        col_img, col_info = st.columns([1, 2])

        with col_img:
            try:
                img = Image.open(io.BytesIO(image_bytes))
                st.image(img, use_container_width=True)
            except Exception:
                st.text("无法预览")
            st.caption(f"📄 {result.get('original_name', '')}")

        with col_info:
            # 鸟种名称和评分
            name_col, score_col = st.columns([3, 1])
            with name_col:
                st.subheader(f"{result.get('chinese_name', '未知')} ({result.get('english_name', '')})")
            with score_col:
                st.markdown(
                    f'<span class="score-badge score-{score_color}">'
                    f'{score_emoji} {score}/100</span>',
                    unsafe_allow_html=True,
                )

            # 分类信息
            st.markdown(
                f'<span class="taxonomy-tag order-tag">{result.get("order_chinese", "")}</span>'
                f'<span class="taxonomy-tag family-tag">{result.get("family_chinese", "")}</span>'
                f'&nbsp;&nbsp;{confidence_emoji} 置信度: {confidence}',
                unsafe_allow_html=True,
            )

            # 详细信息
            detail_cols = st.columns(3)
            with detail_cols[0]:
                basis = result.get("identification_basis", "")
                if basis:
                    st.markdown(f"🔎 **识别依据**: {basis}")
            with detail_cols[1]:
                location = result.get("location", "未知地点")
                source = result.get("location_source", "")
                st.markdown(f"📍 **地点**: {location}")
                if source:
                    st.caption(f"来源: {source}")
            with detail_cols[2]:
                shoot_date = result.get("shoot_date", "")
                if shoot_date and len(shoot_date) >= 8:
                    formatted_date = f"{shoot_date[:4]}-{shoot_date[4:6]}-{shoot_date[6:8]}"
                    st.markdown(f"📅 **日期**: {formatted_date}")

            # 评分理由
            score_detail = result.get("score_detail", "")
            if score_detail:
                st.markdown(f"💬 {score_detail}")

            # 新文件名预览
            new_name = build_filename(result) + item["suffix"]
            st.caption(f"📝 重命名为: `{new_name}`")

        st.divider()

    # ============================================================
    # 下载按钮
    # ============================================================
    st.header("📥 下载整理后的照片")
    st.markdown("照片将按 **目/科** 层级分文件夹整理，并重命名为 `鸟名_地点_时间_评分.jpg` 格式。")

    if st.button("📦 生成下载包", use_container_width=True):
        with st.spinner("正在打包整理..."):
            zip_bytes = create_organized_zip(results_with_bytes)

        st.download_button(
            label="⬇️ 下载 ZIP 文件",
            data=zip_bytes,
            file_name="鸟类照片整理.zip",
            mime="application/zip",
            use_container_width=True,
        )

    # 导出 JSON 结果
    with st.expander("📄 导出识别结果 (JSON)"):
        results_json = json.dumps(results, ensure_ascii=False, indent=2)
        st.code(results_json, language="json")
        st.download_button(
            label="⬇️ 下载 JSON",
            data=results_json,
            file_name="bird_identification_results.json",
            mime="application/json",
        )

# ============================================================
# 页脚
# ============================================================
st.divider()
st.markdown(
    '<div style="text-align:center; color:#9ca3af; font-size:13px;">'
    '🐦 鸟类照片智能识别 | Powered by 通义千问 qwen-vl-max | '
    'Made with ❤️ by Aone Copilot'
    '</div>',
    unsafe_allow_html=True,
)
