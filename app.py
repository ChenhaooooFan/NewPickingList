"""
================================================================================
NailVesta 拣货单汇总工具
================================================================================

【用途】
将 TikTok Shop 导出的"拣货单 PDF"解析为按库位排序的产品汇总表,
方便仓库同学按动线顺序一次性拣完所有订单,并自动核对 PDF 标注的总件数
与实际提取件数是否一致。

【输入】
1. 必选:拣货 PDF(TikTok Shop 后台导出)
   - PDF 头部含 "Item quantity: XXX",作为对账基准
   - 每行 SKU 形如 NPF014-M、NDJ002-S
   - bundle 形式 SKU 形如 NPF014NPJ016-M(多个 SKU 拼接 + 单个尺寸)
2. 可选:产品图册 CSV(含 SKU / 库位 两列)
   - 上传后会自动按库位 A-01-01 → B-XX-XX 的顺序排序

【输出】
- 屏幕上的对账面板(PDF 标注 vs 实际提取)
- 按库位/字母排序的产品明细表(库位、产品名、S/M/L、Total)
- 可下载的 CSV 文件

【对账逻辑(核心)】
PDF 头部的 Item quantity 把所有"行"都算一份,但实际拣货时:
1. bundle SKU(如 NPF014NPJ016-M qty=1)在 PDF 里算 1 件,
   但实际要拣 2 件 → bundle_extra 记录拆分多出来的件数
2. NF001 (Free Giveaway) 是免费赠品,无尺寸,PDF 里独立成行
3. NB001 (Organizer Binder) 是收纳册,无尺寸,PDF 里独立成行
4. "Choose N Sets" 段落用占位 SKU(1/2/3),无具体款式信息,
   只能按段落汇总成一行"混合套装"

最终对账公式:
    期望件数 = PDF 标注数量 + bundle 拆分多出件数
    实际件数 = 所有提取出的 SKU 件数总和(含 NF001 / NB001 / Choose Sets)
    两者应相等

【特殊 SKU 处理】
| SKU       | 名称              | 尺寸  | 库位      | 处理方式            |
|-----------|------------------|------|----------|--------------------|
| NF001     | Free Giveaway    | 无   | 无       | 独立成行,灰色背景  |
| NB001     | Organizer Binder | 无   | 无       | 独立成行,灰色背景  |
| 1/2/3...  | Choose N Sets    | 无   | 无       | 段落汇总,灰色背景  |

【表格颜色含义】
- 🟡 黄色:真正缺库位信息,需补充图册 CSV
- ⚫ 灰色:无尺寸/无库位的特殊款(NF001 / NB001 / Choose Sets)
- 🌸 粉色:近期新款 SKU(在 new_sku_prefix 列表中)
- 白色:正常款

【依赖】
streamlit, pandas, pymupdf (fitz)

【维护】⚠️ 重要:有新款上架时,请记得更新 GitHub 代码中的 SKU 对照表!
- 新增甲片款式 → 在 sku_prefix_to_name 加一行映射
- 新增近期新款 → 同时加入 new_sku_prefix(用于粉色标记)
- 新增无尺寸 SKU → 同时加入 sku_prefix_to_name 和 SIZELESS_SKUS,
  并增加对应的正则匹配(参考 NB_ONLY 的写法)
- 改完后务必 push 到 GitHub,否则线上工具仍是旧版,会出现"❓未识别"
================================================================================
"""

import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具(´∀｀)♡", layout="centered")
st.title("NailVesta 拣货单汇总工具💗")
st.caption("提取 Seller SKU + 数量,并根据 SKU 前缀映射产品名称(支持 bundle、Mystery、Organizer 与 Choose 2 Sets 对账规则)")

# ========== 维护提示 ==========
st.info(
    "📢 **新款上架提醒**:有新款 SKU 上架时,请记得更新 GitHub 代码中的对照表"
    "(`sku_prefix_to_name` 和 `new_sku_prefix`),否则新款会显示为 ❓未识别。"
    "改完别忘了 push 到 GitHub,线上版本才会同步生效~"
)

