"""
================================================================================
NailVesta 拣货单汇总工具（精简版，无 CSS 美化）
================================================================================

【用途】
将 TikTok Shop 导出的"拣货单 PDF"解析为按库位排序的产品汇总表,
方便仓库同学按动线顺序一次性拣完所有订单,并自动核对 PDF 标注的总件数
与实际提取件数是否一致。

【输入】
1. 必选:拣货 PDF(TikTok Shop 后台导出)
2. 可选:产品图册 CSV(含 SKU / 库位 两列)

【维护】⚠️ 有新款上架时,记得更新下面的 SKU 对照表:
- 新增甲片款式 → sku_prefix_to_name 加一行
- 新增近期新款 → new_sku_prefix 加一行(用于标记"新款")
- 新增无尺寸 SKU → sku_prefix_to_name + SIZELESS_SKUS
- 新增 B链产品 → B_CHAIN_SKU_MAP 加一行
- 改完后务必 push 到 GitHub
================================================================================
"""

import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="NailVesta 拣货单工具", page_icon="💅", layout="wide")

st.title("💅 NailVesta 拣货单汇总工具")
st.caption("智能拆分 bundle · 自动对账 · 按库位排序")

st.info(
    "📢 新款上架提醒:请及时更新代码中的 `sku_prefix_to_name` / `new_sku_prefix` / "
    "`B_CHAIN_SKU_MAP`,push 后线上自动同步。"
)

# ============================================================================
# 上传区
# ============================================================================
col_up1, col_up2 = st.columns(2)

with col_up1:
    catalog_file = st.file_uploader(
        "📚 产品图册 CSV（可选，含 SKU / 库位 两列）",
        type=["csv"],
        key="catalog",
        help="包含 SKU 与库位列。上传后会按库位排序拣货单"
    )

with col_up2:
    uploaded_file = st.file_uploader(
        "📤 拣货 PDF（必选）",
        type=["pdf"],
        help="TikTok Shop 后台导出的拣货 PDF"
    )

# 加载图册
sku_to_location = {}
if catalog_file:
    try:
        catalog_df = pd.read_csv(catalog_file, dtype=str)
        if 'SKU' in catalog_df.columns and '库位' in catalog_df.columns:
            catalog_df['SKU'] = catalog_df['SKU'].astype(str).str.strip()
            catalog_df['库位'] = catalog_df['库位'].fillna('').astype(str).str.strip()
            valid = catalog_df[catalog_df['库位'] != '']
            sku_to_location = dict(zip(valid['SKU'], valid['库位']))
            st.success(f"✅ 已加载 {len(sku_to_location)} 个 SKU 的库位映射")
        else:
            st.warning("⚠️ 图册缺少 'SKU' 或 '库位' 列")
    except Exception as e:
        st.error(f"读取图册失败: {e}")

