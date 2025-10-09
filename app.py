import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具(´∀｀)♡", layout="centered")
st.title("NailVesta 拣货单汇总工具💗")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称（支持 1–4 件 bundle；修复换行把最后一位数字折行到下一行的情况）")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射：SKU 前缀 → 产品名（保留你的映射；此处只列出示例，可替换为你的完整映射）
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
    "NPX018":"Ruby Ribbon"
}
updated_mapping = dict(sku_prefix_to_name)

# ---------- 小工具 ----------
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}){1,4}-[SML])', re.DOTALL)  # 1–4件 bundle（允许跨行/空格）
QTY_AFTER  = re.compile(r'\b([1-9]\d{0,2})\b')                          # SKU 后的 1–3位数量

def normalize_text(t: str) -> str:
    t = t.replace("\u00ad","").replace("\u200b","").replace("\u00a0"," ")
    t = t.replace("–","-").replace("—","-")
    return t

def fix_orphan_digit_before_size(txt: str) -> str:
    """
    修复形如：
        NPJ011NPX01\n5-M  → NPJ011NPX015-M
    的换行折断。即：最后一个“3位数字”被切成“前2位在上一行 + 最后一位在下一行，再接 -SIZE”。
    这里只修复最后一段的“2位数字 + 换行 + 1位数字 + -[SML]”的场景。
    """
    # 解释：
    #  - prefix: 前面若干个完整 6 位块 + 最后一个 3 位块只剩下 2 位（如 X01）
    #  - d: 下一行的“1位数字”（如 5）
    #  - size: S/M/L
    # 允许中间出现空格或换行
    pattern = re.compile(
        r'(?P<prefix>(?:[A-Z]{3}\d{3}){0,3}[A-Z]{3}\d{2})\s*[\r\n]+\s*(?P<d>\d)\s*-\s*(?P<size>[SML])'
    )
    def _join(m):
        return f"{m.group('prefix')}{m.group('d')}-{m.group('size')}"
    # 连续修复直到不再匹配（某些页可能多处出现）
    prev = None
    cur = txt
    while prev != cur:
        prev = cur
        cur = pattern.sub(_join, cur)
    return cur

def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    """
    将 1–4 件 bundle 拆成独立 SKU 计数。
    例如：NPJ011NPX015-M → NPJ011-M, NPX015-M 各 +qty
    """
    s = re.sub(r'\s+', '', sku_with_size)
    if '-' not in s:
        counter[s] += qty
        return
    code, size = s.split('-', 1)
    if len(code) % 6 == 0 and 6 <= len(code) <= 24:
        parts = [code[i:i+6] for i in range(0, len(code), 6)]
        if all(re.fullmatch(r'[A-Z]{3}\d{3}', p) for p in parts):
            for p in parts:
                counter[f"{p}-{size}"] += qty
            return
    # 回退：非标准就按原样记
    counter[s] += qty

# ---------- 主逻辑 ----------
if uploaded_file:
    # 读 PDF → 文本
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    text = ""
    for p in doc:
        text += p.get_text("text") + "\n"
    text = normalize_text(text)

    # 对账用：Item quantity
    m_total = re.search(r"Item\s+quantity[:：]?\s*(\d+)", text, re.I)
    expected_total = int(m_total.group(1)) if m_total else None

    # 关键修复：把“最后一位数字换行到下一行”的 SKU 拼回去
    text_fixed = fix_orphan_digit_before_size(text)

    # 匹配所有 SKU（允许跨行）
    sku_counts = defaultdict(int)
    for m in SKU_BUNDLE.finditer(text_fixed):
        sku_raw = re.sub(r'\s+', '', m.group(1))  # 去掉任何空白/换行
        # 找 SKU 之后的第一个 1–3 位数字当作数量（TikTok 通常紧跟在右侧）
        after = text_fixed[m.end(): m.end()+50]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1

        expand_bundle(sku_counts, sku_raw, qty)

    # 生成结果
    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"] = df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))

        # 允许手动补全未识别前缀
        unknown = df[df["Product Name"].str.startswith("❓")]["SKU Prefix"].unique().tolist()
        if unknown:
            st.warning("⚠️ 有未识别的 SKU 前缀，请补全：")
            for prefix in unknown:
                name_input = st.text_input(f"🔧 SKU 前缀 {prefix} 的产品名称：", key=f"fix_{prefix}")
                if name_input:
                    updated_mapping[prefix] = name_input
                    df.loc[df["SKU Prefix"] == prefix, "Product Name"] = name_input

        df = df[["Product Name", "Size", "Seller SKU", "Qty"]].sort_values(by=["Product Name","Size"])
        total_qty = int(df["Qty"].sum())

        st.subheader(f"📦 实际拣货总数量：{total_qty}")
        if expected_total is not None:
            if total_qty == expected_total:
                st.success(f"✅ 与拣货单一致（{expected_total}）")
            else:
                st.warning(f"⚠️ 拣货单数量为 {expected_total}，实际解析为 {total_qty}。如仍不一致，可能还有其他非常规换行。")

        st.dataframe(df, use_container_width=True)

        # 下载结果
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀","产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")

    else:
        st.error("未识别到任何 SKU 行。请确认 PDF 为可复制文本，或发我样例做一次专用适配。")
