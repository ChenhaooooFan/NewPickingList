import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射：SKU 前缀 → 产品名
sku_prefix_to_name = {
    "NDF001": "Tropic Paradise",
    "NPX014": "Afterglow",
    "NDX001": "Pinky Promise",
    "NHF001": "Gothic Moon",
    "NHX001": "Emerald Garden",
    "NLF001": "Divine Emblem",
    "NLF002": "Athena's Glow",
    "NLJ001": "Golden Pearl",
    "NLJ002": "BAROQUE BLISS",
    "NLJ003": "Rainbow Reef",
    "NLX001": "Mermaid's Whisper",
    "NLX003": "Tropical Tide",
    "NLX005": "Pure Grace",
    "NOF001": "Royal Amber",
    "NOF002": "Tiger Lily",
    "NOF003": "Peach Pop",
    "NOF004": "Sunset Punch",
    "NOF005": "Glacier Petal",
    "NOJ001": "Island Bloom",
    "NOJ002": "Floral Lemonade",
    "NOJ003": "Aurora Tide",
    "NOX001": "Lava Latte",
    "NPD001": "Leopard's Kiss",
    "NPF001": "Angel's Grace",
    "NPF002": "Sacred Radiance",
    "NPF003": "Golden Ivy",
    "NPF005": "Auric Taurus",
    "NPF006": "Cocoa Blossom",
    "NPF007": "Bluebell Glow",
    "NPF008": "Lavender Angel",
    "NPF009": "Vintage Bloom",
    "NPF010": "Pastel Meadow",
    "NPF011": "Cherry Cheetah",
    "NPF012": "Rosey Tigress",
    "NPJ001": "SCARLET QUEEN",
    "NPJ003": "Stellar Capricorn",
    "NPJ004": "Midnight Violet",
    "NPJ005": "Vintage Cherry",
    "NPJ006": "Savanna Bloom",
    "NPJ007": "Angel's Blush",
    "NPJ008": "Gothic Sky",
    "NPJ009": "Violet Seashell",
    "NPX001": "Royal Elegance",
    "NPX002": "Angel's Ruby",
    "NPX005": "Indigo Breeze",
    "NPX006": "Autumn Petal",
    "NPX007": "Lavender Bliss",
    "NPX008": "Dreamy Ballerina",
    "NPX009": "Rose Eden",
    "NPX010": "Blooming Meadow",
    "NPX011": "Safari Petal",
    "NPX012": "Milky Ribbon",
    "NPX013": "Champagne Wishes",
    "NLX004": "Holiday Bunny",
    "NPJ010": "Glossy Doll",
    "NPF013": "Opal Glaze",
    "NOX002": "Cherry Kiss",
    "NOJ004": "Peachy Coast",
    "NYJ001": "Rosy Ribbon",
    "NOF008": "Starlit Jungle",
    "NOF006": "Coral Sea",
    "NOF009": "Rosé Angel",
    "NPF014": "Arabian Nights",
    "NOX003": "Caramel Nova",
    "NPF016": "Golden Muse",
    "NPF017": "Ruby Bloom",
    "NOF007": "Citrus Blush",
    "NOJ005": "Ocean Whisper",
    "NPF015": "Rosé Petal",
    "NOF010": "Spring Moss",
    "NM001": "Mystery Set",
    "NOF011": "Velvet Flame",
    "NPJ011": "Bat Boo",
    "NOX004": "Azure Muse",
    "NPX016": "Silky Pearl",
    "NPX015": "Spooky Clown",
    "NOX005": "Honey Daisy",
    "NPJ012": "Gothic Mirage",
    "NOX006": "Imperial Bloom",
    "NPX017": "Rouge Letter",
    "NOF013": "Sakura Blush",
    "NPF018": "Wild Berry",
    "NOF012": "Rose Nocturne",
    "NIX001": "Golden Maple",
    "NOX007": "Stellar Whisper",
    "NOF014": "Desert Rose",
    "NPF019": "Lunar Whisper",
    "NOF015": "Mocha Grace",
    "NOX009": "Moonlit Petal",
    "NOX008": "Espresso Petals",
    "NPX018": "Ruby Ribbon"
}
updated_mapping = dict(sku_prefix_to_name)

# —— Bundle 拆分（1–4件），不合规则原样累计 —— #
def expand_bundle_or_single(sku_with_size: str, qty: int, counter: dict):
    s = re.sub(r'\s+', '', sku_with_size).replace('–', '-').replace('—', '-')
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

def _clean(t: str) -> str:
    return (t.replace('\u00ad','')   # 软连字符
             .replace('\u200b','')  # 零宽空格
             .replace('\u00a0',' ') # NBSP
             .replace('–','-').replace('—','-'))

