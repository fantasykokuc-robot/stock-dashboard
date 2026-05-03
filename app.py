import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time

# ==================== 🛠️ 幕僚介面設定 ====================
st.set_page_config(page_title="TACTICAL COMMAND", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background-color: #1E1E1E; border-left: 4px solid #2ecc71; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
    .buy-point { background-color: #2C1E1E; border-left: 4px solid #E74C3C; }
    .strategy-title { color: #2ecc71; font-weight: bold; font-size: 1.1rem; margin-bottom: 10px;}
    </style>
""", unsafe_allow_html=True)

# ==================== 💾 資料庫與清單管理 ====================
@st.cache_data
def load_stock_dict():
    """讀取靜態台股代碼表，供 PC 端全市場掃描與名稱對照使用"""
    if os.path.exists('twse_listed_codes.csv'):
        try:
            df = pd.read_csv('twse_listed_codes.csv', encoding='utf-8-sig', header=None)
            return dict(zip(df.iloc[:,0].astype(str).str.strip(), df.iloc[:,1].astype(str).str.strip()))
        except: return {}
    return {}

STOCK_DICT = load_stock_dict()

def get_name(code):
    return f"{code} {STOCK_DICT.get(str(code), '')}"

WATCHLIST_FILE = 'watchlist.json'

def save_watchlist():
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(st.session_state.watchlist, f)

if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            st.session_state.watchlist = json.load(f)
    else:
        st.session_state.watchlist = ["2330", "2317", "2603", "3231", "2454"]

ETF_LIST = ["0050", "006208", "0056", "00878", "00919"]

# ==================== 📱 側邊欄：動態清單與圖表選擇 ====================
with st.sidebar:
    st.title("⚙️ 戰術監控管理")
    
    new_code = st.text_input("➕ 新增觀察代碼 (如: 2618)", max_chars=6)
    if st.button("加入清單", use_container_width=True):
        if new_code and new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            save_watchlist()
            st.success(f"已新增 {get_name(new_code)}")
            st.rerun()
            
    st.divider()
    remove_code = st.selectbox("🗑️ 移除代碼", ["無"] + st.session_state.watchlist)
    if st.button("確認移除", type="secondary", use_container_width=True) and remove_code != "無":
        st.session_state.watchlist.remove(remove_code)
        save_watchlist()
        st.rerun()
        
    st.divider()
    st.write("👀 選擇標的觀看波段解析 (顯示於戰情室)")
    selected_code = st.radio("自選股圖表選擇", st.session_state.watchlist, format_func=get_name)

# ==================== 🧠 戰術分析核心引擎 ====================
@st.cache_data(ttl=300)
def fetch_data(code):
    try:
        return yf.Ticker(f"{code}.TW").history(period="6mo")
    except: return pd.DataFrame()

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
    bias_20 = (c - ma20) / ma20
    
    tags = []
    is_buy_point = False
    
    # 幕僚優化：防追高濾網 (過濾掉乖離過大的末升段)
    if c > high_10 and vol > (vol_ma10 * 2) and c > ma5 and bias_20 < 0.15:
        tags.append("🔥 安全放量突破 (起漲點)")
        is_buy_point = True
    elif amp > 0.04 and vol > (vol_ma10 * 1.5) and c > ma5:
        tags.append("⚡ 短線高振幅動能")
    if c > ma20 > ma60:
        tags.append("🛡️ 中線多頭")
        
    return {
        "代碼": code, "名稱": get_name(code), "現價": round(c, 2), 
        "訊號": ", ".join(tags) if tags else "量縮整理中", "強烈買訊": is_buy_point,
        "raw_df": df # 供圖表繪製使用
    }

# ==================== 🎯 主畫面：雙引擎模組 ====================
st.title("⚡ TACTICAL COMMAND CENTER")
st.caption(f"📅 系統更新時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

tab1, tab2, tab3, tab4 = st.tabs(["🌅 1. 自選戰情室 (手機/PC)", "🏦 2. 兆豐 ETF 防禦", "🏆 3. 全市場掃描 (PC專用)", "🕵️ 4. 籌碼戰術板 (PC專用)"])

# ----------------- 頁籤 1：自選戰情室 (結合清單與圖表) -----------------
with tab1:
    st.markdown("#### 盤前/盤中 突圍監控清單")
    
    # 採用多欄位排列提升空間利用率
    cols = st.columns(3)
    for idx, code in enumerate(st.session_state.watchlist):
        res = analyze_stock(code)
        if res:
            with cols[idx % 3]:
                if res["強烈買訊"]:
                    st.markdown(f"<div class='metric-card buy-point'><b>🎯 {res['名稱']}</b> | 現價: {res['現價']}<br>戰術：{res['訊號']}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='metric-card'><b>📊 {res['名稱']}</b> | 現價: {res['現價']}<br>狀態：{res['訊號']}</div>", unsafe_allow_html=True)
    
    st.divider()
    
    # 找回遺失的 Plotly 動態 K 線圖功能
    if selected_code:
        st.markdown(f"#### 📉 {get_name(selected_code)} 動態波段解析")
        res_data = analyze_stock(selected_code)
        if res_data and not res_data['raw_df'].empty:
            df = res_data['raw_df']
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'))
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(5).mean(), line=dict(color='yellow', width=1), name='5MA(週線)'))
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='green', width=1), name='20MA(月線)'))
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(60).mean(), line=dict(color='magenta', width=1), name='60MA(季線)'))
            
            fig.update_layout(template='plotly_dark', margin=dict(l=0, r=0, t=10, b=0), height=450, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

# ----------------- 頁籤 2：兆豐 ETF 防禦 -----------------
with tab2:
    st.markdown("#### 台灣 ETF 位階區 (兆豐證券操作建議)")
    etf_res = []
    for code in ETF_LIST:
        df = fetch_data(code)
        if not df.empty:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            status = "🟢 季線上 (可定期定額)" if c >= ma60 else "🔴 跌破季線 (伺機單筆低接)"
            etf_res.append({"代碼": get_name(code), "現價": round(c,2), "季線": round(ma60,2), "狀態": status})
    if etf_res:
        st.dataframe(pd.DataFrame(etf_res), use_container_width=True, hide_index=True)

# ----------------- 頁籤 3：全市場真實掃描 (PC專用) -----------------
with tab3:
    st.markdown("#### 🏆 執行全市場策略掃描")
    st.warning("⚠️ 此功能將向主機發出逾千次請求，建議僅於網路穩定的 PC 端執行。")
    if st.button("啟動全市場真實運算", use_container_width=True, type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        real_scan_results = []
        codes_to_scan = list(STOCK_DICT.keys())
        total_codes = len(codes_to_scan)
        
        for i, code in enumerate(codes_to_scan):
            status_text.text(f"幕僚運算中: {code} ({i+1}/{total_codes})")
            res = analyze_stock(code)
            # 僅保留具備明確戰術訊號的標的
            if res and ("🔥" in res['訊號'] or "⚡" in res['訊號']):
                real_scan_results.append({
                    "代碼": res['代碼'],
                    "名稱": res['名稱'],
                    "現價": res['現價'],
                    "觸發戰術": res['訊號']
                })
                
            if i % 30 == 0: time.sleep(0.5) 
            progress_bar.progress((i + 1) / total_codes)
            
        status_text.text("✅ 全市場掃描完畢！")
        if real_scan_results:
            st.dataframe(pd.DataFrame(real_scan_results), use_container_width=True, hide_index=True)
        else:
            st.info("今日全市場無符合嚴格條件之標的。")

# ----------------- 頁籤 4：籌碼戰術板 (PC專用) -----------------
with tab4:
    st.markdown("#### 🕵️ 台灣證券交易所：盤後籌碼追蹤")
    if st.button("🔄 獲取盤後三大法人同買清單", use_container_width=True, type="primary"):
        with st.spinner("正與 TWSE 證交所主機連線中..."):
            url = "https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999"
            try:
                res = requests.get(url, timeout=10).json()
                if res['stat'] == 'OK':
                    df = pd.DataFrame(res['data'], columns=res['fields'])
                    df = df[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
                    df.columns = ['代碼', '名稱', '外資買賣超', '投信買賣超']
                    df['外資買賣超'] = pd.to_numeric(df['外資買賣超'].str.replace(',', ''), errors='coerce').fillna(0)
                    df['投信買賣超'] = pd.to_numeric(df['投信買賣超'].str.replace(',', ''), errors='coerce').fillna(0)
                    
                    bull_df = df[(df['外資買賣超'] > 0) & (df['投信買賣超'] > 0)].sort_values(by='外資買賣超', ascending=False)
                    bull_df['外資買超(張)'] = (bull_df['外資買賣超'] / 1000).astype(int)
                    bull_df['投信買超(張)'] = (bull_df['投信買賣超'] / 1000).astype(int)
                    
                    st.success("✅ 籌碼獲取成功！以下為外資與投信「雙箭頭同買」之強勢股：")
                    st.dataframe(bull_df[['代碼', '名稱', '外資買超(張)', '投信買超(張)']].head(30), use_container_width=True, hide_index=True)
                else:
                    st.error("❌ 證交所尚未更新今日盤後數據。")
            except Exception as e:
                st.error("連線異常，請確認網路狀態。")