# ========== 库位映射配置 ==========
catalog_file = st.file_uploader(
    "📚 上传产品图册 CSV(包含 SKU 与库位列)",
    type=["csv"],
    key="catalog",
    help="可选。上传后会按库位排序拣货单,方便仓库按动线拣货"
)

sku_to_location = {}
if catalog_file:
    try:
        catalog_df = pd.read_csv(catalog_file, dtype=str)
        if 'SKU' in catalog_df.columns and '库位' in catalog_df.columns:
            catalog_df['SKU'] = catalog_df['SKU'].astype(str).str.strip()
            catalog_df['库位'] = catalog_df['库位'].fillna('').astype(str).str.strip()
            valid = catalog_df[catalog_df['库位'] != '']
            sku_to_location = dict(zip(valid['SKU'], valid['库位']))
            st.success(f"✅ 已加载 {len(sku_to_location)} 个 SKU 的库位")
        else:
            st.warning("⚠️ 图册缺少 'SKU' 或 '库位' 列")
    except Exception as e:
        st.error(f"读取图册失败: {e}")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ SKU 映射表(保持不变)
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
    "NOJ011":"Snowy Comet","NOX013":"Christmas Village","NOJ009":"Reindeer Glow","NIX002":"Golden Orchid", "NPX021":"Twinkle Pine",
    "NOF018":"Glacier Bloom","NOJ010":"Rosé Noir","NPX022":"Merry Charm", "NPJ014":"Snow Pixie","NPJ018":"Frost Ruby",
    "NPJ017":"Starlit Rift","NPF021":"Candy Cane","NPJ016":"Fairy Nectar","NPJ015":"Icy Viper","NOX014":"Taro Petal","NVT001":"Tool Kits",
    "NF001":"Free Giveaway","NIF001":"Lilac Veil","NIF002":"Gingerbread","NOX015":"Glitter Doll","NOJ012":"Winery Flame",
    "NOF021":"Velvet Ribbon","NPX024":"Rose Wine","NPX023":"Rosy Promise","NMF001":"Cherry Crush","NBX001":"Ballet Petal",
    "NMF003":"Royal Treasure","NMF002":"Safari Princess","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost","NOJ013":"Midnight Denim","NOJ014":"Imperial Frost",
    "NPJ019":"Gothic Mist","NOJ015":"Sapphire Bloom",
    "NPX025":"Cocoa Teddy","NVF001":"Golden Bloom","NBJ002":"Cherry Drop",
    "NOF022":"Aqua Reverie","NPF023":"Arctic Starlight","NDJ001":"Snow Knit",
    "NOX016":"Cherry Ribbon","NOX017":"Ruby Bow","NMF004":"Lavender Bloom","NDX002":"Cloudy Knit","NMJ003":"Gothic Rose","NOF025":"Cherry Romance","NMJ001":"Milky Cloud",
    "NMX001":"Petal Muse","NOF024":"Floral Muse","NVX001":"Sakura Macaron","NVF002":"Dreamy Bloom","NOJ017":"Floral Garden","NOJ016":"Jade Blossom","NVX002":"Pastel Bloom",
    "NPF023":"Fairy Garden","NBJ001":"Stone Petal","NOF027":"Acai Bloom","NPJ021":"Champagne Blossom","NPJ020":"Citrus Daisy","NOJ018":"Ribbon Lily","NVF005":"Dreamy Sakura",
    "NDX003":"Meadow Petals","NOX018":"Strawberry Kiss","NOJ020":"Raibow Bloom","NPF026":"Seaside Sundae","NVJ001":"Prism Aura","NDX005":"Midnight Glam","NDX004":"Starry Tide",
    "NPX027":"Hibiscus Tide","NPX026":"Ocean Yuzu","NWX001":"Seashell Sorbet","NOF026":"Island Paradise","NPF024":"Tropical Breeze","NOJ021":"Petal Gelato",
    "NVF003":"Apricot Cream","NMJ005":"Glossy Aura","NGX001":"Seafoam Jewel","NOF028":"Floral Cherry","NTX001":"Coraline Glow","NOX020":"Floral Drip","NOX019":"Mint Petal","NOF030":"Citrus Veil",
    "NOF031":"Lady Cherry","NOF029":"Marine Glow","NDJ002":"Aqua Blush","NWF001":"Berry Bowtie","NTF001":"Pastel Coast","NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember","NOX022":"Sunlit Petals","NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals",
    # 🆕 无尺寸款 SKU
    "NB001":"Organizer Binder",
}
updated_mapping = dict(sku_prefix_to_name)

