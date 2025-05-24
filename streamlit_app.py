import streamlit as st
import pandas as pd
import datetime
from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
import base64
import streamlit.components.v1 as components
import os

# --- Persistent Invoice Number File ---
INVOICE_FILE = "invoice_number.txt"

# --- Page Configuration ---
st.set_page_config(page_title="Invoice Manager", layout="centered")
st.title("📄 Inventory Invoice Manager")

# --- Invoice Number Load/Save ---
def _load_invoice_number():
    try:
        with open(INVOICE_FILE, 'r') as f:
            return int(f.read().strip())
    except:
        return 1001

def _save_invoice_number(num):
    with open(INVOICE_FILE, 'w') as f:
        f.write(str(num))

# --- Utility functions ---
def load_inventory():
    df = pd.read_csv("inventory.tsv", sep='\t')
    df['SKU'] = df['SKU'].astype(str)
    df['SKU'] = df['SKU'].where(
        ~df['SKU'].duplicated(),
        df['SKU'] + '_' + df.groupby('SKU').cumcount().astype(str)
    )
    return df

def generate_invoice_pdf(df, number, metadata):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    margin = inch
    x = margin
    y = height - margin
    line_height = 14

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "INVOICE")
    y -= 0.4 * inch
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Invoice #: {number}")
    c.drawString(width - margin - 150, y, f"Date: {metadata['date']}")
    y -= 0.3 * inch

    # Column titles
    cols = {'sku': x, 'desc': x+60, 'unit': x+260, 'qty': x+340, 'amount': x+380}
    desc_max_width = cols['unit'] - cols['desc'] - 4
    c.setFont("Helvetica-Bold", 10)
    for label, key in zip(["SKU","Description","Unit Price","Qty","Amount"], cols):
        c.drawString(cols[key], y, label)
    y -= 0.2 * inch
    c.line(margin, y, width - margin, y)
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)

    # Line items
    subtotal = 0
    for _, row in df.iterrows():
        qty = int(row.get('Quantity', 1))
        if qty <= 0:
            continue
        amount = row['Unit Price'] * qty
        subtotal += amount

        desc_lines = simpleSplit(row['Description'], 'Helvetica', 10, desc_max_width)
        for i, line in enumerate(desc_lines):
            c.drawString(cols['desc'], y - i*line_height, line)
        c.drawString(cols['sku'], y, row['SKU'])
        c.drawString(cols['unit'], y, f"${row['Unit Price']:.2f}")
        c.drawString(cols['qty'], y, str(qty))
        c.drawString(cols['amount'], y, f"${amount:.2f}")
        y -= (len(desc_lines)*line_height) + 4
        if y < margin:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)

    # Totals
    tax = subtotal * metadata['tax_rate'] / 100
    y -= line_height
    c.drawRightString(width - margin, y, f"Subtotal: ${subtotal:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Tax ({metadata['tax_rate']:.2f}%): ${tax:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Assembly: ${metadata['assembly']:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Delivery: ${metadata['delivery']:.2f}")
    y -= line_height*1.5
    c.setFont("Helvetica-Bold", 12)
    grand = subtotal + tax + metadata['assembly'] + metadata['delivery']
    c.drawRightString(width - margin, y, f"Grand Total: ${grand:.2f}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# --- Customer & Invoice Settings ---
with st.expander("Invoice & Customer Details", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        customer = st.text_input("Customer Name", key="cust_name")
        address = st.text_area("Customer Address", key="cust_addr", height=80)
    with col2:
        tax_rate = st.number_input("Tax Rate (%)", value=7.0, key="tax")
        upcharge = st.number_input("Upcharge Rate (%)", value=20.0, key="upcharge")
        assembly = st.number_input("Assembly Charge", value=0.0, key="assembly")
        delivery = st.number_input("Delivery Charge", value=0.0, key="delivery")

# --- Load & Filter Inventory ---
df = load_inventory()
df['Unit Price'] = (df['Base Price'] * (1 + upcharge/100)).round(2)
f1, f2, f3 = st.columns([1,1,2])
col = f1.selectbox("Color", ['All'] + sorted(df['Color'].unique()), key='col_filter')
if col!='All': df = df[df['Color']==col]
typ = f2.selectbox("Type", ['All'] + sorted(df['Type'].unique()), key='type_filter')
if typ!='All': df = df[df['Type']==typ]
search = f3.text_input("Search Description", key='search')
if search: df = df[df['Description'].str.contains(search, case=False)]

# --- Single Editable Grid (with Qty & Select) ---
disp = df[['SKU','Description','Unit Price']].copy()
disp['Quantity'] = 0   # start all quantities at 0
disp['Select']   = False

st.markdown("### Select Items and Quantities")
edited = st.data_editor(
    disp,
    column_config={
        'SKU':         st.column_config.TextColumn('SKU', disabled=True),
        'Description': st.column_config.TextColumn('Description', disabled=True),
        'Unit Price':  st.column_config.NumberColumn('Unit Price', disabled=True),
        'Quantity':    st.column_config.NumberColumn('Quantity', min_value=0),
        'Select':      st.column_config.CheckboxColumn('Select', help='Tick to include')
    },
    hide_index=True,
    height=350,
    key='inventory_editor'
)

# --- Selected Items Summary ---
st.markdown("### Review Selected Items")
selected = edited[edited['Select']].copy()
if not selected.empty:
    selected['Amount'] = selected['Unit Price'] * selected['Quantity']
    display = selected[['SKU','Description','Unit Price','Quantity','Amount']].copy()
    display['Unit Price'] = display['Unit Price'].map(lambda x: f"${x:.2f}")
    display['Amount']     = display['Amount'].map(lambda x: f"${x:.2f}")
    st.table(display)
else:
    # show empty table with headers
    empty_df = pd.DataFrame(columns=['SKU','Description','Unit Price','Quantity','Amount'])
    st.table(empty_df)

pdf_df = selected[['SKU','Description','Unit Price','Quantity']]

# --- Totals & PDF Actions ---
sub = (pdf_df['Unit Price'] * pdf_df['Quantity']).sum() if not pdf_df.empty else 0.0
cA, cB = st.columns([2,1])
with cA:
    st.markdown(f"**Subtotal:** ${sub:.2f}")
    st.markdown(f"**Tax:** ${sub * tax_rate/100:.2f}")
    st.markdown(f"**Total:** ${(sub + sub*tax_rate/100 + assembly + delivery):.2f}")
with cB:
    if pdf_df.empty:
        st.button("📄 Preview Invoice PDF", disabled=True)
        st.button("Download Invoice PDF", disabled=True)
    else:
        if st.button("📄 Preview Invoice PDF"):
            num = _load_invoice_number()
            buf = generate_invoice_pdf(pdf_df, num, {
                'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                'tax_rate': tax_rate,
                'assembly': assembly,
                'delivery': delivery
            })
            b64 = base64.b64encode(buf.read()).decode()
            html = (
                f'<object data="data:application/pdf;base64,{b64}" '
                'type="application/pdf" width="100%" height="600px">'
                f'<p>Download: <a href="data:application/pdf;base64,{b64}">here</a></p>'
                '</object>'
            )
            components.html(html, height=600)
            buf.seek(0)

        if st.button("Download Invoice PDF"):
            num = _load_invoice_number()
            buf = generate_invoice_pdf(pdf_df, num, {
                'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                'tax_rate': tax_rate,
                'assembly': assembly,
                'delivery': delivery
            })
            _save_invoice_number(num+1)
            st.download_button(
                "📥 Save PDF",
                data=buf,
                file_name=f"invoice_{num}.pdf",
                mime='application/pdf'
            )
