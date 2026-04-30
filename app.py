import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import json
import os
from datetime import datetime

# ==================== 🛠️ 頁面與主題設定 ====================
st.set_page_config(
    page_title="TACTICAL COMMAND CENTER",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自訂 CSS 讓風格更貼近您的暗黑戰術板
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    .css-1d391kg { background-color: #1E1E1E; } /* Sidebar background */
    .metric-card {
        background-color: #1E1E1E; border: 1px solid #333;
        border-radius: 8px; padding: 15px; margin-bottom: 15px;
    }
    .strategy-title { color: #2ecc71; font-weight: bold; font-size: 1.1rem; }
    </style>
""", unsafe_allow_html=True)

WATCHLIST_FILE = 'watchlist.json'

# ==================== 💾 狀態管理 (Session State) ====================
if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            st.session_state.watchlist = json.load(f)
    else:
        st.session_state.watchlist = ["2330", "2317", "2454"] # 預設名單

if 'scan_results' not in st.session_state:
    st.session_state.scan_results = {
        "強勢多頭 (Stage 2)": [], "量能異動": [], 
        "營收爆發": [], "買點浮現": []
    }

# ==================== 🧠 核心邏輯引擎 ====================
def save_watchlist():
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(st.session_state.watchlist, f)

@st.cache_data(ttl=300) # 快取 5 分鐘避免重複抓取
def fetch_stock_data(code):
    try:
        tk_obj = yf.Ticker(f"{code}.TW")
        df = tk_obj.history(period="1y")
        info = tk_obj.info
        return df, info
    except:
        return pd.DataFrame(), {}

def depth_analyze(code):
    df, info = fetch_stock_data(code)
    if df.empty or len(df) < 50: return None
    
    c = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    ma5 = df['Close'].rolling(5).mean().iloc[-1]
    ma50 = df['Close'].rolling(50).mean().iloc[-1]
    ma200 = df['Close'].rolling(200).mean().iloc[-1]
    
    triggered = []
    if c > ma50 > ma200: triggered.append("強勢多頭 (Stage 2)")
    if vol > 1500000: triggered.append("量能異動")
    if c > ma5 and vol > df['Volume'].tail(5).mean() * 1.5: triggered.append("買點浮現")
    if info.get('revenueGrowth', 0) > 0.15: triggered.append("營收爆發")
    
    return {'code': code, 'price': c, 'triggered': triggered}

# ==================== 📊 介面佈局 ====================

# --- 側邊欄：自選股管理 ---
with st.sidebar:
    st.title("🛡️ 戰術監控名單")
    
    # 新增標的
    new_code = st.text_input("➕ 新增股票代碼 (例如: 2330)", max_chars=6)
    if st.button("加入監控", use_container_width=True):
        if new_code and new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            save_watchlist()
            st.success(f"已加入 {new_code}")
            st.rerun()

    st.divider()
    
    # 選擇要分析的標的
    st.write("👀 選擇標的觀看波段解析")
    selected_code = st.radio("自選股清單", st.session_state.watchlist)
    
    if st.button("🗑️ 移除選定標的", type="secondary"):
        if selected_code in st.session_state.watchlist:
            st.session_state.watchlist.remove(selected_code)
            save_watchlist()
            st.rerun()

# --- 主畫面：控制列 ---
st.markdown("### ⚡ Minervini 戰術整合系統")
col1, col2, col3, col4 = st.columns(4)

if col1.button("🔍 開始深度掃描自選股", use_container_width=True, type="primary"):
    with st.spinner("系統深度掃描中，請稍候..."):
        # 清空舊結果
        st.session_state.scan_results = {k: [] for k in st.session_state.scan_results}
        progress_bar = st.progress(0)
        
        for i, code in enumerate(st.session_state.watchlist):
            res = depth_analyze(code)
            if res:
                for strat in res['triggered']:
                    st.session_state.scan_results[strat].append(code)
            progress_bar.progress((i + 1) / len(st.session_state.watchlist))
        
        st.success("✅ 掃描完成！")

col2.button("☀️ 盤前推薦 20", use_container_width=True)
col3.button("🏆 Minervini 超級績效", use_container_width=True)
col4.button("🕵️ 籌碼戰術板", use_container_width=True)

# --- 主畫面：策略卡片 ---
st.divider()
st.markdown("#### 🎯 策略觸發戰情板")
strat_cols = st.columns(4)
for idx, (strat_name, codes) in enumerate(st.session_state.scan_results.items()):
    with strat_cols[idx]:
        st.markdown(f"<div class='metric-card'><div class='strategy-title'>{strat_name}</div><br/>" + 
                    ("<br/>".join([f"📈 <b>{c}</b>" for c in codes]) if codes else "<span style='color:#666;'>無符合標的</span>") + 
                    "</div>", unsafe_allow_html=True)

# --- 主畫面：動態 K 線圖與波段解析 ---
st.divider()
if selected_code:
    st.markdown(f"#### 📉 {selected_code} 動態波段解析")
    
    df, info = fetch_stock_data(selected_code)
    if not df.empty:
        # 使用 Plotly 繪製可互動 K 線圖
        fig = go.Figure()
        
        # K線
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'))
        # 均線
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(5).mean(), line=dict(color='yellow', width=1), name='5MA'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='cyan', width=1), name='20MA'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(60).mean(), line=dict(color='magenta', width=1), name='60MA'))
        
        fig.update_layout(
            template='plotly_dark',
            margin=dict(l=0, r=0, t=10, b=0),
            height=450,
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # 畫面分割：左邊圖表，右邊分析文字
        chart_col, text_col = st.columns([3, 1])
        
        with chart_col:
            st.plotly_chart(fig, use_container_width=True)
            
        with text_col:
            c_price = df['Close'].iloc[-1]
            ma60_price = df['Close'].rolling(60).mean().iloc[-1]
            
            st.markdown("##### 📝 系統研判")
            st.write(f"**最新收盤:** {c_price:.2f}")
            st.write(f"**季線位置:** {ma60_price:.2f}")
            st.markdown("---")
            if c_price > ma60_price:
                st.success("📈 **多頭慣性**\n\n股價站穩季線之上，波段維持多頭。回測不破均線皆視為良性洗盤。")
            else:
                st.error("📉 **空頭修正**\n\n股價跌破季線，波段轉弱。上方均線將成為後續反彈的沉重壓力區。")
    else:
        st.warning("⚠️ 無法取得該股票資料")