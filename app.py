import streamlit as st
import pandas as pd
import yfinance as yf
import datetime
import json
import os

# ==================== 🛠️ 幕僚介面設定 (行動端最佳化) ====================
st.set_page_config(page_title="TACTICAL COMMAND", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FAFAFA; font-family: 'Microsoft JhengHei', sans-serif; }
    .mobile-card { background-color: #1E1E1E; border-left: 4px solid #2ecc71; border-radius: 5px; padding: 12px; margin-bottom: 12px; }
    .buy-card { border-left: 4px solid #E74C3C; background-color: #2C1E1E; }
    .mobile-title { color: #2ecc71; font-weight: bold; font-size: 1.2rem; margin-bottom: 8px;}
    </style>
""", unsafe_allow_html=True)

# ==================== 💾 資料庫與清單管理 ====================
@st.cache_data
def load_stock_dict():
    """讀取靜態台股代碼表[cite: 2]"""
    if os.path.exists('twse_listed_codes.csv'):
        try:
            df = pd.read_csv('twse_listed_codes.csv', encoding='utf-8-sig', header=None)
            return dict(zip(df.iloc[:,0].astype(str).str.strip(), df.iloc[:,1].astype(str).str.strip()))
        except:
            return {}
    return {}

STOCK_DICT = load_stock_dict()

def get_name(code):
    return f"{code} {STOCK_DICT.get(str(code), '')}"

WATCHLIST_FILE = 'watchlist.json'

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return ["2330", "2317", "2603", "3231", "2454"]

def save_watchlist(lst):
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(lst, f)

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

ETF_LIST = ["0050", "006208", "0056", "00878", "00919"]

# ==================== 📱 側邊欄：手機快速編輯自選股 ====================
with st.sidebar:
    st.title("⚙️ 戰術清單管理")
    new_code = st.text_input("➕ 新增代碼 (如: 2618)", max_chars=6)
    if st.button("加入清單", use_container_width=True):
        if new_code and new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            save_watchlist(st.session_state.watchlist)
            st.success(f"已新增 {get_name(new_code)}")
            st.rerun()
            
    st.divider()
    remove_code = st.selectbox("🗑️ 移除代碼", ["無"] + st.session_state.watchlist)
    if st.button("確認移除", type="secondary", use_container_width=True) and remove_code != "無":
        st.session_state.watchlist.remove(remove_code)
        save_watchlist(st.session_state.watchlist)
        st.rerun()

# ==================== 🧠 戰術分析引擎 (含防追高優化) ====================
@st.cache_data(ttl=300)
def fetch_data(code):
    try:
        return yf.Ticker(f"{code}.TW").history(period="6mo")
    except:
        return pd.DataFrame()

def analyze_stock(code):
    df = fetch_data(code)
    if df.empty or len(df) < 60: return None
    
    c = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    ma5 = df['Close'].rolling(5).mean().iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    ma60 = df['Close'].rolling(60).mean().iloc[-1]
    vol_ma10 = df['Volume'].tail(10).mean()
    high_10 = df['Close'].iloc[-11:-1].max()
    amp = (df['High'].iloc[-1] - df['Low'].iloc[-1]) / df['Close'].iloc[-2] if len(df) > 1 else 0
    
    # 乖離率計算 (Price to 20MA)
    bias_20 = (c - ma20) / ma20
    
    tags = []
    is_buy_point = False
    
    # 優化邏輯：放量突破，且乖離月線不超過 15% (防追高)
    if c > high_10 and vol > (vol_ma10 * 2) and c > ma5 and bias_20 < 0.15:
        tags.append("🔥 安全放量突破 (起漲點)")
        is_buy_point = True
    elif amp > 0.04 and vol > (vol_ma10 * 1.5) and c > ma5:
        tags.append("⚡ 短線高振幅動能")
    if c > ma20 > ma60:
        tags.append("🛡️ 中線多頭")
        
    return {
        "名稱": get_name(code), "現價": round(c, 2), 
        "訊號": ", ".join(tags) if tags else "量縮整理中", "強烈買訊": is_buy_point
    }

# ==================== 📱 戰術司令部主介面 ====================
st.title("📱 戰術司令部")
st.caption(f"📅 系統日期: {datetime.datetime.now().strftime('%Y-%m-%d')} | 點擊左上角 ＞ 可編輯清單")

tab_pre, tab_etf = st.tabs(["🌅 動態戰術掃描", "🏦 兆豐 ETF 防禦"])

with tab_pre:
    st.markdown("<div class='mobile-title'>盤前/盤中 突圍監控</div>", unsafe_allow_html=True)
    for code in st.session_state.watchlist:
        res = analyze_stock(code)
        if res:
            if res["強烈買訊"]:
                st.markdown(f"<div class='mobile-card buy-card'><b>🎯 {res['名稱']}</b> | 現價: {res['現價']}<br>戰術：{res['訊號']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='mobile-card'><b>📊 {res['名稱']}</b> | 現價: {res['現價']}<br>狀態：{res['訊號']}</div>", unsafe_allow_html=True)

with tab_etf:
    st.markdown("<div class='mobile-title'>台灣 ETF 位階區</div>", unsafe_allow_html=True)
    etf_res = []
    for code in ETF_LIST:
        df = fetch_data(code)
        if not df.empty:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            status = "🟢 季線上 (可定期定額)" if c >= ma60 else "🔴 跌破季線 (黃金低接)"
            etf_res.append({"代碼": get_name(code), "現價": round(c,2), "季線": round(ma60,2), "狀態": status})
    if etf_res:
        st.dataframe(pd.DataFrame(etf_res), use_container_width=True, hide_index=True)