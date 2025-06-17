import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单分析工具")
st.caption("上传 PDF，自动提取 SKU 并统计总数")

uploaded_file = st.file_uploader("请上传 PDF 拣货单文件", type=["pdf"])

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 正则提取 SKU + Qty（Seller SKU 与 SKU 相同）
    pattern = r"\b([A-Z]{3}\d{3}-[MSL])\b\s+(\d+)\b"
    matches = re.findall(pattern, text)

    if matches:
        df = pd.DataFrame(matches, columns=["SKU", "Qty"])
        df["Qty"] = df["Qty"].astype(int)
        df["Seller SKU"] = df["SKU"]  # Seller SKU 与 SKU 相同
        df = df[["SKU", "Seller SKU", "Qty"]]

        # 合并数量
        summary_df = df.groupby(["SKU", "Seller SKU"], as_index=False)["Qty"].sum()

        st.success("✅ 成功提取 SKU 数据！")
        st.dataframe(summary_df)

        # 下载按钮
        csv = summary_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载为 CSV 文件", data=csv, file_name="sku_summary.csv", mime="text/csv")
    else:
        st.warning("⚠️ 没有匹配到 SKU 数据，请确认 PDF 内容格式是否正确。")
