import streamlit as st
import pandas as pd
import json
import time
import datetime
from PIL import Image
import google.generativeai as genai

# === การตั้งค่าหน้าเว็บ ===
st.set_page_config(page_title="FoodMarket Data Center", page_icon="🍗", layout="wide")
st.title("🧾 ระบบรวมข้อมูลยอดขาย FoodMarket (All-in-One)")

# === 1. ช่องใส่ API Key (Sidebar) ===
st.sidebar.header("⚙️ ตั้งค่าระบบ")
api_key = st.sidebar.text_input("🔑 AIzaSyBubtOm29JRRNbs2gF5lRzC1movBHvuzqA:", type="password", help="เอา API Key มาวางตรงนี้เพื่อเริ่มใช้งาน")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📅 เลือกวันที่ (Date Filter)")
st.sidebar.caption("• **สลิปรูปภาพ:** ใช้วันที่นี้แทน กรณี AI หาวันที่บนสลิปไม่เจอ\n• **ไฟล์ CSV:** ระบบจะดึงยอดขายมาเฉพาะวันที่ตรงกับช่องนี้เท่านั้น")
selected_date = st.sidebar.date_input("เลือกวันที่ขาย:", datetime.date.today())
formatted_selected_date = selected_date.strftime("%d/%m/%Y")

