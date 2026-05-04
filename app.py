import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time
import random

# ==================== 🛠️ 幕僚介面優化 ====================
st.set_page_config(page_title="TACTICAL COMMAND", page_icon="🛡️", layout="wide")
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background-color: #1E1E1E; border-left: 4px solid #2ecc71; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
    .buy-point { background-color: #2C1E1E; border-left: 4px solid #E74C3C; }
    </style>
""", unsafe_allow_html=True)

# ==================== 🛡️ 雙 LINE 通知設定[cite: 12] ====================
LINE_TOKENS = [
    "HqZt6RC/T2qCZfubMb97OQ7XLgGfUwFNxFlfHl4a/cTMbYhKGkTg/HYcWsBko/ajE7tFjERHMv000AOP3M5BvTw/tShz7Z6SDSOX+Y+GjX0o7nfmNFBAA+Bbmcy0tYm8ENlxUmOfZ13D/6XcwBZyJwdB04t89/1O/w1cDnyilFU=",
    "Hc2Vkkxd7CrZ1NItS7w3FZjG9WaRnXeE5gH5S0CYLqUolXvYbDCx47kWGYC6398IL2oIA7z3rf4k37Qvzct9gs4qGOVSrrxgb8be8zWDaOL9+/HcyiZ9WsFNK0WWCgX86FBclkVyFwX+MMOY0SRH4QdB04t89/1O/w1cDnyilFU="
]

def broadcast_line(message):
    url = "https://notify-api.line.me/api/notify"
    for token in LINE_TOKENS:
        headers = {"Authorization": f"Bearer {token}"}
        try: requests.post(url, headers=headers, data={"message": message}, timeout=10)
        except: pass

# ==================== 💾 資料緩存與管理[cite: 4] ====================
@st.cache_data(ttl=3600)
def load_stock_dict():
    if os.path.exists('twse_listed_codes.csv'):
        df = pd.read_csv('twse_listed_codes.csv', encoding='utf-8-sig', header=None)
        return dict(zip(df.iloc[:,0].astype(str).str.strip(), df.iloc[:,1].astype(str).str.strip()))
    return {}

STOCK_DICT = load_stock_dict()
def get_name(code): return f"{code} {STOCK_DICT.get(str(code), '')}"

WATCHLIST_FILE = 'watchlist.json'
if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            st.session_state.watchlist = json.load(f)
    else:
        st.session_state.watchlist = ["2330", "2317", "2603", "3231", "2454"]

if 'notified_today' not in st.session_state:
    st.session_state.notified_today = {}

# ==================== 🧠 戰術分析核心 ====================
@st.cache_data(ttl=300) # 優化：5分鐘內重複讀取不重複請求
def fetch_data(code):
    try: return yf.Ticker(f"{code}.TW").history(period="6mo")
    except: return pd.DataFrame()

def analyze_stock(code, source="系統"):
    df = fetch_data(code)
    if df.empty or len(df) < 60: return None
    
    c = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    ma5 = df['Close'].rolling(5).mean().iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    vol_ma10 = df['Volume'].tail(10).mean()
    high_10 = df['Close'].iloc[-11:-1].max()
    bias_20 = (c - ma20) / ma20
    
    tags = []
    is_buy_point = (c > high_10 and vol > (vol_ma10 * 2) and c > ma5 and bias_20 < 0.15)
    
    if is_buy_point:
        tags.append("🔥 安全放量突破")
        # 觸發 LINE 通知[cite: 12]
        today = datetime.date.today().isoformat()
        if st.session_state.notified_today.get(code) != today:
            broadcast_line(f"\n🎯 【{source}】發現買點！\n標的：{get_name(code)}\n現價：{round(c, 2)}\n戰術：🔥 安全放量突破\n時間：{datetime.datetime.now().strftime('%H:%M')}")
            st.session_state.notified_today[code] = today
            
    return {"名稱": get_name(code), "現價": round(c, 2), "強烈買訊": is_buy_point, "raw_df": df}

# ==================== 📱 側邊欄與管理[cite: 9] ====================
with st.sidebar:
    st.title("⚙️ 戰術監控管理")
    new_code = st.text_input("➕ 新增觀察代碼")
    if st.button("加入清單") and new_code:
        if new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
            st.rerun()
    
    selected_code = st.radio("👀 選擇標的觀看 K 線圖", st.session_state.watchlist, format_func=get_name)
    st.divider()
    auto_monitor = st.toggle("🚀 啟動 5 分鐘循環監控", value=True)

# ==================== 🎯 主畫面系統[cite: 9] ====================
tab1, tab2, tab3, tab4 = st.tabs(["🌅 自選戰情室", "🏦 ETF 防禦", "🏆 全市場掃描", "🕵️ 籌碼戰術板"])

with tab1:
    # 顯示自選股卡片
    cols = st.columns(3)
    for idx, code in enumerate(st.session_state.watchlist):
        res = analyze_stock(code, source="自選監控")
        if res:
            with cols[idx % 3]:
                card_class = "buy-point" if res["強烈買訊"] else ""
                st.markdown(f"<div class='metric-card {card_class}'><b>{res['名稱']}</b><br>現價: {res['現價']}</div>", unsafe_allow_html=True)

    # 📈 回歸：K 線圖顯示邏輯[cite: 9]
    if selected_code:
        st.divider()
        st.subheader(f"📊 {get_name(selected_code)} 動態波段解析")
        res_data = analyze_stock(selected_code)
        if res_data and not res_data['raw_df'].empty:
            df = res_data['raw_df']
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'))
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(5).mean(), line=dict(color='yellow'), name='5MA'))
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='green'), name='20MA'))
            fig.update_layout(template='plotly_dark', height=500, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

with tab2: # ETF 防禦
    ETF_DICT = {"0050": "大盤", "0056": "高息", "00878": "高息", "00713": "低波"}
    etf_res = []
    for code, cat in ETF_DICT.items():
        df = fetch_data(code)
        if not df.empty:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            etf_res.append({"分類": cat, "標的": get_name(code), "狀態": "🟢 季線上" if c >= ma60 else "🔴 季線下"})
    st.dataframe(pd.DataFrame(etf_res), use_container_width=True)

with tab3: # 全市場掃描
    if st.button("啟動全市場即時掃描"):
        with st.spinner("幕僚運算中..."):
            for code in list(STOCK_DICT.keys()):
                analyze_stock(code, source="全市場掃描")
                time.sleep(0.05)
        st.success("掃描完畢，如有買點已同步發送 LINE。")

# ==================== 🔄 自動循環監控 ====================
if auto_monitor:
    now = datetime.datetime.now()
    # 交易時段 (09:00-13:35) 每 5 分鐘重整一次網頁[cite: 8]
    wait = 300 if (9 <= now.hour < 13 or (now.hour == 13 and now.minute <= 35)) else 1800
    time.sleep(wait)
    st.rerun()