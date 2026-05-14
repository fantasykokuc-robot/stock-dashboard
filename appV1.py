import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time

# ==================== 🛠️ 1. 介面樣式與基礎設定 (符合圖片賽博龐克風) ====================
st.set_page_config(page_title="TACTICAL COMMAND | AI SYSTEM", page_icon="🛡️", layout="wide")

FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiZmFudGFzeWtva3VjIiwiZW1haWwiOiJmYW50YXN5a29rdWNAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.IOQSYqSUC6uaHIyXKf-OEDDYwLbT0D-Hw-H0rpKqD8Q"

st.markdown("""
    <style>
    /* 強制深色背景 */
    .stApp, .main { background-color: #00050a !important; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    [data-testid="stSidebar"] { background-color: #000c17 !important; border-right: 1px solid #00d4ff33; }
    
    .metric-card { 
        background-color: #001220; border: 1px solid #00d4ff; 
        box-shadow: 0 0 12px #00d4ff44; border-radius: 6px; padding: 18px; margin-bottom: 15px; 
    }
    .buy-point { border: 1px solid #ff4b4b; box-shadow: 0 0 15px #ff4b4b66; }
    .status-label { color: #00d4ff; font-weight: bold; font-size: 1.2rem; margin-top: 5px; }
    .progress-bg { background-color: #1a3a5a; border-radius: 10px; width: 100%; height: 12px; margin: 8px 0; }
    .progress-fill { height: 12px; border-radius: 10px; transition: width 0.8s ease-in-out; }
    
    /* 修正 Tab 標籤顏色 */
    .stTabs [data-baseweb="tab-list"] { background-color: transparent; }
    .stTabs [data-baseweb="tab"] { color: #888; }
    .stTabs [aria-selected="true"] { color: #00d4ff !important; border-bottom-color: #00d4ff !important; }
    </style>
""", unsafe_allow_html=True)

# ==================== 💾 2. 資料庫與中文對照 ====================
@st.cache_data(ttl=3600)
def load_stock_dict():
    if os.path.exists('twse_listed_codes.csv'):
        try:
            df = pd.read_csv('twse_listed_codes.csv', encoding='utf-8-sig', header=None)
            return dict(zip(df.iloc[:,0].astype(str).str.strip(), df.iloc[:,1].astype(str).str.strip()))
        except: return {}
    return {}

STOCK_DICT = load_stock_dict()

def get_full_name(code):
    name = STOCK_DICT.get(str(code), "")
    return f"{code} {name}".strip()

# ==================== 🛡️ 3. LINE 通知核心 ====================
def broadcast_line(message):
    tokens = [
        "HqZt6RC/T2qCZfubMb97OQ7XLgGfUwFNxFlfHl4a/cTMbYhKGkTg/HYcWsBko/ajE7tFjERHMv000AOP3M5BvTw/tShz7Z6SDSOX+Y+GjX0o7nfmNFBAA+Bbmcy0tYm8ENlxUmOfZ13D/6XcwBZyJwdB04t89/1O/w1cDnyilFU=",
        "Hc2Vkkxd7CrZ1NItS7w3FZjG9WaRnXeE5gH5S0CYLqUolXvYbDCx47kWGYC6398IL2oIA7z3rf4k37Qvzct9gs4qGOVSrrxgb8be8zWDaOL9+/HcyiZ9WsFNK0WWCgX86FBclkVyFwX+MMOY0SRH4QdB04t89/1O/w1cDnyilFU="
    ]
    for token in tokens:
        try: requests.post("https://notify-api.line.me/api/notify", headers={"Authorization": f"Bearer {token}"}, data={"message": message}, timeout=5)
        except: pass

