import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射：SKU 前缀 → 产品名（不变）
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

# —— Bundle 拆分：支持 1–4 件；不合规则原样累计 —— #
def expand_bundle(counter: dict, sku_with_size: str, qty: int):
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

def _norm_token(t: str) -> str:
    """规范化表头单词，便于匹配 qty / order / seller / sku。"""
    return re.sub(r'[^a-z]', '', t.lower())

# —— 按“列”解析（修正：明确分出 Order ID 列，Qty 列不再覆盖到它） —— #
def parse_table_like(doc) -> dict:
    sku_counts = defaultdict(int)

    for page in doc:
        words = page.get_text('words')  # (x0, y0, x1, y1, text, block, line, span)

        # 规范化文本
        cleaned = []
        for x0, y0, x1, y1, t, b, ln, sp in words:
            t = (t.replace('\u00ad', '')     # 软连字符
                   .replace('\u200b', '')    # 零宽空格
                   .replace('\u00a0', ' ')   # NBSP -> 空格
                   .replace('–', '-')
                   .replace('—', '-'))
            if t.strip():
                cleaned.append((x0, y0, x1, y1, t, b, ln, sp))
        words = cleaned
        if not words:
            continue

        # 1) 找包含 Seller SKU / Qty(/Quantity) / Order ID 的表头行
        header_map = {}
        row_groups = {}
        for x0,y0,x1,y1,t,b,ln,sp in words:
            row_groups.setdefault((b,ln), []).append((x0,t))
        header_key = None
        for key, items in row_groups.items():
            tokens = [_norm_token(t) for _,t in items]
            if ('seller' in tokens and 'sku' in tokens) and (('qty' in tokens) or ('quantity' in tokens)):
                header_key = key
                # 记录各关键单词的最左 x0
                for x,t in items:
                    tt = _norm_token(t)
                    header_map.setdefault(tt, []).append(x)
                break
        if header_key is None:
            # 兜底：用视觉最靠上的一行
            header_key = min(row_groups.keys(), key=lambda k: k[1])
            for x,t in row_groups[header_key]:
                tt = _norm_token(t)
                header_map.setdefault(tt, []).append(x)

        # 2) 计算三列的 x 起点
        col_x = {}
        if 'seller' in header_map:
            col_x['seller_sku'] = min(header_map['seller'])
        if 'qty' in header_map:
            col_x['qty'] = min(header_map['qty'])
        elif 'quantity' in header_map:
            col_x['qty'] = min(header_map['quantity'])
        # “Order ID” 可能分成两个词
        if 'order' in header_map:
            col_x['order_id'] = min(header_map['order'])
        if 'orderid' in header_map:  # 万一合在一起
            col_x['order_id'] = min(col_x.get('order_id', 1e9), min(header_map['orderid']))

        # 必须至少有 seller_sku & qty
        if 'seller_sku' not in col_x or 'qty' not in col_x:
            continue

        # 3) 按列起点算列范围（用“下一个列起点的中点”为右边界）
        page_w = page.rect.width
        positions = sorted([(col_x['seller_sku'], 'seller_sku'),
                            (col_x['qty'], 'qty')] + ([(col_x['order_id'], 'order_id')] if 'order_id' in col_x else []),
                           key=lambda x: x[0])

        def col_range(name):
            idx = [i for i,(_,n) in enumerate(positions) if n==name][0]
            left = positions[idx][0] - 4
            right = positions[idx+1][0] - 4 if idx+1 < len(positions) else page_w
            return left, right

        sku_xmin, sku_xmax = col_range('seller_sku')
        qty_xmin, qty_xmax = col_range('qty')
        # 如果存在 Order ID 列，Qty 右边界就会在它的左侧；否则保持到页面右缘

        # 4) 行高估计 + 锚点数量词（仅允许短数字，避免把 Order ID 当数量）
        heights = [y1-y0 for _,y0,_,y1,_,_,_,_ in words]
        line_h = (sum(heights)/len(heights)) if heights else 12

        qty_words = []
        for x0,y0,x1,y1,t,b,ln,sp in words:
            if qty_xmin <= x0 <= qty_xmax:
                val = t.replace(',', '')
                if re.fullmatch(r'\d{1,3}', val):  # 最多3位，排除长订单号
                    qty_words.append((x0,y0,x1,y1,int(val)))

        # 5) 对每个数量词，聚合同一“行带”的 Seller SKU 单元格词并拼接
        for x0,y0,x1,y1,qty in qty_words:
            yc = (y0 + y1) / 2
            sku_parts = []
            for sx0,sy0,sx1,sy1,t,b,ln,sp in words:
                if sku_xmin <= sx0 <= sku_xmax:
                    sc = (sy0 + sy1) / 2
                    if abs(sc - yc) <= line_h * 1.2:  # 容忍换行
                        sku_parts.append((sx0, t))
            if not sku_parts:
                continue
            sku_cell = ''.join(t for _,t in sorted(sku_parts, key=lambda k: k[0]))
            sku_cell = re.sub(r'\s+', '', sku_cell)
            if re.fullmatch(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]', sku_cell):
                expand_bundle(sku_counts, sku_cell, qty)

    return sku_counts

if uploaded_file:
    # 打开 PDF
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")

    # 读取拣货单总数（保持你的原逻辑）
    all_text = ""
    for p in doc:
        all_text += p.get_text()
    m = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m.group(1)) if m else None

    # 表格版解析（修正后的）
    sku_counts = parse_table_like(doc)

    if not sku_counts:
        st.error("未识别到任何 SKU 行（表格列解析未命中）。请把样例 PDF 发我做一次专用适配，或导出为可复制文本的 PDF。")
        with st.expander("调试预览（前 800 字）"):
            st.text(all_text[:800])
        st.stop()

    # —— 后续输出与导出：保持不变 —— #
    df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
    df["SKU Prefix"] = df["Seller SKU"].apply(lambda x: x.split("-")[0])
    df["Size"] = df["Seller SKU"].apply(lambda x: x.split("-")[1])
    df["Product Name"] = df["SKU Prefix"].apply(lambda x: updated_mapping.get(x, "❓未识别"))

    unknown = df[df["Product Name"].str.startswith("❓")]["SKU Prefix"].unique().tolist()
    if unknown:
        st.warning("⚠️ 有未识别的 SKU 前缀，请补全：")
        for prefix in unknown:
            name_input = st.text_input(f"🔧 SKU 前缀 {prefix} 的产品名称：", key=prefix)
            if name_input:
                updated_mapping[prefix] = name_input
                df.loc[df["SKU Prefix"] == prefix, "Product Name"] = name_input

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

    # 下载结果（文件名与编码不变）
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

    map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀", "产品名称"])
    map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
