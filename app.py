import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称（bundle 展开统计 + 对账口径分开）")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ========= 映射：SKU 前缀 → 产品名（保持你之前的数据） =========
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

# ========= 小工具 =========
ALNUM_HYPHEN = re.compile(r'[A-Z0-9-]+$')                   # 只保留大写/数字/连字符的 token
SKU_FULL      = re.compile(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]') # 1–4 件 bundle 形态
QTY_NUM       = re.compile(r'^\d{1,3}$')                    # 1–3 位数量
ORDER_ID      = re.compile(r'^\d{9,}$')                     # ≥9 位订单号

def _clean(t: str) -> str:
    return (t.replace('\u00ad','').replace('\u200b','').replace('\u00a0',' ')
              .replace('–','-').replace('—','-'))

def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    """将 1–4 件 bundle 拆分为独立 SKU（按 6 位切片）。"""
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
    # 回退：不满足规则则按原样计
    counter[s] += qty

# ====== 路径1：表头解析（每页只跑一次；同页去重） ======
def parse_by_headers(doc):
    expanded = defaultdict(int)
    raw_total = 0
    pages_with_header = set()

    for pi, page in enumerate(doc):
        words = [(x0,y0,x1,y1,_clean(t)) for (x0,y0,x1,y1,t,_,_,_) in page.get_text('words')]
        if not words:
            continue

        heights = [y1-y0 for _,y0,_,y1,_ in words]
        line_h  = (sum(heights)/len(heights)) if heights else 12
        band    = line_h * 3.0  # 容差放宽：可覆盖单元格内换行

        header_words = { re.sub(r'[^a-z]','', t.lower()): x0 for x0,_,_,_,t in words if t and t.isprintable() }

        def get_x(*keys):
            xs = [header_words[k] for k in keys if k in header_words]
            return min(xs) if xs else None

        x_sku = get_x('sellersku','sku','seller')
        x_qty = get_x('qty','quantity')
        x_ord = get_x('orderid','order')

        if x_sku is None or x_qty is None:
            continue

        pages_with_header.add(pi)

        page_w = page.rect.width
        def col_range(left, nxt):
            left = left - 4
            right = (min([n for n in nxt if n is not None]) - 4) if any(nxt) else page_w
            return left, right

        sku_l, sku_r = col_range(x_sku, [x_qty, x_ord])
        qty_l, qty_r = col_range(x_qty, [x_ord])

        # 本页去重：同一行被多次渲染（或 Qty 出现两个短数字）只计一次
        seen = set()

        qtys = []
        for x0,y0,x1,y1,t in words:
            if qty_l <= x0 <= qty_r and QTY_NUM.match(t.strip()):
                qtys.append((x0,y0,x1,y1,int(t.strip())))
        if not qtys:
            continue

        for qx0,qy0,qx1,qy1,qty in qtys:
            yc = (qy0+qy1)/2
            tokens=[]
            for sx0,sy0,_,sy1,t in words:
                if sku_l <= sx0 <= sku_r and abs(((sy0+sy1)/2)-yc) <= band and ALNUM_HYPHEN.match(t):
                    tokens.append((sy0, sx0, t))
            if not tokens:
                continue

            tokens.sort(key=lambda k: (round(k[0],1), k[1]))
            cat = re.sub(r'\s+','', ''.join(t for _,_,t in tokens))
            m = SKU_FULL.search(cat)
            if not m:
                continue

            seller_sku = m.group(0)
            key = (round(yc, 1), round(qx0, 1), seller_sku, qty)  # 去重键
            if key in seen:
                continue
            seen.add(key)

            raw_total += qty                  # 按行计数（对账口径）
            expand_bundle(expanded, seller_sku, qty)  # 展开计数（明细）

    return expanded, raw_total, pages_with_header