# 🆕 新款映射表
new_sku_prefix = {
    "NOX025":"Golden Nectar","NWX002":"Meadow Daisy","NOX023":"Mermaid Glam","NOX021":"Peach Ember","NOX022":"Sunlit Petals","NOX024":"Teal Blossom","NVF006":"Lime Petals","NOJ022":"Leaf Petals"
}

# 🆕 无尺寸 SKU 集合(出现时不带 -S/-M/-L,但仍是真实可拣货商品)
SIZELESS_SKUS = {"NF001", "NB001"}

# ---------- 小工具 ----------
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}|NF001){1,4}-[SML])', re.DOTALL)
QTY_AFTER  = re.compile(r'\b([1-9]\d{0,2})\b')
ITEM_QTY_RE = re.compile(r"Item\s+quantity[:：]?\s*(\d+)", re.I)
NM_ONLY = re.compile(r'\bNF001\b')
# 🆕 NB001 匹配(无尺寸)
NB_ONLY = re.compile(r'\bNB001\b')
# 🆕 Choose 2 Sets 段落识别
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
            parts.append('NM001')
            i += 5
            continue
        seg = code[i:i+6]
        if re.fullmatch(r'[A-Z]{3}\d{3}', seg):
            parts.append(seg)
            i += 6
            continue
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

# 🆕 估算 Choose N Sets 的实际拣货件数
def count_choose_sets_items(text: str) -> int:
    # Choose N Sets 段落:每个套装下面跟若干行,每行最后一个数字是该子项数量。
    # PDF 文本提取后大致形如:
    #   Choose 2 Sets
    #   1   1   1   <orderID>
    #   2   2   1   <orderID>
    # 启发式抓:从每个 'Choose N Sets' 出现位置往后,直到遇到下一个正式 SKU
    # 或下一个 Choose 段落,在这段范围内累加 (数量, 18位订单ID) 配对的"数量"。
    total = 0
    # 找所有 Choose N Sets 出现位置
    positions = [m.start() for m in CHOOSE_SETS_RE.finditer(text)]
    if not positions:
        return 0
    positions.append(len(text))
    # 订单 ID 一般是 18 位左右数字,前面那个 1-3 位数字就是数量
    qty_pattern = re.compile(r'\b([1-9]\d{0,2})\s+(\d{15,20})\b')
    for i in range(len(positions) - 1):
        block = text[positions[i]:positions[i+1]]
        # 如果这个 block 内出现了正式 SKU(NXX###),只取到 SKU 之前
        m_sku = re.search(r'\b[A-Z]{3}\d{3}-[SML]\b', block)
        if m_sku:
            block = block[:m_sku.start()]
        # 数 block 里所有"数量 + 订单ID"对中的数量
        for m in qty_pattern.finditer(block):
            total += int(m.group(1))
    return total

# ---------- 库位排序辅助函数 ----------
def location_sort_key(loc: str):
    if not loc or loc == "未识别库位":
        return (99, 99, 99)
    m = re.match(r'^([AB])-(\d{2})-(\d{2})$', loc)
    if not m:
        return (98, 0, 0)
    zone = 0 if m.group(1) == 'A' else 1
    return (zone, int(m.group(2)), int(m.group(3)))