# ============================================================================
# SKU 映射表
# ============================================================================
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
    "NPX018":"Ruby Ribbon","NPF020":"Amber Mist","NOJ006":"Toffee Muse","NOJ007":"Cherry Glaze","NOX011":"Opal Mirage",
    "NOF016":"Cinnamon Bloom","NOX010":"Twilight Muse","NPX020":"Peachy Glaze","NPX019":"Blossom Tart","NPJ013":"Velvet Cherry",
    "NOX012":"Harvest Glaze","NOJ008":"Crystal Whisper","NOF017":"Twinkle Bow","NPX021":"Twinkle Pine","NOF018":"Glacier Bloom",
    "NOJ010":"Rosé Noir","NPX022":"Merry Charm","NPF022":"Holiday Sparkl","NOF020":"Garnet Muse","NOF019":"Twinkle Christmas",
    "NOJ011":"Snowy Comet","NOX013":"Christmas Village","NOJ009":"Reindeer Glow","NIX002":"Golden Orchid",
    "NPJ014":"Snow Pixie","NPJ018":"Frost Ruby","NPJ017":"Starlit Rift","NPF021":"Candy Cane","NPJ016":"Fairy Nectar",
    "NPJ015":"Icy Viper","NOX014":"Taro Petal","NVT001":"Tool Kits","NVT002":"Tool Kits","NSB001":"Storage Box","NOB001":"Organizer Binder","NOB002":"Organizer Binder",
    "NF001":"Free Giveaway","NIF001":"Lilac Veil","NIF002":"Gingerbread","NOX015":"Glitter Doll","NOJ012":"Winery Flame",
    "NOF021":"Velvet Ribbon","NPX024":"Rose Wine","NPX023":"Blooming Kiss","NMF001":"Cherry Crush","NBX001":"Ballet Petal",
    "NMF003":"Royal Treasure","NMF002":"Safari Princess","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost",
    "NPJ019":"Gothic Mist","NOJ015":"Sapphire Bloom","NOX029":"Tidal Mirage","NVF007":"Tangerine Tide","NOF036":"Honey Petal","NOJ030":"Glitter Jasmine",
    "NPX025":"Cocoa Teddy","NVF001":"Golden Bloom","NBJ002":"Cherry Drop","NVX003":"Tidal Butterfly","NOX030":"Glitter Matcha","NOF043":"Golden Camellia","NOF044":"Moss Petal",
    "NOF022":"Aqua Reverie","NDJ001":"Snow Knit","NOF023":"Arctic Starlight",
    "NOX016":"Cherry Ribbon","NOX017":"Ruby Bow","NMF004":"Lavender Bloom","NDX002":"Cloudy Knit","NMJ003":"Gothic Rose",
    "NOF025":"Cherry Romance","NMJ001":"Milky Cloud","NOX028":"Rose Champagne","NOF040":"Champagne Shell","NOF041":"Blooming Malibu","NOF042":"Rosy Puff",
    "NMX001":"Petal Muse","NOF024":"Floral Muse","NVX001":"Sakura Macaron","NVF002":"Dreamy Bloom","NOJ017":"Floral Garden",
    "NOJ016":"Jade Blossom","NVX002":"Pastel Bloom","NVF008":"Glazed Ballet","NWF008":"Waikiki Blossom","NWF009":"Petal French",
    "NPF023":"Fairy Garden","NBJ001":"Stone Petal","NOF027":"Acai Bloom","NPJ021":"Champagne Blossom","NPJ020":"Citrus Daisy",
    "NOJ018":"Ribbon Lily","NVF005":"Dreamy Sakura","NOF037":"Tropical Spritz","NOF039":"Citrus Pop","NVJ005":"Guava Nectar",
    "NDX003":"Meadow Petals","NOX018":"Strawberry Kiss","NOJ020":"Raibow Bloom","NPF026":"Seaside Sundae","NVJ001":"Prism Aura",
    "NDX005":"Midnight Glam","NDX004":"Starry Tide","NWF006":"Pastel Jungle","NWF007":"Peachy Seaside","NOF003":"Peach Pop","NOJ031":"Palm Mojito",
    "NPX027":"Hibiscus Tide","NPX026":"Ocean Yuzu","NWX001":"Seashell Sorbet","NOF026":"Island Paradise","NPF024":"Tropical Breeze",
    "NOJ021":"Petal Gelato","AUCTION":"Picks Any 2 Sets, 50 g, Choose Your Size",
    "NVF003":"Apricot Cream","NMJ005":"Glossy Aura","NGX001":"Seafoam Jewel","NOF028":"Floral Cherry","NTX001":"Coraline Glow",
    "NOX020":"Floral Drip","NOX019":"Mint Petal","NOF030":"Citrus Veil","NOJ032":"Lavender Prism",
    "NOF031":"Lady Cherry","NOF029":"Marine Glow","NDJ002":"Aqua Blush","NWF001":"Berry Bowtie","NTF001":"Pastel Coast","NWF005":"Sunflower Safari","NOJ028":"Cowgirl Charm","NOJ029":"Pearl Tide",
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember","NOX022":"Sunlit Petals",
    "NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals","NOF032":"Tidal Flower","NWF002":"Tropic Shell","NMX004":"MYSTERY BOX",
    "NOF034":"Golden Hibiscus","NOF033":"Jade Garden","NOJ023":"Mermaid Shell","NOJ024":"Sunset Treasure","NBX003":"Jelly Petal","NWF003":"Silk Blossom","NWF004":"Melon Petal",
    "NVJ002":"Mochi Blossom","NOJ025":"Petal Empress","NVJ003":"Petal Throne","NWX003":"Aloha Bloom","NOX026":"Papaya Bloom","NOF035":"Ocean Picnic","NOJ026":"Aqua Taffy","NOX027":"Coral Foam","NOJ027":"Opal Dynasty",
    # 无尺寸款 SKU
    "NOB001":"Organizer Binder","NVT001":"TOOLKITS",
}
updated_mapping = dict(sku_prefix_to_name)

