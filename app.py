import streamlit as st
import pandas as pd
import json
import time
import datetime
import os
from PIL import Image
import google.generativeai as genai

# ========================================================
# 📊 ตั้งค่าโควตาด้วยตัวเอง (Manual Quota Settings)
# ========================================================
# ปรับตัวเลขตามที่คุณเจอในหน้า Google AI Studio ได้เลยครับ
QUOTA_LIMITS = {
    "gemini-2.5-flash": 20,
    "gemini-2.5-flash-lite": 20,
    "gemini-2.0-flash": 20  # เผื่อคุณสลับไปใช้รุ่นที่โควตาเยอะกว่า
}

USAGE_FILE = "usage_log.json"
# ========================================================

# === การตั้งค่าหน้าเว็บ ===
st.set_page_config(page_title="FoodMarket Data Center", page_icon="🍗", layout="wide")
st.title("🧾 ระบบรวมข้อมูลยอดขาย (Usage Tracker v2)")

# --- ระบบนับจำนวนการใช้งาน (Usage Tracker) ---
def load_usage():
    today = str(datetime.date.today())
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today:
                    return data.get("counts", {})
        except: return {}
    return {}

def update_usage(model_name):
    today = str(datetime.date.today())
    usage_data = load_usage()
    usage_data[model_name] = usage_data.get(model_name, 0) + 1
    with open(USAGE_FILE, "w") as f:
        json.dump({"date": today, "counts": usage_data}, f)
    return usage_data[model_name]

# โหลดข้อมูลปัจจุบัน
current_counts = load_usage()

# === 1. ระบบจัดการ API Key & Model Selection ===
st.sidebar.header("⚙️ ตั้งค่าระบบ")

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("✅ เชื่อมต่อ Key จาก Secrets")
else:
    api_key = st.sidebar.text_input("🔑 ใส่ Gemini API Key:", type="password")

st.sidebar.divider()

# --- เมนูเลือกโมเดลและแสดงตัวนับ ---
st.sidebar.subheader("🤖 สถานะโควตาใช้งานวันนี้")
model_choice = st.sidebar.selectbox(
    "เลือกโมเดล:",
    list(QUOTA_LIMITS.keys()),
    index=1
)

# ดึงค่า Max Quota จากตัวแปรที่เราตั้งไว้ด้านบน
max_q = QUOTA_LIMITS.get(model_choice, 20)
used_q = current_counts.get(model_choice, 0)

# แสดงผล Metric
st.sidebar.metric(
    label=f"โควตา {model_choice}",
    value=f"{used_q} / {max_q}",
    delta=f"เหลือ {max_q - used_q} ครั้ง",
    delta_color="normal" if used_q < max_q else "inverse"
)

# Progress Bar แสดงความคุ้มค่า
st.sidebar.progress(min(used_q / max_q, 1.0))

if used_q >= max_q:
    st.sidebar.error("⚠️ โควตาวันนี้เต็มแล้ว! แนะนำให้เปลี่ยนรุ่นหรือรอพรุ่งนี้ครับ")

st.sidebar.divider()
selected_date = st.sidebar.date_input("เลือกวันที่ขาย:", datetime.date.today())
formatted_selected_date = selected_date.strftime("%d/%m/%Y")

# === 2. โหลด Master Data ===
@st.cache_data
def load_master():
    try:
        with open('item_master.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}
item_master = load_master()

# === 3. ส่วนประมวลผลข้อมูล ===
COL_TOTAL = "ยอด (฿)"

def process_row_data(raw_date, raw_code, raw_name, raw_qty, raw_amount, source_file):
    def clean(v):
        if pd.isna(v) or v == "": return 0
        try: return float(str(v).replace(",", ""))
        except: return 0
    
    qty, amount = clean(raw_qty), clean(raw_amount)
    if qty == 0 and amount == 0: return None
    
    code = str(raw_code).strip().upper().replace("FMFCO", "FMFC0").replace("FMC0", "FMFC0")
    name, branch = str(raw_name).strip(), "ไม่ระบุสาขา"
    
    for k, v in item_master.items():
        if "|" in k:
            b, c = k.split("|", 1)
            if c == code:
                name, branch = v, b
                break
    
    return {
        "วันที่": str(raw_date) if raw_date else formatted_selected_date,
        "สาขา": branch, "รหัสสินค้า": code, "ชื่อเมนู": name,
        "ราคา (฿)": round(amount/qty, 2) if qty > 0 else 0,
        "จำนวน (จาน)": int(qty), COL_TOTAL: amount, "แหล่งที่มา": source_file
    }

# === 4. หน้าจอหลัก ===
st.info(f"🚀 Engine: **{model_choice}** | 📅 วันที่: **{formatted_selected_date}**")
uploaded_files = st.file_uploader("อัปโหลดไฟล์สลิปหรือ CSV", type=['jpg', 'jpeg', 'png', 'csv'], accept_multiple_files=True)

if st.button("🚀 ประมวลผลข้อมูล", type="primary", use_container_width=True):
    if not api_key:
        st.error("🚨 กรุณากรอก API Key")
    elif used_q >= max_q:
        st.error(f"🚨 ไม่สามารถทำงานได้เนื่องจากโควตา {model_choice} ของคุณเต็มแล้ว")
    elif not uploaded_files:
        st.warning("ℹ️ กรุณาอัปโหลดไฟล์")
    else:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_choice)
        
        all_data = []
        progress = st.progress(0)
        status = st.empty()
        
        for i, file in enumerate(uploaded_files):
            ext = file.name.lower().split('.')[-1]
            status.text(f"กำลังจัดการ: {file.name}")
            
            if ext in ['jpg', 'jpeg', 'png']:
                try:
                    img = Image.open(file)
                    prompt = "Extract sales to JSON: [{'Date':'DD/MM/YYYY', 'Item_Code':'str', 'Item_Name':'str', 'Qty':int, 'Amount':float}]"
                    response = model.generate_content([prompt, img])
                    
                    # บันทึกการใช้งานลงไฟล์ทันทีที่ AI ตอบกลับสำเร็จ[cite: 1]
                    update_usage(model_choice)
                    
                    raw_txt = response.text.replace("```json", "").replace("```", "").strip()
                    for item in json.loads(raw_txt):
                        res = process_row_data(item.get("Date"), item.get("Item_Code"), item.get("Item_Name"), item.get("Qty"), item.get("Amount"), file.name)
                        if res: all_data.append(res)
                    time.sleep(4) 
                except Exception as e:
                    st.error(f"❌ {file.name} ล้มเหลว: {e}")
            
            elif ext == 'csv':
                # จัดการ CSV ตามปกติ (ไม่นับโควตา AI)[cite: 1]
                try:
                    df_csv = pd.read_csv(file, encoding='utf-8-sig')
                    for _, r in df_csv.iterrows():
                        res = process_row_data(formatted_selected_date, r.get("รหัสเมนู"), r.get("ชื่อเมนู"), r.get("จำนวน"), r.get("ยอดขาย"), file.name)
                        if res: all_data.append(res)
                except: st.error(f"❌ อ่าน CSV {file.name} ไม่ได้")
            
            progress.progress((i + 1) / len(uploaded_files))

        if all_data:
            st.success(f"✅ ประมวลผลสำเร็จ! พบข้อมูล {len(all_data)} รายการ")
            df_final = pd.DataFrame(all_data)
            st.dataframe(df_final, use_container_width=True)
            
            # กราฟสรุปยอดขาย (ป้องกัน Error ชื่อคอลัมน์)[cite: 1]
            if COL_TOTAL in df_final.columns:
                st.bar_chart(df_final.groupby("สาขา")[COL_TOTAL].sum())
            
            st.download_button("📥 ดาวน์โหลดรายงาน", df_final.to_csv(index=False).encode('utf-8-sig'), f"Summary_{formatted_selected_date}.csv")
            
            # สั่งรีเฟรชเพื่อให้ตัวนับใน Sidebar อัปเดตล่าสุด
            st.rerun()