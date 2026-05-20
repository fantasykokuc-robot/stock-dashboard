import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time

# ==================== 🛠️ 1. 介面樣式與基礎設定 ====================
st.set_page_config(page_title="TACTICAL COMMAND", page_icon="🛡️", layout="wide")
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background-color: #1E1E1E; border-left: 4px solid #2ecc71; border-radius: 8px; padding: 15px; margin-bottom: 10px; min-height: 115px; }
    .buy-point { background-color: #2C1E1E; border-left: 4px solid #E74C3C; }
    .status-label { color: #FFA500; font-size: 0.9rem; font-weight: bold; margin-top: 5px; }
    </style>
""", unsafe_allow_html=True)

# ==================== 💾 2. 資料庫自檢 (確保中文讀取) ====================
@st.cache_data(ttl=3600)
def load_stock_dict():
    """讀取台股代碼表並確保編碼正確[cite: 9]"""
    if os.path.exists('twse_listed_codes.csv'):
        try:
            df = pd.read_csv('twse_listed_codes.csv', encoding='utf-8-sig', header=None)
            return dict(zip(df.iloc[:,0].astype(str).str.strip(), df.iloc[:,1].astype(str).str.strip()))
        except: return {}
    return {}

STOCK_DICT = load_stock_dict()

def get_full_name(code):
    """回傳「代碼 中文名稱」[cite: 9]"""
    name = STOCK_DICT.get(str(code), "")
    return f"{code} {name}".strip()

# ==================== 🛡️ 3. 雙 LINE 通知核心[cite: 12] ====================
def broadcast_line(message):
    tokens = [
        "HqZt6RC/T2qCZfubMb97OQ7XLgGfUwFNxFlfHl4a/cTMbYhKGkTg/HYcWsBko/ajE7tFjERHMv000AOP3M5BvTw/tShz7Z6SDSOX+Y+GjX0o7nfmNFBAA+Bbmcy0tYm8ENlxUmOfZ13D/6XcwBZyJwdB04t89/1O/w1cDnyilFU=",
        "Hc2Vkkxd7CrZ1NItS7w3FZjG9WaRnXeE5gH5S0CYLqUolXvYbDCx47kWGYC6398IL2oIA7z3rf4k37Qvzct9gs4qGOVSrrxgb8be8zWDaOL9+/HcyiZ9WsFNK0WWCgX86FBclkVyFwX+MMOY0SRH4QdB04t89/1O/w1cDnyilFU="
    ]
    for token in tokens:
        try: requests.post("https://notify-api.line.me/api/notify", headers={"Authorization": f"Bearer {token}"}, data={"message": message}, timeout=10)
        except: pass

# ==================== 🧠 4. 分析引擎自檢[cite: 9] ====================
@st.cache_data(ttl=300)
def fetch_data(code):
    try: return yf.Ticker(f"{code}.TW").history(period="6mo")
    except: return pd.DataFrame()

def analyze_stock(code, source="系統"):
    df = fetch_data(code)
    if df.empty or len(df) < 60: return None
    
    # 計算指標[cite: 9]
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    high_10 = round(df['Close'].iloc[-11:-1].max(), 2)
    
    c, vol = df['Close'].iloc[-1], df['Volume'].iloc[-1]
    vol_ma10 = df['Volume'].tail(10).mean()
    is_buy = (c > high_10 and vol > (vol_ma10 * 2) and c > df['MA5'].iloc[-1])
    
    if is_buy:
        today = datetime.date.today().isoformat()
        if st.session_state.get('notified', {}).get(code) != today:
            broadcast_line(f"\n🎯 【{source}】買點通報\n標的：{get_full_name(code)}\n現價：{round(c, 2)}\n戰術：🔥 安全放量突破")
            if 'notified' not in st.session_state: st.session_state.notified = {}
            st.session_state.notified[code] = today
            
    return {
        "全名": get_full_name(code), 
        "現價": round(c, 2), 
        "狀態": "🔥 安全放量突破" if is_buy else "⌛ 量縮整理中", 
        "強烈買訊": is_buy, 
        "raw_df": df, 
        "壓力線": high_10
    }

# ==================== 💾 5. 資料管理[cite: 4, 8] ====================
WATCHLIST_FILE = 'watchlist.json'
if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r') as f: st.session_state.watchlist = json.load(f)
    else: st.session_state.watchlist = ["2330", "2317", "2603", "3231", "2454"]

with st.sidebar:
    st.title("⚙️ 戰術監控管理")
    new_code = st.text_input("➕ 新增代碼")
    if st.button("加入清單") and new_code:
        st.session_state.watchlist.append(new_code)
        with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
        st.rerun()
    selected_code = st.radio("📈 K 線選擇", st.session_state.watchlist, format_func=get_full_name)
    auto_monitor = st.toggle("🚀 啟動 5 分鐘循環監控", value=True)

# ==================== 🎯 6. 主畫面分頁系統[cite: 9] ====================
tab1, tab2, tab3, tab4 = st.tabs(["🌅 自選戰情", "🏦 ETF 防禦", "🏆 市場掃描", "🕵️ 籌碼戰術"])

with tab1: # 自選戰情室
    cols = st.columns(3)
    for idx, code in enumerate(st.session_state.watchlist):
        res = analyze_stock(code, source="自選監控")
        if res:
            with cols[idx % 3]:
                card_style = "buy-point" if res["強烈買訊"] else ""
                st.markdown(f"<div class='metric-card {card_style}'><b>{res['全名']}</b><br>價：{res['現價']}<div class='status-label'>{res['狀態']}</div></div>", unsafe_allow_html=True)
    
    if selected_code:
        st.divider()
        res_data = analyze_stock(selected_code)
        if res_data:
            df = res_data['raw_df']
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='yellow'), name='5MA'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='green'), name='20MA'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='magenta'), name='60MA'))
            fig.add_hline(y=res_data['壓力線'], line_dash="dash", line_color="red", annotation_text=f" 壓力: {res_data['壓力線']}")
            fig.update_layout(title=f"📊 {res_data['全名']} 戰術解析", template='plotly_dark', height=500, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

with tab2: # ETF 防禦
    st.subheader("🏦 核心 ETF 位階監控")
    etf_list = ["0050", "0056", "00878", "00713", "00919"]
    etf_data = []
    for code in etf_list:
        df = fetch_data(code)
        if not df.empty:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            etf_data.append({"標的": get_full_name(code), "現價": round(c, 2), "狀態": "🟢 季線上" if c >= ma60 else "🔴 季線下"})
    st.table(pd.DataFrame(etf_data))

with tab3: # 🏆 市場掃描 (補回功能)[cite: 9]
    st.subheader("🏆 全市場買點即時掃描")
    if st.button("🚀 啟動全市場掃描 (預計 1~2 分鐘)"):
        all_codes = list(STOCK_DICT.keys())
        progress_bar = st.progress(0)
        status_text = st.empty()
        found_list = []
        for i, code in enumerate(all_codes):
            status_text.text(f"正在掃描: {get_full_name(code)}")
            res = analyze_stock(code, source="全市場掃描")
            if res and res["強烈買訊"]:
                found_list.append({"代碼": code, "名稱": res["全名"], "現價": res["現價"]})
            progress_bar.progress((i + 1) / len(all_codes))
        st.success(f"掃描完成！共發現 {len(found_list)} 檔符合戰術標的。")
        if found_list: st.dataframe(pd.DataFrame(found_list), use_container_width=True)

with tab4: # 籌碼戰術[cite: 9]
    if st.button("🔄 獲取盤後法人籌碼"):
        try:
            res = requests.get("https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999", timeout=10).json()
            df_chip = pd.DataFrame(res['data'], columns=res['fields'])[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
            df_chip.columns = ['代碼', '名稱', '外資', '投信']
            for col in ['外資', '投信']: df_chip[col] = pd.to_numeric(df_chip[col].str.replace(',', ''), errors='coerce').fillna(0)
            st.dataframe(df_chip[(df_chip['外資'] > 0) & (df_chip['投信'] > 0)].sort_values(by='外資', ascending=False).head(20), use_container_width=True, hide_index=True)
        except: st.error("證交所數據載入失敗。")

# ==================== 🔄 7. 監控循環[cite: 11] ====================
if auto_monitor:
    now = datetime.datetime.now()
    wait = 300 if (9 <= now.hour < 14) else 1800
    time.sleep(wait)
    st.rerun()