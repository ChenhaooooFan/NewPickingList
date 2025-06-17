import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单产品名汇总工具")
st.caption("提取商品名称 + 尺码 + 数量")

uploaded_file = st.file_uploader("请上传 PDF 拣货单文件", type=["pdf"])

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 正则匹配：产品名 + 尺码 + 数量
    pattern = r"([A-Za-z’'’]+(?:\s+[A-Za-z’'’]+)+),\s*([SML])\s*\n([A-Z]{3}\d{3}-[SML])\s+(\d+)"

    matches = re.findall(pattern, text)

    if matches:
        data = []
        for name, size, sku, qty in matches:
            product_name = " ".join(name.strip().split()[:2])  # 取前两个词
            data.append([product_name, size, int(qty)])

        df = pd.DataFrame(data, columns=["Product Name", "Size", "Qty"])
        df_summary = df.groupby(["Product Name", "Size"], as_index=False)["Qty"].sum()

        st.success("✅ 成功提取产品信息！")
        st.dataframe(df_summary)

        # 下载按钮
        csv = df_summary.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载为 CSV 文件", data=csv, file_name="product_summary.csv", mime="text/csv")
    else:
        st.warning("⚠️ 没有匹配到有效数据，请检查 PDF 格式是否正确。")
