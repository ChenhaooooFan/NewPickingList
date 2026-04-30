"""
================================================================================
NailVesta 拣货单汇总工具
================================================================================

【用途】
将 TikTok Shop 导出的"拣货单 PDF"解析为按库位排序的产品汇总表,
方便仓库同学按动线顺序一次性拣完所有订单,并自动核对 PDF 标注的总件数
与实际提取件数是否一致。

【输入】
1. 必选:拣货 PDF(TikTok Shop 后台导出)
   - PDF 头部含 "Item quantity: XXX",作为对账基准
   - 每行 SKU 形如 NPF014-M、NDJ002-S
   - bundle 形式 SKU 形如 NPF014NPJ016-M(多个 SKU 拼接 + 单个尺寸)
2. 可选:产品图册 CSV(含 SKU / 库位 两列)
   - 上传后会自动按库位 A-01-01 → B-XX-XX 的顺序排序

【输出】
- 屏幕上的对账面板(PDF 标注 vs 实际提取)
- 按库位/字母排序的产品明细表(库位、产品名、S/M/L、Total)
- 可下载的 CSV 文件

【对账逻辑(核心)】
PDF 头部的 Item quantity 把所有"行"都算一份,但实际拣货时:
1. bundle SKU(如 NPF014NPJ016-M qty=1)在 PDF 里算 1 件,
   但实际要拣 2 件 → bundle_extra 记录拆分多出来的件数
2. NF001 (Free Giveaway) 是免费赠品,无尺寸,PDF 里独立成行
3. NB001 (Organizer Binder) 是收纳册,无尺寸,PDF 里独立成行
4. "Choose N Sets" 段落用占位 SKU(1/2/3),无具体款式信息,
   只能按段落汇总成一行"混合套装"

最终对账公式:
    期望件数 = PDF 标注数量 + bundle 拆分多出件数
    实际件数 = 所有提取出的 SKU 件数总和(含 NF001 / NB001 / Choose Sets)
    两者应相等

【特殊 SKU 处理】
| SKU       | 名称              | 尺寸  | 库位      | 处理方式            |
|-----------|------------------|------|----------|--------------------|
| NF001     | Free Giveaway    | 无   | 无       | 独立成行,灰色背景  |
| NB001     | Organizer Binder | 无   | 无       | 独立成行,灰色背景  |
| 1/2/3...  | Choose N Sets    | 无   | 无       | 段落汇总,灰色背景  |

【表格颜色含义】
- 🟡 黄色:真正缺库位信息,需补充图册 CSV
- ⚫ 灰色:无尺寸/无库位的特殊款(NF001 / NB001 / Choose Sets)
- 🌸 粉色:近期新款 SKU(在 new_sku_prefix 列表中)
- 白色:正常款

【依赖】
streamlit, pandas, pymupdf (fitz)

【维护】⚠️ 重要:有新款上架时,请记得更新 GitHub 代码中的 SKU 对照表!
- 新增甲片款式 → 在 sku_prefix_to_name 加一行映射
- 新增近期新款 → 同时加入 new_sku_prefix(用于粉色标记)
- 新增无尺寸 SKU → 同时加入 sku_prefix_to_name 和 SIZELESS_SKUS,
  并增加对应的正则匹配(参考 NB_ONLY 的写法)
- 改完后务必 push 到 GitHub,否则线上工具仍是旧版,会出现"❓未识别"
================================================================================
"""

import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