new_sku_prefix = {
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember",
    "NOX022":"Sunlit Petals","NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals"
}

SIZELESS_SKUS = {"NF001", "NB001"}

# ============================================================================
# B链产品 SKU 对照表
# ============================================================================
B_CHAIN_SKU_MAP = {
    "NVT001": "工具包 Toolkits",
    "NVT002": "工具包 Toolkits",
    "NSB001": "美甲折叠盒 Storage Box",
    "NOB001": "Organizer Binder 美甲册",
    "NOB002": "Organizer Binder 美甲册",
}
B_CHAIN_SKUS_SET = set(B_CHAIN_SKU_MAP.keys())
B_CHAIN_RE = re.compile(r'\b(' + '|'.join(B_CHAIN_SKUS_SET) + r')\b')
QTY_WITH_TRACKING = re.compile(r'\b([1-9]\d{0,2})\s+\d{15,20}\b')

# ============================================================================
# 解析工具函数
# ============================================================================
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}|NF001){1,4}-[SML])', re.DOTALL)
QTY_AFTER  = re.compile(r'\b([1-9]\d{0,2})\b')
ITEM_QTY_RE = re.compile(r"Item\s+quantity[:：]?\s*(\d+)", re.I)
NM_ONLY = re.compile(r'\bNF001\b')
NB_ONLY = re.compile(r'\bNB001\b')
CHOOSE_SETS_RE = re.compile(r'Choose\s+\d+\s+Sets', re.I)


def normalize_text(t: str) -> str:
    return t.replace("\u00ad","").replace("\u200b","").replace("\u00a0"," ").replace("–","-").replace("—","-")


def fix_orphan_digit_before_size(txt: str) -> str:
    pattern = re.compile(r'(?P<prefix>(?:[A-Z]{3}\d{3}|NM001){0,3}[A-Z]{3}\d{2})\s*[\r\n]+\s*(?P<d>\d)\s*-\s*(?P<size>[SML])')
    def _join(m): return f"{m.group('prefix')}{m.group('d')}-{m.group('size')}"
    prev, cur = None, txt
    while prev != cur:
        prev, cur = cur, pattern.sub(_join, cur)
    return cur


def parse_code_parts(code: str):
    parts, i, n = [], 0, len(code)
    while i < n:
        if code.startswith('NM001', i):
            parts.append('NM001'); i += 5; continue
        seg = code[i:i+6]
        if re.fullmatch(r'[A-Z]{3}\d{3}', seg):
            parts.append(seg); i += 6; continue
        return None
    return parts if 1 <= len(parts) <= 4 else None


def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    s = re.sub(r'\s+', '', sku_with_size)
    if '-' not in s:
        counter[s] += qty
        return 0, (qty if s == 'NF001' else 0)
    code, size = s.split('-', 1)
    parts = parse_code_parts(code)
    if parts:
        mystery_units = 0
        for p in parts:
            key = f"{p}-{size}"
            counter[key] += qty
            if p == 'NF001':
                mystery_units += qty
        extra = (len(parts) - 1) * qty
        return extra, mystery_units
    counter[s] += qty
    return 0, (qty if code == 'NF001' else 0)


