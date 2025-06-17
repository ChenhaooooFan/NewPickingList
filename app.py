import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单产品名汇总工具")
st.caption("提取商品名称 + 尺码 + 数量，并验证总数是否一致")

uploaded_file = st.file_uploader("请上传 PDF 拣货单文件", type=["pdf"])

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 尝试从 PDF 中抓取总数（Product quantity: 32）
    total_quantity_match = re.search(r"Product quantity:\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    # 提取产品名 + 尺码 + SKU + 数量
    pattern = r"([A-Za-z’'’]+(?:\s+[A-Za-z’'’]+)+),\s*([SML])\s*\n([A-Z]{3}\d{3}-[SML])\s+(\d+)"
    matches = re.findall(pattern, text)

    if matches:
        data = []
        for name, size, sku, qty in matches:
            product_name = " ".join(name.strip().split()[:2])  # 前两个词
            data.append([product_name, size, int(qty)])

        df = pd.DataFrame(data, columns=["Product Name", "Size", "Qty"])
        df_summary = df.groupby(["Product Name", "Size"], as_index=False)["Qty"].sum()

        # 排序 S/M/L
        size_order = {"S": 0, "M": 1, "L": 2}
        df_summary["Size Sort"] = df_summary["Size"].map(size_order)
        df_summary = df_summary.sort_values(by=["Product Name", "Size Sort"]).drop(columns=["Size Sort"])

        st.success("✅ 提取成功并已排序！")
        st.dataframe(df_summary)

        # 总数量
        total_qty = df_summary["Qty"].sum()
        st.subheader(f"📦 实际拣货总数量：{total_qty}")

        if expected_total is not None:
            if total_qty == expected_total:
                st.success(f"✅ 与拣货单标注的总数一致！（{expected_total}）")
            else:
                st.error(f"❌ 数量不一致！拣货单写的是 {expected_total}，实际提取为 {total_qty}")
        else:
            st.warning("⚠️ 无法识别拣货单标注的总数。")

        # 下载按钮
        csv = df_summary.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载为 CSV 文件", data=csv, file_name="product_summary_sorted.csv", mime="text/csv")
    else:
        st.warning("⚠️ 没有匹配到有效数据，请检查 PDF 格式是否正确。")
