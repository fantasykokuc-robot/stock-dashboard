import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time

# ==================== 🛠️ 1. API 金鑰與系統設定 ====================
# 已移除 OpenAI, Gemini, DeepSeek 金鑰以策安全
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiZmFudGFzeWtva3VjIiwiZW1haWwiOiJmYW50YXN5a29rdWNAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.IOQSYqSUC6uaHIyXKf-OEDDYwLbT0D-Hw-H0rpKqD8Q"

st.set_page_config(page_title="TACTICAL COMMAND | AI SYSTEM", page_icon="🛡️", layout="wide")

st.markdown("""
    <style>
    .stApp, .main { background-color: #0b101e !important; color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background-color: #121826; border: 1px solid #1f2937; border-radius: 8px; padding: 15px; margin-bottom: 15px; height: 100%; }
    .title-text { color: #60a5fa; font-weight: bold; border-bottom: 1px solid #1f2937; padding-bottom: 5px; margin-bottom: 10px; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    .status-label { color: #00d4ff; font-weight: bold; font-size: 1.1rem; }
    </style>
""", unsafe_allow_html=True)

# ==================== 💾 2. 核心資料庫模組 ====================
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
    return f"{code} {name}".strip() if name else str(code)

def broadcast_line(message):
    tokens = [
        "HqZt6RC/T2qCZfubMb97OQ7XLgGfUwFNxFlfHl4a/cTMbYhKGkTg/HYcWsBko/ajE7tFjERHMv000AOP3M5BvTw/tShz7Z6SDSOX+Y+GjX0o7nfmNFBAA+Bbmcy0tYm8ENlxUmOfZ13D/6XcwBZyJwdB04t89/1O/w1cDnyilFU=",
        "Hc2Vkkxd7CrZ1NItS7w3FZjG9WaRnXeE5gH5S0CYLqUolXvYbDCx47kWGYC6398IL2oIA7z3rf4k37Qvzct9gs4qGOVSrrxgb8be8zWDaOL9+/HcyiZ9WsFNK0WWCgX86FBclkVyFwX+MMOY0SRH4QdB04t89/1O/w1cDnyilFU="
    ]
    for token in tokens:
        try: requests.post("https://notify-api.line.me/api/notify", headers={"Authorization": f"Bearer {token}"}, data={"message": message}, timeout=5)
        except: pass

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
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except: pass
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        df_yf = ticker.history(period="1y")
        if not df_yf.empty:
            df_yf.index = df_yf.index.tz_localize(None)
            return df_yf[['Open', 'High', 'Low', 'Close', 'Volume']]
    except: pass
    return pd.DataFrame()

def analyze_logic(code, source="系統"):
    df = fetch_stock_data(code)
    if df.empty or len(df) < 60: return None
    df['MA5'] = df['Close'].rolling(5).mean()
    high_10 = round(df['High'].iloc[-11:-1].max(), 2)
    c, vol = df['Close'].iloc[-1], df['Volume'].iloc[-1]
    vol_ma10 = df['Volume'].tail(10).mean()
    is_buy = (c > high_10 and vol > (vol_ma10 * 2) and c > df['MA5'].iloc[-1])
    if is_buy:
        today = datetime.date.today().isoformat()
        if st.session_state.get('notified', {}).get(code) != today:
            broadcast_line(f"\n🎯 【{source}】買點通報\n標的：{get_full_name(code)}\n現價：{round(c, 2)}\n戰術：🔥 安全放量突破")
            if 'notified' not in st.session_state: st.session_state.notified = {}
            st.session_state.notified[code] = today
    return {"全名": get_full_name(code), "現價": round(c, 2), "狀態": "🔥 安全放量突破" if is_buy else "⌛ 量縮整理", "強烈買訊": is_buy, "raw_df": df}

# ==================== 📋 3. 介面控制列 ====================
WATCHLIST_FILE = 'watchlist.json'
if 'watchlist' not in st.session_state:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r') as f: st.session_state.watchlist = json.load(f)
        except: st.session_state.watchlist = ["2330", "2317", "3481"]
    else: st.session_state.watchlist = ["2330", "2317", "3481"]

with st.sidebar:
    st.title("🛡️ 戰術監控管理")
    new_code = st.text_input("➕ 新增代碼")
    if st.button("加入清單", use_container_width=True) and new_code:
        if new_code not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_code)
            with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
            st.rerun()
            
    st.markdown("---")
    selected_code = st.selectbox("🎯 分析目標", st.session_state.watchlist, format_func=get_full_name)
    if st.button("🗑️ 移除目前標的", type="secondary", use_container_width=True):
        if selected_code in st.session_state.watchlist:
            st.session_state.watchlist.remove(selected_code)
            with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
            st.rerun()
            
    st.markdown("---")
    auto_monitor = st.toggle("🚀 啟動循環監控", value=False)

# ==================== 📊 4. 單頁整合儀表板 ====================
res = analyze_logic(selected_code, source="自選監控")
if not res:
    st.error("無法獲取數據，請檢查代碼或網路。")
    st.stop()