# ============================================================================
# 页面配置 + 全局样式
# ============================================================================
st.set_page_config(
    page_title="NailVesta 拣货单工具",
    page_icon="💅",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------- 自定义 CSS(安全的酷炫效果版) ----------
st.markdown("""
<style>
    /* 隐藏默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
    header[data-testid="stHeader"] {background: transparent;}

    /* === 飘动的极光背景 === */
    .stApp {
        background: #fdfafb;
        position: relative;
    }
    .stApp::before {
        content: '';
        position: fixed;
        top: -150px;
        left: -100px;
        width: 500px;
        height: 500px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(255, 209, 220, 0.55) 0%, transparent 70%);
        filter: blur(60px);
        z-index: 0;
        pointer-events: none;
        animation: floatA 18s ease-in-out infinite;
    }
    .stApp::after {
        content: '';
        position: fixed;
        bottom: -200px;
        right: -150px;
        width: 600px;
        height: 600px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(252, 228, 236, 0.5) 0%, transparent 70%);
        filter: blur(70px);
        z-index: 0;
        pointer-events: none;
        animation: floatB 22s ease-in-out infinite;
    }
    @keyframes floatA {
        0%, 100% { transform: translate(0, 0) scale(1); }
        33%      { transform: translate(80px, 60px) scale(1.1); }
        66%      { transform: translate(-40px, 100px) scale(0.95); }
    }
    @keyframes floatB {
        0%, 100% { transform: translate(0, 0) scale(1); }
        50%      { transform: translate(-100px, -80px) scale(1.15); }
    }

    /* === 主容器(浮在极光之上) === */
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 1180px;
        position: relative;
        z-index: 1;
    }

    /* === Hero 标题区 === */
    .hero-wrap {
        background: linear-gradient(135deg, #ffffff 0%, #fff8f5 50%, #fef2f5 100%);
        border-radius: 28px;
        padding: 40px 48px;
        margin-bottom: 28px;
        box-shadow:
            0 8px 32px rgba(232, 165, 180, 0.15),
            0 1px 3px rgba(232, 165, 180, 0.08);
        border: 1px solid rgba(232, 165, 180, 0.18);
        position: relative;
        overflow: hidden;
    }
    /* 呼吸光晕(纯 CSS 动画,安全) */
    .hero-wrap::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -10%;
        width: 350px;
        height: 350px;
        background: radial-gradient(circle, rgba(255, 180, 200, 0.4) 0%, transparent 70%);
        pointer-events: none;
        animation: breathe 6s ease-in-out infinite;
    }
    .hero-wrap::after {
        content: '';
        position: absolute;
        bottom: -40%;
        left: -5%;
        width: 280px;
        height: 280px;
        background: radial-gradient(circle, rgba(255, 220, 230, 0.35) 0%, transparent 70%);
        pointer-events: none;
        animation: breathe 8s ease-in-out infinite reverse;
    }
    @keyframes breathe {
        0%, 100% { transform: scale(1); opacity: 0.6; }
        50%      { transform: scale(1.15); opacity: 0.9; }
    }

    .hero-title {
        font-size: 36px;
        font-weight: 700;
        background: linear-gradient(135deg, #e89cb1 0%, #d4849a 30%, #c46e89 60%, #b85a78 100%);
        background-size: 200% 200%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 0 8px 0;
        letter-spacing: -0.5px;
        position: relative;
        animation: shimmer 4s ease-in-out infinite;
    }
    @keyframes shimmer {
        0%, 100% { background-position: 0% 50%; }
        50%      { background-position: 100% 50%; }
    }
    .hero-subtitle {
        font-size: 15px;
        color: #8a7170;
        margin: 0;
        font-weight: 400;
        letter-spacing: 0.2px;
        position: relative;
    }
    .hero-tag {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: linear-gradient(135deg, #fdd9e0 0%, #fce4ec 100%);
        color: #b85a78;
        padding: 5px 14px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-bottom: 14px;
        text-transform: uppercase;
        position: relative;
        box-shadow: 0 2px 8px rgba(212, 132, 154, 0.15);
    }
    .hero-tag::before {
        content: '';
        width: 6px;
        height: 6px;
        background: #d4849a;
        border-radius: 50%;
        box-shadow: 0 0 0 0 rgba(212, 132, 154, 0.7);
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%   { box-shadow: 0 0 0 0 rgba(212, 132, 154, 0.7); }
        70%  { box-shadow: 0 0 0 8px rgba(212, 132, 154, 0); }
        100% { box-shadow: 0 0 0 0 rgba(212, 132, 154, 0); }
    }

    /* === 卡片样式 === */
    .nv-card {
        background: white;
        border-radius: 20px;
        padding: 24px 28px;
        margin-bottom: 18px;
        box-shadow: 0 2px 12px rgba(232, 165, 180, 0.08);
        border: 1px solid rgba(232, 165, 180, 0.12);
    }
    .nv-card-title {
        font-size: 15px;
        font-weight: 600;
        color: #6b4f55;
        margin: 0 0 14px 0;
        letter-spacing: 0.2px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* === 维护提醒条 === */
    .reminder-bar {
        background: linear-gradient(90deg, #fef5e7 0%, #fef0f0 100%);
        border-left: 4px solid #e8a5a5;
        border-radius: 12px;
        padding: 12px 18px;
        margin-bottom: 22px;
        font-size: 13px;
        color: #7a5a5e;
        line-height: 1.6;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .reminder-bar code {
        background: rgba(212, 132, 154, 0.12);
        color: #b85a78;
        padding: 1px 7px;
        border-radius: 5px;
        font-size: 12px;
        font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
    }

    /* === 文件上传区美化 === */
    [data-testid="stFileUploader"] {
        background: linear-gradient(135deg, #ffffff 0%, #fef8f9 100%);
        border-radius: 16px;
        padding: 4px;
    }
    [data-testid="stFileUploader"] section {
        background: rgba(255, 245, 247, 0.5) !important;
        border: 2px dashed rgba(212, 132, 154, 0.35) !important;
        border-radius: 14px !important;
        padding: 24px !important;
        transition: all 0.3s ease;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: rgba(212, 132, 154, 0.6) !important;
        background: rgba(255, 235, 240, 0.4) !important;
    }
    [data-testid="stFileUploader"] button {
        background: linear-gradient(135deg, #e8a5a5 0%, #d4849a 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 8px 18px !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        box-shadow: 0 2px 6px rgba(212, 132, 154, 0.25) !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stFileUploader"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(212, 132, 154, 0.35) !important;
    }
    [data-testid="stFileUploaderFile"] {
        background: linear-gradient(135deg, #fef0f5 0%, #fff5f7 100%);
        border-radius: 10px;
        padding: 8px 12px !important;
    }

    /* === Radio 美化 === */
    [data-testid="stRadio"] label {
        font-size: 14px !important;
        color: #6b4f55 !important;
        font-weight: 500 !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] {
        gap: 8px !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label {
        background: white;
        padding: 8px 16px;
        border-radius: 10px;
        border: 1px solid rgba(212, 132, 154, 0.2);
        transition: all 0.2s ease;
        cursor: pointer;
    }
    [data-testid="stRadio"] [role="radiogroup"] label:hover {
        border-color: rgba(212, 132, 154, 0.5);
        background: #fef8f9;
    }

    /* === KPI 数字卡(流光描边 + hover 升起) === */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background: white;
        border-radius: 18px;
        padding: 20px 22px;
        border: 1px solid rgba(232, 165, 180, 0.15);
        box-shadow: 0 4px 16px rgba(232, 165, 180, 0.08);
        transition: all 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
        position: relative;
        overflow: hidden;
    }
    /* 流光扫过(hover 触发) */
    .kpi-card::after {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 60%;
        height: 100%;
        background: linear-gradient(90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.6) 50%,
            transparent 100%);
        transition: left 0.7s ease;
        pointer-events: none;
    }
    .kpi-card:hover {
        transform: translateY(-4px) scale(1.02);
        box-shadow: 0 12px 28px rgba(232, 165, 180, 0.2);
        border-color: rgba(212, 132, 154, 0.4);
    }
    .kpi-card:hover::after {
        left: 130%;
    }
    .kpi-label {
        font-size: 11px;
        color: #a8888a;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .kpi-icon-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: currentColor;
        opacity: 0.6;
    }
    .kpi-value {
        font-size: 34px;
        font-weight: 700;
        background: linear-gradient(135deg, #6b4f55 0%, #b85a78 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1;
        margin-bottom: 4px;
        letter-spacing: -0.8px;
    }
    .kpi-sub {
        font-size: 12px;
        color: #a8888a;
        font-weight: 400;
    }
    .kpi-card.success {
        border-left: 3px solid #a8d5ba;
    }
    .kpi-card.success .kpi-value {
        background: linear-gradient(135deg, #4a8061 0%, #6bb88a 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .kpi-card.primary {
        border-left: 3px solid #d4849a;
    }
    .kpi-card.primary .kpi-value {
        background: linear-gradient(135deg, #b85a78 0%, #e89cb1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .kpi-card.muted {
        border-left: 3px solid #d4c5c0;
    }
    .kpi-card.warning {
        border-left: 3px solid #e8c587;
    }
    .kpi-card.warning .kpi-value {
        background: linear-gradient(135deg, #b58a3a 0%, #d4a956 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    /* === 对账状态条(流光 + 图标动效) === */
    .status-bar {
        border-radius: 16px;
        padding: 16px 22px;
        margin: 12px 0 22px 0;
        font-weight: 500;
        font-size: 14px;
        display: flex;
        align-items: center;
        gap: 12px;
        position: relative;
        overflow: hidden;
    }
    .status-bar.success {
        background: linear-gradient(135deg, #f0f9f3 0%, #e6f5ec 100%);
        color: #4a8061;
        border: 1px solid rgba(168, 213, 186, 0.4);
    }
    /* 成功条:顶部流光 */
    .status-bar.success::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 50%;
        height: 100%;
        background: linear-gradient(90deg,
            transparent 0%,
            rgba(168, 213, 186, 0.3) 50%,
            transparent 100%);
        animation: sweep 3s ease-in-out infinite;
    }
    @keyframes sweep {
        0%   { left: -100%; }
        100% { left: 200%; }
    }
    .status-bar.success .status-icon {
        animation: bounceIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    @keyframes bounceIn {
        0%   { transform: scale(0.3); opacity: 0; }
        50%  { transform: scale(1.2); }
        100% { transform: scale(1); opacity: 1; }
    }
    .status-bar.error {
        background: linear-gradient(135deg, #fef0f0 0%, #fde6e6 100%);
        color: #b85a5a;
        border: 1px solid rgba(232, 165, 165, 0.4);
    }
    .status-bar.error .status-icon {
        animation: shake 0.5s ease-in-out;
    }
    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25%      { transform: translateX(-3px); }
        75%      { transform: translateX(3px); }
    }
    .status-bar.warning {
        background: linear-gradient(135deg, #fef9ec 0%, #fdf3d9 100%);
        color: #8a6a2a;
        border: 1px solid rgba(232, 197, 135, 0.4);
    }
    .status-icon {
        font-size: 20px;
        flex-shrink: 0;
        position: relative;
        z-index: 1;
    }

    /* === 明细块小标题 === */
    .detail-section {
        background: linear-gradient(135deg, #fefaf9 0%, #fdf5f7 100%);
        border-radius: 12px;
        padding: 14px 18px;
        margin: 12px 0;
        border: 1px solid rgba(232, 165, 180, 0.1);
    }
    .detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 5px 0;
        font-size: 13px;
        color: #6b4f55;
    }
    .detail-row:not(:last-child) {
        border-bottom: 1px dashed rgba(212, 132, 154, 0.18);
    }
    .detail-label { color: #8a7170; }
    .detail-value { font-weight: 600; color: #6b4f55; }
    .detail-value.pink { color: #b85a78; }
    .detail-section-title {
        font-size: 12px;
        font-weight: 700;
        color: #b85a78;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }

    /* === DataFrame 表格美化 === */
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(232, 165, 180, 0.18);
        box-shadow: 0 2px 12px rgba(232, 165, 180, 0.06);
    }

    /* === Streamlit 默认 alert 美化兜底 === */
    [data-testid="stAlert"] {
        border-radius: 14px !important;
        border: none !important;
    }

    /* === 分隔线 === */
    .nv-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, rgba(212, 132, 154, 0.25) 50%, transparent 100%);
        margin: 28px 0;
        border: none;
    }

    /* === 段落小标题(发光光条) === */
    .section-header {
        font-size: 18px;
        font-weight: 700;
        color: #6b4f55;
        margin: 24px 0 14px 0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .section-header::before {
        content: '';
        width: 4px;
        height: 20px;
        background: linear-gradient(180deg, #e89cb1 0%, #d4849a 50%, #b85a78 100%);
        border-radius: 2px;
        box-shadow: 0 2px 8px rgba(212, 132, 154, 0.3);
        animation: glowPulse 2.5s ease-in-out infinite;
    }
    @keyframes glowPulse {
        0%, 100% { box-shadow: 0 2px 8px rgba(212, 132, 154, 0.3); }
        50%      { box-shadow: 0 2px 16px rgba(212, 132, 154, 0.7); }
    }

    /* === 下载按钮(渐变流动 + hover 上浮) === */
    [data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #e89cb1 0%, #d4849a 50%, #c46e89 100%) !important;
        background-size: 200% 200% !important;
        color: white !important;
        border: none !important;
        border-radius: 14px !important;
        padding: 12px 28px !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        box-shadow: 0 4px 14px rgba(196, 110, 137, 0.3) !important;
        transition: all 0.3s ease !important;
        letter-spacing: 0.3px;
        animation: gradientShift 3s ease infinite;
    }
    @keyframes gradientShift {
        0%, 100% { background-position: 0% 50%; }
        50%      { background-position: 100% 50%; }
    }
    [data-testid="stDownloadButton"] button:hover {
        transform: translateY(-3px) scale(1.02);
        box-shadow: 0 10px 24px rgba(196, 110, 137, 0.4) !important;
    }
    [data-testid="stDownloadButton"] button:active {
        transform: translateY(-1px) scale(0.98);
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# Hero 区
# ============================================================================
st.markdown("""
<div class="hero-wrap">
    <span class="hero-tag">✨ NailVesta Warehouse Tool</span>
    <h1 class="hero-title">拣货单汇总工具 💅</h1>
    <p class="hero-subtitle">
        Smart picking & reconciliation · 智能拆分 bundle、自动对账、按库位排序
    </p>
</div>
""", unsafe_allow_html=True)

# ========== 维护提醒 ==========
st.markdown("""
<div class="reminder-bar">
    <span style="font-size:18px;">📢</span>
    <div>
        <strong>新款上架提醒</strong>:有新款 SKU 上架时,请及时更新 GitHub 代码中的对照表
        <code>sku_prefix_to_name</code> 与 <code>new_sku_prefix</code>,push 后线上自动同步,
        否则会显示为 ❓未识别。
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# 上传区
# ============================================================================
st.markdown('<div class="section-header">📁 文件上传</div>', unsafe_allow_html=True)

col_up1, col_up2 = st.columns(2)

with col_up1:
    st.markdown('<div style="font-size:13px; color:#8a7170; margin-bottom:6px; font-weight:500;">📚 产品图册 CSV<span style="color:#c4c4c4; font-weight:400;"> · 可选</span></div>', unsafe_allow_html=True)
    catalog_file = st.file_uploader(
        " ",
        type=["csv"],
        key="catalog",
        label_visibility="collapsed",
        help="包含 SKU 与库位列。上传后会按库位排序拣货单"
    )

with col_up2:
    st.markdown('<div style="font-size:13px; color:#8a7170; margin-bottom:6px; font-weight:500;">📤 拣货 PDF<span style="color:#d4849a; font-weight:600;"> · 必选</span></div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        " ",
        type=["pdf"],
        label_visibility="collapsed",
        help="TikTok Shop 后台导出的拣货 PDF"
    )

# 加载图册
sku_to_location = {}
if catalog_file:
    try:
        catalog_df = pd.read_csv(catalog_file, dtype=str)
        if 'SKU' in catalog_df.columns and '库位' in catalog_df.columns:
            catalog_df['SKU'] = catalog_df['SKU'].astype(str).str.strip()
            catalog_df['库位'] = catalog_df['库位'].fillna('').astype(str).str.strip()
            valid = catalog_df[catalog_df['库位'] != '']
            sku_to_location = dict(zip(valid['SKU'], valid['库位']))
            st.markdown(f"""
            <div class="status-bar success">
                <span class="status-icon">✅</span>
                <span>已加载 <strong>{len(sku_to_location)}</strong> 个 SKU 的库位映射</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("⚠️ 图册缺少 'SKU' 或 '库位' 列")
    except Exception as e:
        st.error(f"读取图册失败: {e}")

# ============================================================================
# SKU 映射表(保持不变)
# ============================================================================
sku_prefix_to_name = {
    "NDF001":"Tropic Paradise","NPX014":"Afterglow","NDX001":"Pinky Promise","NHF001":"Gothic Moon","NHX001":"Emerald Garden",
    "NLF001":"Divine Emblem","NLF002":"Athena's Glow","NLJ001":"Golden Pearl","NLJ002":"BAROQUE BLISS","NLJ003":"Rainbow Reef",
    "NLX001":"Mermaid's Whisper","NLX003":"Tropical Tide","NLX005":"Pure Grace","NOF001":"Royal Amber","NOF002":"Tiger Lily",
    "NOF003":"Peach Pop","NOF004":"Sunset Punch","NOF005":"Glacier Petal","NOJ001":"Island Bloom","NOJ002":"Floral Lemonade",
    "NOJ003":"Aurora Tide","NOX001":"Lava Latte","NPD001":"Leopard's Kiss","NPF001":"Angel's Grace","NPF002":"Sacred Radiance",
    "NPF003":"Golden Ivy","NPF005":"Auric Taurus","NPF006":"Cocoa Blossom","NPF007":"Bluebell Glow","NPF008":"Lavender Angel",
    "NPF009":"Vintage Bloom","NPF010":"Pastel Meadow","NPF011":"Cherry Cheetah","NPF012":"Rosey Tigress","NPJ001":"SCARLET QUEEN",
    "NPJ003":"Stellar Capricorn","NPJ004":"Midnight Violet","NPJ005":"Vintage Cherry","NPJ006":"Savanna Bloom","NPJ007":"Angel's Blush",
    "NPJ008":"Gothic Sky","NPJ009":"Violet Seashell","NPX001":"Royal Elegance","NPX002":"Angel's Ruby","NPX005":"Indigo Breeze",
    "NPX006":"Autumn Petal","NPX007":"Lavender Bliss","NPX008":"Dreamy Ballerina","NPX009":"Rose Eden","NPX010":"Blooming Meadow",
    "NPX011":"Safari Petal","NPX012":"Milky Ribbon","NPX013":"Champagne Wishes","NLX004":"Holiday Bunny","NPJ010":"Glossy Doll",
    "NPF013":"Opal Glaze","NOX002":"Cherry Kiss","NOJ004":"Peachy Coast","NYJ001":"Rosy Ribbon","NOF008":"Starlit Jungle",
    "NOF006":"Coral Sea","NOF009":"Rosé Angel","NPF014":"Arabian Nights","NOX003":"Caramel Nova","NPF016":"Golden Muse",
    "NPF017":"Ruby Bloom","NOF007":"Citrus Blush","NOJ005":"Ocean Whisper","NPF015":"Rosé Petal","NOF010":"Spring Moss",
    "NM001":"Mystery Set","NOF011":"Velvet Flame","NPJ011":"Bat Boo","NOX004":"Azure Muse","NPX016":"Silky Pearl",
    "NPX015":"Spooky Clown","NOX005":"Honey Daisy","NPJ012":"Gothic Mirage","NOX006":"Imperial Bloom","NPX017":"Rouge Letter",
    "NOF013":"Sakura Blush","NPF018":"Wild Berry","NOF012":"Rose Nocturne","NIX001":"Golden Maple","NOX007":"Stellar Whisper",
    "NOF014":"Desert Rose","NPF019":"Lunar Whisper","NOF015":"Mocha Grace","NOX009":"Moonlit Petal","NOX008":"Espresso Petals",
    "NPX018":"Ruby Ribbon","NPF020":"Amber Mist","NOJ006":"Toffee Muse","NOJ007":"Cherry Glaze","NOX011":"Opal Mirage",
    "NOF016":"Cinnamon Bloom","NOX010":"Twilight Muse","NPX020":"Peachy Glaze","NPX019":"Blossom Tart","NPJ013":"Velvet Cherry",
    "NOX012":"Harvest Glaze","NOJ008":"Crystal Whisper","NOF017":"Twinkle Bow","NPX021":"Twinkle Pine","NOF018":"Glacier Bloom",
    "NOJ010":"Rosé Noir","NPX022":"Merry Charm","NPF022":"Holiday Sparkl","NOF020":"Garnet Muse","NOF019":"Twinkle Christmas",
    "NOJ011":"Snowy Comet","NOX013":"Christmas Village","NOJ009":"Reindeer Glow","NIX002":"Golden Orchid",
    "NPJ014":"Snow Pixie","NPJ018":"Frost Ruby","NPJ017":"Starlit Rift","NPF021":"Candy Cane","NPJ016":"Fairy Nectar",
    "NPJ015":"Icy Viper","NOX014":"Taro Petal","NVT001":"Tool Kits",
    "NF001":"Free Giveaway","NIF001":"Lilac Veil","NIF002":"Gingerbread","NOX015":"Glitter Doll","NOJ012":"Winery Flame",
    "NOF021":"Velvet Ribbon","NPX024":"Rose Wine","NPX023":"Rosy Promise","NMF001":"Cherry Crush","NBX001":"Ballet Petal",
    "NMF003":"Royal Treasure","NMF002":"Safari Princess","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost",
    "NPJ019":"Gothic Mist","NOJ015":"Sapphire Bloom",
    "NPX025":"Cocoa Teddy","NVF001":"Golden Bloom","NBJ002":"Cherry Drop",
    "NOF022":"Aqua Reverie","NDJ001":"Snow Knit",
    "NOX016":"Cherry Ribbon","NOX017":"Ruby Bow","NMF004":"Lavender Bloom","NDX002":"Cloudy Knit","NMJ003":"Gothic Rose",
    "NOF025":"Cherry Romance","NMJ001":"Milky Cloud",
    "NMX001":"Petal Muse","NOF024":"Floral Muse","NVX001":"Sakura Macaron","NVF002":"Dreamy Bloom","NOJ017":"Floral Garden",
    "NOJ016":"Jade Blossom","NVX002":"Pastel Bloom",
    "NPF023":"Fairy Garden","NBJ001":"Stone Petal","NOF027":"Acai Bloom","NPJ021":"Champagne Blossom","NPJ020":"Citrus Daisy",
    "NOJ018":"Ribbon Lily","NVF005":"Dreamy Sakura",
    "NDX003":"Meadow Petals","NOX018":"Strawberry Kiss","NOJ020":"Raibow Bloom","NPF026":"Seaside Sundae","NVJ001":"Prism Aura",
    "NDX005":"Midnight Glam","NDX004":"Starry Tide",
    "NPX027":"Hibiscus Tide","NPX026":"Ocean Yuzu","NWX001":"Seashell Sorbet","NOF026":"Island Paradise","NPF024":"Tropical Breeze",
    "NOJ021":"Petal Gelato",
    "NVF003":"Apricot Cream","NMJ005":"Glossy Aura","NGX001":"Seafoam Jewel","NOF028":"Floral Cherry","NTX001":"Coraline Glow",
    "NOX020":"Floral Drip","NOX019":"Mint Petal","NOF030":"Citrus Veil",
    "NOF031":"Lady Cherry","NOF029":"Marine Glow","NDJ002":"Aqua Blush","NWF001":"Berry Bowtie","NTF001":"Pastel Coast",
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember","NOX022":"Sunlit Petals",
    "NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals",
    # 无尺寸款 SKU
    "NB001":"Organizer Binder",
}
updated_mapping = dict(sku_prefix_to_name)

new_sku_prefix = {
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember",
    "NOX022":"Sunlit Petals","NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals"
}

SIZELESS_SKUS = {"NF001", "NB001"}

# ============================================================================
# 解析工具函数
# ============================================================================
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}|NF001){1,4}-[SML])', re.DOTALL)
QTY_AFTER  = re.compile(r'\b([1-9]\d{0,2})\b')
ITEM_QTY_RE = re.compile(r"Item\s+quantity[:：]?\s*(\d+)", re.I)
NM_ONLY = re.compile(r'\bNF001\b')
NB_ONLY = re.compile(r'\bNB001\b')
CHOOSE_SETS_RE = re.compile(r'Choose\s+\d+\s+Sets', re.I)


def normalize_text(t: str) -> str:
    return t.replace("\u00ad","").replace("\u200b","").replace("\u00a0"," ").replace("–","-").replace("—","-")


def fix_orphan_digit_before_size(txt: str) -> str:
    pattern = re.compile(r'(?P<prefix>(?:[A-Z]{3}\d{3}|NM001){0,3}[A-Z]{3}\d{2})\s*[\r\n]+\s*(?P<d>\d)\s*-\s*(?P<size>[SML])')
    def _join(m): return f"{m.group('prefix')}{m.group('d')}-{m.group('size')}"
    prev, cur = None, txt
    while prev != cur:
        prev, cur = cur, pattern.sub(_join, cur)
    return cur


def parse_code_parts(code: str):
    parts, i, n = [], 0, len(code)
    while i < n:
        if code.startswith('NM001', i):
            parts.append('NM001'); i += 5; continue
        seg = code[i:i+6]
        if re.fullmatch(r'[A-Z]{3}\d{3}', seg):
            parts.append(seg); i += 6; continue
        return None
    return parts if 1 <= len(parts) <= 4 else None


def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    s = re.sub(r'\s+', '', sku_with_size)
    if '-' not in s:
        counter[s] += qty
        return 0, (qty if s == 'NF001' else 0)
    code, size = s.split('-', 1)
    parts = parse_code_parts(code)
    if parts:
        mystery_units = 0
        for p in parts:
            key = f"{p}-{size}"
            counter[key] += qty
            if p == 'NF001':
                mystery_units += qty
        extra = (len(parts) - 1) * qty
        return extra, mystery_units
    counter[s] += qty
    return 0, (qty if code == 'NF001' else 0)


def count_choose_sets_items(text: str) -> int:
    # Choose N Sets 段落:每个套装下面跟若干行,每行最后一个数字是该子项数量。
    # 启发式:从每个 'Choose N Sets' 出现位置往后,直到下一个正式 SKU 或下一个 Choose 段落,
    # 在这段范围内累加 (数量, 18位订单ID) 配对的"数量"。
    total = 0
    positions = [m.start() for m in CHOOSE_SETS_RE.finditer(text)]
    if not positions:
        return 0
    positions.append(len(text))
    qty_pattern = re.compile(r'\b([1-9]\d{0,2})\s+(\d{15,20})\b')
    for i in range(len(positions) - 1):
        block = text[positions[i]:positions[i+1]]
        m_sku = re.search(r'\b[A-Z]{3}\d{3}-[SML]\b', block)
        if m_sku:
            block = block[:m_sku.start()]
        for m in qty_pattern.finditer(block):
            total += int(m.group(1))
    return total


def location_sort_key(loc: str):
    if not loc or loc == "未识别库位":
        return (99, 99, 99)
    m = re.match(r'^([AB])-(\d{2})-(\d{2})$', loc)
    if not m:
        return (98, 0, 0)
    zone = 0 if m.group(1) == 'A' else 1
    return (zone, int(m.group(2)), int(m.group(3)))


# ============================================================================
# 主逻辑
# ============================================================================
if not uploaded_file:
    st.markdown("""
    <div class="nv-card" style="text-align:center; padding: 50px 30px; background: linear-gradient(135deg, #ffffff 0%, #fef8f9 100%);">
        <div style="font-size: 48px; margin-bottom: 12px;">📤</div>
        <div style="font-size: 16px; color: #8a7170; font-weight: 500;">
            等待上传拣货 PDF
        </div>
        <div style="font-size: 13px; color: #b0a0a0; margin-top: 6px;">
            上传后将自动解析、拆分 bundle 并按库位排序
        </div>
    </div>
    """, unsafe_allow_html=True)

else:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    text = "\n".join([p.get_text("text") for p in doc])
    text = normalize_text(text)

    m_total = ITEM_QTY_RE.search(text)
    expected_total = int(m_total.group(1)) if m_total else 0

    text_fixed = fix_orphan_digit_before_size(text)

    sku_counts = defaultdict(int)
    bundle_extra = 0
    mystery_units = 0
    binder_units = 0

    for m in SKU_BUNDLE.finditer(text_fixed):
        sku_raw = re.sub(r'\s+', '', m.group(1))
        after = text_fixed[m.end(): m.end()+50]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        extra, myst = expand_bundle(sku_counts, sku_raw, qty)
        bundle_extra += extra
        mystery_units += myst

    for m in NM_ONLY.finditer(text_fixed):
        nxt = text_fixed[m.end(): m.end()+3]
        if '-' in nxt:
            continue
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NF001'] += qty
        mystery_units += qty

    for m in NB_ONLY.finditer(text_fixed):
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NB001'] += qty
        binder_units += qty

    choose_sets_units = count_choose_sets_items(text_fixed)
    if choose_sets_units > 0:
        sku_counts['__CHOOSE_SETS__'] += choose_sets_units

    total_qty = sum(sku_counts.values())
    expected_with_bundle = expected_total + bundle_extra

    # ========== 构建 DataFrame ==========
    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]

        def map_name(prefix):
            if prefix == "__CHOOSE_SETS__":
                return "Choose 2 Sets(混合套装)"
            return updated_mapping.get(prefix, "❓未识别")
        df["Product Name"] = df["SKU Prefix"].map(map_name)

        df_sized = df[df["Size"].notna()].copy()
        df_nosized = df[df["Size"].isna()].copy()

        if not df_sized.empty:
            pivot = df_sized.pivot_table(
                index=["SKU Prefix", "Product Name"],
                columns="Size",
                values="Qty",
                aggfunc="sum",
                fill_value=0
            ).reset_index()
            for sz in ["S", "M", "L"]:
                if sz not in pivot.columns:
                    pivot[sz] = 0
            pivot = pivot[["Product Name", "SKU Prefix", "S", "M", "L"]]
            pivot["Total"] = pivot["S"] + pivot["M"] + pivot["L"]
        else:
            pivot = pd.DataFrame(columns=["Product Name", "SKU Prefix", "S", "M", "L", "Total"])

        if not df_nosized.empty:
            for _, row in df_nosized.iterrows():
                new_row = {
                    "SKU Prefix": row["SKU Prefix"],
                    "Product Name": row["Product Name"],
                    "S": 0, "M": 0, "L": 0,
                    "Total": row["Qty"]
                }
                pivot = pd.concat([pivot, pd.DataFrame([new_row])], ignore_index=True)

        def map_location(prefix):
            if prefix in SIZELESS_SKUS or prefix == "__CHOOSE_SETS__":
                return "无库位(特殊款)"
            return sku_to_location.get(prefix, "未识别库位")
        pivot["库位"] = pivot["SKU Prefix"].map(map_location)

        # ========== 对账区:KPI 卡 ==========
        st.markdown('<div class="section-header">📊 对账结果</div>', unsafe_allow_html=True)

        nail_qty = int(pivot[~pivot["库位"].str.startswith("无库位")]["Total"].sum()) \
                   if not pivot.empty else 0
        special_qty = int(pivot[pivot["库位"].str.startswith("无库位")]["Total"].sum()) \
                      if not pivot.empty else 0

        # 状态条
        if expected_total == 0:
            st.markdown("""
            <div class="status-bar warning">
                <span class="status-icon">⚠️</span>
                <span>未识别到 PDF 中的 Item quantity,无法进行对账校验</span>
            </div>
            """, unsafe_allow_html=True)
        elif total_qty == expected_with_bundle or total_qty == expected_total:
            st.markdown(f"""
            <div class="status-bar success">
                <span class="status-icon">✨</span>
                <span><strong>对账成功</strong> · PDF 标注 {expected_total}
                {'+ bundle 拆分 ' + str(bundle_extra) if bundle_extra else ''}
                = 实际提取 {total_qty} 件 ✅</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            diff = total_qty - expected_with_bundle
            st.markdown(f"""
            <div class="status-bar error">
                <span class="status-icon">❌</span>
                <span><strong>对账不一致</strong> · 期望 {expected_with_bundle},实际 {total_qty},差 {diff:+d} 件</span>
            </div>
            """, unsafe_allow_html=True)

        # KPI 数字卡
        st.markdown(f"""
        <div class="kpi-grid">
            <div class="kpi-card primary">
                <div class="kpi-label"><span class="kpi-icon-dot"></span>PDF 标注</div>
                <div class="kpi-value">{expected_total:,}</div>
                <div class="kpi-sub">Item quantity</div>
            </div>
            <div class="kpi-card success">
                <div class="kpi-label"><span class="kpi-icon-dot"></span>实际提取</div>
                <div class="kpi-value">{total_qty:,}</div>
                <div class="kpi-sub">含 bundle 拆分</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span class="kpi-icon-dot"></span>普通甲片</div>
                <div class="kpi-value">{nail_qty:,}</div>
                <div class="kpi-sub">有库位</div>
            </div>
            <div class="kpi-card muted">
                <div class="kpi-label"><span class="kpi-icon-dot"></span>特殊款</div>
                <div class="kpi-value">{special_qty:,}</div>
                <div class="kpi-sub">无尺寸/无库位</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 提取明细卡
        st.markdown(f"""
        <div class="detail-section">
            <div class="detail-section-title">📋 提取明细</div>
            <div class="detail-row">
                <span class="detail-label">🎁 Free Giveaway (NF001)</span>
                <span class="detail-value pink">{mystery_units} 件</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">📒 Organizer Binder (NB001)</span>
                <span class="detail-value pink">{binder_units} 件</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">🎀 Choose Sets(混合套装)</span>
                <span class="detail-value pink">{choose_sets_units} 件</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">🔗 bundle 拆分多出件数</span>
                <span class="detail-value">+{bundle_extra} 件</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 未识别 SKU 提示
        unknown_prefix_list = []
        for sku in sku_counts.keys():
            prefix = sku.split("-")[0] if "-" in sku else sku
            if prefix not in updated_mapping and prefix != "__CHOOSE_SETS__":
                if prefix not in unknown_prefix_list:
                    unknown_prefix_list.append(prefix)
        if unknown_prefix_list:
            sku_chips = " ".join([
                f'<code style="background:#fde6e6; color:#b85a5a; padding:3px 9px; border-radius:6px; font-size:12px; margin:2px;">{p}</code>'
                for p in unknown_prefix_list
            ])
            st.markdown(f"""
            <div class="status-bar error">
                <span class="status-icon">🚨</span>
                <div>
                    <strong>发现 {len(unknown_prefix_list)} 个未识别的 SKU 前缀</strong><br>
                    <div style="margin:6px 0;">{sku_chips}</div>
                    <span style="font-size:12px; opacity:0.85;">
                        请尽快在 GitHub 仓库中更新 <code style="background:rgba(184,90,90,0.12); padding:1px 5px; border-radius:4px;">sku_prefix_to_name</code>,push 后重新部署
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # 缺库位提示
        truly_unknown = pivot[pivot["库位"] == "未识别库位"]
        if not truly_unknown.empty:
            names = "、".join(truly_unknown['Product Name'].tolist())
            st.markdown(f"""
            <div class="status-bar warning">
                <span class="status-icon">⚠️</span>
                <span><strong>{len(truly_unknown)} 个款式没有库位信息</strong>(需补充图册 CSV):{names}</span>
            </div>
            """, unsafe_allow_html=True)

        # 特殊款提示
        special_rows = pivot[pivot["库位"] == "无库位(特殊款)"]
        if not special_rows.empty:
            special_names = "、".join(special_rows["Product Name"].tolist())
            st.markdown(f"""
            <div class="status-bar warning" style="background:linear-gradient(135deg,#f5f0f5 0%,#ede5ec 100%); color:#6a4f60; border-color:rgba(180,150,170,0.3);">
                <span class="status-icon">ℹ️</span>
                <span><strong>{len(special_rows)} 类无尺寸/特殊款</strong>不参与库位拣货:{special_names}(需单独处理)</span>
            </div>
            """, unsafe_allow_html=True)

        # ========== 排序模式 ==========
        st.markdown('<div class="nv-divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">📋 拣货明细表</div>', unsafe_allow_html=True)

        sort_mode = st.radio(
            "排序方式",
            ["📦 按库位顺序(拣货模式)", "🔤 按字母顺序(A-Z)"],
            horizontal=True,
            label_visibility="collapsed",
            help="拣货模式:从 A-01-01 顺着货架走一遍即可。字母顺序:按产品名 A-Z 排列,方便查找"
        )

        is_special = pivot["SKU Prefix"].isin(SIZELESS_SKUS | {"__CHOOSE_SETS__"})
        pivot["_special"] = is_special.astype(int)

        if sort_mode.startswith("📦"):
            pivot["_loc_key"] = pivot["库位"].apply(location_sort_key)
            pivot = pivot.sort_values(
                by=["_special", "_loc_key", "Product Name"],
                ascending=[True, True, True]
            ).drop(columns=["_loc_key", "_special"]).reset_index(drop=True)
        else:
            pivot["_name_key"] = pivot["Product Name"].str.lower()
            pivot = pivot.sort_values(
                by=["_special", "_name_key"],
                ascending=[True, True]
            ).drop(columns=["_special", "_name_key"]).reset_index(drop=True)

        pivot = pivot[["库位", "Product Name", "S", "M", "L", "Total"]]

        # 行高亮
        prefix_lookup = {name: sku_p for sku_p, name in updated_mapping.items()}

        def highlight_row(row):
            loc = str(row["库位"])
            name = str(row["Product Name"])
            prefix = prefix_lookup.get(name, "")

            if loc == "未识别库位":
                return ['background-color: #fef5e7'] * len(row)
            if loc == "无库位(特殊款)":
                return ['background-color: #f5f0f5'] * len(row)
            if prefix in new_sku_prefix:
                return ['background-color: #fff0f5'] * len(row)
            return [''] * len(row)

        pivot_styled = pivot.style.apply(highlight_row, axis=1).set_properties(**{
            'font-size': '13px',
            'color': '#6b4f55',
        })

        st.dataframe(
            pivot_styled,
            use_container_width=True,
            hide_index=True,
            height=min(600, 50 + len(pivot) * 35)
        )

        # 颜色图例
        st.markdown("""
        <div style="display:flex; gap:18px; flex-wrap:wrap; padding:10px 0; font-size:12px; color:#8a7170;">
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="width:14px; height:14px; background:#fff0f5; border:1px solid rgba(212,132,154,0.3); border-radius:3px;"></span>
                <span>新款</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="width:14px; height:14px; background:#fef5e7; border:1px solid rgba(232,197,135,0.4); border-radius:3px;"></span>
                <span>缺库位信息</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="width:14px; height:14px; background:#f5f0f5; border:1px solid rgba(180,150,170,0.3); border-radius:3px;"></span>
                <span>无尺寸特殊款</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 下载
        st.markdown('<div style="margin-top:18px;"></div>', unsafe_allow_html=True)
        csv = pivot.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 下载产品明细 CSV",
            data=csv,
            file_name="product_summary_named.csv",
            mime="text/csv"
        )

    else:
        st.markdown("""
        <div class="status-bar error">
            <span class="status-icon">❌</span>
            <span>未识别到任何 SKU。请确认 PDF 为可复制文本(非扫描件)</span>
        </div>
        """, unsafe_allow_html=True)