# ====== 路径2：OrderID 锚点兜底（跳过已表头解析的页面；同页去重） ======
def parse_by_order_anchor(doc, pages_to_skip=None):
    if pages_to_skip is None:
        pages_to_skip = set()

    expanded = defaultdict(int)
    raw_total = 0

    for pi, page in enumerate(doc):
        if pi in pages_to_skip:
            continue

        words = [(x0,y0,x1,y1,_clean(t)) for (x0,y0,x1,y1,t,_,_,_) in page.get_text('words')]
        if not words:
            continue

        heights = [y1-y0 for _,y0,_,y1,_ in words]
        line_h  = (sum(heights)/len(heights)) if heights else 12
        band    = line_h * 3.0

        # 粗估 SKU 列左界（没有表头也能跑）
        sku_left_guess = min([x0 for x0,_,_,_,t in words if 'sku' in t.lower()], default=page.rect.width*0.2)

        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t in words if ORDER_ID.match(t)]
        seen = set()  # 本页去重

        for ax0,ay0,ax1,ay1,_ in anchors:
            yc = (ay0+ay1)/2
            # 找“最靠右”的 1–3 位数字作为 Qty（在锚点左侧、同一行带）
            qty_cands = [(x0,int(t)) for x0,y0,_,y1,t in words
                         if (x0 < ax0) and QTY_NUM.match(t) and abs(((y0+y1)/2)-yc) <= band]
            if not qty_cands:
                continue
            qx0, qty = max(qty_cands, key=lambda k:k[0])

            tokens=[]
            for sx0,sy0,_,sy1,t in words:
                if sku_left_guess <= sx0 < qx0 and abs(((sy0+sy1)/2)-yc) <= band and ALNUM_HYPHEN.match(t):
                    tokens.append((sy0, sx0, t))
            if not tokens:
                continue

            tokens.sort(key=lambda k: (round(k[0],1), k[1]))
            cat = re.sub(r'\s+','', ''.join(t for _,_,t in tokens))
            m = SKU_FULL.search(cat)
            if not m:
                continue

            seller_sku = m.group(0)
            key = (round(yc, 1), round(qx0, 1), seller_sku, qty)
            if key in seen:
                continue
            seen.add(key)

            raw_total += qty
            expand_bundle(expanded, seller_sku, qty)

    return expanded, raw_total

# ========= 主流程 =========
if uploaded_file:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")

    # 读取 Item quantity（用于与拣货单对账）
    all_text = "".join(p.get_text() for p in doc)
    m_total = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m_total.group(1)) if m_total else None

    # 先用表头解析，再用锚点兜底（仅在“没有表头的页面”上跑）
    exp1, raw1, pages_with_header = parse_by_headers(doc)
    exp2, raw2 = parse_by_order_anchor(doc, pages_to_skip=pages_with_header)

    # 合并展开计数：以表头为主，兜底只补“表头没抓到”的键
    sku_counts = exp1.copy()
    for k, v in exp2.items():
        if k not in sku_counts:
            sku_counts[k] = v

    # 按行对账口径：优先表头结果，否则用兜底
    raw_total = raw1 if raw1 > 0 else raw2

    if sku_counts:
        # ===== 明细（展开后） =====
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]  = df["Seller SKU"].str.split("-").str[0]
        df["Size"]        = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"]= df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))
        df = df[["Product Name","Size","Seller SKU","Qty"]].sort_values(by=["Product Name","Size"])

        # A. 展开件数（给拣货明细/出库用）
        pieces_total = int(df["Qty"].sum())
        st.subheader(f"📦 实际拣货总数量：{pieces_total}")

        # B. 对账口径（按行，与拣货单 Item quantity 对齐）
        if expected_total is not None:
            if raw_total == expected_total:
                st.success(f"🧾 对账口径（按行）：{raw_total}  ✅ 与拣货单一致")
            else:
                st.error(f"🧾 对账口径（按行）：{raw_total}  ❌ 与拣货单 {expected_total} 不一致")
        else:
            st.warning("⚠️ 未能识别拣货单的 Item quantity（对账口径无法比对）")

        st.dataframe(df, use_container_width=True)

        # 下载结果（保持你原来的文件名/编码）
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df  = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀","产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行。请确认 PDF 为可复制文本或发我样例做一次适配。")
        with st.expander("调试预览（前 800 字）"):
            st.text(all_text[:800])