def count_choose_sets_items(text: str) -> int:
    total = 0
    positions = [m.start() for m in CHOOSE_SETS_RE.finditer(text)]
    if not positions:
        return 0
    positions.append(len(text))
    qty_pattern = re.compile(r'\b([1-9]\d{0,2})\s+(\d{15,20})\b')
    for i in range(len(positions) - 1):
        block = text[positions[i]:positions[i+1]]
        m_sku = re.search(r'\b[A-Z]{3}\d{3}-[SML]\b', block)
        if m_sku:
            block = block[:m_sku.start()]
        for m in qty_pattern.finditer(block):
            total += int(m.group(1))
    return total


def location_sort_key(loc: str):
    if not loc or loc == "未识别库位":
        return (99, 99, 99)
    m = re.match(r'^([AB])-(\d{2})-(\d{2})$', loc)
    if not m:
        return (98, 0, 0)
    zone = 0 if m.group(1) == 'A' else 1
    return (zone, int(m.group(2)), int(m.group(3)))


# ============================================================================
# 主逻辑
# ============================================================================
if not uploaded_file:
    st.info("📤 等待上传拣货 PDF —— 上传后将自动解析、拆分 bundle 并按库位排序")

else:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    text = "\n".join([p.get_text("text") for p in doc])
    doc.close()
    text = normalize_text(text)

    m_total = ITEM_QTY_RE.search(text)
    expected_total = int(m_total.group(1)) if m_total else 0

    text_fixed = fix_orphan_digit_before_size(text)

    sku_counts = defaultdict(int)
    bundle_extra = 0
    mystery_units = 0
    binder_units = 0

    for m in SKU_BUNDLE.finditer(text_fixed):
        sku_raw = re.sub(r'\s+', '', m.group(1))
        after = text_fixed[m.end(): m.end()+50]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        extra, myst = expand_bundle(sku_counts, sku_raw, qty)
        bundle_extra += extra
        mystery_units += myst

    for m in NM_ONLY.finditer(text_fixed):
        nxt = text_fixed[m.end(): m.end()+3]
        if '-' in nxt:
            continue
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NF001'] += qty
        mystery_units += qty

    for m in NB_ONLY.finditer(text_fixed):
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NB001'] += qty
        binder_units += qty

    choose_sets_units = count_choose_sets_items(text_fixed)
    if choose_sets_units > 0:
        sku_counts['__CHOOSE_SETS__'] += choose_sets_units

    # 提取 B链产品数量
    b_chain_counts = defaultdict(int)
    for m in B_CHAIN_RE.finditer(text_fixed):
        sku = m.group(1)
        after = text_fixed[m.end(): m.end() + 300]
        mq = QTY_WITH_TRACKING.search(after)
        if mq:
            qty = int(mq.group(1))
        else:
            mq2 = QTY_AFTER.search(after)
            qty = int(mq2.group(1)) if mq2 else 1
        b_chain_counts[sku] += qty

    b_chain_agg = defaultdict(int)
    for sku, qty in b_chain_counts.items():
        b_chain_agg[B_CHAIN_SKU_MAP[sku]] += qty
    b_chain_total = sum(b_chain_counts.values())

    total_qty = sum(sku_counts.values()) + b_chain_total
    expected_with_bundle = expected_total + bundle_extra

    # ========== 构建 DataFrame ==========
    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]

        def map_name(prefix):
            if prefix == "__CHOOSE_SETS__":
                return "Choose 2 Sets(混合套装)"
            return updated_mapping.get(prefix, "❓未识别")
        df["Product Name"] = df["SKU Prefix"].map(map_name)

        df_sized = df[df["Size"].notna()].copy()
        df_nosized = df[df["Size"].isna()].copy()

        if not df_sized.empty:
            pivot = df_sized.pivot_table(
                index=["SKU Prefix", "Product Name"],
                columns="Size",
                values="Qty",
                aggfunc="sum",
                fill_value=0
            ).reset_index()
            for sz in ["S", "M", "L"]:
                if sz not in pivot.columns:
                    pivot[sz] = 0
            pivot = pivot[["Product Name", "SKU Prefix", "S", "M", "L"]]
            pivot["Total"] = pivot["S"] + pivot["M"] + pivot["L"]
        else:
            pivot = pd.DataFrame(columns=["Product Name", "SKU Prefix", "S", "M", "L", "Total"])

        if not df_nosized.empty:
            for _, row in df_nosized.iterrows():
                new_row = {
                    "SKU Prefix": row["SKU Prefix"],
                    "Product Name": row["Product Name"],
                    "S": 0, "M": 0, "L": 0,
                    "Total": row["Qty"]
                }
                pivot = pd.concat([pivot, pd.DataFrame([new_row])], ignore_index=True)

        def map_location(prefix):
            if prefix in SIZELESS_SKUS or prefix == "__CHOOSE_SETS__":
                return "无库位(特殊款)"
            return sku_to_location.get(prefix, "未识别库位")
        pivot["库位"] = pivot["SKU Prefix"].map(map_location)

        # ========== 对账区 ==========
        st.subheader("📊 对账结果")

        nail_qty = int(pivot[~pivot["库位"].str.startswith("无库位")]["Total"].sum()) \
                   if not pivot.empty else 0
        special_qty = int(pivot[pivot["库位"].str.startswith("无库位")]["Total"].sum()) \
                      if not pivot.empty else 0

        if expected_total == 0:
            st.warning("⚠️ 未识别到 PDF 中的 Item quantity,无法进行对账校验")
        elif total_qty == expected_with_bundle or total_qty == expected_total:
            msg = f"✨ 对账成功 · PDF 标注 {expected_total}"
            if bundle_extra:
                msg += f" + bundle 拆分 {bundle_extra}"
            msg += f" = 实际提取 {total_qty} 件 ✅"
            st.success(msg)
        else:
            diff = total_qty - expected_with_bundle
            st.error(f"❌ 对账不一致 · 期望 {expected_with_bundle},实际 {total_qty},差 {diff:+d} 件")

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("PDF 标注", expected_total)
        k2.metric("实际提取", total_qty)
        k3.metric("普通甲片", nail_qty)
        k4.metric("特殊款", special_qty)
        k5.metric("B链产品", b_chain_total)

        with st.expander("📋 提取明细"):
            st.write(f"🎁 Free Giveaway (NF001):{mystery_units} 件")
            st.write(f"📒 Organizer Binder (NB001):{binder_units} 件")
            st.write(f"🎀 Choose Sets(混合套装):{choose_sets_units} 件")
            st.write(f"🔗 bundle 拆分多出件数:+{bundle_extra} 件")
            st.write(f"🛍️ B链产品合计:{b_chain_total} 件")

        unknown_prefix_list = []
        for sku in sku_counts.keys():
            prefix = sku.split("-")[0] if "-" in sku else sku
            if prefix not in updated_mapping and prefix != "__CHOOSE_SETS__":
                if prefix not in unknown_prefix_list:
                    unknown_prefix_list.append(prefix)
        if unknown_prefix_list:
            st.error(
                f"🚨 发现 {len(unknown_prefix_list)} 个未识别的 SKU 前缀:"
                f"{', '.join(unknown_prefix_list)} —— 请尽快在代码中更新 sku_prefix_to_name,push 后重新部署"
            )

        truly_unknown = pivot[pivot["库位"] == "未识别库位"]
        if not truly_unknown.empty:
            names = "、".join(truly_unknown['Product Name'].tolist())
            st.warning(f"⚠️ {len(truly_unknown)} 个款式没有库位信息(需补充图册 CSV):{names}")

        special_rows = pivot[pivot["库位"] == "无库位(特殊款)"]
        if not special_rows.empty:
            special_names = "、".join(special_rows["Product Name"].tolist())
            st.info(f"ℹ️ {len(special_rows)} 类无尺寸/特殊款不参与库位拣货:{special_names}(需单独处理)")

        # ========== 排序模式 ==========
        st.subheader("📋 拣货明细表")

        sort_mode = st.radio(
            "排序方式",
            ["📦 按库位顺序(拣货模式)", "🔤 按字母顺序(A-Z)"],
            horizontal=True,
            help="拣货模式:从 A-01-01 顺着货架走一遍即可。字母顺序:按产品名 A-Z 排列,方便查找"
        )

        is_special = pivot["SKU Prefix"].isin(SIZELESS_SKUS | {"__CHOOSE_SETS__"})
        pivot["_special"] = is_special.astype(int)

        if sort_mode.startswith("📦"):
            pivot["_loc_key"] = pivot["库位"].apply(location_sort_key)
            pivot = pivot.sort_values(
                by=["_special", "_loc_key", "Product Name"],
                ascending=[True, True, True]
            ).drop(columns=["_loc_key", "_special"]).reset_index(drop=True)
        else:
            pivot["_name_key"] = pivot["Product Name"].str.lower()
            pivot = pivot.sort_values(
                by=["_special", "_name_key"],
                ascending=[True, True]
            ).drop(columns=["_special", "_name_key"]).reset_index(drop=True)

        pivot = pivot[["库位", "Product Name", "S", "M", "L", "Total"]]

        prefix_lookup = {name: sku_p for sku_p, name in updated_mapping.items()}

        def highlight_row(row):
            loc = str(row["库位"])
            name = str(row["Product Name"])
            prefix = prefix_lookup.get(name, "")
            if loc == "未识别库位":
                return ['background-color: #fef5e7'] * len(row)
            if loc == "无库位(特殊款)":
                return ['background-color: #f5f0f5'] * len(row)
            if prefix in new_sku_prefix:
                return ['background-color: #fff0f5'] * len(row)
            return [''] * len(row)

        pivot_styled = pivot.style.apply(highlight_row, axis=1)

        st.dataframe(
            pivot_styled,
            use_container_width=True,
            hide_index=True,
            height=min(600, 50 + len(pivot) * 35)
        )

        st.caption("🌸 粉色=新款　🟡 黄色=缺库位信息　⚫ 灰色=无尺寸特殊款")

        # ========== 下载 ==========
        if b_chain_agg:
            cols = pivot.columns.tolist()
            empty_row = pd.DataFrame([[""] * len(cols)], columns=cols)
            section_label = pd.DataFrame(
                [["─── B链产品 ───"] + [""] * (len(cols) - 1)],
                columns=cols
            )
            b_rows = pd.DataFrame(
                [[name] + ["", "", "", "", qty] for name, qty in sorted(b_chain_agg.items())],
                columns=cols
            )
            combined_df = pd.concat([pivot, empty_row, section_label, b_rows], ignore_index=True)
            csv = combined_df.to_csv(index=False).encode("utf-8-sig")
        else:
            csv = pivot.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            "📥 下载拣货明细 CSV（含 B链）" if b_chain_agg else "📥 下载产品明细 CSV",
            data=csv,
            file_name="product_summary_named.csv",
            mime="text/csv"
        )

        # ========== B链产品展示区 ==========
        if b_chain_agg:
            st.subheader("🛍️ B链产品")
            b_chain_df = pd.DataFrame(
                sorted(b_chain_agg.items()),
                columns=["产品名称", "数量"]
            )
            st.dataframe(b_chain_df, use_container_width=True, hide_index=True)

    else:
        st.error("❌ 未识别到任何 SKU。请确认 PDF 为可复制文本(非扫描件)")