# —— 兜底：用 Order ID（≥9位数字）锚点定位每一行，再向左找 Qty（1–3位），再拼接 Seller SKU —— #
def parse_by_order_anchor(doc) -> dict:
    out = defaultdict(int)
    SKU_WINDOW = 320  # 从 Qty 向左回看窗口宽度（像素）
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t),b,ln,sp)
                 for (x0,y0,x1,y1,t,b,ln,sp) in page.get_text('words')
                 if _clean(t).strip()]
        if not words:
            continue

        # 行高估计
        heights = [y1-y0 for _,y0,_,y1,_,_,_,_ in words]
        line_h = (sum(heights)/len(heights)) if heights else 12
        band = line_h * 1.3

        # 订单号锚点
        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t,_,_,_ in words
                   if re.fullmatch(r'\d{9,}', t.replace(',', ''))]

        for ax0,ay0,ax1,ay1,oid in anchors:
            yc = (ay0+ay1)/2

            # Qty：锚点左侧，同一行带内，取“最靠右”的 1–3 位短数字
            qty_cands = []
            for x0,y0,x1,y1,t,_,_,_ in words:
                if x0 < ax0 and re.fullmatch(r'\d{1,3}', t.replace(',','')):
                    if abs(((y0+y1)/2) - yc) <= band:
                        qty_cands.append((x0,int(t.replace(',',''))))
            if not qty_cands:
                continue
            qx0, qty = max(qty_cands, key=lambda k: k[0])  # 最靠右

            # Seller SKU：在 Qty 左侧一个窗口内，同一行带；先纵后横拼接
            cand = []
            left_bound = qx0 - SKU_WINDOW
            for x0,y0,x1,y1,t,_,_,_ in words:
                if left_bound <= x0 < qx0 and abs(((y0+y1)/2) - yc) <= band:
                    cand.append((y0, x0, t))
            if not cand:
                continue
            cand.sort(key=lambda k: (round(k[0],1), k[1]))
            cell = re.sub(r'\s+', '', ''.join(t for _,_,t in cand))

            m = re.search(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]', cell)
            if not m:
                continue
            sku_text = m.group(0)
            expand_bundle_or_single(sku_text, qty, out)
    return out

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 读取拣货单总数（原逻辑保持）
    total_quantity_match = re.search(r"Item quantity[:：]?\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    # —— 快速路径：整段文本正则（列内未换行的行都会命中） —— 
    pattern = r"((?:[A-Z]{3}\d{3}){1,4}-[SML])\s+(\d+)\s+\d{9,}"
    matches = re.findall(pattern, text)

    sku_counts = defaultdict(int)
    for raw_sku, qty in matches:
        expand_bundle_or_single(raw_sku, int(qty), sku_counts)

    # —— 兜底：针对被拆行的 Seller SKU（如：NPJ011NPX01 + 下一行 5-M） —— #
    anchor_counts = parse_by_order_anchor(doc)
    # 只补充“快速路径未识别到”的 SKU，避免重复
    for k, v in anchor_counts.items():
        if k not in sku_counts:
            sku_counts[k] += v

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"] = df["Seller SKU"].apply(lambda x: x.split("-")[0])
        df["Size"] = df["Seller SKU"].apply(lambda x: x.split("-")[1])
        df["Product Name"] = df["SKU Prefix"].apply(lambda x: updated_mapping.get(x, "❓未识别"))

        # 用户手动补全未知前缀（原逻辑保持）
        unknown = df[df["Product Name"].str.startswith("❓")]["SKU Prefix"].unique().tolist()
        if unknown:
            st.warning("⚠️ 有未识别的 SKU 前缀，请补全：")
            for prefix in unknown:
                name_input = st.text_input(f"🔧 SKU 前缀 {prefix} 的产品名称：", key=prefix)
                if name_input:
                    updated_mapping[prefix] = name_input
                    df.loc[df["SKU Prefix"] == prefix, "Product Name"] = name_input

        # 列顺序与排序（原样保持）
        df = df[["Product Name", "Size", "Seller SKU", "Qty"]].sort_values(by=["Product Name", "Size"])

        total_qty = df["Qty"].sum()
        st.subheader(f"📦 实际拣货总数量：{total_qty}")

        if expected_total:
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

        # 下载 SKU 映射表（文件名与编码保持不变）
        map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀", "产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行（已启用 Order ID 锚点兜底仍未命中）。请确认 PDF 为可复制文本。")
        with st.expander("调试预览（前 800 字）"):
            st.text(text[:800])
