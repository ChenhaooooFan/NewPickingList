import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射：SKU 前缀 → 产品名（保持不变）
sku_prefix_to_name = {
    "NDF001": "Tropic Paradise", "NPX014": "Afterglow", "NDX001": "Pinky Promise",
    "NHF001": "Gothic Moon", "NHX001": "Emerald Garden", "NLF001": "Divine Emblem",
    "NLF002": "Athena's Glow", "NLJ001": "Golden Pearl", "NLJ002": "BAROQUE BLISS",
    "NLJ003": "Rainbow Reef", "NLX001": "Mermaid's Whisper", "NLX003": "Tropical Tide",
    "NLX005": "Pure Grace", "NOF001": "Royal Amber", "NOF002": "Tiger Lily",
    "NOF003": "Peach Pop", "NOF004": "Sunset Punch", "NOF005": "Glacier Petal",
    "NOJ001": "Island Bloom", "NOJ002": "Floral Lemonade", "NOJ003": "Aurora Tide",
    "NOX001": "Lava Latte", "NPD001": "Leopard's Kiss", "NPF001": "Angel's Grace",
    "NPF002": "Sacred Radiance", "NPF003": "Golden Ivy", "NPF005": "Auric Taurus",
    "NPF006": "Cocoa Blossom", "NPF007": "Bluebell Glow", "NPF008": "Lavender Angel",
    "NPF009": "Vintage Bloom", "NPF010": "Pastel Meadow", "NPF011": "Cherry Cheetah",
    "NPF012": "Rosey Tigress", "NPJ001": "SCARLET QUEEN", "NPJ003": "Stellar Capricorn",
    "NPJ004": "Midnight Violet", "NPJ005": "Vintage Cherry", "NPJ006": "Savanna Bloom",
    "NPJ007": "Angel's Blush", "NPJ008": "Gothic Sky", "NPJ009": "Violet Seashell",
    "NPX001": "Royal Elegance", "NPX002": "Angel's Ruby", "NPX005": "Indigo Breeze",
    "NPX006": "Autumn Petal", "NPX007": "Lavender Bliss", "NPX008": "Dreamy Ballerina",
    "NPX009": "Rose Eden", "NPX010": "Blooming Meadow", "NPX011": "Safari Petal",
    "NPX012": "Milky Ribbon", "NPX013": "Champagne Wishes", "NLX004": "Holiday Bunny",
    "NPJ010": "Glossy Doll", "NPF013": "Opal Glaze", "NOX002": "Cherry Kiss",
    "NOJ004": "Peachy Coast", "NYJ001": "Rosy Ribbon", "NOF008": "Starlit Jungle",
    "NOF006": "Coral Sea", "NOF009": "Rosé Angel", "NPF014": "Arabian Nights",
    "NOX003": "Caramel Nova", "NPF016": "Golden Muse", "NPF017": "Ruby Bloom",
    "NOF007": "Citrus Blush", "NOJ005": "Ocean Whisper", "NPF015": "Rosé Petal",
    "NOF010": "Spring Moss", "NM001": "Mystery Set", "NOF011": "Velvet Flame",
    "NPJ011": "Bat Boo", "NOX004": "Azure Muse", "NPX016": "Silky Pearl",
    "NPX015": "Spooky Clown", "NOX005": "Honey Daisy", "NPJ012": "Gothic Mirage",
    "NOX006": "Imperial Bloom", "NPX017": "Rouge Letter", "NOF013": "Sakura Blush",
    "NPF018": "Wild Berry", "NOF012": "Rose Nocturne", "NIX001": "Golden Maple",
    "NOX007": "Stellar Whisper", "NOF014": "Desert Rose", "NPF019": "Lunar Whisper",
    "NOF015": "Mocha Grace", "NOX009": "Moonlit Petal", "NOX008": "Espresso Petals",
    "NPX018": "Ruby Ribbon"
}
updated_mapping = dict(sku_prefix_to_name)

# —— 小工具 —— #
def _clean(t: str) -> str:
    return (t.replace('\u00ad','')   # 软连字符
             .replace('\u200b','')  # 零宽空格
             .replace('\u00a0',' ') # NBSP
             .replace('–','-').replace('—','-'))

# 1–4 件 bundle 拆分
def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    s = re.sub(r'\s+','', sku_with_size).replace('–','-').replace('—','-')
    if '-' not in s:
        counter[s] += qty; return
    code, size = s.split('-', 1)
    if len(code) % 6 == 0 and 6 <= len(code) <= 24:
        parts = [code[i:i+6] for i in range(0, len(code), 6)]
        if all(re.fullmatch(r'[A-Z]{3}\d{3}', p or '') for p in parts):
            for p in parts:
                counter[f'{p}-{size}'] += qty
            return
    counter[s] += qty  # 回退