# ---------- 主逻辑 ----------
if uploaded_file:
    raw = uploaded_file.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    text = "\n".join([p.get_text("text") for p in doc])
    text = normalize_text(text)

    m_total = ITEM_QTY_RE.search(text)
    expected_total = int(m_total.group(1)) if m_total else 0

    text_fixed = fix_orphan_digit_before_size(text)

    sku_counts = defaultdict(int)
    bundle_extra = 0
    mystery_units = 0  # NF001 件数(在 PDF 226 中已包含)
    binder_units = 0   # NB001 件数(在 PDF 226 中已包含)

    # 1️⃣ 抓所有带尺寸的 SKU(含 bundle)
    matched_spans = []
    for m in SKU_BUNDLE.finditer(text_fixed):
        sku_raw = re.sub(r'\s+', '', m.group(1))
        after = text_fixed[m.end(): m.end()+50]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        extra, myst = expand_bundle(sku_counts, sku_raw, qty)
        bundle_extra += extra
        mystery_units += myst
        matched_spans.append((m.start(), m.end()))

    # 2️⃣ 抓孤立的 NF001(没尺寸的 Free Giveaway)
    for m in NM_ONLY.finditer(text_fixed):
        nxt = text_fixed[m.end(): m.end()+3]
        if '-' in nxt:
            continue
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NF001'] += qty
        mystery_units += qty

    # 3️⃣ 🆕 抓 NB001(Organizer Binder,无尺寸)
    for m in NB_ONLY.finditer(text_fixed):
        after = text_fixed[m.end(): m.end()+80]
        mq = QTY_AFTER.search(after)
        qty = int(mq.group(1)) if mq else 1
        sku_counts['NB001'] += qty
        binder_units += qty

    # 4️⃣ 🆕 抓 Choose N Sets 段落(无具体 SKU,只能记总数)
    choose_sets_units = count_choose_sets_items(text_fixed)
    if choose_sets_units > 0:
        sku_counts['__CHOOSE_SETS__'] += choose_sets_units

    total_qty = sum(sku_counts.values())

    # 🆕 期望值计算:bundle 拆分会让件数比 PDF 标注多,所以加 bundle_extra
    # NF001 / NB001 / Choose Sets 这些 PDF 标注里已经包含了,不需要单独加减
    expected_with_bundle = expected_total + bundle_extra

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"]   = df["Seller SKU"].str.split("-").str[0]
        df["Size"]         = df["Seller SKU"].str.split("-").str[1]

        # 🆕 Choose Sets 的产品名特殊处理
        def map_name(prefix):
            if prefix == "__CHOOSE_SETS__":
                return "Choose 2 Sets(混合套装)"
            return updated_mapping.get(prefix, "❓未识别")
        df["Product Name"] = df["SKU Prefix"].map(map_name)

        df_sized = df[df["Size"].notna()].copy()
        df_nosized = df[df["Size"].isna()].copy()

        # 透视表(只对有尺寸的)
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

        # 🆕 把无尺寸 SKU(NF001/NB001/Choose Sets)追加到表里
        if not df_nosized.empty:
            for _, row in df_nosized.iterrows():
                new_row = {
                    "SKU Prefix": row["SKU Prefix"],
                    "Product Name": row["Product Name"],
                    "S": 0, "M": 0, "L": 0,
                    "Total": row["Qty"]
                }
                pivot = pd.concat([pivot, pd.DataFrame([new_row])], ignore_index=True)

        # 加入库位列(无尺寸款标记为"无库位/特殊")
        def map_location(prefix):
            if prefix in SIZELESS_SKUS or prefix == "__CHOOSE_SETS__":
                return "无库位(特殊款)"
            return sku_to_location.get(prefix, "未识别库位")
        pivot["库位"] = pivot["SKU Prefix"].map(map_location)

        # 排序模式切换
        sort_mode = st.radio(
            "🔀 排序方式",
            ["📦 按库位顺序(拣货模式)", "🔤 按字母顺序(A-Z)"],
            horizontal=True,
            help="拣货模式:从 A-01-01 顺着货架走一遍即可。字母顺序:按产品名 A-Z 排列,方便查找。"
        )

        # 🆕 把"特殊款"(NF001/NB001/Choose Sets)永远排到最后
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

        # 调整列顺序
        pivot = pivot[["库位", "Product Name", "S", "M", "L", "Total"]]

        # 📊 对账展示
        st.subheader("📦 对账结果")

        # 🆕 拆分明细的对账显示
        nail_qty = pivot[~pivot["库位"].str.startswith("无库位")]["Total"].sum() \
                   if not pivot.empty else 0
        special_qty = pivot[pivot["库位"].str.startswith("无库位")]["Total"].sum() \
                      if not pivot.empty else 0

        st.markdown(f"""
        **📋 PDF 头部信息**
        - PDF 标注数量(Item quantity):**{expected_total}**

        **🔢 提取明细**
        - 普通甲片(有库位):**{nail_qty}** 件
        - 无尺寸特殊款(NF001 Free Giveaway / NB001 Organizer / Choose Sets):**{special_qty}** 件
          - Free Giveaway(NF001):**{mystery_units}**
          - Organizer Binder(NB001):**{binder_units}**
          - Choose Sets(混合套装):**{choose_sets_units}**
        - bundle 拆分多出的件数(+):**{bundle_extra}**

        **🎯 对账公式**
        - 实际提取总数:**{total_qty}**(= 普通甲片 {nail_qty} + 特殊款 {special_qty})
        - PDF 标注 + bundle 拆分:**{expected_with_bundle}**(= {expected_total} + {bundle_extra})
        """)

        if expected_total == 0:
            st.warning("⚠️ 未识别到 Item quantity。")
        elif total_qty == expected_with_bundle:
            st.success(f"✅ 完全对账成功(PDF {expected_total} + bundle 拆分 {bundle_extra} = 提取 {total_qty})")
        elif total_qty == expected_total:
            st.success(f"✅ 与原始 PDF 数量一致({expected_total})")
        else:
            diff = total_qty - expected_with_bundle
            st.error(f"❌ 不一致:期望 {expected_with_bundle},实际 {total_qty},差 {diff:+d} 件")

        # 🆕 未识别 SKU 提示(优先级最高,提醒及时更新代码)
        unknown_sku = pivot[pivot["Product Name"] == "❓未识别"]
        if not unknown_sku.empty:
            unknown_prefixes = unknown_sku["库位"].tolist()  # 这里其实没有库位,后面会读 SKU
            # 直接从 sku_counts 反查 prefix
            unknown_prefix_list = []
            for sku in sku_counts.keys():
                prefix = sku.split("-")[0] if "-" in sku else sku
                if prefix not in updated_mapping and prefix != "__CHOOSE_SETS__":
                    if prefix not in unknown_prefix_list:
                        unknown_prefix_list.append(prefix)
            st.error(
                f"🚨 **发现 {len(unknown_prefix_list)} 个未识别的 SKU 前缀**:"
                f"`{', '.join(unknown_prefix_list)}`\n\n"
                f"👉 这些 SKU 不在代码的对照表里,请尽快在 GitHub 仓库中更新 "
                f"`sku_prefix_to_name`(以及如果是新款,同时加入 `new_sku_prefix`),"
                f"push 后重新部署,否则新款将无法正确显示产品名。"
            )

        # 未识别库位提示
        truly_unknown = pivot[pivot["库位"] == "未识别库位"]
        if not truly_unknown.empty:
            st.warning(f"⚠️ 有 {len(truly_unknown)} 个款式没有库位信息(需要补充图册):"
                       f"{', '.join(truly_unknown['Product Name'].tolist())}")

        # 特殊款提示(给仓库一个 heads up)
        special_rows = pivot[pivot["库位"] == "无库位(特殊款)"]
        if not special_rows.empty:
            special_names = special_rows["Product Name"].tolist()
            st.info(f"ℹ️ 有 {len(special_rows)} 类无尺寸/特殊款不参与库位拣货:"
                    f"{', '.join(special_names)}(需单独处理)")

        # 🌸 行高亮
        prefix_lookup = {name: sku_p for sku_p, name in updated_mapping.items()}

        def highlight_row(row):
            loc = str(row["库位"])
            name = str(row["Product Name"])
            prefix = prefix_lookup.get(name, "")

            if loc == "未识别库位":
                return ['background-color: #ffd966'] * len(row)
            if loc == "无库位(特殊款)":
                return ['background-color: #e0e0e0'] * len(row)
            if prefix in new_sku_prefix:
                return ['background-color: #ffe4ec'] * len(row)
            return [''] * len(row)

        pivot_styled = pivot.style.apply(highlight_row, axis=1)
        st.dataframe(pivot_styled, use_container_width=True)

        csv = pivot.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

    else:
        st.error("未识别到任何 SKU。请确认 PDF 为可复制文本。")
