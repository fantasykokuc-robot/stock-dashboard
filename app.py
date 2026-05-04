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

# ==================== 🛠️ 幕僚介面設定 ====================
st.set_page_config(page_title="TACTICAL COMMAND", page_icon="🛡️", layout="wide")
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background-color: #1E1E1E; border-left: 4px solid #2ecc71; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
    .buy-point { background-color: #2C1E1E; border-left: 4px solid #E74C3C; }
    </style>
""", unsafe_allow_html=True)

# ==================== 🛡️ 雙 LINE 通知加密設定 ====================
# 如果部署在 Streamlit Cloud，請在 Secrets 設定中加入 LINE_TOKEN_1 與 LINE_TOKEN_2
# 本機執行時若 Secrets 不存在，會自動使用下方預留的權杖
def get_tokens():
    try:
        return [st.secrets["LINE_TOKEN_1"], st.secrets["LINE_TOKEN_2"]]
    except:
        return [
            "HqZt6RC/T2qCZfubMb97OQ7XLgGfUwFNxFlfHl4a/cTMbYhKGkTg/HYcWsBko/ajE7tFjERHMv000AOP3M5BvTw/tShz7Z6SDSOX+Y+GjX0o7nfmNFBAA+Bbmcy0tYm8ENlxUmOfZ13D/6XcwBZyJwdB04t89/1O/w1cDnyilFU=",
            "Hc2Vkkxd7CrZ1NItS7w3FZjG9WaRnXeE5gH5S0CYLqUolXvYbDCx47kWGYC6398IL2oIA7z3rf4k37Qvzct9gs4qGOVSrrxgb8be8zWDaOL9+/HcyiZ9WsFNK0WWCgX86FBclkVyFwX+MMOY0SRH4QdB04t89/1O/w1cDnyilFU="
        ]

LINE_TOKENS = get_tokens()

def broadcast_line(message):
    url = "https://notify-api.line.me/api/notify"
    for token in LINE_TOKENS:
        headers = {"Authorization": f"Bearer {token}"}
        try: requests.post(url, headers=headers, data={"message": message}, timeout=10)
        except: pass

# ==================== 💾 資料緩存管理[cite: 4] ====================
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

# ==================== 🧠 核心分析引擎 ====================
@st.cache_data(ttl=300)
def fetch_data(code):
    try: return yf.Ticker(f"{code}.TW").history(period="6mo")
    except: return pd.DataFrame()

def analyze_stock(code, source="系統"):
    df = fetch_data(code)
    if df.empty or len(df) < 60: return None
    
    c, vol = df['Close'].iloc[-1], df['Volume'].iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    vol_ma10 = df['Volume'].tail(10).mean()
    high_10 = df['Close'].iloc[-11:-1].max()
    
    is_buy_point = (c > high_10 and vol > (vol_ma10 * 2) and (c - ma20)/ma20 < 0.15)
    
    if is_buy_point:
        today = datetime.date.today().isoformat()
        if st.session_state.notified_today.get(code) != today:
            broadcast_line(f"\n🎯 【{source}】發現買點！\n標的：{get_name(code)}\n現價：{round(c, 2)}\n戰術：🔥 安全放量突破")
            st.session_state.notified_today[code] = today
            
    return {"名稱": get_name(code), "現價": round(c, 2), "強烈買訊": is_buy_point, "raw_df": df}

# ==================== 📱 側邊欄[cite: 9] ====================
with st.sidebar:
    st.title("⚙️ 戰術監控管理")
    new_code = st.text_input("➕ 新增代碼")
    if st.button("加入清單") and new_code:
        st.session_state.watchlist.append(new_code)
        with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
        st.rerun()
    selected_code = st.radio("📈 K 線選擇", st.session_state.watchlist, format_func=get_name)
    st.divider()
    auto_monitor = st.toggle("🚀 5 分鐘循環監控", value=True)

# ==================== 🎯 四頁籤系統[cite: 9] ====================
tab1, tab2, tab3, tab4 = st.tabs(["🌅 自選戰情", "🏦 ETF 防禦", "🏆 市場掃描", "🕵️ 籌碼戰術板"])

with tab1: # 自選卡片與圖表
    cols = st.columns(3)
    for idx, code in enumerate(st.session_state.watchlist):
        res = analyze_stock(code, source="自選監控")
        if res:
            with cols[idx % 3]:
                card_style = "buy-point" if res["強烈買訊"] else ""
                st.markdown(f"<div class='metric-card {card_style}'><b>{res['名稱']}</b><br>現價: {res['現價']}</div>", unsafe_allow_html=True)
    if selected_code:
        st.divider()
        res_data = analyze_stock(selected_code)
        if res_data:
            df = res_data['raw_df']
            fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
            fig.update_layout(template='plotly_dark', height=450, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

with tab2: # ETF 防禦表
    ETF_LIST = ["0050", "0056", "00878", "00713", "00919"]
    etf_data = []
    for code in ETF_LIST:
        df = fetch_data(code)
        if not df.empty:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            etf_data.append({"標的": get_name(code), "現價": round(c,2), "位階": "🟢 季線上" if c >= ma60 else "🔴 季線下"})
    st.dataframe(pd.DataFrame(etf_data), use_container_width=True)

with tab3: # 全市場掃描
    if st.button("手動執行全市場買點掃描"):
        for code in list(STOCK_DICT.keys()):
            analyze_stock(code, source="全市場掃描")
            time.sleep(0.05)
        st.success("完成！若有符合買點已發送 LINE。")

with tab4: # 🕵️ 籌碼戰術板補回[cite: 9]
    st.subheader("🕵️ 盤後三大法人同買追蹤")
    if st.button("🔄 獲取證交所最新籌碼數據"):
        try:
            url = "https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999"
            data = requests.get(url, timeout=10).json()
            if data['stat'] == 'OK':
                df_chip = pd.DataFrame(data['data'], columns=data['fields'])
                df_chip = df_chip[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
                df_chip.columns = ['代碼', '名稱', '外資', '投信']
                for col in ['外資', '投信']: df_chip[col] = pd.to_numeric(df_chip[col].str.replace(',', ''), errors='coerce').fillna(0)
                # 過濾雙向買超標的[cite: 9]
                bull = df_chip[(df_chip['外資'] > 0) & (df_chip['投信'] > 0)].sort_values(by='外資', ascending=False)
                st.dataframe(bull.head(30), hide_index=True)
            else: st.warning("今日數據尚未更新。")
        except: st.error("連線超時。")

# ==================== 🔄 自動重整[cite: 11] ====================
if auto_monitor:
    now = datetime.datetime.now()
    wait = 300 if (9 <= now.hour < 13 or (now.hour == 13 and now.minute <= 35)) else 1800
    time.sleep(wait)
    st.rerun()