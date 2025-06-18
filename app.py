import streamlit as st
import pandas as pd
import re
import fitz  # PyMuPDF
from collections import defaultdict

st.set_page_config(page_title="拣货单汇总工具", layout="centered")
st.title("📦 NailVesta 拣货单产品名汇总工具")
st.caption("提取产品名称 + 尺码 + 数量（按订单去重），并验证总数是否一致")

uploaded_file = st.file_uploader("请上传 PDF 拣货单文件", type=["pdf"])

if uploaded_file:
    text = ""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    for page in doc:
        text += page.get_text()

    # 正确抓取 Item quantity（不是 Product quantity）
    total_quantity_match = re.search(r"Item quantity[:：]?\s*(\d+)", text)
    expected_total = int(total_quantity_match.group(1)) if total_quantity_match else None

    # 用两种方式提取数据：常规 + 紧凑型
    pattern_multi = r"([A-Za-z’'’]+(?:\s+[A-Za-z’'’]+)+),\s*([SML])\s*\n([A-Z]{3}\d{3}-[SML])\s+(\d+)\s+([\d\s]+)"
    pattern_inline = r"([A-Za-z’'’]+(?:\s+[A-Za-z’'’]+)+),\s*([SML])\s+([A-Z]{3}\d{3}-[SML])\s+(\d+)\s+([\d\s]+)"
    matches = re.findall(pattern_multi, text) + re.findall(pattern_inline, text)

    if matches:
        sku_data = defaultdict(set)

        for name, size, sku, qty, order_block in matches:
            product_name = " ".join(name.strip().split()[:2])
            order_ids = re.findall(r"\d{15,}", order_block)
            for oid in order_ids:
                sku_data[(product_name, size)].add(oid)

        # 转为 DataFrame
        summary_data = []
        for (pname, size), order_ids in sku_data.items():
            summary_data.append({
                "Product Name": pname,
                "Size": size,
                "Qty": len(order_ids)
            })

        df_summary = pd.DataFrame(summary_data)
        df_summary["Size Order"] = df_summary["Size"].map({"S": 0, "M": 1, "L": 2})
        df_summary = df_summary.sort_values(by=["Product Name", "Size Order"]).drop(columns=["Size Order"])

        # 展示表格
        st.success("✅ 提取成功并排序！")
        st.dataframe(df_summary)

        # 比对总数
        total_qty = df_summary["Qty"].sum()
        st.subheader(f"📦 实际拣货总数量：{total_qty}")

        if expected_total is not None:
            if total_qty == expected_total:
                st.success(f"✅ 与拣货单标注的总数一致！（{expected_total}）")
            else:
                st.error(f"❌ 数量不一致！拣货单写的是 {expected_total}，实际提取为 {total_qty}")
        else:
            st.warning("⚠️ 未能识别 PDF 中的 Item quantity")

        # 下载按钮
        csv = df_summary.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载汇总结果 CSV", data=csv, file_name="product_summary.csv", mime="text/csv")
    else:
        st.warning("⚠️ 没有成功匹配到任何产品数据，请检查 PDF 内容格式。")
