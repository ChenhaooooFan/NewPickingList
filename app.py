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

# ——— 辅助：Bundle 拆分（1–4件），不合规则原样累计 ———
def add_sku_expanded(counter: dict, sku_with_size: str, qty: int):
    sku = re.sub(r'\s+', '', sku_with_size)               # 去内部空白
    sku = sku.replace('–', '-').replace('—', '-')         # 统一破折号
    if '-' not in sku:
        counter[sku] += qty
        return
    code, size = sku.split('-', 1)
    if len(code) % 6 == 0 and 6 <= len(code) <= 24:
        parts = [code[i:i+6] for i in range(0, len(code), 6)]
        if all(re.fullmatch(r'[A-Z]{3}\d{3}', p) for p in parts):
            for p in parts:
                counter[f'{p}-{size}'] += qty
            return
    counter[sku] += qty  # 回退

# ——— 词级兜底解析：同一行内拼接相邻词识别 SKU，并向右找数量 ———
def parse_by_words(doc) -> dict:
    sku_counts = defaultdict(int)
    for page in doc:
        words = page.get_text('words')  # (x0, y0, x1, y1, "word", block_no, line_no, span_no)
        # 按行分组
        lines = defaultdict(list)
        for (x0, y0, x1, y1, w, b, ln, sp) in words:
            # 统一一些怪空白
            w = w.replace('\u00ad', '').replace('\u200b', '').replace('\u00a0', ' ')
            w = w.replace('–', '-').replace('—', '-')
            if w.strip():
                lines[(b, ln)].append((x0, w))
        # 每行处理
        for key in sorted(lines.keys()):
            line_words = [w for _, w in sorted(lines[key], key=lambda t: t[0])]
            # 滑动窗口：相邻 1~3 词拼接试成 SKU
            n = len(line_words)
            i = 0
            while i < n:
                found = False
                for win in (3, 2, 1):
                    if i + win > n:
                        continue
                    cand = ''.join(line_words[i:i+win])
                    cand_clean = re.sub(r'\s+', '', cand)
                    cand_clean = cand_clean.replace('–', '-').replace('—', '-')
                    if re.fullmatch(r'(?:[A-Z]{3}\d{3}){1,4}-[SML]', cand_clean):
                        # 向右找第一个纯数字词作为数量
                        qty = None
                        j = i + win
                        while j < n:
                            wj = line_words[j].replace(',', '')
                            if re.fullmatch(r'\d+', wj):
                                qty = int(wj)
                                break
                            j += 1
                        if qty is not None:
                            add_sku_expanded(sku_counts, cand_clean, qty)
                            i = j + 1
                            found = True
                        break
                if not found:
                    i += 1
    return sku_counts

if uploaded_file:
    # 读取 PDF 原文
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")

    # 读取整段文本用于“快速路径”
    raw_text = ""
    for page in doc:
        raw_text += page.get_text()

    # —— 文本规范化：粘合/清理/统一 —— #
    text = raw_text
    text = re.sub(r'(?<=[A-Z0-9])\r?\n(?=[A-Z0-9])', '', text)   # 粘合字母数字间换行
    text = (text.replace('\u00ad', '')        # 软连字符
                 .replace('\u200b', '')       # 零宽空格
                 .replace('\u00a0', ' ')      # NBSP
                 .replace('–', '-')
                 .replace('—', '-'))
    text = re.sub(r'[\u2000-\u200A\u202F\u205F\u3000]', ' ', text)  # 统一稀有空白

    # 读取拣货单总数（保持原逻辑）
    total_quantity_match = re.search(r"Item quantity[:：]?\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    # —— 快速路径：整段文本匹配（能命中就用） —— #
    fast_pat = r"((?:[A-Z]{3}\s*\d\s*\d\s*\d){1,4}\s*-\s*[SML])\s+(\d+)(?:\s+\d{7,})?"
    matches = re.findall(fast_pat, text)

    sku_counts = defaultdict(int)
    for raw_sku, qty in matches:
        add_sku_expanded(sku_counts, raw_sku, int(qty))

    # —— 兜底：若快速路径没抓全/抓不到，启用“词级解析” —— #
    if not sku_counts:
        sku_counts = parse_by_words(doc)

    if not sku_counts:
        st.error("未识别到任何 SKU 行。\n已尝试：\n- 粘合跨行/清理特殊空白\n- 文本级与词级双路径解析\n\n仍未命中，可能是整页为图片或版式与规则差异较大。\n建议：提供可复制文本的 PDF，或把样例发我做一次专用适配。")
        with st.expander("调试预览（前 800 字）"):
            st.text(text[:800])
        st.stop()

    # —— 后续与原来一致 —— #
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

    # 下载结果（文件名/编码保持不变）
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

    map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀", "产品名称"])
    map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
