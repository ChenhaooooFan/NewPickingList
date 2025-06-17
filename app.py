import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF

# 页面设置
st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单分析工具")
st.caption("上传 PDF，系统自动提取 SKU 并合并相同项数量")

# 上传 PDF 文件
uploaded_file = st.file_uploader("请上传拣货单 PDF 文件", type=["pdf"])

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 使用正则表达式提取 SKU, Seller SKU, Qty 信息
    pattern = r"([A-Z]{3}\d{3}-[MSL])(?:.*?)\s+(\1)\s+(\d+)"
    matches = re.findall(pattern, text)

    if matches:
        df = pd.DataFrame(matches, columns=["SKU", "Seller SKU", "Qty"])
        df["Qty"] = df["Qty"].astype(int)

        # 汇总相同 SKU + Seller SKU 的数量
        df_summary = df.groupby(["SKU", "Seller SKU"], as_index=False)["Qty"].sum()

        st.success("✅ 提取成功！以下是汇总结果：")
        st.dataframe(df_summary)

        # 下载链接
        csv = df_summary.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载汇总结果 (CSV)", data=csv, file_name="sku_summary.csv", mime="text/csv")
    else:
        st.warning("未能提取有效数据，请检查 PDF 格式是否与示例一致。")
