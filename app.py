import streamlit as st
import os
import io
import re
import json
import base64
import zipfile
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from pathlib import Path
from openai import OpenAI
from china_cities import CHINA_PROVINCES_CITIES

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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
    /* ============================================================
       eBird 自然风格主题 — 清爽、专业、自然
       主色：自然绿 #4a7c59  深蓝 #1a3a5c  白色 #ffffff
       辅色：浅绿 #e8f5e9  暖灰 #f5f5f5  边框灰 #e0e0e0
       ============================================================ */

    /* 全局字体和背景 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                     'Roboto', 'Helvetica Neue', Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
        color: #333;
    }
    .stApp {
        background: #f7f7f7 !important;
    }

    /* 隐藏 Streamlit 默认元素 */
    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none !important; }
    .viewerBadge_container__r5tak { display: none !important; }
    .styles_viewerBadge__CvC9N { display: none !important; }
    ._profileContainer_gzau3_53 { display: none !important; }
    [data-testid="manage-app-button"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stHeader"] { display: none !important; }
    .reportview-container .main footer { display: none !important; }
    div[class*="stToolbar"] { display: none !important; }
    button[kind="manage"] { display: none !important; }
    ._container_gzau3_1 { display: none !important; }
    ._profilePreview_gzau3_63 { display: none !important; }

    /* 彻底消除所有间距 */
    .block-container {
        padding: 0 !important;
        max-width: 100% !important;
    }
    .stApp > header { height: 0 !important; min-height: 0 !important; }
    .stMainBlockContainer { padding: 0 !important; }
    [data-testid="stAppViewBlockContainer"] { padding: 0 !important; }
    [data-testid="stMainBlockContainer"] { padding: 0 !important; }
    .appview-container { padding: 0 !important; }
    section[data-testid="stSidebar"] + section { padding: 0 !important; }
    .main .block-container { padding: 0 !important; }
    .stApp [data-testid="stHeader"] { height: 0 !important; min-height: 0 !important; display: none !important; }
    .stApp iframe[height="0"] { display: none !important; }

    /* 主标题区域 — eBird 深蓝绿渐变（全宽无圆角） */
    .hero-section {
        padding: 14px 24px;
        position: relative;
        overflow: hidden;
        border-radius: 0;
        background: linear-gradient(135deg, #1a3a5c 0%, #2d6a4f 100%);
        margin: 0;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        width: 100%;
        box-sizing: border-box;
    }
    .hero-icon {
        font-size: 36px;
        margin-bottom: 4px;
        display: block;
    }
    .hero-title {
        font-size: 26px;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #ffffff;
        margin: 0;
        line-height: 1.15;
    }
    .hero-subtitle {
        font-size: 12px;
        font-weight: 400;
        color: rgba(255,255,255,0.8);
        margin-top: 4px;
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
        padding: 5px 10px;
        background: rgba(255,255,255,0.12);
        border-radius: 6px;
        text-align: left;
    }

    /* 登录卡片 */
    .login-card {
        text-align: center;
        padding: 20px 0 10px;
    }
    .login-title {
        font-size: 20px;
        font-weight: 700;
        color: #1a3a5c;
        margin: 0 0 4px;
    }
    .login-subtitle {
        font-size: 14px;
        color: #666;
        margin: 0;
    }

    /* 识别进度 */
    .progress-banner {
        text-align: center;
        padding: 12px 16px;
        margin: 8px 0;
        border-radius: 8px;
        background: #4a7c59;
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
        animation: pulse-glow 2s ease-in-out infinite;
    }
    @keyframes pulse-glow {
        0%, 100% { box-shadow: 0 0 6px rgba(74,124,89,0.3); }
        50% { box-shadow: 0 0 16px rgba(74,124,89,0.5); }
    }
    .progress-done {
        text-align: center;
        padding: 10px 16px;
        margin: 8px 0;
        border-radius: 8px;
        background: #2d6a4f;
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
    }
    .results-divider {
        height: 1px;
        background: #e0e0e0;
        margin: 16px 0;
    }

    /* 排行榜区域 — eBird 深蓝头部 */
    .leaderboard-header {
        text-align: center;
        padding: 12px;
        border-radius: 10px 10px 0 0;
        background: linear-gradient(135deg, #1a3a5c 0%, #2d6a4f 100%);
        margin-bottom: 0;
    }
    .leaderboard-header-title {
        font-size: 16px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
    }
    .leaderboard-body {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-top: none;
        border-radius: 0 0 10px 10px;
        padding: 8px;
    }
    .leaderboard-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border-radius: 8px;
        margin-bottom: 4px;
        transition: background 0.2s;
    }
    .leaderboard-item:hover {
        background: #f5f5f5;
    }
    .leaderboard-item-current {
        background: #e8f5e9;
        border: 1.5px solid #a5d6a7;
    }
    .leaderboard-rank {
        font-size: 16px;
        width: 24px;
        text-align: center;
        flex-shrink: 0;
    }
    .leaderboard-rank-num {
        font-size: 12px;
        color: #888;
        font-weight: 600;
        width: 24px;
        text-align: center;
        flex-shrink: 0;
    }
    .leaderboard-name {
        font-size: 13px;
        font-weight: 600;
        color: #1a3a5c;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin: 0;
    }
    .leaderboard-name-current {
        color: #2d6a4f;
    }
    .leaderboard-stats {
        font-size: 10px;
        color: #888;
        margin: 1px 0 0;
    }

    /* 白色卡片 — 替代毛玻璃 */
    .glass-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 16px;
        transition: box-shadow 0.2s ease;
    }
    .glass-card:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
    }

    /* 统计卡片 */
    .stat-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 14px;
        text-align: center;
    }
    .stat-value {
        font-size: 26px;
        font-weight: 700;
        color: #1a3a5c;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 12px;
        font-weight: 500;
        color: #888;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    /* 鸟类结果卡片 */
    .bird-result-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 0;
        margin-bottom: 20px;
        overflow: hidden;
        transition: box-shadow 0.2s ease;
    }
    .bird-result-card:hover {
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.1);
    }

    /* 评分徽章 */
    .score-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 14px;
        border-radius: 100px;
        font-weight: 600;
        font-size: 14px;
    }
    .score-excellent {
        background: #2d6a4f;
        color: white;
    }
    .score-good {
        background: #4a7c59;
        color: white;
    }
    .score-fair {
        background: #e8a317;
        color: white;
    }
    .score-poor {
        background: #c0392b;
        color: white;
    }

    /* 分类标签 */
    .taxonomy-pill {
        display: inline-flex;
        align-items: center;
        padding: 3px 10px;
        border-radius: 100px;
        font-size: 12px;
        font-weight: 500;
        margin-right: 6px;
    }
    .order-pill {
        background: #e3f2fd;
        color: #1565c0;
    }
    .family-pill {
        background: #e8f5e9;
        color: #2e7d32;
    }

    /* 置信度指示器 */
    .confidence-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
    }
    .confidence-high { background: #2d6a4f; }
    .confidence-medium { background: #e8a317; }
    .confidence-low { background: #c0392b; }

    /* 信息行 */
    .info-row {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 14px;
        color: #555;
        margin: 4px 0;
    }
    .info-row .label {
        color: #888;
        font-weight: 500;
    }
    .info-row .value {
        color: #1a3a5c;
    }

    /* 鸟名标题 */
    .bird-name {
        font-size: 18px;
        font-weight: 700;
        color: #1a3a5c;
        margin: 0 0 2px 0;
        line-height: 1.2;
    }
    .bird-name-en {
        font-size: 13px;
        font-weight: 400;
        color: #888;
        margin: 0 0 8px 0;
    }

    /* 评分详情 */
    .score-detail {
        font-size: 14px;
        color: #555;
        font-style: italic;
        margin-top: 8px;
        padding: 8px 12px;
        background: #f5f5f5;
        border-radius: 8px;
    }

    /* 上传区域 */
    .stFileUploader > div {
        border-radius: 10px !important;
        border: 2px dashed #c8e6c9 !important;
        background: #fafff9 !important;
    }
    .stFileUploader > div:hover {
        border-color: #4a7c59 !important;
        background: #f1f8e9 !important;
    }

    /* 按钮样式 — eBird 绿色实心 */
    .stButton > button {
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 10px 24px !important;
        transition: all 0.2s ease !important;
        border: none !important;
    }
    .stButton > button[kind="primary"] {
        background: #4a7c59 !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #3d6b4a !important;
        box-shadow: 0 2px 8px rgba(74,124,89,0.3) !important;
    }
    .stButton > button[kind="secondary"] {
        background: #f5f5f5 !important;
        color: #1a3a5c !important;
        border: 1px solid #e0e0e0 !important;
    }
    .stButton > button[kind="secondary"]:hover {
        background: #eeeeee !important;
    }

    /* 下载按钮 */
    .stDownloadButton > button {
        border-radius: 6px !important;
        font-weight: 600 !important;
        background: #2d6a4f !important;
        color: white !important;
        border: none !important;
        padding: 10px 24px !important;
    }
    .stDownloadButton > button:hover {
        background: #245a42 !important;
        box-shadow: 0 2px 8px rgba(45,106,79,0.3) !important;
    }

    /* 输入框 */
    .stTextInput > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
    }
    .stTextInput > div > div:focus-within {
        border-color: #4a7c59 !important;
        box-shadow: 0 0 0 2px rgba(74,124,89,0.15) !important;
    }

    /* 下拉选择框 */
    .stSelectbox > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
        background: #fff !important;
    }
    .stSelectbox > div > div:focus-within {
        border-color: #4a7c59 !important;
        box-shadow: 0 0 0 2px rgba(74,124,89,0.15) !important;
    }
    [data-baseweb="select"] > div {
        border-radius: 6px !important;
        border-color: #ccc !important;
    }
    [data-baseweb="select"] > div:focus-within {
        border-color: #4a7c59 !important;
    }

    /* 多选框 */
    .stMultiSelect > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
    }

    /* 数字输入 */
    .stNumberInput > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
    }

    /* 文本域 */
    .stTextArea > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
    }
    .stTextArea > div > div:focus-within {
        border-color: #4a7c59 !important;
        box-shadow: 0 0 0 2px rgba(74,124,89,0.15) !important;
    }

    /* 日期选择 */
    .stDateInput > div > div {
        border-radius: 6px !important;
        border: 1px solid #ccc !important;
    }

    /* 进度条 */
    .stProgress > div > div {
        border-radius: 100px !important;
        background: linear-gradient(90deg, #4a7c59, #81c784) !important;
    }

    /* Expander */
    .streamlit-expanderHeader {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }

    /* 分割线 */
    hr {
        border: none;
        height: 1px;
        background: #e0e0e0;
        margin: 10px 0;
    }

    /* 图片圆角 */
    .stImage img {
        border-radius: 8px;
    }

    /* 页脚 */
    .app-footer {
        text-align: center;
        padding: 20px 0 12px;
        color: #888;
        font-size: 13px;
        border-top: 1px solid #e0e0e0;
        margin-top: 24px;
    }
    .app-footer a {
        color: #4a7c59;
        text-decoration: none;
    }
    .app-footer a:hover {
        text-decoration: underline;
    }

    /* Tab 页签 — eBird 风格底部高亮，全宽 */
    .stTabs {
        background: #ffffff;
        border-radius: 0;
        padding: 0;
        margin: 0;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
        border: 1px solid #e0e0e0;
        border-top: none;
        width: 100%;
        box-sizing: border-box;
        overflow: visible !important;
    }
    /* Tab 按钮行 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: #fafafa;
        border-radius: 0;
        padding: 0 16px;
        border-bottom: 2px solid #e0e0e0;
    }
    /* 单个 Tab 按钮 */
    .stTabs [data-baseweb="tab"] {
        border-radius: 0;
        padding: 14px 18px;
        font-size: 18px;
        font-weight: 600;
        color: #666;
        border: none;
        background: transparent;
        transition: color 0.2s ease;
        white-space: nowrap;
        border-bottom: 3px solid transparent;
        margin-bottom: -2px;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #1a3a5c;
        background: transparent;
    }
    /* 选中的 Tab — 绿色底部边框 */
    .stTabs [aria-selected="true"] {
        background: transparent !important;
        color: #4a7c59 !important;
        font-weight: 600 !important;
        border-bottom: 3px solid #4a7c59 !important;
        box-shadow: none !important;
    }
    /* 隐藏默认下划线 */
    .stTabs [data-baseweb="tab-highlight"] {
        display: none;
    }
    .stTabs [data-baseweb="tab-border"] {
        display: none;
    }
    /* Tab 内容区 */
    .stTabs [data-baseweb="tab-panel"] {
        padding: 16px 16px;
    }

    /* PWA 安装提示横幅 */
    .pwa-install-banner {
        display: none;
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 9999;
        background: linear-gradient(135deg, #1a3a5c 0%, #2d6a4f 100%);
        color: #fff;
        padding: 14px 24px;
        border-radius: 10px;
        box-shadow: 0 4px 20px rgba(26,58,92,0.3);
        font-size: 14px;
        font-weight: 600;
        text-align: center;
        max-width: 360px;
        width: calc(100% - 40px);
        animation: slide-up 0.4s ease-out;
    }
    @keyframes slide-up {
        from { transform: translateX(-50%) translateY(100px); opacity: 0; }
        to   { transform: translateX(-50%) translateY(0); opacity: 1; }
    }
    .pwa-install-banner .pwa-btn-row {
        display: flex;
        gap: 10px;
        margin-top: 10px;
        justify-content: center;
    }
    .pwa-install-banner button {
        border: none;
        border-radius: 6px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
    }
    .pwa-install-btn {
        background: #fff;
        color: #1a3a5c;
    }
    .pwa-install-btn:hover {
        background: #f0f0f0;
    }
    .pwa-dismiss-btn {
        background: rgba(255,255,255,0.2);
        color: #fff;
    }
    .pwa-dismiss-btn:hover {
        background: rgba(255,255,255,0.3);
    }
    /* iOS Safari 安装引导 */
    .pwa-ios-guide {
        font-size: 12px;
        color: rgba(255,255,255,0.85);
        margin-top: 8px;
        line-height: 1.5;
    }

    /* ============================================================
       移动端适配（屏幕宽度 ≤ 768px）
       ============================================================ */
    @media screen and (max-width: 768px) {
        /* Hero 区域紧凑化 */
        .hero-section {
            padding: 10px 12px !important;
        }
        .hero-section h1 {
            font-size: 20px !important;
        }
        .hero-section p {
            font-size: 11px !important;
        }

        /* Tab 页签缩小 */
        .stTabs [data-baseweb="tab"] {
            padding: 10px 8px !important;
            font-size: 14px !important;
            font-weight: 500 !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            padding: 0 8px !important;
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }
        .stTabs [data-baseweb="tab-panel"] {
            padding: 12px 10px !important;
        }

        /* 统计卡片紧凑 */
        .stat-card {
            padding: 10px 6px !important;
        }
        .stat-value {
            font-size: 20px !important;
        }
        .stat-label {
            font-size: 10px !important;
        }

        /* 排行榜紧凑 */
        .leaderboard-item {
            padding: 6px 8px !important;
        }
        .leaderboard-name {
            font-size: 12px !important;
        }

        /* 按钮适配 */
        .stButton > button {
            padding: 8px 16px !important;
            font-size: 13px !important;
        }

        /* 登录卡片 */
        .login-title {
            font-size: 18px !important;
        }
        .login-subtitle {
            font-size: 13px !important;
        }

        /* 鸟名 */
        .bird-name {
            font-size: 16px !important;
        }

        /* 评分徽章 */
        .score-pill {
            font-size: 12px !important;
            padding: 3px 10px !important;
        }

        /* 图片圆角 */
        .stImage img {
            border-radius: 6px !important;
        }

        /* PWA 横幅 */
        .pwa-install-banner {
            bottom: 10px !important;
            padding: 10px 16px !important;
            font-size: 13px !important;
        }
    }

    /* 超小屏幕（≤ 480px，如小屏手机） */
    @media screen and (max-width: 480px) {
        .hero-section {
            padding: 8px 10px !important;
        }
        .hero-section h1 {
            font-size: 18px !important;
        }

        .stTabs [data-baseweb="tab"] {
            padding: 8px 6px !important;
            font-size: 13px !important;
        }

        .stat-card {
            padding: 8px 4px !important;
            border-radius: 6px !important;
        }
        .stat-value {
            font-size: 18px !important;
        }
        .stat-label {
            font-size: 9px !important;
        }

        .leaderboard-header-title {
            font-size: 14px !important;
        }

        .bird-name {
            font-size: 15px !important;
        }
        .bird-name-en {
            font-size: 11px !important;
        }

        .glass-card {
            padding: 12px !important;
        }
    }

    /* 确保移动端 viewport 正确 */
    @viewport { width: device-width; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# PWA 支持：注入 manifest、meta 标签 & Service Worker 注册
# ============================================================
st.markdown("""
<link rel="manifest" href="./static/manifest.json" crossorigin="use-credentials">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#1a3a5c">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="影禽">
<link rel="apple-touch-icon" href="./static/icon-192.png">

<!-- 将 meta/link 标签提升到顶层 head（Streamlit iframe 内注入的标签浏览器可能忽略） -->
<script>
(function() {
    try {
        var topDoc = window.parent.document || document;
        var head = topDoc.head || topDoc.getElementsByTagName('head')[0];
        if (!head) return;

        // 避免重复注入
        if (topDoc.querySelector('link[rel="manifest"]')) return;

        var tags = [
            {tag:'link', attrs:{rel:'manifest', href:'./static/manifest.json', crossOrigin:'use-credentials'}},
            {tag:'meta', attrs:{name:'theme-color', content:'#1a3a5c'}},
            {tag:'meta', attrs:{name:'apple-mobile-web-app-capable', content:'yes'}},
            {tag:'meta', attrs:{name:'apple-mobile-web-app-status-bar-style', content:'black-translucent'}},
            {tag:'meta', attrs:{name:'apple-mobile-web-app-title', content:'影禽'}},
            {tag:'link', attrs:{rel:'apple-touch-icon', href:'./static/icon-192.png'}}
        ];
        tags.forEach(function(t) {
            var el = topDoc.createElement(t.tag);
            for (var k in t.attrs) { el.setAttribute(k, t.attrs[k]); }
            head.appendChild(el);
        });

        // 注册 Service Worker（在顶层窗口注册）
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('./static/sw.js')
                .then(function(r) { console.log('[PWA] SW registered', r.scope); })
                .catch(function(e) { console.warn('[PWA] SW failed', e); });
        }

    } catch(e) { console.warn('[PWA] meta inject skipped', e); }
})();
</script>
""", unsafe_allow_html=True)

# ============================================================
# 隐藏 Streamlit Cloud 外层框架的红色图标和头像
# 使用 st.components.v1.html 注入零高度 iframe，突破 CSP 限制
# ============================================================
import streamlit.components.v1 as components
components.html("""
<script>
(function() {
    function hideStreamlitBranding() {
        try {
            var doc = window.top.document || window.parent.document;
            if (!doc) return;

            // 注入隐藏样式到顶层
            if (!doc.getElementById('hide-st-branding')) {
                var style = doc.createElement('style');
                style.id = 'hide-st-branding';
                style.textContent = `
                    /* Streamlit Cloud manage app 按钮（红色波浪图标） */
                    ._container_gzau3_1,
                    ._profileContainer_gzau3_53,
                    ._profilePreview_gzau3_63,
                    [data-testid="manage-app-button"],
                    [data-testid="stStatusWidget"],
                    [data-testid="stToolbar"],
                    [data-testid="stDecoration"],
                    .stDeployButton,
                    button[kind="manage"],
                    .viewerBadge_container__r5tak,
                    .styles_viewerBadge__CvC9N,
                    #MainMenu, header {
                        display: none !important;
                        visibility: hidden !important;
                        height: 0 !important;
                        width: 0 !important;
                        overflow: hidden !important;
                        position: absolute !important;
                        top: -9999px !important;
                    }
                    footer {
                        visibility: hidden !important;
                    }
                    /* 通配：右下角固定定位的小按钮 */
                    div[style*="position: fixed"][style*="bottom"][style*="right"] {
                        display: none !important;
                    }
                `;
                doc.head.appendChild(style);
            }

            // 直接查找并隐藏右下角的元素
            var allFixed = doc.querySelectorAll('div, button, a, img');
            allFixed.forEach(function(el) {
                var cs = window.top.getComputedStyle(el);
                if (cs.position === 'fixed' &&
                    parseInt(cs.bottom) < 80 &&
                    parseInt(cs.right) < 80 &&
                    el.offsetWidth < 100 &&
                    el.offsetHeight < 100) {
                    el.style.display = 'none';
                }
            });
        } catch(e) {}
    }

    // 立即执行 + 延迟执行 + 持续监控
    hideStreamlitBranding();
    setTimeout(hideStreamlitBranding, 1000);
    setTimeout(hideStreamlitBranding, 3000);
    setTimeout(hideStreamlitBranding, 5000);

    // MutationObserver 持续监控新增元素
    try {
        var doc = window.top.document || window.parent.document;
        var observer = new MutationObserver(function() {
            hideStreamlitBranding();
        });
        observer.observe(doc.body, { childList: true, subtree: true });
        // 30秒后停止监控，避免性能影响
        setTimeout(function() { observer.disconnect(); }, 30000);
    } catch(e) {}

    // ---- Tab 页签滚动时固定在顶部 ----
    function setupStickyTabs() {
        try {
            var doc = window.parent.document || document;
            var tabList = doc.querySelector('[data-baseweb="tab-list"]');
            if (!tabList || tabList.dataset.stickyDone) return;
            tabList.dataset.stickyDone = '1';

            // 找到 Streamlit 的实际滚动容器
            var scrollContainer = doc.querySelector('[data-testid="stAppViewContainer"]')
                || doc.querySelector('.main')
                || doc.querySelector('section.main > div');
            if (!scrollContainer) {
                // fallback: 找有滚动的容器
                var candidates = doc.querySelectorAll('div, section');
                for (var i = 0; i < candidates.length; i++) {
                    var cs = window.top.getComputedStyle(candidates[i]);
                    if ((cs.overflow === 'auto' || cs.overflow === 'scroll' ||
                         cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                        candidates[i].scrollHeight > candidates[i].clientHeight) {
                        scrollContainer = candidates[i];
                        break;
                    }
                }
            }
            if (!scrollContainer) return;

            var tabOriginalTop = tabList.getBoundingClientRect().top + scrollContainer.scrollTop;
            var tabHeight = tabList.offsetHeight;
            var placeholder = doc.createElement('div');
            placeholder.style.display = 'none';
            placeholder.style.height = tabHeight + 'px';
            tabList.parentNode.insertBefore(placeholder, tabList);

            scrollContainer.addEventListener('scroll', function() {
                var scrollTop = scrollContainer.scrollTop;
                if (scrollTop > tabOriginalTop) {
                    tabList.style.position = 'fixed';
                    tabList.style.top = '0';
                    tabList.style.left = '0';
                    tabList.style.right = '0';
                    tabList.style.zIndex = '9998';
                    tabList.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
                    placeholder.style.display = 'block';
                } else {
                    tabList.style.position = '';
                    tabList.style.top = '';
                    tabList.style.left = '';
                    tabList.style.right = '';
                    tabList.style.zIndex = '';
                    tabList.style.boxShadow = '';
                    placeholder.style.display = 'none';
                }
            });
        } catch(e) { console.warn('[StickyTab]', e); }
    }
    setTimeout(setupStickyTabs, 1500);
    setTimeout(setupStickyTabs, 3000);
})();
</script>
""", height=0, scrolling=False)

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


def encode_image_to_base64(image_bytes: bytes, max_size: int = 2048, filename: str = "") -> str:
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


def _extract_json_from_text(text: str) -> dict | None:
    """从 AI 返回的文本中提取 JSON 对象"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            return None
    return None

def identify_bird(image_base64: str, api_key: str, exif_info: dict) -> dict:
    """单阶段鸟类识别 + 摄影评分（使用 qwen-vl-max-latest）

    通过强化版思维链 prompt 引导 AI 先逐项观察特征、列候选、排除，再做最终判断。
    单次调用完成，兼顾速度和准确率。
    """
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    context_block, season = _build_context_block(exif_info)

    fail_result = {
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

    try:
        response = client.chat.completions.create(
            model="qwen-vl-max-latest",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位专精中国鸟类的顶级鸟类学家和鸟类摄影评审专家。"
                        "你熟悉《中国鸟类野外手册》《中国鸟类分类与分布名录》中记录的所有鸟种，"
                        "精通中国境内1400余种鸟类的辨识要点、分布范围和季节性变化。"
                        "你能根据细微的羽色差异区分中国常见的易混淆种（如柳莺类、鹀类、鸫类、鹟类等）。"
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
                                "## 任务一：鸟种识别（严格按步骤执行）\n"
                                "这张照片拍摄于中国境内。\n\n"
                                "**步骤1 - 逐项特征观察（必须每项都描述）：**\n"
                                "- 体型：大小（与麻雀/鸽子/乌鸦对比）、体型比例\n"
                                "- 喙：形状（锥形/钩形/细长/扁平）、长度、粗细、颜色\n"
                                "- 头部：冠羽有无、眉纹（颜色/粗细）、贯眼纹、眼圈、头顶色\n"
                                "- 上体：背部羽色、翼斑有无及颜色、腰色\n"
                                "- 下体：喉/胸/腹/胁部颜色和斑纹\n"
                                "- 尾羽：长短、形状（方尾/圆尾/叉尾）、颜色\n"
                                "- 腿脚颜色\n"
                                "- 栖息环境\n\n"
                                "**步骤2 - 列出3个候选种并逐一比对：**\n"
                                "对每个候选种说明：哪些特征支持、哪些不符、在该地区该季节是否有分布。\n\n"
                                "**步骤3 - 最终判定：**\n"
                                "从候选种中选出最匹配的，说明决定性的区分依据。\n\n"
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
                                '  "chinese_name": "最终确定的中文种名（相似度最高的）",\n'
                                '  "english_name": "英文种名",\n'
                                '  "order_chinese": "目中文名",\n'
                                '  "order_english": "目英文名",\n'
                                '  "family_chinese": "科中文名",\n'
                                '  "family_english": "科英文名",\n'
                                '  "confidence": "high/medium/low",\n'
                                '  "candidates": [\n'
                                '    {"chinese_name": "第1候选种中文名", "english_name": "英文名", "similarity": 85, "reason": "支持该种的关键特征（15字以内）"},\n'
                                '    {"chinese_name": "第2候选种中文名", "english_name": "英文名", "similarity": 60, "reason": "支持该种的关键特征（15字以内）"},\n'
                                '    {"chinese_name": "第3候选种中文名", "english_name": "英文名", "similarity": 30, "reason": "支持该种的关键特征（15字以内）"}\n'
                                '  ],\n'
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
                                "6. excluded_similar_species 必须列出至少1个排除的易混淆种及理由\n"
                                "7. candidates 必须包含2-3个候选鸟种，按 similarity 从高到低排列\n"
                                "8. similarity 为0-100的整数，表示该候选种与照片中鸟的匹配程度，所有候选种的 similarity 之和不需要等于100\n"
                                "9. chinese_name 必须与 candidates 中 similarity 最高的候选种一致"
                                f"{context_block}"
                            ),
                        },
                    ],
                },
            ],
        )
    except Exception as api_error:
        import traceback
        traceback.print_exc()
        fail_result["score_comment"] = f"AI 接口调用失败: {type(api_error).__name__}: {str(api_error)[:100]}"
        return fail_result

    try:
        result_text = response.choices[0].message.content.strip()
    except (AttributeError, IndexError) as parse_error:
        fail_result["score_comment"] = f"AI 返回数据异常: {parse_error}"
        return fail_result

    parsed = _extract_json_from_text(result_text)
    if not parsed:
        fail_result["score_comment"] = "AI 返回内容中未找到有效 JSON"
        return fail_result

    # 校正评分
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


def draw_bird_bbox(img: "Image.Image", bbox: list, color=(102, 126, 234), thickness: int = 3, opacity: float = 0.15) -> "Image.Image":
    """在原图上绘制半透明高亮框标注 AI 识别的鸟的位置。

    bbox 格式: [x1, y1, x2, y2]，值为 0-100 的百分比。
    返回带有高亮框的新图片。
    """
    if not bbox or len(bbox) != 4:
        return img

    from PIL import ImageDraw

    annotated = img.copy().convert("RGBA")
    width, height = annotated.size
    x1_pct, y1_pct, x2_pct, y2_pct = bbox

    x1 = int(width * x1_pct / 100)
    y1 = int(height * y1_pct / 100)
    x2 = int(width * x2_pct / 100)
    y2 = int(height * y2_pct / 100)

    if x2 <= x1 or y2 <= y1:
        return img

    # 绘制半透明填充层
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    fill_color = (*color, int(255 * opacity))
    overlay_draw.rectangle([x1, y1, x2, y2], fill=fill_color)
    annotated = Image.alpha_composite(annotated, overlay)

    # 绘制边框
    draw = ImageDraw.Draw(annotated)
    for offset in range(thickness):
        draw.rectangle(
            [x1 - offset, y1 - offset, x2 + offset, y2 + offset],
            outline=(*color, 220),
        )

    # 在左上角绘制 "AI 识别区域" 小标签
    label = "AI"
    label_padding = 4
    label_x = x1
    label_y = max(0, y1 - 20)
    label_bg = (*color, 200)
    draw.rectangle(
        [label_x, label_y, label_x + 24, label_y + 16],
        fill=label_bg,
    )
    draw.text((label_x + label_padding, label_y + 1), label, fill=(255, 255, 255, 255))

    return annotated.convert("RGB")


@st.cache_data(ttl=86400, show_spinner=False)
def get_seasonal_bird_recommendations(api_key: str, city: str, month: int) -> list:
    """根据城市和月份，用 AI 生成本月可能观测到的鸟种推荐。

    返回格式: [{"name": "白头鹎", "emoji": "🐦", "tip": "常见于公园灌丛"}]
    结果缓存 24 小时。
    """
    season_map = {
        1: "冬季（越冬期）", 2: "冬季（越冬期）", 3: "春季（春迁期）",
        4: "春季（春迁期）", 5: "春季（春迁期）", 6: "夏季（繁殖期）",
        7: "夏季（繁殖期）", 8: "夏季（繁殖期）", 9: "秋季（秋迁期）",
        10: "秋季（秋迁期）", 11: "秋季（秋迁期）", 12: "冬季（越冬期）",
    }
    season = season_map.get(month, "")
    month_names = ["", "一月", "二月", "三月", "四月", "五月", "六月",
                   "七月", "八月", "九月", "十月", "十一月", "十二月"]
    month_name = month_names[month] if 1 <= month <= 12 else ""

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        response = client.chat.completions.create(
            model="qwen-plus",
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位中国鸟类学专家，精通中国各地各季节的鸟类分布。"
                        "请根据用户提供的城市和月份，推荐该地区该时节最值得观测的鸟种。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"我在{city}，现在是{month_name}（{season}）。\n\n"
                        "请推荐 6 种本月在该地区最可能观测到的鸟种，优先推荐：\n"
                        "1. 当季特色鸟种（如迁徙过境的旅鸟、刚到达的候鸟）\n"
                        "2. 容易观测到的常见种\n"
                        "3. 有观赏价值的鸟种\n\n"
                        "只返回 JSON 数组，格式如下：\n"
                        "[\n"
                        '  {"name": "鸟种中文名", "emoji": "合适的emoji", "tip": "一句话观测提示（在哪里容易看到、有什么特征，15字以内）"},\n'
                        "  ...\n"
                        "]\n\n"
                        "要求：\n"
                        "- 必须是该城市该月份确实有分布记录的鸟种\n"
                        "- emoji 要与鸟的特征相关（如水鸟用🦆，猛禽用🦅，小型鸟用🐦等）\n"
                        "- 不要返回 JSON 以外的内容"
                    ),
                },
            ],
        )
        result_text = response.choices[0].message.content.strip()
        json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[:6]
    except Exception as exc:
        print(f"[季节推荐] 生成失败: {exc}")
    return []


CHINA_CITY_COORDS = {
    "北京市": (39.9042, 116.4074), "天津市": (39.3434, 117.3616),
    "上海市": (31.2304, 121.4737), "重庆市": (29.5630, 106.5516),
    "石家庄市": (38.0428, 114.5149), "唐山市": (39.6309, 118.1802),
    "秦皇岛市": (39.9354, 119.5977), "邯郸市": (36.6258, 114.5391),
    "邢台市": (37.0682, 114.5048), "保定市": (38.8739, 115.4646),
    "张家口市": (40.7677, 114.8869), "承德市": (40.9510, 117.9634),
    "沧州市": (38.3037, 116.8388), "廊坊市": (39.5168, 116.6831),
    "衡水市": (37.7350, 115.6700), "太原市": (37.8706, 112.5489),
    "大同市": (40.0766, 113.2955), "阳泉市": (37.8568, 113.5804),
    "长治市": (36.1954, 113.1163), "晋城市": (35.4908, 112.8513),
    "朔州市": (39.3313, 112.4329), "晋中市": (37.6872, 112.7525),
    "运城市": (35.0268, 111.0070), "忻州市": (38.4177, 112.7340),
    "临汾市": (36.0881, 111.5190), "吕梁市": (37.5193, 111.1340),
    "呼和浩特市": (40.8414, 111.7519), "包头市": (40.6571, 109.8403),
    "乌海市": (39.6553, 106.7943), "赤峰市": (42.2580, 118.8869),
    "通辽市": (43.6174, 122.2630), "鄂尔多斯市": (39.6086, 109.7812),
    "呼伦贝尔市": (49.2115, 119.7653), "巴彦淖尔市": (40.7574, 107.3877),
    "乌兰察布市": (40.9930, 113.1143),
    "沈阳市": (41.8057, 123.4315), "大连市": (38.9140, 121.6147),
    "鞍山市": (41.1087, 122.9956), "抚顺市": (41.8819, 123.9573),
    "本溪市": (41.2976, 123.7660), "丹东市": (40.1290, 124.3826),
    "锦州市": (41.0950, 121.1270), "营口市": (40.6672, 122.2350),
    "阜新市": (42.0215, 121.6709), "辽阳市": (41.2681, 123.2368),
    "盘锦市": (41.1198, 122.0707), "铁岭市": (42.2860, 123.8441),
    "朝阳市": (41.5718, 120.4508), "葫芦岛市": (40.7556, 120.8560),
    "长春市": (43.8171, 125.3235), "吉林市": (43.8378, 126.5496),
    "四平市": (43.1666, 124.3507), "辽源市": (42.8877, 125.1437),
    "通化市": (41.7285, 125.9396), "白山市": (41.9425, 126.4274),
    "松原市": (45.1411, 124.8249), "白城市": (45.6190, 122.8390),
    "延边朝鲜族自治州": (42.8914, 129.5092),
    "哈尔滨市": (45.8038, 126.5350), "齐齐哈尔市": (47.3542, 123.9179),
    "鸡西市": (45.3005, 130.9697), "鹤岗市": (47.3321, 130.2776),
    "双鸭山市": (46.6465, 131.1591), "大庆市": (46.5907, 125.1040),
    "伊春市": (47.7277, 128.8994), "佳木斯市": (46.7996, 130.3180),
    "七台河市": (45.7710, 131.0030), "牡丹江市": (44.5522, 129.6329),
    "黑河市": (50.2456, 127.5285), "绥化市": (46.6374, 126.9688),
    "南京市": (32.0603, 118.7969), "无锡市": (31.4912, 120.3119),
    "徐州市": (34.2618, 117.1859), "常州市": (31.8106, 119.9741),
    "苏州市": (31.2990, 120.5853), "南通市": (31.9800, 120.8943),
    "连云港市": (34.5967, 119.2216), "淮安市": (33.6104, 119.0153),
    "盐城市": (33.3477, 120.1614), "扬州市": (32.3936, 119.4126),
    "镇江市": (32.1877, 119.4250), "泰州市": (32.4559, 119.9231),
    "宿迁市": (33.9631, 118.2750),
    "杭州市": (30.2741, 120.1551), "宁波市": (29.8683, 121.5440),
    "温州市": (28.0015, 120.6721), "嘉兴市": (30.7469, 120.7555),
    "湖州市": (30.8927, 120.0993), "绍兴市": (30.0303, 120.5801),
    "金华市": (29.0789, 119.6496), "衢州市": (28.9353, 118.8594),
    "舟山市": (29.9853, 122.1074), "台州市": (28.6561, 121.4208),
    "丽水市": (28.4679, 119.9229),
    "合肥市": (31.8206, 117.2272), "芜湖市": (31.3524, 118.4331),
    "蚌埠市": (32.9168, 117.3889), "淮南市": (32.6253, 116.9997),
    "马鞍山市": (31.6706, 118.5076), "淮北市": (33.9555, 116.7983),
    "铜陵市": (30.9454, 117.8122), "安庆市": (30.5430, 117.0631),
    "黄山市": (29.7147, 118.3376), "滁州市": (32.3017, 118.3170),
    "阜阳市": (32.8901, 115.8140), "宿州市": (33.6461, 116.9641),
    "六安市": (31.7350, 116.5078), "亳州市": (33.8693, 115.7785),
    "池州市": (30.6650, 117.4912), "宣城市": (30.9457, 118.7590),
    "福州市": (26.0745, 119.2965), "厦门市": (24.4798, 118.0894),
    "莆田市": (25.4540, 119.0078), "三明市": (26.2654, 117.6389),
    "泉州市": (24.8741, 118.6757), "漳州市": (24.5128, 117.6471),
    "南平市": (26.6356, 118.1778), "龙岩市": (25.0758, 117.0174),
    "宁德市": (26.6656, 119.5486),
    "南昌市": (28.6820, 115.8579), "景德镇市": (29.2689, 117.1784),
    "萍乡市": (27.6229, 113.8543), "九江市": (29.7050, 115.9930),
    "新余市": (27.8174, 114.9170), "鹰潭市": (28.2600, 117.0694),
    "赣州市": (25.8312, 114.9334), "吉安市": (27.1138, 114.9866),
    "宜春市": (27.8043, 114.4161), "抚州市": (27.9484, 116.3582),
    "上饶市": (28.4551, 117.9433),
    "济南市": (36.6512, 117.1201), "青岛市": (36.0671, 120.3826),
    "淄博市": (36.8131, 118.0548), "枣庄市": (34.8564, 117.5576),
    "东营市": (37.4346, 118.6749), "烟台市": (37.4638, 121.4479),
    "潍坊市": (36.7068, 119.1619), "济宁市": (35.4145, 116.5871),
    "泰安市": (36.1999, 117.0870), "威海市": (37.5131, 122.1200),
    "日照市": (35.4164, 119.5269), "临沂市": (35.1041, 118.3564),
    "德州市": (37.4347, 116.3575), "聊城市": (36.4568, 115.9854),
    "滨州市": (37.3835, 117.9706), "菏泽市": (35.2334, 115.4810),
    "郑州市": (34.7466, 113.6254), "开封市": (34.7972, 114.3416),
    "洛阳市": (34.6197, 112.4540), "平顶山市": (33.7662, 113.1925),
    "安阳市": (36.0997, 114.3929), "鹤壁市": (35.7481, 114.2975),
    "新乡市": (35.3030, 113.9268), "焦作市": (35.2156, 113.2418),
    "濮阳市": (35.7622, 115.0293), "许昌市": (34.0357, 113.8523),
    "漯河市": (33.5816, 114.0166), "三门峡市": (34.7736, 111.2003),
    "南阳市": (32.9908, 112.5283), "商丘市": (34.4371, 115.6506),
    "信阳市": (32.1264, 114.0913), "周口市": (33.6260, 114.6498),
    "驻马店市": (32.9802, 114.0249),
    "武汉市": (30.5928, 114.3055), "黄石市": (30.2004, 115.0389),
    "十堰市": (32.6292, 110.7981), "宜昌市": (30.6918, 111.2864),
    "襄阳市": (32.0420, 112.1443), "鄂州市": (30.3907, 114.8949),
    "荆门市": (31.0354, 112.1993), "孝感市": (30.9244, 113.9268),
    "荆州市": (30.3340, 112.2390), "黄冈市": (30.4461, 114.8724),
    "咸宁市": (29.8413, 114.3226), "随州市": (31.6900, 113.3826),
    "恩施土家族苗族自治州": (30.2720, 109.4884),
    "长沙市": (28.2282, 112.9388), "株洲市": (27.8274, 113.1340),
    "湘潭市": (27.8297, 112.9441), "衡阳市": (26.8930, 112.5720),
    "邵阳市": (27.2389, 111.4674), "岳阳市": (29.3572, 113.1289),
    "常德市": (29.0316, 111.6986), "张家界市": (29.1170, 110.4793),
    "益阳市": (28.5530, 112.3553), "郴州市": (25.7702, 113.0149),
    "永州市": (26.4345, 111.6133), "怀化市": (27.5501, 109.9978),
    "娄底市": (27.7281, 112.0083),
    "广州市": (23.1291, 113.2644), "韶关市": (24.8107, 113.5975),
    "深圳市": (22.5431, 114.0579), "珠海市": (22.2710, 113.5767),
    "汕头市": (23.3535, 116.6819), "佛山市": (23.0218, 113.1219),
    "江门市": (22.5790, 113.0815), "湛江市": (21.2707, 110.3594),
    "茂名市": (21.6627, 110.9254), "肇庆市": (23.0469, 112.4653),
    "惠州市": (23.1116, 114.4161), "梅州市": (24.2886, 116.1226),
    "汕尾市": (22.7862, 115.3754), "河源市": (23.7433, 114.7000),
    "阳江市": (21.8579, 111.9822), "清远市": (23.6820, 113.0560),
    "东莞市": (23.0430, 113.7633), "中山市": (22.5176, 113.3926),
    "潮州市": (23.6568, 116.6225), "揭阳市": (23.5500, 116.3728),
    "云浮市": (22.9154, 112.0444),
    "南宁市": (22.8170, 108.3665), "柳州市": (24.3264, 109.4281),
    "桂林市": (25.2742, 110.2992), "梧州市": (23.4748, 111.2791),
    "北海市": (21.4733, 109.1195), "防城港市": (21.6146, 108.3454),
    "钦州市": (21.9813, 108.6543), "贵港市": (23.1116, 109.5988),
    "玉林市": (22.6540, 110.1810), "百色市": (23.9026, 106.6186),
    "贺州市": (24.4141, 111.5526), "河池市": (24.6930, 108.0853),
    "来宾市": (23.7338, 109.2214), "崇左市": (22.3773, 107.3647),
    "海口市": (20.0174, 110.3493), "三亚市": (18.2528, 109.5120),
    "成都市": (30.5728, 104.0668), "自贡市": (29.3393, 104.7786),
    "攀枝花市": (26.5823, 101.7187), "泸州市": (28.8717, 105.4423),
    "德阳市": (31.1311, 104.3979), "绵阳市": (31.4675, 104.6796),
    "广元市": (32.4354, 105.8440), "遂宁市": (30.5330, 105.5929),
    "内江市": (29.5800, 105.0586), "乐山市": (29.5521, 103.7660),
    "南充市": (30.8373, 106.1107), "眉山市": (30.0754, 103.8314),
    "宜宾市": (28.7513, 104.6308), "广安市": (30.4563, 106.6333),
    "达州市": (31.2090, 107.4682), "雅安市": (29.9808, 103.0013),
    "巴中市": (31.8672, 106.7474), "资阳市": (30.1222, 104.6279),
    "阿坝藏族羌族自治州": (31.8990, 102.2214),
    "甘孜藏族自治州": (30.0486, 101.9625),
    "凉山彝族自治州": (27.8816, 102.2673),
    "贵阳市": (26.6470, 106.6302), "六盘水市": (26.5935, 104.8306),
    "遵义市": (27.7254, 106.9272), "安顺市": (26.2456, 105.9473),
    "毕节市": (27.2847, 105.2847), "铜仁市": (27.7183, 109.1896),
    "黔西南布依族苗族自治州": (25.0880, 104.9063),
    "黔东南苗族侗族自治州": (26.5834, 107.9829),
    "黔南布依族苗族自治州": (26.2582, 107.5224),
    "昆明市": (25.0389, 102.7183), "曲靖市": (25.4900, 103.7961),
    "玉溪市": (24.3528, 102.5428), "保山市": (25.1120, 99.1671),
    "昭通市": (27.3400, 103.7172), "丽江市": (26.8721, 100.2299),
    "普洱市": (22.7772, 100.9722), "临沧市": (23.8864, 100.0927),
    "大理白族自治州": (25.6065, 100.2676),
    "红河哈尼族彝族自治州": (23.3636, 103.3750),
    "文山壮族苗族自治州": (23.3695, 104.2440),
    "西双版纳傣族自治州": (22.0017, 100.7975),
    "德宏傣族景颇族自治州": (24.4367, 98.5849),
    "怒江傈僳族自治州": (25.8170, 98.8543),
    "迪庆藏族自治州": (27.8190, 99.7069),
    "拉萨市": (29.6500, 91.1409), "日喀则市": (29.2678, 88.8848),
    "昌都市": (31.1369, 97.1785), "林芝市": (29.6490, 94.3624),
    "山南市": (29.2368, 91.7665), "那曲市": (31.4762, 92.0514),
    "西安市": (34.2658, 108.9541), "铜川市": (34.8966, 108.9452),
    "宝鸡市": (34.3617, 107.2370), "咸阳市": (34.3296, 108.7089),
    "渭南市": (34.4998, 109.5099), "延安市": (36.5853, 109.4898),
    "汉中市": (33.0674, 107.0230), "榆林市": (38.2850, 109.7345),
    "安康市": (32.6849, 109.0293), "商洛市": (33.8700, 109.9401),
    "兰州市": (36.0611, 103.8343), "嘉峪关市": (39.7731, 98.2773),
    "金昌市": (38.5200, 102.1877), "白银市": (36.5447, 104.1389),
    "天水市": (34.5809, 105.7249), "武威市": (37.9283, 102.6371),
    "张掖市": (38.9260, 100.4497), "平凉市": (35.5428, 106.6652),
    "酒泉市": (39.7320, 98.4941), "庆阳市": (35.7341, 107.6380),
    "定西市": (35.5806, 104.5920), "陇南市": (33.3886, 104.9219),
    "临夏回族自治州": (35.6013, 103.2106),
    "甘南藏族自治州": (34.9864, 102.9113),
    "西宁市": (36.6171, 101.7782), "海东市": (36.5029, 102.1028),
    "银川市": (38.4872, 106.2309), "石嘴山市": (38.9842, 106.3762),
    "吴忠市": (37.9976, 106.1991), "固原市": (36.0160, 106.2425),
    "中卫市": (37.5149, 105.1965),
    "乌鲁木齐市": (43.8256, 87.6168), "克拉玛依市": (45.5799, 84.8893),
    "吐鲁番市": (42.9513, 89.1895), "哈密市": (42.8332, 93.5151),
    "香港": (22.3193, 114.1694), "澳门": (22.1987, 113.5439),
    "台北市": (25.0330, 121.5654), "高雄市": (22.6273, 120.3014),
}


def geocode_city(city_name: str) -> tuple:
    """将城市名转为经纬度坐标（正向地理编码）。返回 (lat, lon) 或 (None, None)。
    优先查内置字典，fallback 到 Nominatim API。"""
    if not city_name:
        return None, None

    # 优先从内置字典匹配
    if city_name in CHINA_CITY_COORDS:
        return CHINA_CITY_COORDS[city_name]
    for key, coords in CHINA_CITY_COORDS.items():
        if city_name in key or key in city_name:
            return coords

    # Fallback: Nominatim API
    try:
        encoded_city = urllib.parse.quote(city_name)
        url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&format=json&limit=1&accept-language=zh-CN"
        request = urllib.request.Request(url, headers={"User-Agent": "BirdPhotoApp/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data and len(data) > 0:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None


@st.cache_data(ttl=86400, show_spinner=False)
def reverse_geocode(latitude: float, longitude: float) -> dict:
    """反向地理编码：经纬度 → 省市区。返回 {"province": ..., "city": ..., "district": ...}。"""
    result = {"province": "", "city": "", "district": ""}
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?"
            f"lat={latitude}&lon={longitude}&format=json&accept-language=zh-CN&zoom=12"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "BirdPhotoApp/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            address = data.get("address", {})
            result["province"] = address.get("state", "")
            result["city"] = address.get("city", "") or address.get("town", "") or address.get("county", "")
            result["district"] = address.get("suburb", "") or address.get("district", "") or address.get("village", "")
    except Exception:
        pass
    return result


def match_province_in_data(province_name: str) -> str:
    """将反向地理编码返回的省名匹配到 CHINA_PROVINCES_CITIES 的 key。"""
    if not province_name:
        return ""
    for key in CHINA_PROVINCES_CITIES:
        if province_name in key or key in province_name:
            return key
    return ""


def match_city_in_data(province_key: str, city_name: str) -> str:
    """将反向地理编码返回的市名匹配到省下面的城市列表。"""
    if not province_key or not city_name:
        return ""
    cities = CHINA_PROVINCES_CITIES.get(province_key, [])
    for city in cities:
        if city_name in city or city in city_name:
            return city
    return ""


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_current_weather(latitude: float, longitude: float) -> dict:
    """通过 Open-Meteo 获取当前天气（免费，无需 API Key）。缓存 1 小时。"""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={latitude}&longitude={longitude}"
            f"&current_weather=true&timezone=auto"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "BirdPhotoApp/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            current = data.get("current_weather", {})
            temperature = current.get("temperature", 0)
            windspeed = current.get("windspeed", 0)
            weathercode = current.get("weathercode", 0)

            # WMO 天气代码转描述和 emoji
            weather_descriptions = {
                0: ("晴", "☀️"), 1: ("大部晴", "🌤️"), 2: ("多云", "⛅"),
                3: ("阴天", "☁️"), 45: ("雾", "🌫️"), 48: ("雾凇", "🌫️"),
                51: ("小毛毛雨", "🌦️"), 53: ("毛毛雨", "🌦️"), 55: ("大毛毛雨", "🌦️"),
                61: ("小雨", "🌧️"), 63: ("中雨", "🌧️"), 65: ("大雨", "🌧️"),
                71: ("小雪", "🌨️"), 73: ("中雪", "🌨️"), 75: ("大雪", "🌨️"),
                80: ("阵雨", "🌦️"), 81: ("中阵雨", "🌧️"), 82: ("大阵雨", "🌧️"),
                95: ("雷暴", "⛈️"), 96: ("冰雹雷暴", "⛈️"), 99: ("大冰雹雷暴", "⛈️"),
            }
            description, emoji = weather_descriptions.get(weathercode, ("未知", "🌡️"))

            # 观鸟适宜度评估
            birding_score = "适宜"
            birding_emoji = "✅"
            if weathercode >= 61 or windspeed > 30:
                birding_score = "不太适宜"
                birding_emoji = "⚠️"
            elif weathercode >= 95:
                birding_score = "不建议外出"
                birding_emoji = "❌"
            elif weathercode <= 2 and windspeed < 15:
                birding_score = "非常适宜"
                birding_emoji = "🌟"

            return {
                "temperature": temperature,
                "windspeed": windspeed,
                "description": description,
                "emoji": emoji,
                "birding_score": birding_score,
                "birding_emoji": birding_emoji,
            }
    except Exception as exc:
        print(f"[天气] 获取失败: {exc}")
    return {}


@st.cache_data(ttl=7200, show_spinner=False)
def _build_query_points(latitude: float, longitude: float, radius_km: int) -> list:
    """根据搜索半径生成查询点列表。eBird API 单次最大 50km，超过需多点覆盖。"""
    points = [(latitude, longitude)]
    if radius_km <= 50:
        return points
    # 100km: 中心 + 东西南北各偏移 0.6°≈67km
    if radius_km <= 100:
        offset = 0.6
        points += [
            (latitude + offset, longitude),
            (latitude - offset, longitude),
            (latitude, longitude + offset),
            (latitude, longitude - offset),
        ]
        return points
    # 150km: 中心 + 东西南北各偏移 1°≈100km
    if radius_km <= 150:
        offset = 1.0
        points += [
            (latitude + offset, longitude),
            (latitude - offset, longitude),
            (latitude, longitude + offset),
            (latitude, longitude - offset),
        ]
        return points
    # 200km: 中心 + 8 方向偏移 1.3°≈145km
    offset = 1.3
    points += [
        (latitude + offset, longitude),
        (latitude - offset, longitude),
        (latitude, longitude + offset),
        (latitude, longitude - offset),
        (latitude + offset, longitude + offset),
        (latitude + offset, longitude - offset),
        (latitude - offset, longitude + offset),
        (latitude - offset, longitude - offset),
    ]
    return points


def _fetch_ebird_observations(query_points: list, ebird_api_key: str,
                              endpoint: str, dist_km: int) -> dict:
    """通用 eBird 观测数据查询，支持 notable 和 recent 两种 endpoint。"""
    api_dist = min(dist_km, 50)
    all_observations = {}
    for lat, lng in query_points:
        try:
            url = (
                f"https://api.ebird.org/v2/data/obs/geo/recent/{endpoint}?"
                f"lat={lat:.4f}&lng={lng:.4f}&dist={api_dist}&back=7"
            )
            request = urllib.request.Request(url, headers={
                "X-eBirdApiToken": ebird_api_key,
                "User-Agent": "BirdPhotoApp/1.0",
            })
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                for obs in data:
                    species_code = obs.get("speciesCode", "")
                    if not species_code:
                        continue
                    if species_code in all_observations:
                        existing = all_observations[species_code]
                        existing["how_many"] = max(
                            existing.get("how_many", 1) or 1,
                            obs.get("howMany", 1) or 1,
                        )
                        existing["obs_count"] = existing.get("obs_count", 1) + 1
                    else:
                        all_observations[species_code] = {
                            "species_code": species_code,
                            "common_name": obs.get("comName", ""),
                            "scientific_name": obs.get("sciName", ""),
                            "location": obs.get("locName", ""),
                            "observation_date": obs.get("obsDt", ""),
                            "how_many": obs.get("howMany", 1) or 1,
                            "latitude": obs.get("lat", lat),
                            "longitude": obs.get("lng", lng),
                            "obs_count": 1,
                        }
        except Exception as exc:
            print(f"[eBird] {endpoint} 查询点 ({lat:.2f}, {lng:.2f}) 失败: {exc}")
            continue
    return all_observations


@st.cache_data(ttl=7200, show_spinner=False)
def fetch_ebird_notable_nearby(latitude: float, longitude: float,
                               ebird_api_key: str, radius_km: int = 150) -> list:
    """查询 eBird 附近稀有鸟种观测记录。缓存 2 小时。"""
    if not ebird_api_key:
        return []
    query_points = _build_query_points(latitude, longitude, radius_km)
    observations = _fetch_ebird_observations(query_points, ebird_api_key, "notable", radius_km)
    return list(observations.values())


@st.cache_data(ttl=7200, show_spinner=False)
def fetch_ebird_popular_nearby(latitude: float, longitude: float,
                               ebird_api_key: str, radius_km: int = 50) -> list:
    """查询 eBird 附近热门鸟种（按观测次数排序）。缓存 2 小时。"""
    if not ebird_api_key:
        return []
    query_points = _build_query_points(latitude, longitude, radius_km)
    observations = _fetch_ebird_observations(query_points, ebird_api_key, "", radius_km)
    result = list(observations.values())
    result.sort(key=lambda x: x.get("obs_count", 1), reverse=True)
    return result


@st.cache_data(ttl=7200, show_spinner=False)
def translate_ebird_species(species_list: list, ebird_api_key: str,
                            _cache_version: int = 3) -> dict:
    """通过 eBird taxonomy API 获取鸟种的官方简体中文名。缓存 2 小时。

    使用 locale=zh_SIM 参数直接从 eBird 获取简体中文名，比 AI 翻译更准确可靠。
    返回 {english_name: chinese_name} 映射。
    _cache_version: 缓存版本号，修改此值可强制刷新旧缓存。
    """
    if not species_list or not ebird_api_key:
        return {}

    # 收集所有 species_code
    code_to_english = {}
    for species in species_list:
        code = species.get("species_code", "")
        english_name = species.get("common_name", "")
        if code and english_name:
            code_to_english[code] = english_name
    if not code_to_english:
        return {}

    # eBird taxonomy API 支持逗号分隔的多个 species code
    species_codes = ",".join(code_to_english.keys())
    translations = {}
    try:
        url = (
            f"https://api.ebird.org/v2/ref/taxonomy/ebird?"
            f"species={species_codes}&locale=zh_SIM&fmt=json"
        )
        request = urllib.request.Request(url, headers={
            "X-eBirdApiToken": ebird_api_key,
            "User-Agent": "BirdPhotoApp/1.0",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            for taxon in data:
                code = taxon.get("speciesCode", "")
                chinese_name = taxon.get("comName", "")
                english_name = code_to_english.get(code, "")
                if english_name and chinese_name:
                    translations[english_name] = chinese_name
    except Exception as exc:
        print(f"[翻译] eBird taxonomy API 查询中文名失败: {exc}")
    return translations

def build_birding_recommendations(notable_species: list, user_species_set: set,
                                  name_translations: dict) -> list:
    """构建个性化观鸟推荐列表。

    将 eBird 稀有鸟种与用户已拍鸟种对比，标注是否为新种。
    返回按推荐优先级排序的列表。
    """
    recommendations = []
    for species in notable_species:
        english_name = species.get("common_name", "")
        chinese_name = name_translations.get(english_name, "")
        is_new_species = True
        if chinese_name and chinese_name in user_species_set:
            is_new_species = False
        elif english_name and english_name in user_species_set:
            is_new_species = False
        # 同时检查学名（eBird CSV 导出中包含学名）
        scientific_name = species.get("scientific_name", "")
        if scientific_name and scientific_name in user_species_set:
            is_new_species = False

        recommendations.append({
            "species_code": species.get("species_code", ""),
            "english_name": english_name,
            "chinese_name": chinese_name or english_name,
            "scientific_name": scientific_name,
            "location": species.get("location", ""),
            "observation_date": species.get("observation_date", ""),
            "how_many": species.get("how_many", 1),
            "is_new_species": is_new_species,
            "latitude": species.get("latitude", 0),
            "longitude": species.get("longitude", 0),
        })

    # 新种优先排序
    recommendations.sort(key=lambda x: (not x["is_new_species"], x["chinese_name"]))
    return recommendations

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_species_photo_urls(species_codes: tuple) -> dict:
    """批量获取鸟种照片 URL（通过 Macaulay Library API）。缓存 24 小时。

    返回 {species_code: photo_url} 映射。
    """
    photo_map = {}
    if not species_codes:
        return photo_map

    def _fetch_single_photo(species_code: str) -> tuple:
        try:
            url = (
                f"https://search.macaulaylibrary.org/api/v1/search?"
                f"taxonCode={species_code}&mediaType=photo"
                f"&sort=rating_rank_desc&count=1"
            )
            request = urllib.request.Request(url, headers={
                "User-Agent": "BirdPhotoApp/1.0",
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                results = data.get("results", {}).get("content", [])
                if results:
                    asset_id = results[0].get("assetId", "")
                    if asset_id:
                        photo_url = f"https://cdn.download.ams.birds.cornell.edu/api/v1/asset/{asset_id}/480"
                        return (species_code, photo_url)
        except Exception as exc:
            print(f"[照片] 获取 {species_code} 照片失败: {exc}")
        return (species_code, "")

    # 并行获取，最多 15 个（避免请求过多）
    codes_to_fetch = list(species_codes)[:15]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_single_photo, code) for code in codes_to_fetch]
        for future in concurrent.futures.as_completed(futures):
            code, url = future.result()
            if url:
                photo_map[code] = url

    return photo_map

def parse_import_csv(csv_content: str) -> list:
    """解析 eBird 或观鸟中心导出的 CSV，提取去重后的鸟种列表。

    自动检测 CSV 格式（eBird / 观鸟中心 / 通用），
    返回 [{"common_name": "...", "scientific_name": "...", "chinese_name": "..."}, ...] 去重列表。
    """
    if not csv_content:
        return []

    lines = csv_content.strip().split("\n")
    if len(lines) < 2:
        return []

    header = lines[0]
    separator = ","
    if "\t" in header:
        separator = "\t"

    columns = header.split(separator)
    columns = [col.strip().strip('"').strip("'") for col in columns]
    columns_lower = [col.lower().replace(" ", "_") for col in columns]

    # 自动检测列索引
    common_name_idx = -1
    scientific_name_idx = -1
    chinese_name_idx = -1

    for idx, col in enumerate(columns_lower):
        if col in ("common_name", "common.name", "comname", "species"):
            common_name_idx = idx
        elif col in ("scientific_name", "scientific.name", "sciname"):
            scientific_name_idx = idx
        # 中文列名（观鸟中心格式）
        if columns[idx] in ("鸟种", "鸟种名称", "中文名", "物种", "种名", "鸟名"):
            chinese_name_idx = idx
        elif columns[idx] in ("学名", "拉丁名", "拉丁学名"):
            scientific_name_idx = idx

    # 如果没找到任何已知列名，尝试启发式检测
    if common_name_idx == -1 and chinese_name_idx == -1:
        for idx, col in enumerate(columns):
            # 检测是否包含中文字符（可能是中文鸟名列）
            if any('\u4e00' <= ch <= '\u9fff' for ch in col):
                chinese_name_idx = idx
                break
        if chinese_name_idx == -1:
            common_name_idx = 0

    seen_species = set()
    species_list = []

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(separator)
        parts = [p.strip().strip('"').strip("'") for p in parts]

        common_name = ""
        scientific_name = ""
        chinese_name = ""

        if common_name_idx >= 0 and common_name_idx < len(parts):
            common_name = parts[common_name_idx].strip()
        if scientific_name_idx >= 0 and scientific_name_idx < len(parts):
            scientific_name = parts[scientific_name_idx].strip()
        if chinese_name_idx >= 0 and chinese_name_idx < len(parts):
            chinese_name = parts[chinese_name_idx].strip()

        # 确定用于去重的唯一标识
        dedup_key = chinese_name or common_name or scientific_name
        if not dedup_key or dedup_key.lower() in ("species", "common name", "scientific name", "鸟种", ""):
            continue

        if dedup_key not in seen_species:
            seen_species.add(dedup_key)
            species_list.append({
                "common_name": common_name,
                "scientific_name": scientific_name,
                "chinese_name": chinese_name,
            })

    return species_list

def import_species_to_db(user_nickname: str, species_list: list,
                         api_key: str = "") -> tuple:
    """将导入的鸟种列表批量写入数据库。

    对于英文名鸟种，先用 AI 翻译为中文名再入库。
    返回 (imported_count, skipped_count, error_msg)。
    """
    if not species_list or not user_nickname:
        return 0, 0, "无有效数据"

    base_url, db_key = _supabase_config()
    if not base_url or not db_key:
        return 0, 0, "数据库未配置"

    # 获取用户已有的鸟种（用于去重）
    existing_species = set()
    try:
        encoded_nickname = urllib.parse.quote(user_nickname)
        result = _supabase_request(
            "GET", "bird_records",
            params=f"user_nickname=eq.{encoded_nickname}&select=chinese_name,english_name"
        )
        if result and isinstance(result, list):
            for record in result:
                if record.get("chinese_name"):
                    existing_species.add(record["chinese_name"])
                if record.get("english_name"):
                    existing_species.add(record["english_name"])
    except Exception as exc:
        print(f"[导入] 查询已有记录失败: {exc}")

    # 筛选需要导入的新鸟种
    new_species = []
    for species in species_list:
        chinese = species.get("chinese_name", "")
        english = species.get("common_name", "")
        scientific = species.get("scientific_name", "")
        if chinese and chinese in existing_species:
            continue
        if english and english in existing_species:
            continue
        new_species.append(species)

    if not new_species:
        return 0, len(species_list), ""

    # 对于只有英文名没有中文名的鸟种，批量翻译
    need_translate = [s for s in new_species if not s.get("chinese_name") and s.get("common_name")]
    if need_translate and api_key:
        name_pairs = []
        for species in need_translate:
            name_pairs.append((species["common_name"], species.get("scientific_name", "")))

        names_str = "\n".join(
            f"- {common} ({scientific})" if scientific else f"- {common}"
            for common, scientific in name_pairs[:30]
        )
        try:
            client = OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            response = client.chat.completions.create(
                model="qwen-plus",
                temperature=0.1,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位资深鸟类学专家，精通 eBird/IOC 英文鸟名与中国鸟类中文名的对照关系。"
                            "你必须根据学名（拉丁名）来确定正确的中文名，而不是直译英文名。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请将以下鸟名翻译为中文名，只返回 JSON 对象：\n"
                            f"{names_str}\n\n"
                            '格式：{"English Name": "中文名", ...}（key 只用英文名）\n'
                            "必须根据学名查找对应中文名，不要直译英文名。"
                        ),
                    },
                ],
            )
            result_text = response.choices[0].message.content.strip()
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                translations = json.loads(json_match.group())
                for species in need_translate:
                    translated = translations.get(species["common_name"], "")
                    if translated:
                        species["chinese_name"] = translated
        except Exception as exc:
            print(f"[导入] 翻译失败: {exc}")

    # 批量写入数据库
    imported_count = 0
    for species in new_species:
        chinese_name = species.get("chinese_name") or species.get("common_name", "未知鸟类")
        english_name = species.get("common_name", "")
        record = {
            "user_nickname": user_nickname,
            "chinese_name": chinese_name,
            "english_name": english_name,
            "confidence": "imported",
            "score": 0,
            "identification_basis": f"从外部平台导入 | {species.get('scientific_name', '')}",
        }
        url = f"{base_url}/rest/v1/bird_records"
        headers = {
            "apikey": db_key,
            "Authorization": f"Bearer {db_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        data = json.dumps(record).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    imported_count += 1
        except Exception as exc:
            print(f"[导入] 写入 {chinese_name} 失败: {exc}")

    skipped_count = len(species_list) - imported_count
    return imported_count, skipped_count, ""

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
# 模块级缓存，确保子线程可以安全读取（必须在函数定义之前初始化）
_SUPABASE_URL_CACHE = None
_SUPABASE_KEY_CACHE = None

def _supabase_config():
    """获取 Supabase 配置，返回 (url, key) 或 (None, None)。
    结果会缓存到模块级变量，确保子线程也能安全访问。
    """
    global _SUPABASE_URL_CACHE, _SUPABASE_KEY_CACHE
    if _SUPABASE_URL_CACHE and _SUPABASE_KEY_CACHE:
        return _SUPABASE_URL_CACHE, _SUPABASE_KEY_CACHE
    try:
        _SUPABASE_URL_CACHE = st.secrets["SUPABASE_URL"]
        _SUPABASE_KEY_CACHE = st.secrets["SUPABASE_KEY"]
        return _SUPABASE_URL_CACHE, _SUPABASE_KEY_CACHE
    except (KeyError, FileNotFoundError):
        return None, None

def _supabase_request(method: str, endpoint: str, body: dict = None,
                      params: str = "", override_url: str = None,
                      override_key: str = None):
    """通用 Supabase REST API 请求（线程安全，不调用 Streamlit API）。
    可通过 override_url/override_key 直接传入配置，用于子线程调用。
    """
    if override_url and override_key:
        base_url, api_key = override_url, override_key
    else:
        base_url, api_key = _supabase_config()
    if not base_url or not api_key:
        print(f"[Supabase] 配置缺失，跳过 {method} {endpoint}")
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
            status_code = resp.status
            response_body = resp.read().decode("utf-8")
            print(f"[Supabase] {method} {endpoint} 状态码: {status_code} 响应长度: {len(response_body)}")
            # POST 插入成功时返回 201，即使响应体为空也视为成功
            if method == "POST" and status_code in (200, 201):
                if response_body:
                    return json.loads(response_body)
                return {"_inserted": True}
            if response_body:
                return json.loads(response_body)
            return None
    except urllib.error.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        print(f"[Supabase] {method} {endpoint} 失败: {http_err.code} {error_body[:200]}")
        return None
    except Exception as exc:
        print(f"[Supabase] {method} {endpoint} 异常: {type(exc).__name__}: {exc}")
        return None

def get_supabase_client():
    """检查 Supabase 是否可用，返回 True/False（兼容原有调用方式）。
    同时在主线程中预加载配置到缓存。
    """
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
                      thumbnail_b64: str, image_b64: str = "",
                      supabase_url: str = None, supabase_key: str = None) -> tuple:
    """将一条识别记录保存到 Supabase 数据库（完全线程安全，自包含 HTTP 请求）。
    返回 (success: bool, error_msg: str)。
    必须通过 supabase_url/supabase_key 直接传入配置。
    """
    db_url = supabase_url
    db_key = supabase_key
    if not db_url or not db_key:
        return False, "Supabase URL 或 Key 未传入"

    record = {
        "user_nickname": user_nickname,
        "chinese_name": result.get("chinese_name", "未知鸟类"),
        "english_name": result.get("english_name", ""),
        "original_ai_name": result.get("chinese_name", "未知鸟类"),
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
        "image_base64": image_b64,
    }

    url = f"{db_url}/rest/v1/bird_records"
    headers = {
        "apikey": db_key,
        "Authorization": f"Bearer {db_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    data = json.dumps(record).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    def _do_post(payload):
        post_data = json.dumps(payload).encode("utf-8")
        post_req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(post_req, timeout=30) as resp:
            status_code = resp.status
            resp_body = resp.read().decode("utf-8", errors="replace")
            record_id = None
            try:
                resp_data = json.loads(resp_body)
                if isinstance(resp_data, list) and resp_data:
                    record_id = resp_data[0].get("id")
                elif isinstance(resp_data, dict):
                    record_id = resp_data.get("id")
            except (json.JSONDecodeError, ValueError):
                pass
            return status_code, record_id

    try:
        status_code, record_id = _do_post(record)
        print(f"[Supabase] 保存成功: {user_nickname} - {result.get('chinese_name', '未知')} (HTTP {status_code}, id={record_id})")
        return True, "", record_id
    except urllib.error.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        # 如果写入失败且包含 image_base64，可能是字段不存在，去掉后重试
        if "image_base64" in record and record["image_base64"]:
            try:
                fallback_record = {k: v for k, v in record.items() if k != "image_base64"}
                status_code, record_id = _do_post(fallback_record)
                print(f"[Supabase] 降级保存成功(无image_base64): {user_nickname} (HTTP {status_code}, id={record_id})")
                return True, "", record_id
            except Exception:
                pass
        msg = f"HTTP {http_err.code}: {error_body[:200]}"
        print(f"[Supabase] 保存失败: {msg}")
        return False, msg, None
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"[Supabase] 保存异常: {msg}")
        return False, msg, None


@st.cache_data(ttl=30, show_spinner=False)
def fetch_user_history(_supabase_client, user_nickname: str, limit: int = 1000) -> list:
    """查询用户的历史识别记录（缓存 30 秒）。limit 默认 1000 以容纳导入记录。"""
    if not _supabase_client:
        return []
    try:
        encoded_nickname = urllib.parse.quote(user_nickname)
        params = (
            f"user_nickname=eq.{encoded_nickname}"
            f"&order=created_at.desc"
            f"&limit={limit}"
            f"&select=id,chinese_name,english_name,score,created_at,thumbnail_base64,confidence,identification_basis"
        )
        result = _supabase_request("GET", "bird_records", params=params)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _get_import_sync_info(supabase_client, user_nickname: str) -> dict:
    """获取用户导入记录的同步信息（鸟种数和最后同步时间）。"""
    if not supabase_client or not user_nickname:
        return {"count": 0, "last_sync": ""}
    try:
        encoded_nickname = urllib.parse.quote(user_nickname)
        params = (
            f"user_nickname=eq.{encoded_nickname}"
            f"&confidence=eq.imported"
            f"&select=chinese_name,created_at"
            f"&order=created_at.desc"
            f"&limit=500"
        )
        result = _supabase_request("GET", "bird_records", params=params)
        if not result or not isinstance(result, list):
            return {"count": 0, "last_sync": ""}

        # 去重统计鸟种数
        species_set = set()
        for record in result:
            name = record.get("chinese_name", "")
            if name:
                species_set.add(name)

        # 最后同步时间（取最新的 created_at）
        last_sync = ""
        if result:
            raw_date = result[0].get("created_at", "")
            if raw_date:
                last_sync = raw_date[:10]

        return {"count": len(species_set), "last_sync": last_sync}
    except Exception as exc:
        print(f"[同步信息] 查询失败: {exc}")
        return {"count": 0, "last_sync": ""}

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


def update_record_name_in_db(record_id: int, new_chinese_name: str, new_english_name: str = "",
                             user_nickname: str = "", old_chinese_name: str = "",
                             shoot_date: str = "") -> bool:
    """更新数据库中某条记录的鸟种名称（中文名 + 英文名）。

    优先通过 record_id 定位记录；如果 record_id 为 None，
    则通过 user_nickname + old_chinese_name + shoot_date 组合定位。
    使用与 fetch_user_history 相同的 _supabase_request 通道确保一致性。
    """
    base_url, api_key = _supabase_config()
    if not base_url or not api_key:
        print("[Supabase] 更新失败: 配置缺失")
        return False

    # 构建查询参数：优先用 id，否则用组合条件定位
    if record_id:
        query_params = f"id=eq.{record_id}"
    elif user_nickname and old_chinese_name:
        encoded_nickname = urllib.parse.quote(user_nickname)
        encoded_name = urllib.parse.quote(old_chinese_name)
        query_params = f"user_nickname=eq.{encoded_nickname}&chinese_name=eq.{encoded_name}"
        if shoot_date:
            query_params += f"&shoot_date=eq.{urllib.parse.quote(shoot_date)}"
    else:
        print("[Supabase] 更新失败: 无法定位记录（无 id 且无组合条件）")
        return False

    update_data = {"chinese_name": new_chinese_name, "user_corrected_name": new_chinese_name}
    if new_english_name:
        update_data["english_name"] = new_english_name

    # 使用 urllib 直接发 PATCH 请求（与 _supabase_request 相同的方式）
    url = f"{base_url}/rest/v1/bird_records?{query_params}"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    data = json.dumps(update_data).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status_code = resp.status
            print(f"[Supabase] 更新鸟名成功: {old_chinese_name} -> {new_chinese_name} (HTTP {status_code})")
            return status_code in (200, 204)
    except urllib.error.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        print(f"[Supabase] 更新鸟名失败: HTTP {http_err.code} {error_body[:200]}")
        return False
    except Exception as exc:
        print(f"[Supabase] 更新鸟名异常: {type(exc).__name__}: {exc}")
        return False

def fetch_user_stats_from_records(records: list) -> dict:
    """从已有的历史记录中计算统计数据（避免额外的数据库请求）。

    区分拍照识别记录和导入记录：
    - 鸟种数：包含全部（拍照 + 导入）
    - 累计识别 / 平均分 / 最高分：仅统计拍照识别记录
    - 导入鸟种数：单独统计
    """
    if not records:
        return {"total": 0, "species": 0, "avg_score": 0, "best_score": 0,
                "imported_species": 0, "photo_total": 0}

    all_species = set()
    imported_species = set()
    photo_records = []

    for record in records:
        chinese_name = record.get("chinese_name", "")
        if chinese_name:
            all_species.add(chinese_name)
        if record.get("confidence") == "imported":
            if chinese_name:
                imported_species.add(chinese_name)
        else:
            photo_records.append(record)

    scores = [r["score"] for r in photo_records if r.get("score")]
    avg_score = sum(scores) / len(scores) if scores else 0
    best_score = max(scores) if scores else 0

    return {
        "total": len(records),
        "photo_total": len(photo_records),
        "species": len(all_species),
        "imported_species": len(imported_species),
        "avg_score": round(avg_score, 1),
        "best_score": best_score,
    }


@st.cache_data(ttl=60, show_spinner=False)
def fetch_top_photos(limit: int = 10) -> list:
    """查询全局评分最高的照片（缓存 60 秒）"""
    try:
        params = (
            f"select=id,user_nickname,chinese_name,english_name,score,"
            f"image_base64,thumbnail_base64,shoot_date,identification_basis,bird_description,"
            f"score_sharpness,score_composition,score_lighting,"
            f"score_background,score_pose,score_artistry,"
            f"order_chinese,family_chinese"
            f"&order=score.desc"
            f"&limit={limit}"
            f"&score=gt.0"
        )
        result = _supabase_request("GET", "bird_records", params=params)
        if isinstance(result, list):
            return result
        # 如果查询失败（可能 image_base64 字段不存在），降级查询不含该字段
        params_fallback = (
            f"select=id,user_nickname,chinese_name,english_name,score,"
            f"thumbnail_base64,shoot_date,identification_basis,bird_description,"
            f"score_sharpness,score_composition,score_lighting,"
            f"score_background,score_pose,score_artistry,"
            f"order_chinese,family_chinese"
            f"&order=score.desc"
            f"&limit={limit}"
            f"&score=gt.0"
        )
        result_fallback = _supabase_request("GET", "bird_records", params=params_fallback)
        return result_fallback if isinstance(result_fallback, list) else []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def fetch_leaderboard(limit: int = 20) -> list:
    """查询所有用户的排行榜数据，按鸟种数降序排列（缓存 60 秒）"""
    try:
        params = "select=user_nickname,chinese_name,score,confidence&limit=2000"
        result = _supabase_request("GET", "bird_records", params=params)
        records = result if isinstance(result, list) else []
        if not records:
            return []
        # 按用户聚合统计（包含所有记录：拍照识别 + 导入记录）
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
            species_list = sorted(data["species"])
            leaderboard.append({
                "nickname": nickname,
                "species": len(species_list),
                "species_list": species_list,
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
# 顶部条：Logo + 登录/昵称（紧凑单行）
# ============================================================
# 顶部条：Logo + 用户名/登录
if not st.session_state["user_nickname"]:
    # 未登录：只显示 Logo
    st.markdown(
        '<div class="hero-section">'
        '<div style="display:flex;align-items:center;gap:14px;">'
        '<span style="font-size:34px;">🦅</span>'
        '<div>'
        '<h1 style="font-size:24px;font-weight:700;margin:0;color:#fff;letter-spacing:-0.02em;">影禽</h1>'
        '<p style="font-size:12px;color:rgba(255,255,255,0.85);margin:2px 0 0;">BirdEye · 发现身边的鸟 · AI 识别与摄影评分</p>'
        '</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
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

    # 检测退出参数
    if st.query_params.get("logout") == "1":
        st.session_state["user_nickname"] = ""
        st.query_params.clear()
        st.session_state.pop("identified_cache", None)
        st.session_state.pop("results_with_bytes", None)
        st.session_state.pop("zip_bytes", None)
        st.rerun()

    # 已登录：全宽一体化顶栏 — Logo 左 + 用户名&退出 右
    st.markdown(
        f'<div class="hero-section">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;">'
        f'<div style="display:flex;align-items:center;gap:14px;">'
        f'<span style="font-size:34px;">🦅</span>'
        f'<div>'
        f'<h1 style="font-size:24px;font-weight:700;margin:0;color:#fff;letter-spacing:-0.02em;">影禽</h1>'
        f'<p style="font-size:12px;color:rgba(255,255,255,0.85);margin:2px 0 0;">BirdEye · 发现身边的鸟 · AI 识别与摄影评分</p>'
        f'</div>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<span style="font-size:14px;">🐦</span>'
        f'<span style="font-size:14px;font-weight:600;color:#fff;">{nickname_display}</span>'
        f'<span style="color:rgba(255,255,255,0.4);font-size:12px;">|</span>'
        f'<a href="?logout=1" target="_self" '
        f'style="font-size:12px;color:rgba(255,255,255,0.7);text-decoration:none;"'
        f'>退出</a>'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

user_nickname = st.session_state["user_nickname"]

# ============================================================
# ============================================================
# 主功能区：五个 Tab 页签
# ============================================================
# 初始化定位 session state
if "loc_province" not in st.session_state:
    st.session_state["loc_province"] = "浙江省"
if "loc_city" not in st.session_state:
    st.session_state["loc_city"] = "杭州市"
if "loc_district" not in st.session_state:
    st.session_state["loc_district"] = ""
if "geo_detected" not in st.session_state:
    st.session_state["geo_detected"] = False

ebird_api_key = ""
try:
    ebird_api_key = st.secrets.get("EBIRD_API_KEY", "")
except (KeyError, FileNotFoundError):
    pass


tab_explore, tab_upload, tab_history, tab_gallery, tab_rank = st.tabs(
    ["🔭 附近推荐", "📷 添加记录", "📚 观鸟记录", "📸 佳作榜", "🏆 排行榜"]
)

# ---- Tab 1: 附近推荐 ----
with tab_explore:
    if supabase_client and user_nickname and ebird_api_key:
        # 浏览器 Geolocation 自动定位（仅首次）
        if not st.session_state["geo_detected"]:
            geo_js = """
            <div id="geo-status" style="font-size:12px;color:#888;padding:4px 0;">📍 正在获取定位...</div>
            <script>
            (function() {
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(pos) {
                            const lat = pos.coords.latitude.toFixed(4);
                            const lon = pos.coords.longitude.toFixed(4);
                            document.getElementById('geo-status').innerHTML =
                                '📍 已获取定位: ' + lat + ', ' + lon;
                            // Send to Streamlit via query params
                            const url = new URL(window.parent.location);
                            url.searchParams.set('geo_lat', lat);
                            url.searchParams.set('geo_lon', lon);
                            window.parent.history.replaceState({}, '', url);
                            // Navigate with geo params to trigger Streamlit rerun (single reload)
                            window.parent.location.href = url.toString();
                        },
                        function(err) {
                            document.getElementById('geo-status').innerHTML =
                                '📍 定位失败，请手动选择位置';
                        },
                        {timeout: 8000, maximumAge: 300000}
                    );
                }
            })();
            </script>
            """
            # 检查是否已有 geo 参数
            geo_lat_str = st.query_params.get("geo_lat", "")
            geo_lon_str = st.query_params.get("geo_lon", "")
            if geo_lat_str and geo_lon_str:
                # 一次性处理 geo 参数：解析 → 设置 state → 清理参数
                try:
                    geo_lat = float(geo_lat_str)
                    geo_lon = float(geo_lon_str)
                    geo_result = reverse_geocode(geo_lat, geo_lon)
                    matched_province = match_province_in_data(geo_result.get("province", ""))
                    matched_city = match_city_in_data(matched_province, geo_result.get("city", ""))
                    if matched_province:
                        st.session_state["loc_province"] = matched_province
                    if matched_city:
                        st.session_state["loc_city"] = matched_city
                    if geo_result.get("district"):
                        st.session_state["loc_district"] = geo_result["district"]
                except (ValueError, TypeError):
                    pass
                st.session_state["geo_detected"] = True
                # 批量清理 geo URL 参数（只触发一次 rerun）
                del st.query_params["geo_lat"]
                del st.query_params["geo_lon"]
                st.rerun()
            else:
                import streamlit.components.v1 as components
                components.html(geo_js, height=30)

        # 省市区三级下拉选择
        province_list = list(CHINA_PROVINCES_CITIES.keys())
        current_province = st.session_state.get("loc_province", "浙江省")
        province_index = province_list.index(current_province) if current_province in province_list else 0

        loc_col1, loc_col2, loc_col3 = st.columns([2, 2, 2])
        with loc_col1:
            selected_province = st.selectbox(
                "省份", province_list, index=province_index,
                key="sel_province", label_visibility="collapsed",
            )
        city_list = CHINA_PROVINCES_CITIES.get(selected_province, [""])
        current_city = st.session_state.get("loc_city", "")
        city_index = city_list.index(current_city) if current_city in city_list else 0
        with loc_col2:
            selected_city = st.selectbox(
                "城市", city_list, index=city_index,
                key="sel_city", label_visibility="collapsed",
            )
        with loc_col3:
            selected_district = st.text_input(
                "区/镇（可选）",
                value=st.session_state.get("loc_district", ""),
                key="sel_district",
                placeholder="区/县/镇",
                label_visibility="collapsed",
            )

        # 更新 session state
        st.session_state["loc_province"] = selected_province
        st.session_state["loc_city"] = selected_city
        st.session_state["loc_district"] = selected_district

        # 搜索范围 & 鸟种类型选择
        range_col, type_col = st.columns([3, 3])
        distance_options = {
            "5km": 5, "10km": 10, "50km": 50,
            "100km": 100, "150km": 150, "200km": 200,
        }
        with range_col:
            selected_range_label = st.selectbox(
                "搜索范围",
                list(distance_options.keys()),
                index=4,
                key="sel_range",
            )
        selected_radius_km = distance_options[selected_range_label]
        bird_type_options = ["🔭 稀有鸟种", "🔥 热门鸟种"]
        with type_col:
            selected_bird_type = st.radio(
                "鸟种类型",
                bird_type_options,
                index=0,
                key="sel_bird_type",
                horizontal=True,
            )
        is_notable_mode = selected_bird_type == bird_type_options[0]

        # 拼接地名用于地理编码
        location_query = selected_city
        if selected_district:
            location_query = f"{selected_city}{selected_district}"

        birding_lat, birding_lon = geocode_city(location_query)

        if birding_lat and birding_lon:
            weather = fetch_current_weather(birding_lat, birding_lon)
            if is_notable_mode:
                bird_species = fetch_ebird_notable_nearby(
                    birding_lat, birding_lon, ebird_api_key, radius_km=selected_radius_km,
                )
            else:
                bird_species = fetch_ebird_popular_nearby(
                    birding_lat, birding_lon, ebird_api_key, radius_km=selected_radius_km,
                )

            if weather:
                from datetime import datetime as _dt
                today_str = _dt.now().strftime("%m月%d日 %A").replace(
                    "Monday", "周一").replace("Tuesday", "周二").replace(
                    "Wednesday", "周三").replace("Thursday", "周四").replace(
                    "Friday", "周五").replace("Saturday", "周六").replace(
                    "Sunday", "周日")
                st.markdown(
                    f'<div style="background:#e8f5e9; padding:10px 14px; '
                    f'border-radius:12px; margin-bottom:8px;">'
                    f'<span style="font-size:13px;">'
                    f'📅 <b>{today_str}</b> &nbsp;·&nbsp; '
                    f'{weather.get("emoji", "🌡️")} <b>{weather.get("description", "")}</b> '
                    f'{weather.get("temperature", 0)}°C · 风速 {weather.get("windspeed", 0)}km/h'
                    f'</span><br>'
                    f'<span style="font-size:12px; color:#888;">'
                    f'观鸟适宜度：{weather.get("birding_emoji", "")} {weather.get("birding_score", "")}'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )

            if bird_species:
                name_translations = translate_ebird_species(bird_species, ebird_api_key)

                user_species_set = set()
                if supabase_client and st.session_state.get("user_nickname"):
                    user_history = fetch_user_history(
                        supabase_client, st.session_state["user_nickname"]
                    )
                    for record in user_history:
                        if record.get("chinese_name"):
                            user_species_set.add(record["chinese_name"])
                        if record.get("english_name"):
                            user_species_set.add(record["english_name"])

                recommendations = build_birding_recommendations(
                    bird_species, user_species_set, name_translations
                )

                species_codes_for_photos = tuple(
                    bird["species_code"] for bird in recommendations[:15]
                    if bird.get("species_code")
                )
                photo_urls = fetch_species_photo_urls(species_codes_for_photos)

                new_count = sum(1 for r in recommendations if r["is_new_species"])
                total_count = len(recommendations)

                type_label = "稀有鸟种" if is_notable_mode else "热门鸟种"
                st.markdown(
                    f'<p style="font-size:12px; color:#888; margin:4px 0 8px;">'
                    f'📍 {location_query}周边 {selected_range_label} · 近 7 天发现 <b style="color:#1a3a5c;">'
                    f'{total_count}</b> 种{type_label}'
                    f'{"，其中 <b style=color:#4a7c59;>" + str(new_count) + "</b> 种你还没拍过 🎯" if new_count > 0 else ""}'
                    f'</p>',
                    unsafe_allow_html=True,
                )

                bird_cards_html = ""
                for bird in recommendations[:15]:
                    new_badge_html = (
                        '<span style="position:absolute; top:6px; right:6px; '
                        'background:#4a7c59; color:#fff; font-size:9px; '
                        'padding:2px 6px; border-radius:6px; font-weight:600; '
                        'letter-spacing:0.02em;">新种</span>'
                        if bird["is_new_species"] else ""
                    )
                    date_str = bird.get("observation_date", "")[:10]
                    how_many = bird.get("how_many", 1)
                    count_str = f" · {how_many}只" if how_many and how_many > 1 else ""

                    bird_photo_url = photo_urls.get(bird.get("species_code", ""), "")
                    if bird_photo_url:
                        card_img_html = (
                            f'<img src="{bird_photo_url}" '
                            f'style="width:100%;height:140px;object-fit:cover;'
                            f'border-radius:10px 10px 0 0;" '
                            f'loading="lazy" '
                            f'onerror="this.parentElement.innerHTML='
                            f"'<div style=\\'width:100%;height:140px;background:"
                            f"linear-gradient(135deg,#1a3a5c,#2d6a4f);border-radius:"
                            f"10px 10px 0 0;display:flex;align-items:center;"
                            f"justify-content:center;font-size:40px;\\'>🐦</div>'"
                            f'" />'
                        )
                    else:
                        card_img_html = (
                            '<div style="width:100%;height:140px;'
                            'background:linear-gradient(135deg,#1a3a5c,#2d6a4f);'
                            'border-radius:10px 10px 0 0;display:flex;'
                            'align-items:center;justify-content:center;'
                            'font-size:40px;">🐦</div>'
                        )

                    ebird_species_url = f"https://ebird.org/species/{bird.get('species_code', '')}"

                    bird_cards_html += (
                        f'<a href="{ebird_species_url}" target="_blank" '
                        f'style="text-decoration:none; color:inherit;">'
                        f'<div style="min-width:160px;max-width:160px;background:#fff;'
                        f'border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);'
                        f'flex-shrink:0;overflow:hidden;position:relative;">'
                        f'{new_badge_html}'
                        f'{card_img_html}'
                        f'<div style="padding:8px 10px;">'
                        f'<div style="font-size:13px;font-weight:600;color:#1a3a5c;'
                        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                        f'{bird["chinese_name"]}</div>'
                        f'<div style="font-size:10px;color:#888;margin-top:2px;'
                        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                        f'{bird.get("english_name", "")}</div>'
                        f'<div style="font-size:10px;color:#888;margin-top:1px;'
                        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                        f'📍 {bird.get("location", "未知")}</div>'
                        f'<div style="font-size:10px;color:#aaa;margin-top:1px;">'
                        f'{date_str}{count_str}</div>'
                        f'</div></div></a>'
                    )

                st.markdown(
                    f'<div style="display:flex;gap:10px;overflow-x:auto;'
                    f'padding:4px 0 8px;-webkit-overflow-scrolling:touch;">'
                    f'{bird_cards_html}</div>',
                    unsafe_allow_html=True,
                )

                if total_count > 15:
                    st.caption(f"还有 {total_count - 15} 种未显示…")
            else:
                no_result_label = "稀有鸟种" if is_notable_mode else "热门鸟种"
                st.info(f"🔍 近 7 天该区域暂无{no_result_label}记录，试试换个城市或扩大搜索范围？")
        else:
            st.warning("⚠️ 无法识别该城市，请输入更具体的地名")

    else:
        st.info("🔭 请先设置昵称，即可查看附近鸟种推荐")

# ============================================================
# ---- Tab 2: 添加记录 ----
with tab_upload:
    if user_nickname:
        upload_col, import_col = st.columns(2, gap="medium")

        with upload_col:
            st.markdown(
                '<p style="font-size:13px;font-weight:600;color:#1a3a5c;margin:0 0 6px;">'
                '📷 方式一：上传照片识别</p>'
                f'<p style="font-size:11px;color:#888;margin:0 0 8px;">'
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
                    f'<p style="font-size:14px; color:#888; margin:4px 0;">已选择 '
                    f'<b style="color:#1a3a5c;">{len(uploaded_files)}</b> 张照片</p>',
                    unsafe_allow_html=True,
                )
            else:
                # 未上传时显示示范图片，与右栏高度对齐
                st.markdown(
                    '<div style="display:flex;gap:8px;margin-top:8px;">'
                    '<div style="flex:1;background:linear-gradient(135deg,#e8f4fd,#d1ecf9);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🦅</div>'
                    '<p style="font-size:10px;color:#4a7c59;margin:4px 0 0;font-weight:600;">猛禽</p>'
                    '</div>'
                    '<div style="flex:1;background:linear-gradient(135deg,#fef3e2,#fde8c8);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🐦</div>'
                    '<p style="font-size:10px;color:#e67e22;margin:4px 0 0;font-weight:600;">雀形目</p>'
                    '</div>'
                    '<div style="flex:1;background:linear-gradient(135deg,#e8f8e8,#d4f0d4);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🦆</div>'
                    '<p style="font-size:10px;color:#27ae60;margin:4px 0 0;font-weight:600;">水鸟</p>'
                    '</div>'
                    '</div>'
                    '<div style="display:flex;gap:8px;margin-top:6px;">'
                    '<div style="flex:1;background:linear-gradient(135deg,#f3e8fd,#e8d5f5);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🦉</div>'
                    '<p style="font-size:10px;color:#8e44ad;margin:4px 0 0;font-weight:600;">鸮形目</p>'
                    '</div>'
                    '<div style="flex:1;background:linear-gradient(135deg,#fde8e8,#f5d4d4);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🦜</div>'
                    '<p style="font-size:10px;color:#e74c3c;margin:4px 0 0;font-weight:600;">鹦形目</p>'
                    '</div>'
                    '<div style="flex:1;background:linear-gradient(135deg,#e8f0fd,#d4e4f5);'
                    'border-radius:10px;padding:16px 8px;text-align:center;">'
                    '<div style="font-size:32px;">🦩</div>'
                    '<p style="font-size:10px;color:#3498db;margin:4px 0 0;font-weight:600;">涉禽</p>'
                    '</div>'
                    '</div>'
                    '<p style="font-size:10px;color:#aaa;text-align:center;margin:6px 0 0;">'
                    '支持识别 1000+ 种鸟类 · AI 自动评分</p>',
                    unsafe_allow_html=True,
                )

        with import_col:
            st.markdown(
                '<p style="font-size:13px;font-weight:600;color:#1a3a5c;margin:0 0 6px;">'
                '📥 方式二：导入观鸟记录</p>'
                '<p style="font-size:11px;color:#888;margin:0 0 8px;">'
                '导入 eBird / 观鸟中心的历史记录，让推荐更精准</p>',
                unsafe_allow_html=True,
            )
            if supabase_client:
                import_sync_info = _get_import_sync_info(
                    supabase_client, st.session_state["user_nickname"]
                )
                last_sync_date = import_sync_info.get("last_sync", "")
                imported_total = import_sync_info.get("count", 0)

                if imported_total > 0:
                    st.markdown(
                        f'<div style="background:rgba(52,199,89,0.08); padding:8px 12px; '
                        f'border-radius:10px; margin-bottom:8px;">'
                        f'<span style="font-size:12px; font-weight:600; color:#1a3a5c;">'
                        f'✅ 已同步 {imported_total} 种</span>'
                        f'<span style="font-size:10px; color:#888; margin-left:8px;">'
                        f'📅 {last_sync_date}</span></div>',
                        unsafe_allow_html=True,
                    )

                import_source = st.radio(
                    "数据来源",
                    ["eBird", "中国观鸟记录中心", "其他（通用 CSV）"],
                    horizontal=True,
                    key="import_source_radio",
                    label_visibility="collapsed",
                )

                if import_source == "eBird":
                    st.markdown(
                        '<div style="background:#f1f8e9; padding:6px 10px; '
                        'border-radius:8px; margin:4px 0 6px;">'
                        '<p style="font-size:11px; color:#888; margin:0; line-height:1.5;">'
                        '1. 打开 <a href="https://ebird.org/downloadMyData" target="_blank" '
                        'style="color:#4a7c59;">ebird.org/downloadMyData</a><br>'
                        '2. 登录并点击 "Download My Data"<br>'
                        '3. 上传下载的 CSV 文件</p></div>',
                        unsafe_allow_html=True,
                    )
                elif import_source == "中国观鸟记录中心":
                    st.markdown(
                        '<div style="background:#f1f8e9; padding:6px 10px; '
                        'border-radius:8px; margin:4px 0 6px;">'
                        '<p style="font-size:11px; color:#888; margin:0; line-height:1.5;">'
                        '1. 打开 <a href="https://www.birdreport.cn/" target="_blank" '
                        'style="color:#4a7c59;">birdreport.cn</a> 并登录<br>'
                        '2. 进入「我的记录」导出 CSV<br>'
                        '3. 上传下载的 CSV 文件</p></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<p style="font-size:11px; color:#aaa; margin:2px 0 4px;">'
                        '支持包含鸟种名称列的 CSV 文件</p>',
                        unsafe_allow_html=True,
                    )

                import_csv_file = st.file_uploader(
                    "上传 CSV",
                    type=["csv"],
                    key="import_csv_uploader",
                    label_visibility="collapsed",
                )

                if import_csv_file:
                    csv_content = import_csv_file.getvalue().decode("utf-8", errors="ignore")
                    parsed_species = parse_import_csv(csv_content)

                    if parsed_species:
                        st.markdown(
                            f'<p style="font-size:12px; color:#1a3a5c; margin:4px 0;">'
                            f'📋 检测到 <b>{len(parsed_species)}</b> 个鸟种</p>',
                            unsafe_allow_html=True,
                        )
                        preview_names = []
                        for species in parsed_species[:8]:
                            name = species.get("chinese_name") or species.get("common_name", "")
                            if name:
                                preview_names.append(name)
                        if preview_names:
                            st.markdown(
                                f'<p style="font-size:11px; color:#888; margin:2px 0 6px;">'
                                f'{" · ".join(preview_names)}'
                                f'{"…" if len(parsed_species) > 8 else ""}</p>',
                                unsafe_allow_html=True,
                            )

                        import_action_label = "🔄 增量更新" if imported_total > 0 else "🚀 开始导入"
                        if st.button(import_action_label, type="primary", use_container_width=True):
                            with st.spinner("正在导入并翻译鸟种名称…"):
                                imported, skipped, error = import_species_to_db(
                                    st.session_state["user_nickname"],
                                    parsed_species,
                                    api_key,
                                )
                            if error:
                                st.error(f"导入出错：{error}")
                            elif imported > 0:
                                st.success(
                                    f"✅ 成功导入 **{imported}** 个新鸟种！"
                                    f"{'（' + str(skipped) + ' 个已存在）' if skipped > 0 else ''}"
                                )
                                fetch_user_history.clear()
                                st.rerun()
                            else:
                                st.info("数据已是最新 👍")
                    else:
                        st.warning("⚠️ 未能识别鸟种，请检查 CSV 格式")

        # ============================================================
        # 上传后自动识别
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
                progress_text = st.empty()
    
                current_nickname = st.session_state.get("user_nickname", "")
                # 在主线程中读取 Supabase 配置，通过闭包传入子线程（彻底避免子线程访问 st.secrets）
                _sb_url, _sb_key = _supabase_config()
    
                # 用于子线程向主线程报告当前步骤的共享状态
                import threading
                _file_progress_lock = threading.Lock()
                _file_progress = {}  # {file_name: "当前步骤描述"}
    
                def _update_file_step(file_name: str, step: str):
                    with _file_progress_lock:
                        _file_progress[file_name] = step
    
                def _process_single_file(uploaded_file):
                    """在线程中处理单张照片：EXIF提取 + 编码 + AI识别 + 保存数据库"""
                    fname = uploaded_file.name
                    _update_file_step(fname, "📂 读取图片信息…")
                    image_bytes = uploaded_file.getvalue()
                    suffix = Path(fname).suffix.lower()
    
                    _update_file_step(fname, "📷 提取 EXIF 数据…")
                    exif_info = extract_exif_info(image_bytes, fname)
    
                    if exif_info.get("gps_lat") and exif_info.get("gps_lon"):
                        _update_file_step(fname, "🗺️ 解析拍摄地点…")
                        geocoded_location = reverse_geocode(exif_info["gps_lat"], exif_info["gps_lon"])
                        if geocoded_location:
                            exif_info["geocoded_location"] = geocoded_location
    
                    _update_file_step(fname, "🔄 压缩编码图片…")
                    image_base64 = encode_image_to_base64(image_bytes, filename=fname)
    
                    _update_file_step(fname, "🤖 AI 识别鸟种中…（耗时较长）")
                    result = identify_bird(image_base64, api_key, exif_info)
    
                    shoot_date = ""
                    if exif_info.get("shoot_time"):
                        shoot_date = exif_info["shoot_time"][:8]
                    result["shoot_date"] = shoot_date
                    result["original_name"] = fname
    
                    # 生成缩略图并保存到数据库（通过闭包传入 URL/Key，不依赖 st.secrets）
                    db_saved = False
                    db_error = ""
                    db_record_id = None
                    if supabase_client and current_nickname and _sb_url and _sb_key:
                        _update_file_step(fname, "💾 保存识别记录…")
                        thumb_b64 = generate_thumbnail_base64(image_bytes, fname)
                        # 生成大图 base64（1200px 宽），如果失败不影响上传
                        try:
                            full_img_b64 = generate_thumbnail_base64(image_bytes, fname, max_width=1200)
                        except Exception:
                            full_img_b64 = ""
                        db_saved, db_error, db_record_id = save_record_to_db(
                            supabase_client, current_nickname, result, thumb_b64,
                            image_b64=full_img_b64,
                            supabase_url=_sb_url, supabase_key=_sb_key,
                        )
                    elif not _sb_url or not _sb_key:
                        db_error = "Supabase 配置在主线程中读取失败"
                    result["_db_saved"] = db_saved
                    result["_db_error"] = db_error
                    result["_db_record_id"] = db_record_id if db_saved else None
    
                    _update_file_step(fname, "✅ 完成")
                    return uploaded_file, {
                        "result": result,
                        "image_bytes": image_bytes,
                        "suffix": suffix,
                    }
    
                # 并发识别（最多 3 个线程，避免 API 限流）
                max_workers = min(3, len(new_files))
                completed_count = 0
                db_save_failures = []
    
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_file = {
                        executor.submit(_process_single_file, f): f
                        for f in new_files
                    }
                    pending_futures = set(future_to_file.keys())
                    while pending_futures:
                        # 每 0.3 秒轮询一次，更新进度显示
                        done_batch, pending_futures = concurrent.futures.wait(
                            pending_futures, timeout=0.3,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        # 构建当前所有文件的进度摘要
                        with _file_progress_lock:
                            step_lines = []
                            for fname_key, step_desc in _file_progress.items():
                                short_name = fname_key if len(fname_key) <= 20 else fname_key[:17] + "…"
                                step_lines.append(f"**{short_name}**　{step_desc}")
                        progress_text.markdown("　\n".join(step_lines) if step_lines else "⏳ 准备中…")
    
                        for future in done_batch:
                            completed_count += 1
                            progress_bar.progress(
                                completed_count / len(new_files),
                                text=f"🔍 已完成 {completed_count}/{len(new_files)}",
                            )
                            try:
                                done_file, cache_entry = future.result()
                                fkey = make_file_key(done_file)
                                st.session_state["identified_cache"][fkey] = cache_entry
                                if not cache_entry["result"].get("_db_saved", False):
                                    db_save_failures.append(done_file.name)
                            except Exception as exc:
                                failed_name = future_to_file[future].name
                                st.toast(f"⚠️ {failed_name} 识别失败: {exc}", icon="⚠️")
    
                progress_text.empty()
    
                if db_save_failures:
                    # 收集具体的错误原因
                    error_details = []
                    for fkey_check, cache_check in st.session_state["identified_cache"].items():
                        db_err = cache_check["result"].get("_db_error", "")
                        if db_err:
                            error_details.append(db_err)
                    error_hint = f" 错误详情：{error_details[0]}" if error_details else ""
                    st.warning(
                        f"⚠️ 以下照片的识别结果未能保存到云端数据库：{', '.join(db_save_failures)}。{error_hint}"
                    )
    
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
        # 展示结果
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
                                    # 在原图上绘制 AI 识别区域高亮框
                                    annotated_img = draw_bird_bbox(preview_img.copy(), bird_bbox)
                                    # 裁剪聚焦到鸟的区域用于展示
                                    cropped_img = crop_to_bird(annotated_img.copy(), bird_bbox)
                                    st.image(cropped_img, use_container_width=True)
                                except Exception:
                                    st.image(preview_img, use_container_width=True)
                            else:
                                st.image(preview_img, use_container_width=True)
                        else:
                            st.text("无法预览")
    
                        # 低置信度提示
                        candidates = result.get("candidates", [])
                        if candidates:
                            max_similarity = max(c.get("similarity", 0) for c in candidates)
                            if max_similarity < 50:
                                st.markdown(
                                    '<div style="background:rgba(255,149,0,0.12); color:#cc7700; '
                                    'padding:6px 10px; border-radius:8px; font-size:12px; '
                                    'margin-bottom:6px; text-align:center;">'
                                    '⚠️ AI 不太确定，建议人工确认或提供更清晰的照片</div>',
                                    unsafe_allow_html=True,
                                )
    
                        # 候选鸟种选择（带相似度百分比）
                        card_index = row_start + col_idx
                        select_key = f"select_species_{card_index}"
                        current_name = result.get("chinese_name", "未知")
    
                        if candidates and len(candidates) > 0:
                            # 构建选项列表：「中文名 (相似度%)」
                            option_labels = []
                            option_names = []
                            for candidate in candidates:
                                cname = candidate.get("chinese_name", "未知")
                                similarity = candidate.get("similarity", 0)
                                reason = candidate.get("reason", "")
                                label = f"{cname}（{similarity}%）- {reason}" if reason else f"{cname}（{similarity}%）"
                                option_labels.append(label)
                                option_names.append(cname)
    
                            # 如果当前名称不在候选列表中，添加到首位
                            if current_name not in option_names:
                                option_labels.insert(0, f"{current_name}（当前）")
                                option_names.insert(0, current_name)
    
                            # 默认选中当前名称
                            default_index = option_names.index(current_name) if current_name in option_names else 0
    
                            selected_label = st.selectbox(
                                "选择鸟种",
                                options=option_labels,
                                index=default_index,
                                key=select_key,
                                label_visibility="collapsed",
                            )
                            selected_index = option_labels.index(selected_label)
                            selected_name = option_names[selected_index]
    
                            # 获取选中候选种的英文名
                            selected_english = result.get("english_name", "")
                            for candidate in candidates:
                                if candidate.get("chinese_name") == selected_name:
                                    selected_english = candidate.get("english_name", selected_english)
                                    break
    
                            # 选择了不同鸟种时，显示确认按钮
                            if selected_name != current_name:
                                confirm_key = f"confirm_species_{card_index}"
                                if st.button(f"✅ 确认修改为「{selected_name}」", key=confirm_key, use_container_width=True):
                                    old_name = current_name
                                    result["chinese_name"] = selected_name
                                    result["english_name"] = selected_english
                                    if card_index < len(results_with_bytes):
                                        results_with_bytes[card_index]["result"]["chinese_name"] = selected_name
                                        results_with_bytes[card_index]["result"]["english_name"] = selected_english
                                    # 同步写回 session_state，确保 rerun 后数据一致
                                    st.session_state["results_with_bytes"] = results_with_bytes
                                    # 同步更新 identified_cache
                                    if "identified_cache" in st.session_state:
                                        for fkey, cached in st.session_state["identified_cache"].items():
                                            if cached["result"].get("original_name") == result.get("original_name"):
                                                cached["result"]["chinese_name"] = selected_name
                                                cached["result"]["english_name"] = selected_english
                                                break
                                    # 更新数据库：无论 _db_saved 标记如何，只要有用户就尝试更新
                                    current_user = st.session_state.get("user_nickname", "")
                                    if current_user:
                                        db_record_id = result.get("_db_record_id")
                                        record_shoot_date = result.get("shoot_date", "")
                                        db_updated = update_record_name_in_db(
                                            db_record_id, selected_name, selected_english,
                                            user_nickname=current_user,
                                            old_chinese_name=old_name,
                                            shoot_date=record_shoot_date,
                                        )
                                        if not db_updated:
                                            st.warning("⚠️ 数据库更新失败，请检查网络连接")
                                    fetch_user_history.clear()
                                    fetch_leaderboard.clear()
                                    fetch_top_photos.clear()
                                    st.toast(f"✅ 已修改为「{selected_name}」", icon="✏️")
                                    st.rerun()
                        else:
                            # 没有候选列表时，保留文本输入框作为兜底
                            edit_key = f"edit_name_{card_index}"
                            new_name = st.text_input(
                                "鸟种名称",
                                value=current_name,
                                key=edit_key,
                                label_visibility="collapsed",
                                placeholder="输入鸟种中文名",
                            )
                            if new_name and new_name != current_name:
                                old_name = current_name
                                result["chinese_name"] = new_name
                                if card_index < len(results_with_bytes):
                                    results_with_bytes[card_index]["result"]["chinese_name"] = new_name
                                # 同步写回 session_state
                                st.session_state["results_with_bytes"] = results_with_bytes
                                if "identified_cache" in st.session_state:
                                    for fkey, cached in st.session_state["identified_cache"].items():
                                        if cached["result"].get("original_name") == result.get("original_name"):
                                            cached["result"]["chinese_name"] = new_name
                                            break
                                current_user = st.session_state.get("user_nickname", "")
                                if current_user:
                                    db_record_id = result.get("_db_record_id")
                                    record_shoot_date = result.get("shoot_date", "")
                                    db_updated = update_record_name_in_db(
                                        db_record_id, new_name,
                                        user_nickname=current_user,
                                        old_chinese_name=old_name,
                                        shoot_date=record_shoot_date,
                                    )
                                    if not db_updated:
                                        st.warning("⚠️ 数据库更新失败，请检查网络连接")
                                fetch_user_history.clear()
                                fetch_leaderboard.clear()
                                fetch_top_photos.clear()
                                st.toast(f"✅ 已修改为「{new_name}」", icon="✏️")
                                st.rerun()
                            selected_english = result.get("english_name", "")
    
                        st.markdown(
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
                            f'<span style="font-size:12px; color:#888;">{confidence}</span>',
                            unsafe_allow_html=True,
                        )
    
                        basis = result.get("identification_basis", "")
                        if basis:
                            st.markdown(
                                f'<div style="font-size:12px; color:#6e6e73; margin-top:6px;">'
                                f'<b style="color:#888;">识别依据</b> {basis}</div>',
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
                                f'<div style="font-size:12px; color:#888; margin-top:4px;">'
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
                                bar_color = "#2d6a4f"
                            elif percentage >= 70:
                                bar_color = "#4a7c59"
                            elif percentage >= 50:
                                bar_color = "#e8a317"
                            else:
                                bar_color = "#c0392b"
                            bars_html += (
                                f'<div style="display:flex; align-items:center; margin:2px 0; font-size:11px;">'
                                f'<span style="width:28px; color:#888; font-weight:500; flex-shrink:0;">{dim_name}</span>'
                                f'<div style="flex:1; height:6px; background:rgba(0,0,0,0.06); border-radius:3px; margin:0 4px; overflow:hidden;">'
                                f'<div style="width:{percentage}%; height:100%; background:{bar_color}; border-radius:3px;"></div></div>'
                                f'<span style="width:32px; text-align:right; color:#1a3a5c; font-weight:600; font-size:11px;">{dim_score}/{dim_max}</span>'
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


    else:
        st.info("📷 请先设置昵称，即可上传照片识别鸟种")

# ============================================================
# ---- Tab 3: 佳作榜 ----
with tab_gallery:
    if supabase_client:
        top_photos = fetch_top_photos(limit=30)
        if top_photos:
            # ---------- 佳作榜：纯 HTML+JS，点击图片弹出 modal ----------
            import json as _json

            # 构建每张佳作的数据（供 JS modal 使用）
            gallery_data_list = []
            for photo in top_photos:
                sp_score = photo.get("score", 0)
                sp_date_raw = photo.get("shoot_date", "")
                formatted_date = ""
                if sp_date_raw and len(sp_date_raw) >= 8:
                    formatted_date = f"{sp_date_raw[:4]}.{sp_date_raw[4:6]}.{sp_date_raw[6:8]}"

                # 评分维度条 HTML
                dimensions = [
                    ("清晰", photo.get("score_sharpness", 0), 20),
                    ("构图", photo.get("score_composition", 0), 20),
                    ("光线", photo.get("score_lighting", 0), 20),
                    ("背景", photo.get("score_background", 0), 15),
                    ("姿态", photo.get("score_pose", 0), 15),
                    ("艺术", photo.get("score_artistry", 0), 10),
                ]
                has_dims = any(d[1] > 0 for d in dimensions)
                bars_html = ""
                if has_dims:
                    for dim_name, dim_score, dim_max in dimensions:
                        pct = (dim_score / dim_max * 100) if dim_max > 0 else 0
                        if pct >= 85:
                            bar_c = "#2d6a4f"
                        elif pct >= 70:
                            bar_c = "#4a7c59"
                        elif pct >= 50:
                            bar_c = "#e8a317"
                        else:
                            bar_c = "#c0392b"
                        bars_html += (
                            f'<div style="display:flex;align-items:center;margin:3px 0;font-size:11px;">'
                            f'<span style="width:28px;color:#888;font-weight:500;flex-shrink:0;">{dim_name}</span>'
                            f'<div style="flex:1;height:6px;background:rgba(0,0,0,0.06);border-radius:3px;margin:0 4px;overflow:hidden;">'
                            f'<div style="width:{pct:.0f}%;height:100%;background:{bar_c};border-radius:3px;"></div></div>'
                            f'<span style="width:20px;text-align:right;color:#888;font-size:10px;">{dim_score}</span></div>'
                        )

                gallery_data_list.append({
                    "thumb": photo.get("thumbnail_base64", ""),
                    "fullImg": photo.get("image_base64", ""),
                    "name": photo.get("chinese_name", "未知"),
                    "enName": photo.get("english_name", ""),
                    "score": sp_score,
                    "scoreEmoji": get_score_emoji(sp_score),
                    "scoreColor": get_score_color(sp_score),
                    "photographer": photo.get("user_nickname", "匿名"),
                    "date": formatted_date,
                    "order": photo.get("order_chinese", ""),
                    "family": photo.get("family_chinese", ""),
                    "basis": photo.get("identification_basis", ""),
                    "desc": photo.get("bird_description", ""),
                    "barsHtml": bars_html,
                })

            # 缩略图卡片 HTML（纯展示，带 data-gallery-idx 属性）
            gallery_cards_html = ""
            for idx, gd in enumerate(gallery_data_list):
                if gd["thumb"]:
                    img_tag = (
                        f'<img src="data:image/jpeg;base64,{gd["thumb"]}" '
                        f'style="width:100%;object-fit:contain;'
                        f'border-radius:8px 8px 0 0;display:block;" loading="lazy" alt="{gd["name"]}">'
                    )
                else:
                    img_tag = (
                        '<div style="width:100%;min-height:100px;'
                        'background:linear-gradient(135deg,#1a3a5c,#2d6a4f);'
                        'border-radius:8px 8px 0 0;display:flex;'
                        'align-items:center;justify-content:center;'
                        'font-size:36px;">📷</div>'
                    )

                gallery_cards_html += (
                    f'<div data-gallery-idx="{idx}" '
                    f'style="background:#fff;border-radius:8px;cursor:pointer;'
                    f'box-shadow:0 1px 4px rgba(0,0,0,0.06);overflow:hidden;'
                    f'border:1px solid #e8e8e8;transition:transform 0.15s,box-shadow 0.15s;">'
                    f'{img_tag}'
                    f'<div style="padding:6px 8px 6px;">'
                    f'<div style="font-size:12px;font-weight:600;color:#1a3a5c;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{gd["name"]}</div>'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-top:2px;">'
                    f'<span style="font-size:10px;color:#888;">{gd["photographer"]}</span>'
                    f'<span style="font-size:9px;padding:1px 5px;border-radius:4px;'
                    f'background:#e8f5e9;color:#2d6a4f;font-weight:600;">'
                    f'{gd["scoreEmoji"]} {gd["score"]}</span>'
                    f'</div></div></div>'
                )

            # 渲染缩略图网格（st.markdown，纯展示无事件）
            st.markdown(
                f'<div id="galleryGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));'
                f'gap:10px;padding:4px 0 8px;">'
                f'{gallery_cards_html}</div>',
                unsafe_allow_html=True,
            )

            # 用 components.html 注入 JS：在父窗口创建 modal 并绑定点击事件
            import streamlit.components.v1 as _components
            gallery_js_data = _json.dumps({
                "thumbs": [gd["thumb"] for gd in gallery_data_list],
                "fullImgs": [gd["fullImg"] for gd in gallery_data_list],
                "details": [{
                    "name": gd["name"],
                    "enName": gd["enName"],
                    "score": gd["score"],
                    "scoreEmoji": gd["scoreEmoji"],
                    "photographer": gd["photographer"],
                    "date": gd["date"],
                    "order": gd["order"],
                    "family": gd["family"],
                    "basis": gd["basis"],
                    "desc": gd["desc"],
                    "barsHtml": gd["barsHtml"],
                } for gd in gallery_data_list],
            }, ensure_ascii=False)

            _components.html(f"""
            <script>
            (function() {{
                var parentDoc = window.parent.document;
                if (!parentDoc) return;

                // 注入 modal 样式到父窗口（仅一次）
                if (!parentDoc.getElementById('galleryModalStyle')) {{
                    var style = parentDoc.createElement('style');
                    style.id = 'galleryModalStyle';
                    style.textContent = `
                        #galleryModalOverlay {{
                            display:none; position:fixed; top:0; left:0; right:0; bottom:0;
                            background:rgba(0,0,0,0.6); z-index:10000;
                            justify-content:center; align-items:center; padding:16px;
                        }}
                        #galleryModalOverlay.active {{ display:flex; }}
                        #galleryModal {{
                            background:#fff; border-radius:12px; max-width:680px; width:100%;
                            max-height:90vh; overflow-y:auto; position:relative;
                            box-shadow:0 20px 60px rgba(0,0,0,0.3);
                            animation: galleryModalIn 0.2s ease;
                        }}
                        @keyframes galleryModalIn {{
                            from {{ opacity:0; transform:scale(0.95); }}
                            to {{ opacity:1; transform:scale(1); }}
                        }}
                        #galleryModal .modal-close-btn {{
                            position:sticky; top:0; z-index:10;
                            display:flex; justify-content:flex-end; padding:8px 12px;
                            background:linear-gradient(180deg,rgba(255,255,255,0.95),rgba(255,255,255,0));
                        }}
                        #galleryModal .modal-close-btn button {{
                            background:#f0f0f0; border:none; border-radius:50%;
                            width:36px; height:36px; font-size:20px; cursor:pointer;
                            color:#333; display:flex; align-items:center; justify-content:center;
                        }}
                        #galleryModal .modal-close-btn button:hover {{ background:#e0e0e0; }}
                        #galleryModal .modal-main-img {{
                            width:100%; display:block;
                        }}
                        #galleryModal .modal-info {{
                            padding:16px 20px 20px;
                        }}
                        @media screen and (max-width:480px) {{
                            #galleryModal {{ border-radius:8px; max-height:85vh; }}
                            #galleryModal .modal-info {{ padding:12px 14px 16px; }}
                        }}
                        /* 卡片 hover 效果 */
                        [data-gallery-idx] {{
                            transition: transform 0.15s, box-shadow 0.15s;
                        }}
                        [data-gallery-idx]:hover {{
                            transform: translateY(-2px);
                            box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
                        }}
                    `;
                    parentDoc.head.appendChild(style);
                }}

                // 创建 modal DOM（仅一次）
                var overlay = parentDoc.getElementById('galleryModalOverlay');
                if (!overlay) {{
                    overlay = parentDoc.createElement('div');
                    overlay.id = 'galleryModalOverlay';
                    overlay.innerHTML = '<div id="galleryModal"><div class="modal-close-btn"><button id="galleryCloseBtn">&times;</button></div><div id="galleryModalContent"></div></div>';
                    parentDoc.body.appendChild(overlay);

                    // 点击遮罩关闭
                    overlay.addEventListener('click', function(e) {{
                        if (e.target === overlay) {{
                            overlay.classList.remove('active');
                        }}
                    }});
                    // 关闭按钮
                    parentDoc.getElementById('galleryCloseBtn').addEventListener('click', function() {{
                        overlay.classList.remove('active');
                    }});
                    // ESC 关闭
                    parentDoc.addEventListener('keydown', function(e) {{
                        if (e.key === 'Escape' && overlay.classList.contains('active')) {{
                            overlay.classList.remove('active');
                        }}
                    }});
                }}

                // 数据
                var galleryData = {gallery_js_data};

                // 打开 modal
                function openModal(idx) {{
                    var d = galleryData.details[idx];
                    var fullSrc = galleryData.fullImgs[idx];
                    var thumbSrc = galleryData.thumbs[idx];
                    var imgSrc = fullSrc || thumbSrc;
                    var content = parentDoc.getElementById('galleryModalContent');

                    var imgHtml = imgSrc
                        ? '<img class="modal-main-img" src="data:image/jpeg;base64,' + imgSrc + '">'
                        : '<div style="width:100%;height:300px;background:linear-gradient(135deg,#1a3a5c,#2d6a4f);display:flex;align-items:center;justify-content:center;font-size:60px;">📷</div>';

                    var taxonomyHtml = '';
                    if (d.order) taxonomyHtml += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:#e8f5e9;color:#2d6a4f;margin-right:4px;">' + d.order + '</span>';
                    if (d.family) taxonomyHtml += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:#fff3e0;color:#e8a317;">' + d.family + '</span>';

                    var metaParts = ['📷 ' + d.photographer];
                    if (d.date) metaParts.push('📅 ' + d.date);

                    var basisHtml = d.basis
                        ? '<div style="font-size:12px;color:#555;margin-top:10px;padding:8px 10px;background:#f1f8e9;border-radius:6px;"><b style="color:#4a7c59;">识别依据</b><br>' + d.basis + '</div>'
                        : '';
                    var descHtml = d.desc
                        ? '<div style="font-size:13px;color:#3a3a3c;line-height:1.7;margin-top:10px;padding:10px 12px;background:#fafafa;border-radius:6px;border:1px solid #e8e8e8;"><b style="color:#1a3a5c;">🐦 鸟类介绍</b><br>' + d.desc + '</div>'
                        : '';
                    var barsSection = d.barsHtml
                        ? '<div style="margin-top:10px;">' + d.barsHtml + '</div>'
                        : '';

                    content.innerHTML = imgHtml +
                        '<div class="modal-info">' +
                        '<div style="font-size:20px;font-weight:700;color:#1a3a5c;">' + d.name + '</div>' +
                        (d.enName ? '<div style="font-size:13px;color:#888;font-style:italic;margin-top:2px;">' + d.enName + '</div>' : '') +
                        (taxonomyHtml ? '<div style="margin-top:6px;">' + taxonomyHtml + '</div>' : '') +
                        '<div style="margin-top:8px;"><span style="display:inline-block;padding:3px 10px;border-radius:4px;font-size:13px;font-weight:600;background:#e8f5e9;color:#2d6a4f;">' + d.scoreEmoji + ' ' + d.score + '</span></div>' +
                        '<div style="font-size:13px;color:#888;margin-top:8px;">' + metaParts.join(' &middot; ') + '</div>' +
                        basisHtml + barsSection + descHtml +
                        '</div>';

                    overlay.classList.add('active');
                }}

                // 给父窗口中的卡片绑定点击事件（事件委托）
                function bindCardClicks() {{
                    var cards = parentDoc.querySelectorAll('[data-gallery-idx]');
                    cards.forEach(function(card) {{
                        if (card.dataset.galleryBound) return;
                        card.dataset.galleryBound = '1';
                        card.addEventListener('click', function() {{
                            var idx = parseInt(this.dataset.galleryIdx);
                            openModal(idx);
                        }});
                    }});
                }}

                // 延迟绑定（等 Streamlit 渲染完成）
                bindCardClicks();
                setTimeout(bindCardClicks, 500);
                setTimeout(bindCardClicks, 1500);
                setTimeout(bindCardClicks, 3000);
            }})();
            </script>
            """, height=0, scrolling=False)
        else:
            st.markdown(
                '<p style="text-align:center; color:#888; font-size:13px; padding:16px 0;">'
                '还没有佳作，上传照片成为第一个吧 📷</p>',
                unsafe_allow_html=True,
            )

    else:
        st.info("📸 佳作榜加载中…")

# ============================================================
# ---- Tab 4: 观鸟记录 ----
with tab_history:
    if supabase_client and user_nickname:
        # 先处理待删除的记录（确保统计数据和列表都是最新的）
        pending_delete_key = "_pending_delete_record_id"
        if pending_delete_key in st.session_state:
            delete_id = st.session_state.pop(pending_delete_key)
            if delete_record_from_db(delete_id):
                fetch_user_history.clear()
                fetch_leaderboard.clear()
                fetch_top_photos.clear()
                st.toast("✅ 已删除", icon="✅")
            else:
                st.toast("⚠️ 删除失败，请检查数据库权限", icon="⚠️")

        history_records = fetch_user_history(supabase_client, user_nickname)
        user_stats = fetch_user_stats_from_records(history_records)
        if user_stats and user_stats.get("total", 0) > 0:
            imported_count = user_stats.get("imported_species", 0)
            photo_total = user_stats.get("photo_total", 0)

            if imported_count > 0:
                hist_stat_cols = st.columns(5, gap="small")
                hist_stat_data = [
                    (str(photo_total), "📷 拍摄识别"),
                    (str(imported_count), "📥 导入鸟种"),
                    (str(user_stats["species"]), "🐦 总鸟种"),
                    (str(user_stats["avg_score"]), "⭐ 平均分"),
                    (str(user_stats["best_score"]), "🏆 最高分"),
                ]
            else:
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

            # 历史记录列表
            photo_records = [r for r in history_records if r.get("confidence") != "imported"]
            imported_records = [r for r in history_records if r.get("confidence") == "imported"]

            if history_records:
                # 拍照识别记录
                if photo_records:
                    with st.expander(f"📷 拍摄识别记录（{len(photo_records)} 条）", expanded=True):
                        for row_start in range(0, len(photo_records), 4):
                            row_items = photo_records[row_start:row_start + 4]
                            hist_cols = st.columns(4)
                            for col_idx, record in enumerate(row_items):
                                with hist_cols[col_idx]:
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
                                            'justify-content:center; color:#888; font-size:20px;">🐦</div>',
                                            unsafe_allow_html=True,
                                        )

                                    hist_score = record.get("score", 0)
                                    hist_score_color = get_score_color(hist_score)
                                    st.markdown(
                                        f'<p style="font-size:13px; font-weight:600; color:#1a3a5c; '
                                        f'margin:4px 0 2px; line-height:1.2;">{record.get("chinese_name", "未知")}</p>'
                                        f'<span class="score-pill score-{hist_score_color}" '
                                        f'style="font-size:11px; padding:2px 8px;">'
                                        f'{get_score_emoji(hist_score)} {hist_score}</span>',
                                        unsafe_allow_html=True,
                                    )

                                    created_at = record.get("created_at", "")
                                    if created_at:
                                        try:
                                            date_display = created_at[:10]
                                            st.markdown(
                                                f'<p style="font-size:11px; color:#888; margin:2px 0 8px;">'
                                                f'📅 {date_display}</p>',
                                                unsafe_allow_html=True,
                                            )
                                        except Exception:
                                            pass

                                    record_id = record.get("id")
                                    if record_id:
                                        if st.button("🗑️", key=f"del_{record_id}",
                                                     help="删除这条记录",
                                                     use_container_width=True):
                                            st.session_state[pending_delete_key] = record_id
                                            st.rerun()

                # 导入的观鸟记录
                if imported_records:
                    seen_imported = set()
                    unique_imported = []
                    for record in imported_records:
                        name = record.get("chinese_name", "")
                        if name and name not in seen_imported:
                            seen_imported.add(name)
                            unique_imported.append(record)

                    with st.expander(f"📥 导入的观鸟记录（{len(unique_imported)} 个鸟种）", expanded=False):
                        tags_html = ""
                        for record in unique_imported:
                            bird_name = record.get("chinese_name", "未知")
                            english_name = record.get("english_name", "")
                            source_info = record.get("identification_basis", "")
                            scientific_name = ""
                            if "| " in source_info:
                                scientific_name = source_info.split("| ", 1)[1].strip()

                            subtitle = ""
                            if english_name:
                                subtitle = english_name
                            elif scientific_name:
                                subtitle = scientific_name

                            tags_html += (
                                f'<div style="display:inline-flex; align-items:center; gap:4px; '
                                f'padding:6px 12px; margin:3px; background:#e8f5e9; '
                                f'border-radius:20px; font-size:13px;">'
                                f'<span style="font-weight:600; color:#1a3a5c;">{bird_name}</span>'
                            )
                            if subtitle:
                                tags_html += (
                                    f'<span style="font-size:11px; color:#888; '
                                    f'font-style:italic;">{subtitle}</span>'
                                )
                            tags_html += '</div>'

                        st.markdown(
                            f'<div style="line-height:2.2;">{tags_html}</div>',
                            unsafe_allow_html=True,
                        )

                        if st.button("🗑️ 清除所有导入记录", key="clear_imported",
                                     use_container_width=True):
                            cleared_count = 0
                            for record in imported_records:
                                record_id = record.get("id")
                                if record_id and delete_record_from_db(record_id):
                                    cleared_count += 1
                            if cleared_count > 0:
                                fetch_user_history.clear()
                                fetch_leaderboard.clear()
                                st.toast(f"✅ 已清除 {cleared_count} 条导入记录", icon="✅")
                                st.rerun()
            else:
                st.markdown(
                    '<p style="text-align:center; color:#888; font-size:14px; padding:20px 0;">'
                    '还没有识别记录，上传照片开始你的观鸟之旅吧 🐦</p>',
                    unsafe_allow_html=True,
                )

    else:
        st.info("📚 请先设置昵称，即可查看观鸟记录")

# ---- Tab 5: 排行榜 ----
with tab_rank:
    if supabase_client:
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
                    f'🐦 {entry["species"]}种 · 📷 {entry["total"]}条记录 · ⭐ {entry["avg_score"]}</p>'
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
                '<p style="text-align:center; color:#888; font-size:13px; padding:20px 0;">'
                '暂无排行数据</p>'
                '</div>',
                unsafe_allow_html=True,
            )

    # ============================================================
    else:
        st.info("🏆 排行榜加载中…")

# 页脚
# ============================================================
st.markdown(
    '<div class="app-footer">'
    '影禽 BirdEye · Powered by 通义千问 · '
    'Made with ❤️'
    '</div>',
    unsafe_allow_html=True,
)

# ============================================================