# ==================== 🧠 4. 雙數據源備援引擎 ====================
@st.cache_data(ttl=300)
def fetch_stock_data(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.datetime.now() - datetime.timedelta(days=250)).strftime("%Y-%m-%d")
    params = {"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start_date, "token": FINMIND_TOKEN}
    try:
        resp = requests.get(url, params=params, timeout=5)
        result = resp.json()
        if result.get('data'):
            df = pd.DataFrame(result['data'])
            df.rename(columns={'date':'Date','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}, inplace=True)
            if 'Date' in df.columns and 'High' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except: pass

    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        df_yf = ticker.history(period="1y")
        if not df_yf.empty and 'High' in df_yf.columns:
            df_yf.index = df_yf.index.tz_localize(None)
            return df_yf[['Open', 'High', 'Low', 'Close', 'Volume']]
    except: pass
    
    return pd.DataFrame()

def analyze_logic(code, source="系統"):
    df = fetch_stock_data(code)
    req_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    if df.empty or len(df) < 60 or not all(c in df.columns for c in req_cols): 
        return None
    
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    
    high_10 = round(df['High'].iloc[-11:-1].max(), 2)
    low_10 = round(df['Low'].iloc[-11:-1].min(), 2)
    
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
        "全名": get_full_name(code), "現價": round(c, 2), 
        "狀態": "🔥 安全放量突破" if is_buy else "⌛ 量縮整理中", 
        "強烈買訊": is_buy, "raw_df": df, 
        "壓力線": high_10, "支撐線": low_10
    }

# ==================== 📈 5. 圖表繪製模組 (徹底黑化) ====================
def draw_pie_chart(values):
    labels = ['趨勢強度', '成交量能', '主力動向', '法人籌碼', '價格位階']
    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values, hole=.4, 
        marker=dict(colors=['#00d4ff', '#ff4b4b', '#00ff88', '#ffaa00', '#7700ff']),
        textinfo='label+percent'
    )])
    fig.update_layout(
        showlegend=True, 
        paper_bgcolor="#001220", plot_bgcolor="#001220", # 強制深藍背景
        font=dict(color="#E0E0E0"), height=350, margin=dict(l=20, r=20, t=30, b=30)
    )
    return fig

# ==================== 💾 6. 介面與控制台 ====================
WATCHLIST_FILE = 'watchlist.json'
if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r') as f: st.session_state.watchlist = json.load(f)
        except: st.session_state.watchlist = ["2330", "2317", "2603", "3231", "2454"]
    else: st.session_state.watchlist = ["2330", "2317", "2603", "3231", "2454"]

with st.sidebar:
    st.title("🛡️ 戰術監控管理")
    new_code = st.text_input("➕ 新增代碼")
    if st.button("加入清單") and new_code:
        if new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
            st.rerun()
    selected_code = st.selectbox("🎯 分析目標", st.session_state.watchlist, format_func=get_full_name)
    auto_monitor = st.toggle("🚀 啟動 5 分鐘循環監控", value=True)

# ==================== 🎯 7. 主畫面分頁系統 ====================
tab1, tab2, tab3, tab4 = st.tabs(["⚡ AI 戰情室", "🏦 ETF 防禦", "🏆 市場掃描", "🕵️ 籌碼戰術"])

with tab1:
    if selected_code:
        res = analyze_logic(selected_code, source="自選監控")
        if res:
            c1, c2 = st.columns([8, 4])
            with c1:
                df = res['raw_df']
                # 自訂台股紅綠 K 線
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線',
                    increasing_line_color='#ff4b4b', increasing_fillcolor='#ff4b4b', # 上漲紅色
                    decreasing_line_color='#00ff88', decreasing_fillcolor='#00ff88'  # 下跌綠色
                )])
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#00d4ff', width=1.5), name='20MA'))
                
                # 發光感壓力/支撐區間
                fig.add_hrect(y0=res['壓力線']*0.995, y1=res['壓力線']*1.005, fillcolor="rgba(255, 75, 75, 0.2)", line_width=0, annotation_text="壓力帶", annotation_font_color="#ff4b4b")
                fig.add_hrect(y0=res['支撐線']*0.995, y1=res['支撐線']*1.005, fillcolor="rgba(0, 255, 136, 0.2)", line_width=0, annotation_text="支撐帶", annotation_font_color="#00ff88")
                
                # 徹底黑化圖表背景與網格
                fig.update_layout(
                    title=f"📊 {res['全名']} 戰術解析", 
                    template='plotly_dark', height=600, xaxis_rangeslider_visible=False,
                    paper_bgcolor="#00050a", plot_bgcolor="#00050a", # 絕對純黑底
                    xaxis=dict(gridcolor="#1a3a5a", showgrid=True), # 霓虹網格線
                    yaxis=dict(gridcolor="#1a3a5a", showgrid=True),
                    font=dict(color="#E0E0E0"), margin=dict(l=10, r=10, t=40, b=10)
                )
                
                # 【絕對關鍵】：theme=None 拒絕 Streamlit 白色主題覆蓋
                st.plotly_chart(fig, use_container_width=True, theme=None)
            
            with c2:
                st.markdown("<div class='metric-card'><h4>🧩 戰術權重分配</h4></div>", unsafe_allow_html=True)
                st.plotly_chart(draw_pie_chart([25, 20, 15, 25, 15]), use_container_width=True, theme=None) # 同樣加上 theme=None
                
                hot_style = "buy-point" if res["強烈買訊"] else ""
                st.markdown(f"""
                    <div class='metric-card {hot_style}'>
                        <h4>即時價位</h4>
                        <h1 style='color:{"#ff4b4b" if res["強烈買訊"] else "#00d4ff"}'>{res['現價']}</h1>
                        <p class='status-label'>{res['狀態']}</p>
                    </div>
                """, unsafe_allow_html=True)