# === 2. โหลด Master Data ===
@st.cache_data
def load_master():
    try:
        with open('item_master.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

item_master = load_master()
if len(item_master) > 0:
    st.sidebar.success(f"✅ โหลด Master Data สำเร็จ ({len(item_master)} รายการ)")
else:
    st.sidebar.error("❌ หาไฟล์ item_master.json ไม่เจอ")

# ========================================================
# 🔒 ตั้งค่าชื่อคอลัมน์ให้ตรงกับไฟล์ระบบ POS ของคุณ
# ========================================================
CSV_COL_DATE = "วันที่เปิดบิล"
CSV_COL_CODE = "รหัสเมนู"
CSV_COL_NAME = "ชื่อเมนู"
CSV_COL_QTY = "จำนวน"
CSV_COL_AMOUNT = "ยอดขาย"

# === ฟังก์ชันทำความสะอาดตัวเลข ===
def clean_number(val):
    if pd.isna(val) or val == "" or val == "ไม่ระบุ": return 0
    if isinstance(val, str): val = val.replace(",", "").strip()
    try: return float(val)
    except: return 0

# === ฟังก์ชันจัดรูปแบบข้อมูล ===
def process_row_data(raw_date, raw_code, raw_name, raw_qty, raw_amount, source_file):
    qty = clean_number(raw_qty)
    amount = clean_number(raw_amount)
    if qty == 0 and amount == 0: return None
    
    # ถ้าหา Date ไม่เจอจริงๆ ค่อยใช้วันที่ที่เลือก
    final_date = str(raw_date).strip() if str(raw_date).strip() not in ["", "nan", "NaN", "None"] else formatted_selected_date
    code_raw = str(raw_code).strip().upper().replace("FMFCO", "FMFC0").replace("FMC0", "FMFC0")
    original_name = str(raw_name).strip()
    
    correct_name = original_name
    branch_name = "ไม่ระบุสาขา"
    
    found_in_master = False
    for key, val in item_master.items():
        if "|" in key:
            master_branch, master_code = key.split("|", 1)
            if master_code == code_raw:
                correct_name = val
                branch_name = master_branch
                found_in_master = True
                break
                
    if not found_in_master and code_raw in item_master:
        correct_name = item_master[code_raw]
        
    unit_price = amount / qty if qty > 0 else 0
    
    return {
        "วันที่": final_date,
        "สาขา": branch_name,
        "รหัสสินค้า": code_raw,
        "ชื่อเมนู": correct_name,
        "ราคา (฿)": round(unit_price, 2),
        "จำนวน (จาน)": int(qty),
        "ยอด (฿)": amount,
        "แหล่งที่มา": source_file
    }

# === 3. ส่วนอัปโหลดแบบรวมมิตร ===
st.markdown("### 📤 อัปโหลดไฟล์ทั้งหมด (ภาพสลิป และ CSV)")
st.info(f"💡 ระบบทำงานด้วย AI โมเดล **Gemini 2.5 Flash** | 💡 สำหรับ CSV ดึงเฉพาะวันที่ **{formatted_selected_date}**")

uploaded_files = st.file_uploader("ลากไฟล์รูปภาพและ CSV มารวมกันตรงนี้ได้เลย", type=['jpg', 'jpeg', 'png', 'csv'], accept_multiple_files=True)

if st.button("🚀 ประมวลผลข้อมูลทั้งหมด", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ กรุณาใส่ API Key ที่เมนูด้านซ้ายมือก่อนครับ")
    elif not uploaded_files:
        st.warning("⚠️ กรุณาอัปโหลดไฟล์ก่อนครับ")
    else:
        genai.configure(api_key=api_key)
        
        # ========================================================
        # 🔴 ล็อคโมเดลเป็น gemini-2.5-flash ไว้ตรงนี้เลยครับ!
        # ========================================================
        model = genai.GenerativeModel("gemini-2.5-flash") 
        
        prompt = """
        คุณคือพนักงานบัญชี ดึงข้อมูล 'วันที่' และ 'รายการยอดขาย' จากรูปภาพใบเสร็จนี้ 
        ให้ส่งกลับมาเป็นรูปแบบ JSON Array เท่านั้น ตามโครงสร้างนี้:
        [{"Date": "DD/MM/YYYY", "Item_Code": "รหัสเมนู", "Item_Name": "ชื่อเมนู", "Qty": จำนวน, "Amount": ยอดเงินรวม}]
        เงื่อนไข:
        1. Date: หา "วันที่" ในสลิป แปลงเป็น วัน/เดือน/ปี ถ้าหาไม่พบให้เว้นว่างเป็น "" ให้ใส่ในทุกบรรทัด
        2. ข้ามบรรทัดที่ไม่ใช่เมนูอาหาร ห้ามอธิบายเพิ่ม ตอบแค่ JSON เท่านั้น
        """
        
        all_data = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        st.markdown("---")
        st.markdown("### 🔄 สถานะการประมวลผล")
        
        image_count = sum(1 for f in uploaded_files if f.name.lower().endswith(('.jpg', '.jpeg', '.png')))
        images_processed = 0
        
        for i, file in enumerate(uploaded_files):
            file_ext = file.name.lower().split('.')[-1]
            status_text.text(f"กำลังประมวลผลไฟล์ที่ {i+1}/{len(uploaded_files)}: {file.name} ...")
            
            # --- กรณีไฟล์รูปภาพ (ให้ AI อ่าน) ---
            if file_ext in ['jpg', 'jpeg', 'png']:
                col1, col2 = st.columns([1, 2])
                image = Image.open(file)
                with col1: st.image(image, width=200)
                
                try:
                    response = model.generate_content([prompt, image])
                    clean_text = response.text.strip()
                    if clean_text.startswith("```json"): clean_text = clean_text[7:]
                    if clean_text.endswith("```"): clean_text = clean_text[:-3]
                    
                    data_list = json.loads(clean_text)
                    with col2: st.success(f"✅ สแกนสลิปสำเร็จ พบ {len(data_list)} รายการ")
                    
                    for row in data_list:
                        processed_row = process_row_data(
                            row.get("Date", ""), row.get("Item_Code", ""), row.get("Item_Name", ""),
                            row.get("Qty", 0), row.get("Amount", 0.0), file.name
                        )
                        if processed_row: all_data.append(processed_row)
                        
                except Exception as e:
                    with col2: st.error(f"❌ อ่านภาพ {file.name} ไม่สำเร็จ: ({e})")
                
                images_processed += 1
                if images_processed < image_count:
                    time.sleep(10)
                    
            # --- กรณีไฟล์ CSV (แพนด้าอ่าน และกรองวันที่) ---
            elif file_ext == 'csv':
                try:
                    try: 
                        raw_df = pd.read_csv(file, encoding='utf-8')
                    except UnicodeDecodeError:
                        file.seek(0)
                        raw_df = pd.read_csv(file, encoding='tis-620')
                        
                    missing_cols = [c for c in [CSV_COL_CODE, CSV_COL_QTY, CSV_COL_AMOUNT] if c not in raw_df.columns]
                    if missing_cols:
                        st.error(f"❌ ไฟล์ {file.name} ขาดคอลัมน์: {', '.join(missing_cols)}")
                    else:
                        # กรองเอาเฉพาะข้อมูลที่มีวันที่ตรงกับที่เราเลือกจากเมนูด้านซ้าย
                        if CSV_COL_DATE in raw_df.columns:
                            parsed_dates = pd.to_datetime(raw_df[CSV_COL_DATE], errors='coerce', dayfirst=True).dt.date
                            filtered_df = raw_df[parsed_dates == selected_date]
                        else:
                            filtered_df = raw_df 
                            
                        if filtered_df.empty:
                            st.warning(f"⚠️ ไฟล์ {file.name} ไม่มียอดขายของวันที่ {formatted_selected_date} เลยครับ (ข้ามไฟล์นี้)")
                            continue

                        valid_rows = 0
                        for index, row in filtered_df.iterrows():
                            r_name = row[CSV_COL_NAME] if CSV_COL_NAME in filtered_df.columns else ""
                            
                            processed_row = process_row_data(
                                formatted_selected_date, row[CSV_COL_CODE], r_name, 
                                row[CSV_COL_QTY], row[CSV_COL_AMOUNT], file.name
                            )
                            if processed_row: 
                                all_data.append(processed_row)
                                valid_rows += 1
                        st.success(f"✅ ดึงข้อมูล CSV {file.name} (เฉพาะวันที่ {formatted_selected_date}) สำเร็จ {valid_rows} รายการ")
                except Exception as e:
                    st.error(f"❌ อ่านไฟล์ CSV {file.name} ไม่สำเร็จ: {e}")
            
            progress_bar.progress((i + 1) / len(uploaded_files))
            
        status_text.success("✅ ประมวลผลข้อมูลทั้งหมดเสร็จสิ้น!")
        
        # === 4. แสดงผลตาราง ===
        if all_data:
            st.markdown("---")
            st.markdown("### 📊 ผลลัพธ์ข้อมูลรวม (พร้อมนำไปวางใน Excel)")
            df = pd.DataFrame(all_data)
            
            df = df[["วันที่", "สาขา", "รหัสสินค้า", "ชื่อเมนู", "ราคา (฿)", "จำนวน (จาน)", "ยอด (฿)", "แหล่งที่มา"]]
            
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ CSV (ตารางรวม)",
                data=csv,
                file_name=f'foodmarket_merged_data_{selected_date.strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )