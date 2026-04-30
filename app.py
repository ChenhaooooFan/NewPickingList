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

【依赖】
streamlit, pandas, pymupdf (fitz)

【维护】⚠️ 重要:有新款上架时,请记得更新 GitHub 代码中的 SKU 对照表!
- 新增甲片款式 → 在 sku_prefix_to_name 加一行映射
- 新增近期新款 → 同时加入 new_sku_prefix(用于浅色标记)
- 新增无尺寸 SKU → 同时加入 sku_prefix_to_name 和 SIZELESS_SKUS
- 改完后务必 push 到 GitHub,否则线上工具仍是旧版,会出现"未识别"
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
    page_title="NailVesta · Picking",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------- 现代极简风 CSS(Linear / Notion / Stripe 调性) ----------
st.markdown("""
<style>
    /* === 隐藏默认元素 === */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
    header[data-testid="stHeader"] {background: transparent; height: 0;}

    /* === 全局字体 === */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Display",
                     "PingFang SC", "Microsoft YaHei", sans-serif;
        -webkit-font-smoothing: antialiased;
        letter-spacing: -0.01em;
    }

    /* === 整体背景:中性灰白 === */
    .stApp {
        background: #fafafa;
    }

    /* === 主容器 === */
    .block-container {
        padding-top: 3rem;
        padding-bottom: 5rem;
        max-width: 980px;
    }

    /* === Header === */
    .nv-header {
        margin-bottom: 40px;
        padding-bottom: 24px;
        border-bottom: 1px solid #ececec;
    }
    .nv-eyebrow {
        font-size: 11px;
        font-weight: 600;
        color: #999;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .nv-title {
        font-size: 28px;
        font-weight: 600;
        color: #0a0a0a;
        margin: 0 0 6px 0;
        letter-spacing: -0.02em;
    }
    .nv-subtitle {
        font-size: 14px;
        color: #707070;
        margin: 0;
        font-weight: 400;
    }

    /* === Section 标题 === */
    .nv-section {
        font-size: 13px;
        font-weight: 600;
        color: #0a0a0a;
        margin: 36px 0 14px 0;
        letter-spacing: -0.01em;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .nv-section-count {
        font-size: 12px;
        color: #999;
        font-weight: 400;
        margin-left: 6px;
    }

    /* === 提醒条:克制、单色边框 === */
    .nv-reminder {
        background: #fafafa;
        border: 1px solid #ececec;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 28px;
        font-size: 13px;
        color: #555;
        line-height: 1.6;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .nv-reminder-dot {
        width: 6px;
        height: 6px;
        background: #999;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .nv-reminder code {
        background: #f0f0f0;
        color: #333;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 12px;
        font-family: "SF Mono", "Monaco", "Menlo", monospace;
    }

    /* === 文件上传:克制 === */
    [data-testid="stFileUploader"] {
        background: transparent;
    }
    [data-testid="stFileUploader"] section {
        background: white !important;
        border: 1px dashed #d4d4d4 !important;
        border-radius: 10px !important;
        padding: 20px !important;
        transition: all 0.15s ease;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: #0a0a0a !important;
        background: #fafafa !important;
    }
    [data-testid="stFileUploader"] button {
        background: #0a0a0a !important;
        color: white !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 6px 14px !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        box-shadow: none !important;
        transition: all 0.15s ease !important;
    }
    [data-testid="stFileUploader"] button:hover {
        background: #333 !important;
    }
    [data-testid="stFileUploaderFile"] {
        background: #f5f5f5;
        border-radius: 6px;
        padding: 8px 12px !important;
        font-size: 12px;
    }
    [data-testid="stFileUploader"] small {
        color: #999 !important;
        font-size: 12px !important;
    }

    /* === Radio:tab 风格 === */
    [data-testid="stRadio"] > label {
        display: none !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] {
        gap: 4px !important;
        background: #f0f0f0;
        padding: 3px;
        border-radius: 8px;
        display: inline-flex !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label {
        background: transparent;
        padding: 6px 14px;
        border-radius: 6px;
        border: none !important;
        transition: all 0.15s ease;
        cursor: pointer;
        margin: 0 !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label[data-checked="true"],
    [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
        background: white;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }
    [data-testid="stRadio"] [role="radiogroup"] label p {
        font-size: 13px !important;
        font-weight: 500 !important;
        color: #555 !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label[data-checked="true"] p,
    [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) p {
        color: #0a0a0a !important;
    }
    /* 隐藏 radio 圆点 */
    [data-testid="stRadio"] [role="radiogroup"] label > div:first-child {
        display: none !important;
    }

    /* === KPI 卡:极简、纯白、单线边框 === */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: #ececec;
        border: 1px solid #ececec;
        border-radius: 12px;
        overflow: hidden;
        margin-bottom: 28px;
    }
    .kpi-card {
        background: white;
        padding: 22px 24px;
        transition: background 0.15s ease;
    }
    .kpi-card:hover {
        background: #fafafa;
    }
    .kpi-label {
        font-size: 11px;
        color: #999;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .kpi-value {
        font-size: 32px;
        font-weight: 600;
        color: #0a0a0a;
        line-height: 1;
        margin-bottom: 6px;
        letter-spacing: -0.03em;
        font-feature-settings: "tnum";
    }
    .kpi-sub {
        font-size: 12px;
        color: #999;
        font-weight: 400;
    }
    .kpi-card .kpi-delta {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        font-weight: 500;
        margin-top: 4px;
    }
    .kpi-delta.positive { color: #0d7544; }
    .kpi-delta.negative { color: #b42525; }
    .kpi-delta.neutral { color: #999; }

    /* === 状态条:单色边框 + 简洁 === */
    .status-bar {
        border-radius: 10px;
        padding: 12px 16px;
        margin: 0 0 24px 0;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 12px;
        border: 1px solid;
    }
    .status-bar.success {
        background: #f4faf6;
        color: #0d7544;
        border-color: #d6ebde;
    }
    .status-bar.error {
        background: #fdf5f5;
        color: #b42525;
        border-color: #f0d6d6;
    }
    .status-bar.warning {
        background: #fdfaf2;
        color: #8a6a1a;
        border-color: #efe5cc;
    }
    .status-bar.info {
        background: #fafafa;
        color: #555;
        border-color: #ececec;
    }
    .status-bar strong {
        font-weight: 600;
    }
    .status-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
    }

    /* === 明细块 === */
    .detail-section {
        background: white;
        border: 1px solid #ececec;
        border-radius: 12px;
        padding: 4px 20px;
        margin-bottom: 24px;
    }
    .detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 0;
        font-size: 13px;
        color: #333;
    }
    .detail-row:not(:last-child) {
        border-bottom: 1px solid #f5f5f5;
    }
    .detail-label {
        color: #666;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .detail-label-tag {
        background: #f5f5f5;
        color: #666;
        padding: 2px 7px;
        border-radius: 4px;
        font-size: 11px;
        font-family: "SF Mono", "Monaco", "Menlo", monospace;
        font-weight: 500;
    }
    .detail-value {
        font-weight: 600;
        color: #0a0a0a;
        font-feature-settings: "tnum";
    }
    .detail-value.muted {
        color: #999;
        font-weight: 500;
    }

    /* === 表格 === */
    [data-testid="stDataFrame"] {
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #ececec;
    }
    [data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
        border: none !important;
    }

    /* === 下载按钮 === */
    [data-testid="stDownloadButton"] button {
        background: #0a0a0a !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 9px 18px !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        box-shadow: none !important;
        transition: all 0.15s ease !important;
        letter-spacing: 0;
    }
    [data-testid="stDownloadButton"] button:hover {
        background: #333 !important;
        transform: none;
    }

    /* === 默认 alert 美化兜底 === */
    [data-testid="stAlert"] {
        border-radius: 10px !important;
        border: 1px solid #ececec !important;
        background: #fafafa !important;
        font-size: 13px !important;
    }

    /* === 上传卡标签 === */
    .uploader-label {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 500;
        color: #555;
        margin-bottom: 8px;
    }
    .uploader-required {
        color: #b42525;
        font-size: 11px;
    }
    .uploader-optional {
        color: #999;
        font-size: 11px;
    }

    /* === 空状态 === */
    .empty-state {
        background: white;
        border: 1px solid #ececec;
        border-radius: 12px;
        padding: 64px 40px;
        text-align: center;
        margin: 32px 0;
    }
    .empty-state-icon {
        width: 40px;
        height: 40px;
        margin: 0 auto 16px;
        color: #d4d4d4;
    }
    .empty-state-title {
        font-size: 14px;
        color: #555;
        font-weight: 500;
        margin-bottom: 4px;
    }
    .empty-state-sub {
        font-size: 12px;
        color: #999;
    }

    /* === 颜色图例 === */
    .color-legend {
        display: flex;
        gap: 18px;
        flex-wrap: wrap;
        padding: 12px 0 4px;
        font-size: 12px;
        color: #999;
    }
    .legend-item {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .legend-swatch {
        width: 10px;
        height: 10px;
        border-radius: 2px;
    }

    /* === SKU chip === */
    .sku-chip {
        display: inline-block;
        background: #fdf5f5;
        color: #b42525;
        border: 1px solid #f0d6d6;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-family: "SF Mono", "Monaco", "Menlo", monospace;
        font-weight: 500;
        margin: 2px 4px 2px 0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# Header
# ============================================================================
st.markdown("""
<div class="nv-header">
    <div class="nv-eyebrow">NailVesta · Warehouse</div>
    <h1 class="nv-title">拣货单汇总</h1>
    <p class="nv-subtitle">解析 TikTok Shop 拣货 PDF,自动拆分 bundle、对账核验、按库位排序</p>
</div>
""", unsafe_allow_html=True)

# ========== 维护提醒 ==========
st.markdown("""
<div class="nv-reminder">
    <span class="nv-reminder-dot"></span>
    <div>新款上架时,请同步更新 GitHub 中的 <code>sku_prefix_to_name</code> 与 <code>new_sku_prefix</code>,push 后线上自动同步生效</div>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# 上传区
# ============================================================================
st.markdown('<div class="nv-section">文件上传</div>', unsafe_allow_html=True)

col_up1, col_up2 = st.columns(2)

with col_up1:
    st.markdown('<div class="uploader-label">产品图册 CSV <span class="uploader-optional">· 可选</span></div>', unsafe_allow_html=True)
    catalog_file = st.file_uploader(
        " ",
        type=["csv"],
        key="catalog",
        label_visibility="collapsed",
        help="包含 SKU 与库位列。上传后会按库位排序拣货单"
    )

with col_up2:
    st.markdown('<div class="uploader-label">拣货 PDF <span class="uploader-required">· 必选</span></div>', unsafe_allow_html=True)
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
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <path d="M13.5 4.5L6 12L2.5 8.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>已加载 <strong>{len(sku_to_location)}</strong> 个 SKU 的库位映射</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("图册缺少 'SKU' 或 '库位' 列")
    except Exception as e:
        st.error(f"读取图册失败:{e}")

# ============================================================================
# SKU 映射表
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
    "NB001":"Organizer Binder",
}
updated_mapping = dict(sku_prefix_to_name)

