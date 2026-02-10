# 🐦 鸟类照片智能识别与分类整理

上传鸟类照片，AI 自动识别鸟种、评分、按分类学整理。

## 功能

- 📤 批量上传照片（JPG/PNG/HEIC/TIFF 等）
- 🐦 AI 鸟种识别（结合 GPS + 拍摄季节精确判断）
- 📊 摄影质量评分（满分100分，6维度专业评分）
- 🔬 按「目/科」分类学层级整理
- 📍 GPS 逆地理编码获取精确拍摄地点
- 📥 一键下载整理后的照片 ZIP 包

## 使用方式

### 在线使用

直接访问部署后的链接，在页面左侧输入 DashScope API Key 即可。

API Key 获取地址：https://dashscope.console.aliyun.com/apiKey

### 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 技术栈

- **前端**: Streamlit
- **AI 模型**: 通义千问 qwen-vl-max 多模态大模型
- **地理编码**: OpenStreetMap Nominatim
- **图像处理**: Pillow
