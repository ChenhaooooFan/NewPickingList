import streamlit as st
from PyPDF2 import PdfReader
import pandas as pd
import re
from collections import defaultdict
from fpdf import FPDF
import tempfile

def extract_sku_summary(pdf_file):
    reader = PdfReader(pdf_file)
    all_text = ""
    for page in reader.pages:
        all_text += page.extract_text()

    sku_qty_pattern = re.compile(r"\b([A-Z]{3}\d{3}-[A-Z])\b\s+(\d+)\b")
    sku_totals = defaultdict(int)

    for match in sku_qty_pattern.finditer(all_text):
        sku = match.group(1)
        qty = int(match.group(2))
        sku_totals[sku] += qty

    sku_df = pd.DataFrame(list(sku_totals.items()), columns=["SKU", "Total Qty"])
    sku_df.sort_values(by="SKU", inplace=True)
    return sku_df

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

# --- Streamlit App ---
st.title("📦 SKU 汇总工具")

uploaded_file = st.file_uploader("上传 Picking List PDF 文件", type="pdf")

if uploaded_file:
    with st.spinner("正在处理文件..."):
        sku_df = extract_sku_summary(uploaded_file)
        st.success("提取完成！🎉")
        st.dataframe(sku_df)

        pdf_path = generate_pdf(sku_df)
        with open(pdf_path, "rb") as f:
            st.download_button(
                label="📥 下载 SKU 汇总 PDF",
                data=f,
                file_name="SKU_Summary_Report.pdf",
                mime="application/pdf"
            )
