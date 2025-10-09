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
    counter[s] += qty

# —— 核心：按“列”解析 —— #
def parse_table_like(doc) -> dict:
    sku_counts = defaultdict(int)

    for page in doc:
        words = page.get_text('words')  # (x0, y0, x1, y1, text, block, line, span)
        # 规范化文本
        clean_words = []
        for x0, y0, x1, y1, t, b, ln, sp in words:
            t = (t.replace('\u00ad', '')   # 软连字符
                   .replace('\u200b', '')  # 零宽空格
                   .replace('\u00a0', ' ') # NBSP -> 空格
                   .replace('–', '-')
                   .replace('—', '-'))
            if t.strip():
                clean_words.append((x0, y0, x1, y1, t, b, ln, sp))
        words = clean_words
        if not words:
            continue

        # 1) 找表头所在行：包含 "Seller" 和 "SKU"，以及 "Qty"
        header_candidates = {}
        for x0, y0, x1, y1, t, b, ln, sp in words:
            if t.lower() in ('seller', 'sku', 'seller sku', 'qty', 'quantity', 'order', 'order id'):
                header_candidates.setdefault((b, ln), []).append((x0, y0, x1, y1, t))
        header_key = None
        for key, items in header_candidates.items():
            labels = ' '.join([i[4].lower() for i in items])
            if ('seller' in labels and 'sku' in labels) and ('qty' in labels or 'quantity' in labels):
                header_key = key; break
        if header_key is None:
            # 兜底：用最靠上的一行
            header_key = min({(b, ln) for _,_,_,_,_,b,ln,_ in words}, key=lambda k: k[1])

        # 2) 计算各列 x 范围：根据这一行的各标题位置推断
        header_items = sorted([i for i in header_candidates.get(header_key, [])], key=lambda t: t[0])
        # 如果能拿到明确的 Seller SKU 和 Qty 的 x0
        xs = [i[0] for i in header_items]
        texts = [i[4].lower() for i in header_items]
        col_x = {}
        for x, txt in zip(xs, texts):
            if 'seller' in txt and 'sku' in txt:
                col_x['seller_sku'] = x
            if 'qty' in txt or 'quantity' in txt:
                col_x['qty'] = x

        # 万一没抓到，用启发式：在页面上找包含 "Seller" 的词的 x0 作为 Seller SKU 列
        if 'seller_sku' not in col_x:
            ss = [x0 for x0,_,_,_,t,_,_,_ in words if t.lower() == 'seller']
            if ss: col_x['seller_sku'] = min(ss)
        if 'qty' not in col_x:
            qs = [x0 for x0,_,_,_,t,_,_,_ in words if t.lower() in ('qty','quantity')]
            if qs: col_x['qty'] = min(qs)

        if 'seller_sku' not in col_x or 'qty' not in col_x:
            # 如果列头都找不到，就直接放弃这一页（通常不会发生）
            continue

        # 用标题的 x0 排序得到各列边界（中点当作分界）
        header_positions = sorted([(col_x['seller_sku'], 'seller_sku'), (col_x['qty'], 'qty')], key=lambda x: x[0])
        # 估算 seller_sku 列范围：从它的 x 到下一个列的中点
        page_width = page.rect.width
        def col_range(name):
            idx = [i for i,(_,n) in enumerate(header_positions) if n==name][0]
            left = header
