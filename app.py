import streamlit as st
from PyPDF2 import PdfFileReader
import pandas as pd
import re
from collections import defaultdict
from fpdf import FPDF
import tempfile
import io

# 提取 SKU 汇总
def extract_sku_summary(uploaded_file):
    pdf_stream = io.BytesIO(uploaded_file.read())
    reader = PdfFileReader(pdf_stream)
    all_text = ""
    for page_num in range(reader.getNumPages()):
        page = reader.getPage(page_num)
        if hasattr(page, 'extract_text'):
            all_text += page.extract_text()
        else:
            all_text += page.extractText()

    sku_qty_pattern = re.compile(r"\b([A-Z]{3}\d{3}-[A-Z])\b\s+(\d+)\b")
    sku_totals = defaultdict(int)

    for match in sku_qty_pattern.finditer(all_text):
        sku = match.group(1)
        qty = int(match.group(2))
        sku_totals[sku] += qty

    sku_df = pd.DataFrame(list(sku_totals.items()), columns=["SKU", "Total Qty"])
    sku_df.sort_values(by="SKU", inplace=True)
    return sku_df

# 生成 PDF 汇总文件
def generate_pdf(sku_df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="SKU Summary Report", ln=True, align="C")
    pdf.cell(100, 10, txt="SKU", border=1)
    pdf.cell(40, 10, txt="Total Qty", border=1, ln=True)

    for _, row in sku_df.iterrows():
        pdf.cell(100, 10, txt=row["SKU"], border=1)
        pdf.cell(40, 10, txt=str(row["Total Qty"]), border=1, ln=True)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_file.name)
    return temp_file.name

# --- Streamlit 页面 ---
st.title("📦 SKU 汇总工具（支持 Picking List PDF）")

uploaded_file = st.file_uploader("请上传 PDF 文件（格式为 Picking List）", type="pdf")

if uploaded_file:
    with st.spinner("正在提取数据，请稍候..."):
        try:
            sku_df = extract_sku_summary(uploaded_file)
            st.success("🎉 提取成功！")
            st.dataframe(sku_df)

            pdf_path = generate_pdf(sku_df)
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="📥 下载 SKU 汇总 PDF",
                    data=f,
                    file_name="SKU_Summary_Report.pdf",
                    mime="application/pdf"
                )
        except Exception as e:
            st.error(f"❌ 出现错误：{str(e)}")
