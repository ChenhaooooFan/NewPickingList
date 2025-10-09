import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ===== 映射：SKU 前缀 → 产品名（保持不变） =====
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

# ===== 小工具 =====
ALNUM_HYPHEN = re.compile(r'[A-Z0-9-]+$')         # 只取大写/数字/连字符的 token（避免把文字列拼进来）
SKU_FULL      = re.compile(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]')  # 1~4件 bundle 最终形态
QTY_NUM       = re.compile(r'^\d{1,3}$')          # 短数字作为 Qty
ORDER_ID      = re.compile(r'^\d{9,}$')           # ≥9 位订单号

def _clean(t: str) -> str:
    return (t.replace('\u00ad','').replace('\u200b','').replace('\u00a0',' ')
              .replace('–','-').replace('—','-'))

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
    counter[s] += qty

# ===== 路径1：表头定位列范围 → 用 Qty 作为行锚点，拼接 Seller SKU（容差=3×行高） =====
def parse_by_headers(doc) -> dict:
    out = defaultdict(int)
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t)) for (x0,y0,x1,y1,t,_,_,_) in page.get_text('words')]
        if not words:
            continue
        heights = [y1-y0 for _,y0,_,y1,_ in words]
        line_h  = (sum(heights)/len(heights)) if heights else 12
        band    = line_h * 3.0

        # 定位表头列起点
        header_words = { re.sub(r'[^a-z]','', t.lower()): x0 for x0,_,_,_,t in words
                         if t and t.isprintable() }
        xs = {}
        def get_x(*keys):
            xs_ = [header_words[k] for k in keys if k in header_words]
            return min(xs_) if xs_ else None
        xs['sku']   = get_x('sellersku','sku','seller')
        xs['qty']   = get_x('qty','quantity')
        xs['order'] = get_x('orderid','order')

        if xs['sku'] is None or xs['qty'] is None:
            continue  # 这一页没有表头

        page_w = page.rect.width
        def col_range(left_key, next_keys):
            left = xs[left_key]
            right_candidates = [xs[k] for k in next_keys if xs.get(k) is not None]
            right = min(right_candidates) if right_candidates else page_w
            return (left - 4, right - 4)

        sku_l, sku_r = col_range('sku',   ['qty','order'])
        qty_l, qty_r = col_range('qty',   ['order'])

        # 找 Qty 候选（只取列内 1~3 位数字）
        qtys = []
        for x0,y0,x1,y1,t in words:
            if qty_l <= x0 <= qty_r and QTY_NUM.match(t.strip()):
                qtys.append((x0,y0,x1,y1,int(t.strip())))
        if not qtys:
            continue

        # 对每个 Qty 作为行锚点，去 SKU 列内拼接所有 token（先纵后横）
        for qx0,qy0,qx1,qy1,qty in qtys:
            yc = (qy0+qy1)/2
            tokens = []
            for sx0,sy0,sx1,sy1,t in words:
                if sku_l <= sx0 <= sku_r and abs(((sy0+sy1)/2) - yc) <= band:
                    if ALNUM_HYPHEN.match(t):
                        tokens.append((sy0, sx0, t))
            if not tokens:
                continue
            tokens.sort(key=lambda k: (round(k[0],1), k[1]))
            cat = re.sub(r'\s+','', ''.join(t for _,_,t in tokens))
            m = SKU_FULL.search(cat)
            if not m:
                continue
            expand_bundle(out, m.group(0), qty)
    return out

# ===== 路径2：找不到表头时，用 OrderID 锚点 → Qty → 左侧整块 SKU（同样容差=3×行高） =====
def parse_by_order_anchor(doc) -> dict:
    out = defaultdict(int)
    for page in doc:
        words = [(x0,y0,x1,y1,_clean(t)) for (x0,y0,x1,y1,t,_,_,_) in page.get_text('words')]
        if not words:
            continue
        heights = [y1-y0 for _,y0,_,y1,_ in words]
        line_h  = (sum(heights)/len(heights)) if heights else 12
        band    = line_h * 3.0

        # 估一个 SKU 列的大致左界（见不到表头也能工作）
        sku_left_guess = min([x0 for x0,_,_,_,t in words if 'sku' in t.lower()], default=page.rect.width*0.2)

        # 订单号锚点
        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t in words if ORDER_ID.match(t)]
        for ax0,ay0,ax1,ay1,_ in anchors:
            yc = (ay0+ay1)/2
            # 找最近的 Qty（左侧、同一行带、最靠右的 1~3 位数字）
            qty_cands = [(x0,int(t)) for x0,y0,_,y1,t in words
                         if (x0 < ax0) and QTY_NUM.match(t) and abs(((y0+y1)/2) - yc) <= band]
            if not qty_cands:
                continue
            qx0, qty = max(qty_cands, key=lambda k:k[0])

            # 从 Qty 往左，把疑似 SKU 的 token 全拼起来
            tokens = []
            for sx0,sy0,_,sy1,t in words:
                if sku_left_guess <= sx0 < qx0 and abs(((sy0+sy1)/2) - yc) <= band:
                    if ALNUM_HYPHEN.match(t):
                        tokens.append((sy0, sx0, t))
            if not tokens:
                continue
            tokens.sort(key=lambda k: (round(k[0],1), k[1]))
            cat = re.sub(r'\s+','', ''.join(t for _,_,t in tokens))
            m = SKU_FULL.search(cat)
            if not m:
                continue
            expand_bundle(out, m.group(0), qty)
    return out

if uploaded_file:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")

    # 读取 Item quantity（保留你的校验）
    all_text = "".join(p.get_text() for p in doc)
    m_total = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m_total.group(1)) if m_total else None

    # 先走“表头路径”，再合并“锚点路径”（去重）
    sku_counts = parse_by_headers(doc)
    anchor_counts = parse_by_order_anchor(doc)
    for k, v in anchor_counts.items():
        if k not in sku_counts:
            sku_counts[k] = v

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]  = df["Seller SKU"].str.split("-").str[0]
        df["Size"]        = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"]= df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))

        # 手动补全（保持原交互）
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

        # 下载（文件名/编码保持不变）
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df  = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀","产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行（两种解析路径都未命中）。请确认 PDF 为可复制文本。")
        with st.expander("调试预览（前 800 字）"):
            st.text(all_text[:800])
