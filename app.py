import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称（bundle 展开统计 + 对账口径分开 + 宽松兜底）")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ========= 映射：SKU 前缀 → 产品名 =========
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

# ========= 正则 & 工具 =========
ALNUM_HYPHEN = re.compile(r'[A-Z0-9-]+$')
SKU_FULL      = re.compile(r'(?:[A-Z]{3}\d{3}){1,4}-[A-Z]')   # 1–4 件 bundle
QTY_NUM       = re.compile(r'^\d{1,3}$')                      # 1–3 位数量
ORDER_ID      = re.compile(r'^\d{9,}$')                       # ≥9 位订单号

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

# ====== A 路径：表头解析（同页去重） ======
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
        band    = line_h * 3.0  # 放宽容差，适配单元格内换行

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
            key = (round(yc, 1), round(qx0, 1), seller_sku, qty)
            if key in seen:
                continue
            seen.add(key)

            raw_total += qty
            expand_bundle(expanded, seller_sku, qty)

    return expanded, raw_total, pages_with_header

# ====== B 路径：OrderID 锚点兜底（跳过已表头页面；同页去重） ======
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

        sku_left_guess = min([x0 for x0,_,_,_,t in words if 'sku' in t.lower()], default=page.rect.width*0.2)
        anchors = [(x0,y0,x1,y1,t) for x0,y0,x1,y1,t in words if ORDER_ID.match(t)]
        seen = set()

        for ax0,ay0,ax1,ay1,_ in anchors:
            yc = (ay0+ay1)/2
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

# ====== C 路径：宽松正则（无坐标，最后兜底） ======
def parse_by_loose_regex(doc):
    """
    不依赖坐标。逐页取 text 流，按行分割，在“同行/后一行/两行内”寻找：
      - SKU: (ABC123){1..4}-[SML]
      - Qty: 1..3 位数字
      - Order: ≥9 位数字（没有也允许，但对账口径只加有 Qty 的）
    """
    expanded = defaultdict(int)
    raw_total = 0
    for page in doc:
        txt = _clean(page.get_text("text"))
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        n = len(lines)
        for i, line in enumerate(lines):
            # 把断行合并一点（当前行 + 下一行）供匹配
            cat = re.sub(r'\s+', ' ', (line + ' ' + (lines[i+1] if i+1<n else '')))
            msku = re.search(r'((?:[A-Z]{3}\d{3}){1,4}-[SML])', cat)
            if not msku:
                continue
            sku = msku.group(1)

            # 在本行及后 2 行里找 Qty（尽量靠近 SKU 后面）
            window = ' '.join(lines[i:i+3])
            qtys = re.findall(r'\b(\d{1,3})\b', window)
            qty = None
            if qtys:
                # 过滤掉明显是年份/天数的异常值（>500 基本不是数量）
                cand = [int(x) for x in qtys if 1 <= int(x) <= 500]
                if cand:
                    qty = cand[0]

            if qty is None:
                continue

            raw_total += qty
            expand_bundle(expanded, sku, qty)

    return expanded, raw_total

# ========= 主流程 =========
if uploaded_file:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")

    # Item quantity（对账用）
    all_text = "".join(p.get_text() for p in doc)
    m_total = re.search(r"Item quantity[:：]?\s*(\d+)", all_text)
    expected_total = int(m_total.group(1)) if m_total else None

    # A + B
    exp1, raw1, pages_with_header = parse_by_headers(doc)
    exp2, raw2 = parse_by_order_anchor(doc, pages_to_skip=pages_with_header)

    # 合并（累加）
    sku_counts = exp1.copy()
    for k, v in exp2.items():
        sku_counts[k] += v
    raw_total = raw1 + raw2

    # —— 如果 A+B 完全抓不到任何行，启用 C（宽松模式）——
    used_loose = False
    if not sku_counts:
        exp3, raw3 = parse_by_loose_regex(doc)
        sku_counts = exp3
        raw_total = raw3
        used_loose = True

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]
        df["Product Name"] = df["SKU Prefix"].map(lambda x: updated_mapping.get(x, "❓未识别"))
        df = df[["Product Name","Size","Seller SKU","Qty"]].sort_values(by=["Product Name","Size"])

        pieces_total = int(df["Qty"].sum())
        st.subheader(f"📦 实际拣货总数量：{pieces_total}")

        # 对账提示
        tag = "（宽松模式）" if used_loose else ""
        if expected_total is not None:
            if raw_total == expected_total:
                st.success(f"🧾 对账口径（按行）{tag}：{raw_total}  ✅ 与拣货单一致")
            else:
                st.error(f"🧾 对账口径（按行）{tag}：{raw_total}  ❌ 与拣货单 {expected_total} 不一致")
        else:
            st.warning(f"⚠️ 未能识别拣货单的 Item quantity；当前口径{tag}无法比对")

        st.dataframe(df, use_container_width=True)

        # 下载（与原来保持一致）
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        map_df  = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀","产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
    else:
        st.error("未识别到任何 SKU 行（A/B/C 三种模式均未命中，疑似扫描版或版式过于异常）。")
        with st.expander("调试预览（前 800 字）"):
            st.text(all_text[:800])