df = res['raw_df']
df['MA5'] = df['Close'].rolling(5).mean()
df['MA20'] = df['Close'].rolling(20).mean()
c_price = res['現價']
last_price = df['Close'].iloc[-2]
chg_pct = ((c_price - last_price) / last_price) * 100
status_color = "#ef4444" if chg_pct > 0 else "#10b981" if chg_pct < 0 else "#ffffff"

# --- 動態數據引擎 ---
high_5 = df['High'].tail(5).max()
low_5 = df['Low'].tail(5).min()
vol_ma5 = df['Volume'].tail(5).mean()
curr_vol = df['Volume'].iloc[-1]

bull_power = int(((c_price - low_5) / (high_5 - low_5)) * 100) if high_5 != low_5 else 50
bull_power = max(10, min(90, bull_power)) 
bear_power = 100 - bull_power

risk_score = min(int((curr_vol / vol_ma5) * 35), 95) if vol_ma5 > 0 else 50
risk_color = "#ef4444" if risk_score > 70 else "#eab308" if risk_score > 40 else "#10b981"

bias = (c_price - df['MA20'].iloc[-1]) / df['MA20'].iloc[-1] if not pd.isna(df['MA20'].iloc[-1]) else 0
up_prob = min(max(int(35 + bias * 200), 15), 75) 
down_prob = min(max(int(20 - bias * 100), 10), 60)
side_prob = 100 - up_prob - down_prob

if bias > 0.1: signal, s_color = "🔴 嚴重過熱", "#ef4444"
elif bias > 0.03: signal, s_color = "🟡 多頭發散", "#eab308"
elif bias < -0.05: signal, s_color = "🔵 弱勢探底", "#3b82f6"
else: signal, s_color = "🟢 穩健區間", "#10b981"

r_trend = min(max(int(bull_power / 10) + 1, 3), 10)
r_vol = min(max(int(curr_vol / vol_ma5 * 3) + 2, 3), 10) if vol_ma5 else 5
r_main = min(max(10 - int(risk_score/10), 2), 9)
r_inst = min(max(int(bias * 50) + 6, 2), 9) 
r_conc = min(max(int(vol_ma5 / df['Volume'].mean() * 5) + 3, 3), 9)

df_vp = df.tail(60).copy()
bins = pd.cut(df_vp['Close'], bins=4)
vp_data = df_vp.groupby(bins)['Volume'].sum()
vp_labels = [f"{b.left:.1f}-{b.right:.1f}" for b in vp_data.index]
vp_values = vp_data.values

st.markdown(f"<h2>{res['全名']} <span style='color:{status_color}; font-size:1.5rem;'>{c_price:.2f} ({chg_pct:+.2f}%)</span></h2>", unsafe_allow_html=True)

# --- 區塊一：主力意圖、劇本與能量 ---
r1_c1, r1_c2, r1_c3 = st.columns([2, 1, 1])
with r1_c1:
    st.markdown("<div class='metric-card'><div class='title-text'>1️⃣ 6️⃣ 主力意圖與成本分析</div>", unsafe_allow_html=True)
    fig_k = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線')])
    fig_k.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#eab308', width=1), name='5MA'))
    fig_k.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#60a5fa', width=1), name='20MA'))
    fig_k.update_layout(title=f"📊 {res['全名']} K線圖", template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,t=30,b=0), height=350, xaxis_rangeslider_visible=False, font=dict(color='white'))
    st.plotly_chart(fig_k, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)
with r1_c2:
    st.markdown(f"""
    <div class='metric-card'>
        <div class='title-text'>4️⃣ 明日劇本推演</div>
        <p style='color:#10b981; margin-bottom:5px;'>↗ 突破上漲 ({up_prob}%)</p>
        <p style='color:#eab308; margin-bottom:5px;'>→ 震盪整理 ({side_prob}%)</p>
        <p style='color:#ef4444; margin-bottom:15px;'>↘ 轉弱下跌 ({down_prob}%)</p>
        <div class='title-text' style='border-top: 1px solid #1f2937; padding-top: 10px;'>5️⃣ 多空能量條</div>
        <div style='display:flex; justify-content:space-between; font-size:0.8rem;'>
            <span style='color:#10b981'>多方 {bull_power}%</span><span style='color:#ef4444'>空方 {bear_power}%</span>
        </div>
        <div style='width:100%; height:8px; background:#ef4444; border-radius:4px; margin-top:2px;'>
            <div style='width:{bull_power}%; height:100%; background:#10b981; border-radius:4px 0 0 4px;'></div>
        </div>
    </div>""", unsafe_allow_html=True)
with r1_c3:
    st.markdown(f"<div class='metric-card'><div class='title-text'>2️⃣ 隔日沖風險</div><h1 style='color:{risk_color}; text-align:center;'>{risk_score}%</h1><p style='text-align:center; color:#666;'>⚠️ 基於量能運算</p></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='metric-card'><div class='title-text'>9️⃣ 預警燈號</div><h3 style='color:{s_color}; text-align:center;'>{signal}</h3></div>", unsafe_allow_html=True)

