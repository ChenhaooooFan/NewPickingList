import streamlit as st
import pandas as pd
import re
import fitz
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并根据 SKU 前缀映射产品名称")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 映射：SKU 前缀 → 产品名
sku_prefix_to_name = {
    "NPF001": "Angel's Grace",
    "NPF005": "Auric Taurus",
    "NPF006": "Cocoa Blossom",
    "NPF003": "Golden Ivy",
    "NPF002": "Sacred Radiance",
    "NLF001": "Divine Emblem",
    "NLF002": "Athena's Glow",
    "NPJ003": "Stellar Capricorn",
    "NPJ005": "Vintage Cherry",
    "NPJ004": "Midnight Violet",
    "NPJ001": "Mystic Moon",
    "NPJ002": "Peach Dream",
    "NPJ006": "Twilight Whisper",
    "NPJ007": "Angel’s Blush",
    "NPJ008": "Lilac Muse",
    "NPJ009": "Violet Seashell",
    "NPJ010": "Garden Fairy",
    "NPJ011": "Mermaid Prism",
    "NPJ012": "Amber Romance",
    "NPJ013": "Spring Petals",
    "NPF007": "Bluebell Glow",
    "NPF008": "Lavender Angel",
    "NPF009": "Vintage Bloom",
    "NPF010": "Wild Grace",
    "NPF011": "Pink Eclipse",
    "NPF012": "Honey Moon",
    "NPF013": "Sakura Dream",
    "NPF014": "Ocean Elf",
    "NPX001": "Royal Elegance",
    "NPX006": "Autumn Petal",
    "NPX010": "Blooming Meadow",
    "NPX012": "Milky Ribbon",
    "NPX013": "Champagne Wishes",
    "NPX014": "Moon Crystal",
    "NPX015": "Daisy Melody",
    "NOF001": "Royal Amber",
    "NOF002": "Tiger Lily",
    "NOF003": "Peach Pop",
    "NOF004": "Sunset Punch",
    "NOF005": "Glacier Petal",
    "NOF006": "Cherry Champagne",
    "NOF007": "Pearl Fantasy",
    "NOF008": "Fairy Valley",
    "NOF009": "Snowy Lotus",
    "NOF010": "Creamy Coral",
    "NOF011": "Blossom Frost",
    "NOJ001": "Island Bloom",
    "NOJ002": "Floral Lemonade",
    "NOJ003": "Ocean Bloom",
    "NOJ004": "Sea Breeze",
    "NOJ005": "Sunrise Orchid",
    "NHF001": "Gothic Moon",
    "NDX001": "Pinky Promise",
    "NYJ001": "Rosy Ribbon"
}


updated_mapping = dict(sku_prefix_to_name)

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    total_quantity_match = re.search(r"Item quantity[:：]?\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    pattern = r"([A-Z]{3}\d{3}-[SML])\s+(\d+)\s+\d{9,}"
    matches = re.findall(pattern, text)

    sku_counts = defaultdict(int)
    for sku, qty in matches:
        sku_counts[sku] += int(qty)

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["SKU Prefix"] = df["Seller SKU"].apply(lambda x: x.split("-")[0])
        df["Size"] = df["Seller SKU"].apply(lambda x: x.split("-")[1])
        df["Product Name"] = df["SKU Prefix"].apply(lambda x: updated_mapping.get(x, "❓未识别"))

        # 用户手动补全
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

        # 下载结果
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载产品明细 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        # 下载 SKU 映射表
        map_df = pd.DataFrame(list(updated_mapping.items()), columns=["SKU 前缀", "产品名称"])
        map_csv = map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 映射表 CSV", data=map_csv, file_name="sku_prefix_mapping.csv", mime="text/csv")