# —— 用 Order ID 锚点反推整行（专治“SKU 被拆成两行”的情况） —— #
def parse_rows_by_anchor(doc) -> dict:
    out = defaultdict(int)
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t),b,ln,sp)
                 for (x0,y0,x1,y1,t,b,ln,sp) in page.get_text('words')
                 if _clean(t).strip()]
        if not words:
            continue

        # 行高与行带容差（放宽到 2.5×，能覆盖单元格内的换行）
        heights = [y1-y0 for _,y0,_,y1,_,_,_,_ in words]
        line_h = (sum(heights)/len(heights)) if heights else 12
        band   = line_h * 2.5

        # 找到所有 Order ID（≥9 位数字），一行就一个
        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t,_,_,_ in words
                   if re.fullmatch(r'\d{9,}', t.replace(',',''))]

        for ax0,ay0,ax1,ay1,_ in anchors:
            yc = (ay0+ay1)/2

            # 1) 找 Qty：在锚点左侧、“同一行带”、并且取“最靠右”的 1–3 位数字
            qty_cands = [(x0, int(t.replace(',',''))) for x0,y0,_,y1,t,_,_,_ in words
                         if (x0 < ax0) and re.fullmatch(r'\d{1,3}', t.replace(',',''))
                         and abs(((y0+y1)/2) - yc) <= band]
            if not qty_cands:
                continue
            qx0, qty = max(qty_cands, key=lambda k: k[0])

            # 2) 在 Qty 左侧，收集“疑似 Seller SKU”的词：
            #    只保留由 大写字母/数字/连字符 组成的 token（能拿到“NPJ011NPX01”和“5-M”）
            sku_tokens = []
            for sx0,sy0,_,sy1,t,_,_,_ in words:
                if sx0 < qx0 and abs(((sy0+sy1)/2) - yc) <= band:
                    if re.fullmatch(r'[A-Z0-9-]+', t):
                        sku_tokens.append((sy0, sx0, t))
            if not sku_tokens:
                continue

            # 3) 先纵后横，拼成整块；再用正则抽出目标片段
            sku_tokens.sort(key=lambda k: (round(k[0], 1), k[1]))
            candidate = re.sub(r'\s+', '', ''.join(t for _,_,t in sku_tokens))
            m = re.search(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]', candidate)
            if not m:
                continue
            seller_sku = m.group(0)
            expand_bundle(out, seller_sku, qty)
    return out

if uploaded_file:
    # 读 PDF
    data = uploaded_file.read()
    doc = fitz.open(stream=data, filetype="pdf")

    # 提取全文用于 “Item quantity” 校验（保留你原来的行为）
    all_text = "".join(p.get_text() for p in doc)
    m_total = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m_total.group(1)) if m_total else None

    # —— 只用“锚点法”做解析（更稳，能抓到跨行的 Bundle） —— #
    sku_counts = parse_rows_by_anchor(doc)

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"] = df["Seller SKU"].apply(lambda x: x.split("-")[0])
        df["Size"]       = df["Seller SKU"].apply(lambda x: x.split("-")[1])
        df["Product Name"] = df["SKU Prefix"].apply(lambda x: updated_mapping.get(x, "❓未识别"))

        # 未识别前缀可手动补全（保持你的交互）
        unknown = df[df["Product Name"].str.startswith("❓")]["SKU Prefix"].unique().tolist()
        if unknown:
            st.warning("⚠️ 有未识别的 SKU 前缀，请补全：")
            for prefix in unknown:
                name_input = st.text_input(f"🔧 SKU 前缀 {prefix} 的产品名称：", key=prefix)
                if name_input:
                    updated_mapping[prefix] = name_input
                    df.loc[df["SKU Prefix"] == prefix, "Product Name"] = name_input

        # 列顺序与下载（完全不变）
        df = df[["Product Name", "Size", "Seller SKU", "Qty"]].sort_values(by=["Product Name", "Size"])

        total_qty = int(df["Qty"].sum())
        st.subheader(f"📦 实际拣货总数量：{total_qty}")

        if expected_total is not None:
            if total_qty == expected_total:
                st.success(f"✅ 与拣货单一致！（{expected_total}）")
            else:
                st.error(f"❌ 数量不一致！拣货单为 {expected_total}，实际为 {total_qty}")
        else:
            st.warning("⚠️ 未能识别 Item quantity")

        st.dataframe(df)

        # 下载结果（文件名与编码保持不变）
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df  = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀", "产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行（锚点法仍未命中）。请确认 PDF 为可复制文本，或把样例发我做一次专用适配。")
        with st.expander("调试预览（前 800 字）"):
            st.text(all_text[:800])