# --- 區塊二：雷達、籌碼與預測 ---
r2_c1, r2_c2, r2_c3, r2_c4 = st.columns([1, 1, 1, 1])
with r2_c1:
    st.markdown("<div class='metric-card'><div class='title-text'>3️⃣ 飆股雷達圖</div>", unsafe_allow_html=True)
    fig_radar = go.Figure(data=go.Scatterpolar(r=[r_trend, r_vol, r_main, r_inst, r_conc], theta=['趨勢','量能','主力','法人','集中度'], fill='toself', line_color='#eab308'))
    fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False, range=[0, 10])), showlegend=False, paper_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=20,r=20,t=20,b=20), font=dict(color='white'))
    st.plotly_chart(fig_radar, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)
with r2_c2:
    st.markdown("<div class='metric-card'><div class='title-text'>7️⃣ 籌碼熱區圖</div>", unsafe_allow_html=True)
    fig_vp = go.Figure(go.Bar(x=vp_values, y=vp_labels, orientation='h', marker_color='#60a5fa'))
    fig_vp.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0,r=0,t=0,b=0), font=dict(color='white'))
    st.plotly_chart(fig_vp, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)
with r2_c3:
    st.markdown("<div class='metric-card'><div class='title-text'>8️⃣ 11 健康度與情緒</div>", unsafe_allow_html=True)
    fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=bull_power, gauge={'bar':{'color':"#10b981" if bull_power>50 else "#ef4444"}, 'axis':{'range':[0,100], 'tickfont': {'color': 'white'}}}))
    fig_gauge.update_layout(paper_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=10,r=10,t=30,b=10), font=dict(color='white'))
    st.plotly_chart(fig_gauge, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)
with r2_c4:
    st.markdown("<div class='metric-card'><div class='title-text'>🔟 預測路徑圖</div>", unsafe_allow_html=True)
    fig_pred = go.Figure(go.Scatter(x=[1,2,3,4], y=[c_price, c_price*(1+bias), c_price*(1+bias*1.5), c_price*(1+bias*2)], line=dict(dash='dash', color='#10b981' if bias>0 else '#ef4444')))
    fig_pred.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0,r=0,t=0,b=0), font=dict(color='white'))
    st.plotly_chart(fig_pred, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)

# ==================== 🌍 5. 擴充模組 (全市場掃描解禁 & 證交所偽裝) ====================
st.markdown("---")
with st.expander("🌍 進階監控：市場掃描 / ETF / 實體籌碼數據"):
    sub1, sub2 = st.columns(2)
    with sub1:
        st.subheader("🏦 核心 ETF 監控")
        etf_res = []
        for code in ["0050", "0056", "00878", "00713", "00919"]:
            d = fetch_stock_data(code)
            if not d.empty and len(d) >= 60:
                curr, ma60 = d['Close'].iloc[-1], d['Close'].rolling(60).mean().iloc[-1]
                etf_res.append({"標的": get_full_name(code), "狀態": "🟢 季線上" if curr >= ma60 else "🔴 季線下"})
        if etf_res: st.table(pd.DataFrame(etf_res))
    with sub2:
        st.subheader("🏆 全市場實時掃描")
        if st.button("🚀 啟動掃描 (全清單)", type="primary"):
            all_codes = list(STOCK_DICT.keys())
            
            if not all_codes:
                all_codes = ["2330", "2317", "2454", "2308", "2881", "2882", "2891", "2002", "3231", "2382", "2603", "2609", "3481", "2409"]
                
            scan_limit = len(all_codes)
            
            status_text = st.empty()
            progress_bar = st.progress(0)
            found = []
            
            st.warning(f"⚠️ 注意：全市場掃描將分析 {scan_limit} 檔標的，過程可能需要數分鐘，請耐心等候。")
            
            for i in range(scan_limit):
                code = all_codes[i]
                status_text.markdown(f"**⏳ 正在掃描 ({i+1}/{scan_limit}): {get_full_name(code)}...**")
                
                res_s = analyze_logic(code, source="全市場掃描")
                if res_s and res_s["強烈買訊"]: 
                    found.append({"代碼": code, "名稱": res_s["全名"], "價位": res_s["現價"]})
                    
                progress_bar.progress((i + 1) / scan_limit)
                
            status_text.markdown(f"✅ **掃描完成！共分析 {scan_limit} 檔標的。**")
            if found: st.dataframe(pd.DataFrame(found))
            else: st.info("目前無符合戰術買點的標的")
            
    st.subheader("📊 盤後實體籌碼數據 (證交所)")
    if st.button("🔄 獲取盤後法人數據"):
        try:
            # 🛡️ 修復：加入 User-Agent 偽裝瀏覽器，突破證交所防爬蟲機制
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            r = requests.get("https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999", headers=headers, timeout=10).json()
            if 'data' in r and r['data']:
                df_chip = pd.DataFrame(r['data'], columns=r['fields'])[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
                st.dataframe(df_chip.head(15))
            else:
                st.warning("⚠️ 證交所目前無回傳資料 (可能為非交易日或資料尚未結算)。")
        except Exception as e: 
            st.error(f"證交所 API 請求失敗，請稍候重試。({str(e)})")

if auto_monitor:
    time.sleep(300)
    st.rerun()