new_sku_prefix = {
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember",
    "NOX022":"Sunlit Petals","NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals"
}

SIZELESS_SKUS = {"NF001", "NB001"}

# ============================================================================
# 解析工具
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
    <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M14 3v4a1 1 0 0 0 1 1h4M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"
                  stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="empty-state-title">等待上传拣货 PDF</div>
        <div class="empty-state-sub">上传后将自动解析、拆分 bundle 并按库位排序</div>
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

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]

        def map_name(prefix):
            if prefix == "__CHOOSE_SETS__":
                return "Choose 2 Sets(混合套装)"
            return updated_mapping.get(prefix, "未识别")
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
                return "无库位"
            return sku_to_location.get(prefix, "未识别库位")
        pivot["库位"] = pivot["SKU Prefix"].map(map_location)

        # ========== 对账区 ==========
        st.markdown('<div class="nv-section">对账结果</div>', unsafe_allow_html=True)

        nail_qty = int(pivot[~pivot["库位"].isin(["无库位", "未识别库位"])]["Total"].sum()) \
                   if not pivot.empty else 0
        special_qty = int(pivot[pivot["库位"] == "无库位"]["Total"].sum()) \
                      if not pivot.empty else 0
        unknown_loc_qty = int(pivot[pivot["库位"] == "未识别库位"]["Total"].sum()) \
                          if not pivot.empty else 0

        # 状态条
        if expected_total == 0:
            st.markdown("""
            <div class="status-bar warning">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <path d="M8 5v3.5M8 11h.007M7.13 2.59l-5.84 9.74A1 1 0 002.16 14h11.68a1 1 0 00.87-1.67L8.87 2.59a1 1 0 00-1.74 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>未识别到 PDF 中的 Item quantity,无法进行对账校验</span>
            </div>
            """, unsafe_allow_html=True)
        elif total_qty == expected_with_bundle or total_qty == expected_total:
            bundle_note = f" + bundle 拆分 {bundle_extra}" if bundle_extra else ""
            st.markdown(f"""
            <div class="status-bar success">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <path d="M13.5 4.5L6 12L2.5 8.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span><strong>对账一致</strong> · PDF 标注 {expected_total}{bundle_note} = 实际提取 {total_qty}</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            diff = total_qty - expected_with_bundle
            st.markdown(f"""
            <div class="status-bar error">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
                <span><strong>对账不一致</strong> · 期望 {expected_with_bundle},实际 {total_qty},差 {diff:+d} 件</span>
            </div>
            """, unsafe_allow_html=True)

        # KPI 卡
        st.markdown(f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">PDF 标注</div>
                <div class="kpi-value">{expected_total:,}</div>
                <div class="kpi-sub">Item quantity</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">实际提取</div>
                <div class="kpi-value">{total_qty:,}</div>
                <div class="kpi-sub">含 bundle 拆分</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">普通甲片</div>
                <div class="kpi-value">{nail_qty:,}</div>
                <div class="kpi-sub">有库位</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">特殊款</div>
                <div class="kpi-value">{special_qty:,}</div>
                <div class="kpi-sub">无尺寸 / 无库位</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 提取明细
        st.markdown(f"""
        <div class="detail-section">
            <div class="detail-row">
                <span class="detail-label">
                    <span class="detail-label-tag">NF001</span>
                    Free Giveaway
                </span>
                <span class="detail-value">{mystery_units}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">
                    <span class="detail-label-tag">NB001</span>
                    Organizer Binder
                </span>
                <span class="detail-value">{binder_units}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">
                    <span class="detail-label-tag">SETS</span>
                    Choose Sets 混合套装
                </span>
                <span class="detail-value">{choose_sets_units}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">
                    <span class="detail-label-tag">+</span>
                    bundle 拆分多出件数
                </span>
                <span class="detail-value muted">+{bundle_extra}</span>
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
            chips = "".join([f'<span class="sku-chip">{p}</span>' for p in unknown_prefix_list])
            st.markdown(f"""
            <div class="status-bar error">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <path d="M8 5v3.5M8 11h.007M7.13 2.59l-5.84 9.74A1 1 0 002.16 14h11.68a1 1 0 00.87-1.67L8.87 2.59a1 1 0 00-1.74 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div>
                    <div style="margin-bottom: 4px;"><strong>{len(unknown_prefix_list)} 个未识别的 SKU 前缀</strong></div>
                    <div style="margin: 6px 0;">{chips}</div>
                    <div style="font-size: 12px; opacity: 0.85; margin-top: 6px;">
                        请尽快在 GitHub 中更新 <code style="background:rgba(180,37,37,0.08); padding:1px 5px; border-radius:3px; font-family:monospace;">sku_prefix_to_name</code>,push 后重新部署
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # 缺库位提示
        truly_unknown = pivot[pivot["库位"] == "未识别库位"]
        if not truly_unknown.empty:
            names = "、".join(truly_unknown['Product Name'].tolist())
            st.markdown(f"""
            <div class="status-bar warning">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/>
                    <path d="M8 5v3.5M8 11h.007" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
                <span><strong>{len(truly_unknown)} 个款式没有库位信息</strong>(需补充图册 CSV):{names}</span>
            </div>
            """, unsafe_allow_html=True)

        # 特殊款提示
        special_rows = pivot[pivot["库位"] == "无库位"]
        if not special_rows.empty:
            special_names = "、".join(special_rows["Product Name"].tolist())
            st.markdown(f"""
            <div class="status-bar info">
                <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/>
                    <path d="M8 5.5V8.5M8 11h.007" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
                <span><strong>{len(special_rows)} 类无尺寸特殊款</strong>不参与库位拣货:{special_names}</span>
            </div>
            """, unsafe_allow_html=True)

        # ========== 排序 + 表格 ==========
        st.markdown('<div class="nv-section">拣货明细 <span class="nv-section-count">· '
                    f'{len(pivot)} 个款式</span></div>', unsafe_allow_html=True)

        sort_mode = st.radio(
            "排序方式",
            ["按库位顺序", "按字母 A-Z"],
            horizontal=True,
            label_visibility="collapsed",
            help="按库位:从 A-01-01 顺着货架走一遍。按字母:产品名 A-Z 排列"
        )

        is_special = pivot["SKU Prefix"].isin(SIZELESS_SKUS | {"__CHOOSE_SETS__"})
        pivot["_special"] = is_special.astype(int)

        if sort_mode == "按库位顺序":
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

        # 行高亮(克制配色)
        prefix_lookup = {name: sku_p for sku_p, name in updated_mapping.items()}

        def highlight_row(row):
            loc = str(row["库位"])
            name = str(row["Product Name"])
            prefix = prefix_lookup.get(name, "")

            if loc == "未识别库位":
                return ['background-color: #fdfaf2'] * len(row)
            if loc == "无库位":
                return ['background-color: #f8f8f8; color: #888'] * len(row)
            if prefix in new_sku_prefix:
                return ['background-color: #f4faf6'] * len(row)
            return [''] * len(row)

        pivot_styled = pivot.style.apply(highlight_row, axis=1).set_properties(**{
            'font-size': '13px',
            'color': '#0a0a0a',
        })

        st.dataframe(
            pivot_styled,
            use_container_width=True,
            hide_index=True,
            height=min(600, 50 + len(pivot) * 35)
        )

        # 颜色图例
        st.markdown("""
        <div class="color-legend">
            <div class="legend-item">
                <span class="legend-swatch" style="background:#f4faf6; border:1px solid #d6ebde;"></span>
                <span>新款</span>
            </div>
            <div class="legend-item">
                <span class="legend-swatch" style="background:#fdfaf2; border:1px solid #efe5cc;"></span>
                <span>缺库位信息</span>
            </div>
            <div class="legend-item">
                <span class="legend-swatch" style="background:#f8f8f8; border:1px solid #ececec;"></span>
                <span>无尺寸特殊款</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 下载
        st.markdown('<div style="margin-top: 24px;"></div>', unsafe_allow_html=True)
        csv = pivot.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "下载产品明细 CSV",
            data=csv,
            file_name="product_summary_named.csv",
            mime="text/csv"
        )

    else:
        st.markdown("""
        <div class="status-bar error">
            <svg class="status-icon" viewBox="0 0 16 16" fill="none">
                <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            <span>未识别到任何 SKU。请确认 PDF 为可复制文本(非扫描件)</span>
        </div>
        """, unsafe_allow_html=True)
