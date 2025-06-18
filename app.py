import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("ColorFour LLC 拣货单汇总工具")
st.caption("提取 Seller SKU + 数量，并补全产品名")

uploaded_file = st.file_uploader("📤 上传拣货 PDF", type=["pdf"])

# ✅ 初始内置对照表（可随时扩展）
sku_to_name = {
    "NPJ007-M": "Angel’s Blush",
    "NPF001-M": "Angel’s Grace",
    "NPX006-S": "Autumn Petal",
    "NPX010-S": "Blooming Meadow",
    "NPF007-M": "Bluebell Glow",
    "NPX013-S": "Champagne Wishes",
    "NOF005-S": "Glacier Petal",
    "NHF001-S": "Gothic Moon",
    "NOJ001-M": "Island Bloom",
    "NOJ001-S": "Island Bloom",
    "NPF008-S": "Lavender Angel",
    "NPX012-S": "Milky Ribbon",
    "NOF003-M": "Peach Pop",
    "NOF003-S": "Peach Pop",
    "NDX001-S": "Pinky Promise",
    "NYJ001-S": "Rosy Ribbon",
    "NOF001-M": "Royal Amber",
    "NOF001-S": "Royal Amber",
    "NPX001-L": "Royal Elegance",
    "NOF004-S": "Sunset Punch",
    "NOF002-M": "Tiger Lily",
    "NPF009-M": "Vintage Bloom",
    "NOJ002-S": "Floral Lemonade",
    "NPJ009-S": "Violet Seashell"
}

# 用于动态更新的字典副本
updated_sku_to_name = dict(sku_to_name)

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 提取 Item quantity
    total_quantity_match = re.search(r"Item quantity[:：]?\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    # 提取 SKU + 数量（只匹配含订单号的完整行）
    pattern = r"([A-Z]{3}\d{3}-[SML])\s+(\d+)\s+\d{9,}"
    matches = re.findall(pattern, text)

    sku_counts = defaultdict(int)
    for sku, qty in matches:
        sku_counts[sku] += int(qty)

    if sku_counts:
        df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
        df["Product Name"] = df["Seller SKU"].apply(lambda x: updated_sku_to_name.get(x, "❓未识别"))

        # 对于未知 SKU，让用户输入产品名
        unknown_skus = df[df["Product Name"].str.startswith("❓")]["Seller SKU"].tolist()
        if unknown_skus:
            st.warning("⚠️ 有未识别的 SKU，请输入产品名称：")
            for sku in unknown_skus:
                name_input = st.text_input(f"🔧 SKU: {sku} 的产品名称是？", key=sku)
                if name_input:
                    updated_sku_to_name[sku] = name_input
                    df.loc[df["Seller SKU"] == sku, "Product Name"] = name_input

        # 调整列顺序并排序
        df = df[["Product Name", "Seller SKU", "Qty"]].sort_values(by="Product Name").reset_index(drop=True)

        total_qty = df["Qty"].sum()
        st.subheader(f"📦 实际拣货总数量：{total_qty}")
        if expected_total:
            if total_qty == expected_total:
                st.success(f"✅ 与拣货单标注数量一致！（{expected_total}）")
            else:
                st.error(f"❌ 数量不一致！拣货单为 {expected_total}，实际为 {total_qty}")
        else:
            st.warning("⚠️ 未能识别 Item quantity")

        st.dataframe(df)

        # 下载数据汇总
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载汇总结果 CSV", data=csv, file_name="product_summary_named.csv", mime="text/csv")

        # 下载更新后的 SKU 映射表
        sku_map_df = pd.DataFrame(list(updated_sku_to_name.items()), columns=["Seller SKU", "Product Name"])
        map_csv = sku_map_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📁 下载 SKU 对照表（建议保存）", data=map_csv, file_name="sku_mapping.csv", mime="text/csv")
    else:
        st.warning("⚠️ 没有匹配到任何 SKU，请检查 PDF 格式")
