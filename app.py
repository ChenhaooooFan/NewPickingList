import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# 映射表（原样）
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

# —— Bundle 拆分（1–4 件） —— #
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

def _clean(t: str) -> str:
    return (t.replace('\u00ad','').replace('\u200b','').replace('\u00a0',' ')
              .replace('–','-').replace('—','-'))

# —— A. 快速路径：整段文本（适用于“SKU/Qty/OrderID 在同一行文本里”的情况） —— #
def parse_by_text(text: str) -> dict:
    out = defaultdict(int)
    pattern = r"((?:[A-Z]{3}\d{3}){1,4}-[SML])\s+(\d{1,3})\s+\d{9,}"
    for sku, q in re.findall(pattern, text):
        expand_bundle(out, sku, int(q))
    return out

# —— B. 稳健路径：表头定位列范围；按“行带（2.2×行高）”拼 Seller SKU（可跨一行） —— #
def parse_by_columns(doc) -> dict:
    out = defaultdict(int)
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t),b,ln,sp)
                 for (x0,y0,x1,y1,t,b,ln,sp) in page.get_text('words')
                 if _clean(t).strip()]
        if not words:
            continue

        heights = [y1-y0 for _,y0,_,y1,_,_,_,_ in words]
        line_h = (sum(heights)/len(heights)) if heights else 12
        band = line_h * 2.2  # 关键：放宽“同一行带”的容差

        # 找表头
        header = {}
        for x0,y0,x1,y1,t,b,ln,sp in words:
            key = re.sub(r'[^a-z]','', t.lower())
            header.setdefault(key, []).append((x0,x1))
        def _min_x(keys):
            xs=[]
            for k in keys:
                xs += [x0 for x0,_ in header.get(k,[])]
            return min(xs) if xs else None

        x_seller = _min_x(['sellersku','seller','sku'])
        x_qty    = _min_x(['qty','quantity'])
        x_order  = _min_x(['orderid','order'])

        if x_seller is None or x_qty is None:
            continue  # 表头没命中就换下一页

        page_w = page.rect.width
        # 列范围：从本列起点到下一列起点
        def rng(x_left, x_next):
            left  = x_left - 4
            right = (x_next - 4) if x_next is not None else page_w
            return left, right

        sku_xmin, sku_xmax = rng(x_seller, min([x for x in [x_qty, x_order] if x is not None]))
        qty_xmin, qty_xmax = rng(x_qty, x_order)

        # 先把 Qty 词收集出来（只收 1–3 位短数字）
        qty_words = []
        for x0,y0,x1,y1,t,_,_,_ in words:
            if qty_xmin <= x0 <= qty_xmax and re.fullmatch(r'\d{1,3}', t.replace(',','')):
                qty_words.append((x0,y0,x1,y1,int(t.replace(',',''))))

        # 对每个 Qty，去 SKU 列范围内“先纵后横”拼接
        for qx0,qy0,qx1,qy1,qty in qty_words:
            yc = (qy0+qy1)/2
            cand = []
            for sx0,sy0,sx1,sy1,t,_,_,_ in words:
                if sku_xmin <= sx0 <= sku_xmax and abs(((sy0+sy1)/2) - yc) <= band:
                    cand.append((sy0, sx0, t))
            if not cand:
                continue
            cand.sort(key=lambda k: (round(k[0],1), k[1]))
            cell = re.sub(r'\s+','', ''.join(t for _,_,t in cand))
            m = re.search(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]', cell)
            if not m:
                continue
            sku_text = m.group(0)
            expand_bundle(out, sku_text, qty)
    return out

# —— C. 锚点兜底：以 Order ID(≥9位) → 左侧最近的 Qty → 再在更左侧的 Seller SKU 列范围拼接 —— #
def parse_by_order_anchor(doc) -> dict:
    out = defaultdict(int)
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t),b,ln,sp)
                 for (x0,y0,x1,y1,t,b,ln,sp) in page.get_text('words')
                 if _clean(t).strip()]
        if not words:
            continue

        heights = [y1-y0 for _,y0,_,y1,_,_,_,_ in words]
        line_h = (sum(heights)/len(heights)) if heights else 12
        band = line_h * 2.2

        # 估出 Seller SKU 列的大致左界（取包含 “SKU” 单词的最小 x；没有就用整页左侧 25%）
        sku_left_guess = min([x0 for x0,_,_,_,t,_,_,_ in words if 'sku' in t.lower()], default=page.rect.width*0.25)

        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t,_,_,_ in words
                   if re.fullmatch(r'\d{9,}', t.replace(',',''))]
        for ax0,ay0,ax1,ay1,_ in anchors:
            yc = (ay0+ay1)/2
            # 最近的 Qty（左侧、同一行带、最靠右的 1–3位）
            qty_cands = [(x0,int(t.replace(',',''))) for x0,y0,_,y1,t,_,_,_ in words
                         if x0 < ax0 and re.fullmatch(r'\d{1,3}', t.replace(',',''))
                         and abs(((y0+y1)/2) - yc) <= band]
            if not qty_cands:
                continue
            qx0, qty = max(qty_cands, key=lambda k:k[0])

            # 在 [sku_left_guess, qx0) 范围内拼接 Seller SKU
            cand = []
            for sx0,sy0,_,sy1,t,_,_,_ in words:
                if sku_left_guess <= sx0 < qx0 and abs(((sy0+sy1)/2) - yc) <= band:
                    cand.append((sy0, sx0, t))
            if not cand:
                continue
            cand.sort(key=lambda k: (round(k[0],1), k[1]))
            cell = re.sub(r'\s+','', ''.join(t for _,_,t in cand))
            m = re.search(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]', cell)
            if not m:
                continue
            sku_text = m.group(0)
            expand_bundle(out, sku_text, qty)
    return out

if uploaded_file:
    # 读文本（用于快速路径和总数校验）
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    all_text = "".join([p.get_text() for p in doc])
    m_total = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m_total.group(1)) if m_total else None

    # 先走快速路径
    sku_counts = parse_by_text(all_text)

    # 再走“表头定位”路径（能处理换行）
    col_counts = parse_by_columns(doc)
    for k,v in col_counts.items():
        sku_counts[k] += v if k not in sku_counts else 0  # 避免重复

    # 再兜底一次（Order ID 锚点）
    anchor_counts = parse_by_order_anchor(doc)
    for k,v in anchor_counts.items():
        sku_counts[k] += v if k not in sku_counts else 0

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"] = df["Seller SKU"].str.split("-").str[0]
        df["Size"] = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"] = df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))

        # 手动补全
        unknown = df[df["Product Name"].str.startswith("❓")]["SKU Prefix"].unique().tolist()
        if unknown:
            st.warning("⚠️ 有未识别的 SKU 前缀，请补全：")
            for prefix in unknown:
                name = st.text_input(f"🔧 SKU 前缀 {prefix} 的产品名称：", key=prefix)
                if name:
                    updated_mapping[prefix] = name
                    df.loc[df["SKU Prefix"] == prefix, "Product Name"] = name

        df = df[["Product Name","Size","Seller SKU","Qty"]].sort_values(by=["Product Name","Size"])

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
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀","产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行。请确认 PDF 为可复制文本，或把样例发我做一次专用适配。")
