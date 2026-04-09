import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具(´∀｀)♡", layout="centered")
st.title("NailVesta 拣货单汇总工具💗")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称（支持 bundle 与 Mystery 对账规则）")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射表（保持不变）
# 该映射表保持不变
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
    "NOJ011":"Snowy Comet","NOX013":"Christmas Village","NOJ009":"Reindeer Glow","NIX002":"Golden Orchid", "NPX021":"Twinkle Pine",
    "NOF018":"Glacier Bloom","NOJ010":"Rosé Noir","NPX022":"Merry Charm", "NPJ014":"Snow Pixie","NPJ018":"Frost Ruby",
    "NPJ017":"Starlit Rift","NPF021":"Candy Cane","NPJ016":"Fairy Nectar","NPJ015":"Icy Viper","NOX014":"Taro Petal","NVT001":"Tool Kits",
    "NF001":"Free Giveaway","NIF001":"Lilac Veil","NIF002":"Gingerbread","NOX015":"Glitter Doll","NOJ012":"Winery Flame",
    "NOF021":"Velvet Ribbon","NPX024":"Rose Wine","NPX023":"Rosy Promise","NMF001":"Cherry Crush","NBX001":"Ballet Petal",
    "NMF003":"Royal Treasure","NMF002":"Safari Princess","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost",
    "NPJ019":"Gothic Mist","NOJ015":"Sapphire Bloom",
    "NPX025":"Cocoa Teddy","NVF001":"Golden Bloom","NBJ002":"Cherry Drop",
    "NOF022":"Aqua Reverie","NPF023":"Arctic Starlight","NDJ001":"Snow Knit",
    "NOX016":"Cherry Ribbon","NOX017":"Ruby Bow","NMF004":"Lavender Bloom","NDX002":"Cloudy Knit","NMJ003":"Gothic Rose","NOF025":"Cherry Romance","NMJ001":"Milky Cloud",
    "NMX001":"Petal Muse","NOF024":"Floral Muse","NVX001":"Sakura Macaron","NVF002":"Dreamy Bloom","NOJ017":"Floral Garden","NOJ016":"Jade Blossom","NVX002":"Pastel Bloom",
    "NPF023":"Fairy Garden","NBJ001":"Stone Petal","NOF027":"Acai Bloom","NPJ021":"Champagne Blossom","NPJ020":"Citrus Daisy","NOJ018":"Ribbon Lily","NVF005":"Dreamy Sakura",
    "NDX003":"Meadow Petals","NOX018":"Strawberry Kiss","NOJ020":"Raibow Bloom","NPF026":"Seaside Sundae","NVJ001":"Prism Aura","NDX005":"Midnight Glam","NDX004":"Starry Tide",
    "NPX027":"Hibiscus Tide","NPX026":"Ocean Yuzu","NWX001":"Seashell Sorbet","NOF026":"Island Paradise","NPF024":"Tropical Breeze","NOJ021":"Petal Gelato","NVF003":"Apricot Cream","NMJ005":"Glossy Aura","NGX001":"Seafoam Jewel","NOF028":"Floral Cherry"
}
updated_mapping = dict(sku_prefix_to_name)

# 🆕 新款映射表，所有新款加到这，格式为："NOF018":"Glacier Bloom"
new_sku_prefix = {
    "NPJ014":"Snow Pixie"
}

# ---------- 小工具 ----------
# 支持 NF001，无尺码 bundle
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}|NF001){1,4}-[SML])', re.DOTALL)
QTY_AFTER  = re.compile(r'\b([1-9]\d{0,2})\b')
ITEM_QTY_RE = re.compile(r"Item\s+quantity[:：]?\s*(\d+)", re.I)
NM_ONLY = re.compile(r'\bNF001\b')

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
            parts.append('NM001'); 
            i += 5; 
            continue
        seg = code[i:i+6]
        if re.fullmatch(r'[A-Z]{3}\d{3}', seg):
            parts.append(seg); 
            i += 6; 
            continue
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

