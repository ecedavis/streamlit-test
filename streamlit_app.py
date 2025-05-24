import streamlit as st
import pandas as pd
import json
import os
import datetime
from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import base64
import streamlit.components.v1 as components

# --- Persistent Files ---
INVOICE_FILE = "invoice_number.txt"
QUANTITIES_FILE = "quantities.json"
INVENTORY_FILE = "inventory.tsv"

# --- Initialize state ---
if 'quantities' not in st.session_state:
    if os.path.exists(QUANTITIES_FILE):
        with open(QUANTITIES_FILE) as f:
            st.session_state.quantities = json.load(f)
    else:
        st.session_state.quantities = {}

if 'invoice_number' not in st.session_state:
    if os.path.exists(INVOICE_FILE):
        with open(INVOICE_FILE) as f:
            st.session_state.invoice_number = int(f.read().strip())
    else:
        st.session_state.invoice_number = 1001

# --- Utility functions ---
def load_inventory():
    df = pd.read_csv(INVENTORY_FILE, sep='\t')
    df['SKU'] = df['SKU'].astype(str)
    df['SKU'] = df['SKU'].where(~df['SKU'].duplicated(), df['SKU'] + '_' + df.groupby('SKU').cumcount().astype(str))
    return df

def generate_invoice_pdf(df, metadata):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    margin = inch
    x = margin
    y = height - margin
    line_height = 14

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "INVOICE")
    y -= 0.4 * inch
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Invoice #: {metadata['number']}")
    c.drawString(width - margin - 150, y, f"Date: {metadata['date']}")
    y -= 0.3 * inch

    cols = {'sku': x, 'desc': x+60, 'unit': x+260, 'qty': x+340, 'amount': x+380}
    c.setFont("Helvetica-Bold", 10)
    for label, key in zip(["SKU","Description","Unit Price","Qty","Amount"], cols):
        c.drawString(cols[key], y, label)
    y -= 0.2 * inch
    c.line(margin, y, width - margin, y)
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)

    subtotal = 0
    for _, row in df.iterrows():
        if row['Quantity'] <= 0:
            continue
        amount = row['Unit Price'] * row['Quantity']
        subtotal += amount
        c.drawString(cols['sku'], y, row['SKU'])
        c.drawString(cols['desc'], y, row['Description'])
        c.drawString(cols['unit'], y, f"${row['Unit Price']:.2f}")
        c.drawString(cols['qty'], y, str(row['Quantity']))
        c.drawString(cols['amount'], y, f"${amount:.2f}")
        y -= line_height
        if y < margin:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)

    tax = subtotal * metadata['tax_rate'] / 100
    y -= line_height
    c.drawRightString(width - margin, y, f"Subtotal: ${subtotal:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Tax ({metadata['tax_rate']:.2f}%): ${tax:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Assembly: ${metadata['assembly']:.2f}")
    y -= line_height
    c.drawRightString(width - margin, y, f"Delivery: ${metadata['delivery']:.2f}")
    y -= line_height * 1.5
    c.setFont("Helvetica-Bold", 12)
    grand = subtotal + tax + metadata['assembly'] + metadata['delivery']
    c.drawRightString(width - margin, y, f"Grand Total: ${grand:.2f}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# --- Page Configuration ---
st.set_page_config(page_title="Invoice Manager", layout="centered")
st.title("📄 Inventory Invoice Manager")

# --- Input Section ---
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
        st.write(f"**Invoice #**: {st.session_state.invoice_number}")

# --- Inventory Table & Filters ---
df = load_inventory()
df['Unit Price'] = (df['Base Price'] * (1 + upcharge/100)).round(2)
df['Quantity'] = df['SKU'].map(lambda s: st.session_state.quantities.get(s, 0))
filter1, filter2, filter3 = st.columns([1,1,2])
selected_color = filter1.selectbox("Color", ['All'] + sorted(df['Color'].unique()), key='col_filter')
if selected_color != 'All': df = df[df['Color'] == selected_color]
selected_type = filter2.selectbox("Type", ['All'] + sorted(df['Type'].unique()), key='type_filter')
if selected_type != 'All': df = df[df['Type'] == selected_type]
search = filter3.text_input("Search Description", key='search')
if search: df = df[df['Description'].str.contains(search, case=False)]

# --- Editable Grid ---
disp = df[['SKU','Description','Unit Price','Quantity']]
edited = st.data_editor(
    disp,
    column_config={
        'SKU': st.column_config.TextColumn('SKU', disabled=True),
        'Description': st.column_config.TextColumn('Description', disabled=True),
        'Unit Price': st.column_config.NumberColumn('Unit Price', disabled=True),
        'Quantity': st.column_config.NumberColumn('Quantity', min_value=0)
    },
    hide_index=True,
    height=300
)
for sku, qty in zip(edited['SKU'], edited['Quantity']):
    st.session_state.quantities[sku] = int(qty)
with open(QUANTITIES_FILE, 'w') as f:
    json.dump(st.session_state.quantities, f)

# --- Totals, Preview & Download PDF ---
sub = sum(edited['Unit Price'] * edited['Quantity'])
colA, colB = st.columns([2,1])
with colA:
    st.markdown(f"**Subtotal:** ${sub:.2f}")
    st.markdown(f"**Tax:** ${sub * tax_rate/100:.2f}")
    st.markdown(f"**Total:** ${(sub + sub*tax_rate/100 + assembly + delivery):.2f}")
with colB:
    # Preview button
    if st.button("📄 Preview Invoice PDF"):
        pdf_buf = generate_invoice_pdf(edited, {
            'number': st.session_state.invoice_number,
            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'tax_rate': tax_rate,
            'assembly': assembly,
            'delivery': delivery
        })
        # Embed PDF in page
        b64 = base64.b64encode(pdf_buf.read()).decode('utf-8')
        pdf_html = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600px"></iframe>'
        components.html(pdf_html, height=600)
        pdf_buf.seek(0)
    # Download button
    if st.button("Download Invoice PDF"):
        pdf = generate_invoice_pdf(edited, {
            'number': st.session_state.invoice_number,
            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'tax_rate': tax_rate,
            'assembly': assembly,
            'delivery': delivery
        })
        st.download_button("📥 Save PDF", data=pdf,
                           file_name=f"invoice_{st.session_state.invoice_number}.pdf",
                           mime='application/pdf')
        st.session_state.invoice_number += 1
        with open(INVOICE_FILE, 'w') as f:
            f.write(str(st.session_state.invoice_number))