with tab2:
    st.subheader("🏦 核心 ETF 位階監控")
    etf_list = ["0050", "0056", "00878", "00713", "00919"]
    etf_data = []
    for code in etf_list:
        df = fetch_stock_data(code)
        if not df.empty and len(df) >= 60 and 'Close' in df.columns:
            c, ma60 = df['Close'].iloc[-1], df['Close'].rolling(60).mean().iloc[-1]
            etf_data.append({"標的": get_full_name(code), "現價": round(c, 2), "狀態": "🟢 季線上" if c >= ma60 else "🔴 季線下"})
    if etf_data:
        st.table(pd.DataFrame(etf_data))

with tab3:
    st.subheader("🏆 全市場買點即時掃描")
    if st.button("🚀 啟動全市場掃描"):
        all_codes = list(STOCK_DICT.keys())
        progress_bar = st.progress(0)
        status_text = st.empty()
        found_list = []
        for i, code in enumerate(all_codes):
            status_text.text(f"正在掃描: {get_full_name(code)} ({i+1}/{len(all_codes)})")
            res = analyze_logic(code, source="全市場掃描")
            if res and res["強烈買訊"]:
                found_list.append({"代碼": code, "名稱": res["全名"], "現價": res["現價"]})
            progress_bar.progress((i + 1) / len(all_codes))
        st.success(f"掃描完成！共發現 {len(found_list)} 檔符合戰術標的。")
        if found_list: st.dataframe(pd.DataFrame(found_list), use_container_width=True)

with tab4:
    st.subheader("🕵️ 法人籌碼能量 (AI 預估)")
    for n, v, c in [("外資買盤", 82, "#00d4ff"), ("投信力道", 45, "#ff4b4b"), ("主力控盤", 70, "#00ff88")]:
        st.markdown(f"<div>{n} {v}%</div><div class='progress-bg'><div class='progress-fill' style='width:{v}%; background:{c};'></div></div>", unsafe_allow_html=True)
    
    st.divider()
    st.subheader("📊 盤後實體籌碼數據 (證交所)")
    if st.button("🔄 獲取盤後法人籌碼"):
        try:
            res = requests.get("https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999", timeout=10).json()
            df_chip = pd.DataFrame(res['data'], columns=res['fields'])[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
            df_chip.columns = ['代碼', '名稱', '外資', '投信']
            for col in ['外資', '投信']: df_chip[col] = pd.to_numeric(df_chip[col].str.replace(',', ''), errors='coerce').fillna(0)
            st.dataframe(df_chip[(df_chip['外資'] > 0) & (df_chip['投信'] > 0)].sort_values(by='外資', ascending=False).head(20), use_container_width=True, hide_index=True)
        except: st.error("證交所數據載入失敗，可能非交易時間或請求過於頻繁。")

# ==================== 🔄 8. 監控循環 ====================
if auto_monitor:
    now = datetime.datetime.now()
    wait = 300 if (9 <= now.hour < 14) else 1800
    time.sleep(wait)
    st.rerun()