# ---------- 主逻辑 ----------
if uploaded_file:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    text = "\n".join([p.get_text("text") for p in doc])
    text = normalize_text(text)

    # 对账原始数量
    m_total = ITEM_QTY_RE.search(text)
    expected_total = int(m_total.group(1)) if m_total else 0

    # 修复换行断裂 SKU
    text_fixed = fix_orphan_digit_before_size(text)

    # 提取 SKU 数量
    sku_counts = defaultdict(int)
    bundle_extra = 0
    mystery_units = 0

    # —— 含尺码部分 ——
    for m in SKU_BUNDLE.finditer(text_fixed):
        sku_raw = re.sub(r'\s+', '', m.group(1))
        after = text_fixed[m.end(): m.end()+50]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        extra, myst = expand_bundle(sku_counts, sku_raw, qty)
        bundle_extra += extra
        mystery_units += myst

    # —— 无尺码 NF001 ——
    for m in NM_ONLY.finditer(text_fixed):
        nxt = text_fixed[m.end(): m.end()+3]
        if '-' in nxt: 
            continue
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NF001'] += qty
        mystery_units += qty

    # 实际提取
    total_qty = sum(sku_counts.values())
    expected_bundle = expected_total + bundle_extra
    expected_final = expected_bundle - mystery_units  # ✅ 对账规则：bundle + mystery 抵扣

    # 表格输出
    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"] = df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))

        # ========== 改动1: 透视表 — 一个款式一行，S/M/L 各一列 ==========
        # 先把无尺码的行（如 NF001）单独处理
        df_sized = df[df["Size"].notna()].copy()
        df_nosized = df[df["Size"].isna()].copy()

        pivot = df_sized.pivot_table(
            index=["SKU Prefix", "Product Name"],
            columns="Size",
            values="Qty",
            aggfunc="sum",
            fill_value=0
        ).reset_index()

        # 确保 S/M/L 列都存在且按顺序
        for sz in ["S", "M", "L"]:
            if sz not in pivot.columns:
                pivot[sz] = 0
        pivot = pivot[["SKU Prefix", "Product Name", "S", "M", "L"]]
        pivot["Total"] = pivot["S"] + pivot["M"] + pivot["L"]

        # 无尺码行（如 NF001）追加
        if not df_nosized.empty:
            for _, row in df_nosized.iterrows():
                new_row = {
                    "SKU Prefix": row["SKU Prefix"],
                    "Product Name": row["Product Name"],
                    "S": 0, "M": 0, "L": 0,
                    "Total": row["Qty"]
                }
                pivot = pd.concat([pivot, pd.DataFrame([new_row])], ignore_index=True)

        # ========== 改动2: Free Giveaway (NF001) 放最后 ==========
        is_free = pivot["SKU Prefix"] == "NF001"
        is_new = pivot["SKU Prefix"].isin(new_sku_prefix.keys())

        # 排序键: 0=新款, 1=普通款, 2=Free Giveaway
        pivot["_sort"] = 1
        pivot.loc[is_new, "_sort"] = 0
        pivot.loc[is_free, "_sort"] = 2

        pivot = pivot.sort_values(
            by=["_sort", "Product Name"],
            ascending=[True, True]
        ).drop(columns=["_sort"]).reset_index(drop=True)

        # 📊 对账展示
        st.subheader("📦 对账结果")
        st.markdown(f"""
        - PDF 标注数量（Item quantity）: **{expected_total}**  
        - bundle 额外件数（+）: **{bundle_extra}**  
        - Mystery(NF001) 件数（−）: **{mystery_units}**  
        - 调整后期望值（bundle−Mystery）: **{expected_final}**  
        - 实际提取数量: **{total_qty}**
        """)

        if expected_total == 0:
            st.warning("⚠️ 未识别到 Item quantity。")
        elif total_qty == expected_total:
            st.success(f"✅ 与原始 PDF 数量一致（{expected_total}）")
        elif total_qty == expected_bundle:
            st.info(f"ℹ️ 与原始不符，但考虑 bundle 后相符（差 {total_qty - expected_total}）")
        elif total_qty == expected_final:
            st.success(f"✅ 与 PDF 数量不符，但考虑 bundle 与 Mystery 抵扣后相符（期望 {expected_final}）")
        else:
            st.error(f"❌ 不一致：PDF {expected_total} → 调整后 {expected_final}，实际 {total_qty}")

        # 🌸 新款淡粉色高亮 + Free Giveaway 淡灰色
        def highlight_row(row):
            prefix = str(row["SKU Prefix"])
            if prefix in new_sku_prefix:
                return ['background-color: #ffe4ec'] * len(row)
            if prefix == "NF001":
                return ['background-color: #f0f0f0'] * len(row)
            return [''] * len(row)

        pivot_styled = pivot.style.apply(highlight_row, axis=1)

        # 明细表
        st.dataframe(pivot_styled, use_container_width=True)

        # 下载（用 pivot 原始数据）
        csv = pivot.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

    else:
        st.error("未识别到任何 SKU。请确认 PDF 为可复制文本。")
