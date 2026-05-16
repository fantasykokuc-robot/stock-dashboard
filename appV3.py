import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import datetime
import json
import os
import time
import logging
import random
import sqlite3
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ==================== ⚙️ 1. 系統配置與日誌 ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

FINMIND_TOKEN_DEFAULT = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiZmFudGFzeWtva3VjIiwiZW1haWwiOiJmYW50YXN5a29rdWNAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.IOQSYqSUC6uaHIyXKf-OEDDYwLbT0D-Hw-H0rpKqD8Q"
try:
    CONFIG = {
        "FINMIND_TOKEN": st.secrets.get("FINMIND_TOKEN", FINMIND_TOKEN_DEFAULT),
        "LINE_TOKENS": st.secrets.get("LINE_TOKENS", []),
    }
except Exception:
    CONFIG = {"FINMIND_TOKEN": FINMIND_TOKEN_DEFAULT, "LINE_TOKENS": []}

st.set_page_config(page_title="TACTICAL COMMAND | PRO FUSION", page_icon="🛡️", layout="wide")

# 🛡️ 深度修復：加入強制白字的 CSS，解決黑底黑字問題
st.markdown("""
    <style>
    .stApp { background: linear-gradient(135deg, #0b101e 0%, #1a1f2e 50%, #0f172a 100%); color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background: linear-gradient(135deg, #121826 0%, #1a1f2e 100%); border: 1px solid #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); height: 100%; transition: all 0.3s ease;}
    .metric-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.6); }
    .title-text { color: #60a5fa; font-weight: bold; border-bottom: 2px solid #1f2937; padding-bottom: 10px; margin-bottom: 20px; font-size: 1.2rem; }
    .score-badge { font-size: 3rem; font-weight: bold; text-align: center; padding: 15px; border-radius: 15px; text-shadow: 0 0 10px rgba(96, 165, 250, 0.5); }
    .signal-item { padding: 8px 12px; margin: 5px 0; background: rgba(31, 41, 55, 0.5); border-radius: 6px; border-left: 3px solid #60a5fa; font-size: 0.95rem; }
    
    /* 強制輸入框、下拉選單、表格文字為白色 */
    div[data-baseweb="input"] input, div[data-baseweb="select"] > div {
        background-color: #1f2937 !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    .stDataFrame, table { color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

# 建立 SQLite 檔案快取連線
DB_CONN = sqlite3.connect("market_data.db", check_same_thread=False)

# ==================== 💾 2. 數據引擎 (終極防呆版) ====================
class DataEngine:
    @staticmethod
    @st.cache_data(ttl=3600)
    def load_stock_dict():
        for path in ['twse_listed_codes.csv', 'data/twse_listed_codes.csv']:
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path, encoding='utf-8-sig', header=None)
                    return dict(zip(df.iloc[:,0].astype(str).str.strip().str.zfill(4), df.iloc[:,1].astype(str).str.strip()))
                except: pass
        return {}

    @staticmethod
    def fetch_stock_data(stock_id):
        stock_id = str(stock_id).strip().zfill(4)
        table_name = f"price_{stock_id}"
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        # 🛡️ 1. 讀取 SQLite，若資料損壞則強制重新抓取
        try:
            df = pd.read_sql(f"SELECT * FROM {table_name}", DB_CONN, index_col="Date", parse_dates=["Date"])
            if not df.empty and all(col in df.columns for col in required_cols):
                if (datetime.datetime.now().date() - df.index.max().date()).days <= 1:
                    return DataEngine._precompute_indicators(df)
        except: pass

        df = pd.DataFrame()
        start_date = (datetime.datetime.now() - datetime.timedelta(days=250)).strftime("%Y-%m-%d")

        # 🛡️ 2. FinMind 抓取
        try:
            url = "https://api.finmindtrade.com/api/v4/data"
            resp = requests.get(url, params={"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start_date, "token": CONFIG["FINMIND_TOKEN"]}, timeout=8)
            if resp.status_code == 200 and 'data' in resp.json() and len(resp.json()['data']) > 0:
                df = pd.DataFrame(resp.json()['data'])
                df.columns = [str(c).lower() for c in df.columns]
                rename_map = {'date': 'Date', 'open': 'Open', 'close': 'Close', 'high': 'High', 'low': 'Low', 'volume': 'Volume', 'max': 'High', 'min': 'Low', 'trading_volume': 'Volume'}
                df = df.rename(columns=rename_map)
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'])
                    df.set_index('Date', inplace=True)
        except: pass

        # 🛡️ 3. 深度修復：yfinance MultiIndex 扁平化，解決 3481 抓不到的問題
        if df.empty or 'Close' not in df.columns:
            for suffix in ['.TW', '.TWO']:
                try:
                    df_yf = yf.download(f"{stock_id}{suffix}", period="1y", progress=False)
                    if not df_yf.empty and len(df_yf) > 5:
                        # 處理 yfinance 新版的 MultiIndex 欄位問題
                        if isinstance(df_yf.columns, pd.MultiIndex):
                            df_yf.columns = df_yf.columns.get_level_values(0)
                        
                        df_yf.index = df_yf.index.tz_localize(None)
                        df = df_yf
                        break
                except: continue

        if df.empty: return pd.DataFrame()
        
        # 再次確認欄位完整性
        if not all(col in df.columns for col in required_cols): return pd.DataFrame()
            
        df = df[required_cols].astype(float).ffill().dropna(subset=['Close'])
        
        try: df.to_sql(table_name, DB_CONN, if_exists="replace", index=True)
        except: pass
        
        return DataEngine._precompute_indicators(df)

    @staticmethod
    def fetch_chips_data(stock_id):
        stock_id = str(stock_id).strip().zfill(4)
        start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            url = "https://api.finmindtrade.com/api/v4/data"
            resp = requests.get(url, params={"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": stock_id, "start_date": start_date, "token": CONFIG["FINMIND_TOKEN"]}, timeout=5)
            if resp.status_code == 200 and 'data' in resp.json() and len(resp.json()['data']) > 0:
                df = pd.DataFrame(resp.json()['data'])
                return df
        except: pass
        return pd.DataFrame()

    @staticmethod
    def fetch_fundamental_data(stock_id):
        stock_id = str(stock_id).strip().zfill(4)
        start_date = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
        try:
            url = "https://api.finmindtrade.com/api/v4/data"
            resp = requests.get(url, params={"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date, "token": CONFIG["FINMIND_TOKEN"]}, timeout=5)
            if resp.status_code == 200 and 'data' in resp.json() and len(resp.json()['data']) > 0:
                df = pd.DataFrame(resp.json()['data'])
                return df
        except: pass
        return pd.DataFrame()

    @staticmethod
    def fetch_global_news():
        """獲取國外重大財經新聞 (Google News RSS)"""
        url = "https://news.google.com/rss/search?q=%E5%9C%8B%E9%9A%9B%E8%B2%A1%E7%B6%93&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        try:
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.content)
            news_list = []
            for item in root.findall('.//item')[:5]: # 抓取前 5 則
                title = item.find('title').text
                link = item.find('link').text
                news_list.append({"title": title, "link": link})
            return news_list
        except: return []

    @staticmethod
    def _precompute_indicators(df):
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['VolMA5'] = df['Volume'].rolling(5).mean()
        return df

# ==================== 📈 3. 策略與指標運算引擎 ====================
class StrategyEngine:
    @staticmethod
    def analyze_metrics(code, df_price, df_chips, df_fund, source="系統"):
        if df_price.empty or len(df_price) < 15: return None
        
        def safe_get(val, default): return default if pd.isna(val) else val
        
        latest = df_price.iloc[-1]
        c_price = latest['Close']
        c_vol = latest['Volume']
        ma20 = safe_get(latest.get('MA20'), c_price)
        ma60 = safe_get(latest.get('MA60'), c_price)
        vol_ma5 = safe_get(latest.get('VolMA5'), c_vol)
        
        scores = {'tech': 0, 'chips': 0, 'fund': 0}
        signals = []
        
        if c_price > ma60 and ma20 > ma60: scores['tech'] += 15; signals.append("✅ 完美多頭排列")
        elif c_price > ma20: scores['tech'] += 15; signals.append("🟡 價格站上月線")
        if c_vol > vol_ma5 * 1.5: scores['tech'] += 15; signals.append("💥 量能爆發")
            
        if not df_chips.empty and 'name' in df_chips.columns:
            df_foreign = df_chips[df_chips['name'].str.contains('外資', na=False)]
            df_trust = df_chips[df_chips['name'].str.contains('投信', na=False)]
            f_buy = df_foreign.tail(3)['buy'].sum() - df_foreign.tail(3)['sell'].sum() if not df_foreign.empty else 0
            t_buy = df_trust.tail(3)['buy'].sum() - df_trust.tail(3)['sell'].sum() if not df_trust.empty else 0
            if f_buy > 0: scores['chips'] += 20; signals.append(f"🌍 外資偏多")
            if t_buy > 0: scores['chips'] += 20; signals.append(f"🏦 投信偏多")
        else: scores['chips'] = 20

        if not df_fund.empty and 'revenue_year_on_year_growth_rate' in df_fund.columns:
            latest_yoy = df_fund['revenue_year_on_year_growth_rate'].iloc[-1]
            if latest_yoy > 10: scores['fund'] += 30; signals.append(f"📈 營收高成長")
            elif latest_yoy > 0: scores['fund'] += 15; signals.append(f"穩 營收正成長")
        else: scores['fund'] = 15

        total_score = sum(scores.values())
        if total_score >= 80: status, status_color = "🔥🔥 強力買入", "#34d399"
        elif total_score >= 65: status, status_color = "🔥 買入訊號", "#10b981"
        elif total_score >= 45: status, status_color = "👀 觀察中", "#fbbf24"
        else: status, status_color = "⏸️ 觀望", "#9ca3af"
        
        high_5, low_5 = df_price['High'].tail(5).max(), df_price['Low'].tail(5).min()
        bull_power = max(10, min(90, int(((c_price - low_5) / (high_5 - low_5)) * 100) if high_5 != low_5 else 50))
        risk_score = min(int((c_vol / vol_ma5) * 35), 95) if vol_ma5 > 0 else 50
        bias_20 = (c_price - ma20) / ma20 if ma20 > 0 else 0
        up_prob = min(max(int(35 + bias_20 * 200), 15), 75) 
        
        df_vp = df_price.tail(60).copy()
        if df_vp['Close'].nunique() > 1:
            bins = pd.cut(df_vp['Close'], bins=4)
            vp_data = df_vp.groupby(bins, observed=False)['Volume'].sum()
            vp_labels, vp_values = [f"{b.left:.1f}-{b.right:.1f}" for b in vp_data.index], vp_data.values
        else:
            vp_labels, vp_values = [f"{c_price:.1f}"], [df_vp['Volume'].sum()]

        return {
            "price": round(c_price, 2), "total_score": total_score, "scores": scores,
            "signals": signals, "bias_20": bias_20, "status": status, "status_color": status_color, 
            "bull_power": bull_power, "bear_power": 100 - bull_power,
            "risk_score": risk_score, "up_prob": up_prob, "down_prob": min(max(int(20 - bias_20 * 100), 10), 60),
            "side_prob": 100 - up_prob - min(max(int(20 - bias_20 * 100), 10), 60),
            "r_trend": min(max(int(bull_power / 10) + 1, 3), 10),
            "r_vol": min(max(int((c_vol / vol_ma5) * 3) + 2, 3), 10) if vol_ma5 > 0 else 5,
            "r_main": min(max(10 - int(risk_score/10), 2), 9),
            "r_inst": min(max(int(bias_20 * 50) + 6, 2), 9),
            "r_conc": min(max(int(vol_ma5 / df_price['Volume'].mean() * 5) + 3, 3), 9) if df_price['Volume'].mean() > 0 else 5,
            "vp_labels": vp_labels, "vp_values": vp_values, "df": df_price, "is_buy": total_score >= 65
        }

# ==================== 🎨 4. 單頁視覺儀表板 ====================
def render_dashboard(code, stock_dict):
    with st.spinner(f"🔄 分析 {code} 三因子戰情數據中..."):
        df_price = DataEngine.fetch_stock_data(code)
        df_chips = DataEngine.fetch_chips_data(code)
        df_fund = DataEngine.fetch_fundamental_data(code)
        metrics = StrategyEngine.analyze_metrics(code, df_price, df_chips, df_fund)
    
    if not metrics:
        st.error(f"⚠️ 無法獲取 {code} 的完整數據。可能為剛上市冷門股或 API 限制。")
        return

    df = metrics['df']
    full_name = f"{code} {stock_dict.get(code, '')}".strip()
    c_price = metrics['price']
    last_price = df['Close'].iloc[-2] if len(df) > 1 else c_price
    chg_pct = ((c_price - last_price) / last_price) * 100 if last_price > 0 else 0
    status_color = "#ef4444" if chg_pct > 0 else "#10b981" if chg_pct < 0 else "#ffffff"

    bias = metrics['bias_20']
    if bias > 0.1: signal, s_color = "🔴 嚴重過熱", "#ef4444"
    elif bias > 0.03: signal, s_color = "🟡 多頭發散", "#eab308"
    elif bias < -0.05: signal, s_color = "🔵 弱勢探底", "#3b82f6"
    else: signal, s_color = "🟢 穩健區間", "#10b981"

    st.markdown(f"<h2>{full_name} <span style='color:{status_color}; font-size:1.5rem;'>{c_price:.2f} ({chg_pct:+.2f}%)</span></h2>", unsafe_allow_html=True)

    r1_c1, r1_c2, r1_c3 = st.columns([2, 1, 1])
    with r1_c1:
        st.markdown("<div class='metric-card'><div class='title-text'>1️⃣ 6️⃣ 主力意圖與成本分析</div>", unsafe_allow_html=True)
        fig_k = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線')])
        if not df['MA5'].isna().all(): fig_k.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#eab308', width=1), name='5MA'))
        if not df['MA20'].isna().all(): fig_k.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#60a5fa', width=1), name='20MA'))
        fig_k.update_layout(title=f"📊 {full_name} K線圖", template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,t=30,b=0), height=350, xaxis_rangeslider_visible=False, font=dict(color='white'))
        st.plotly_chart(fig_k, use_container_width=True, theme=None)
        st.markdown("</div>", unsafe_allow_html=True)
    with r1_c2:
        st.markdown(f"""
        <div class='metric-card'>
            <div class='title-text'>4️⃣ 明日劇本推演</div>
            <p style='color:#10b981; margin-bottom:5px;'>↗ 突破上漲 ({metrics['up_prob']}%)</p>
            <p style='color:#eab308; margin-bottom:5px;'>→ 震盪整理 ({metrics['side_prob']}%)</p>
            <p style='color:#ef4444; margin-bottom:15px;'>↘ 轉弱下跌 ({metrics['down_prob']}%)</p>
            <div class='title-text' style='border-top: 1px solid #1f2937; padding-top: 10px;'>5️⃣ 多空能量條</div>
            <div style='display:flex; justify-content:space-between; font-size:0.8rem;'>
                <span style='color:#10b981'>多方 {metrics['bull_power']}%</span><span style='color:#ef4444'>空方 {metrics['bear_power']}%</span>
            </div>
            <div style='width:100%; height:8px; background:#ef4444; border-radius:4px; margin-top:2px;'>
                <div style='width:{metrics['bull_power']}%; height:100%; background:#10b981; border-radius:4px 0 0 4px;'></div>
            </div>
        </div>""", unsafe_allow_html=True)
    with r1_c3:
        r_color = "#ef4444" if metrics['risk_score'] > 70 else "#eab308" if metrics['risk_score'] > 40 else "#10b981"
        st.markdown(f"<div class='metric-card'><div class='title-text'>2️⃣ 隔日沖風險</div><h1 style='color:{r_color}; text-align:center;'>{metrics['risk_score']}%</h1><p style='text-align:center; color:#666;'>⚠️ 基於量能運算</p></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-card'><div class='title-text'>9️⃣ 預警燈號</div><h3 style='color:{s_color}; text-align:center;'>{signal}</h3></div>", unsafe_allow_html=True)

    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns([1, 1, 1, 1])
    with r2_c1:
        st.markdown("<div class='metric-card'><div class='title-text'>3️⃣ 飆股雷達圖</div>", unsafe_allow_html=True)
        fig_radar = go.Figure(data=go.Scatterpolar(r=[metrics['r_trend'], metrics['r_vol'], metrics['r_main'], metrics['r_inst'], metrics['r_conc']], theta=['趨勢','量能','主力','法人','集中度'], fill='toself', line_color='#eab308'))
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False, range=[0, 10])), showlegend=False, paper_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=20,r=20,t=20,b=20), font=dict(color='white'))
        st.plotly_chart(fig_radar, use_container_width=True, theme=None)
        st.markdown("</div>", unsafe_allow_html=True)
    with r2_c2:
        st.markdown("<div class='metric-card'><div class='title-text'>7️⃣ 籌碼熱區圖</div>", unsafe_allow_html=True)
        fig_vp = go.Figure(go.Bar(x=metrics['vp_values'], y=metrics['vp_labels'], orientation='h', marker_color='#60a5fa'))
        fig_vp.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0,r=0,t=0,b=0), font=dict(color='white'))
        st.plotly_chart(fig_vp, use_container_width=True, theme=None)
        st.markdown("</div>", unsafe_allow_html=True)
    with r2_c3:
        st.markdown("<div class='metric-card'><div class='title-text'>8️⃣ 健康度與情緒</div>", unsafe_allow_html=True)
        fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=metrics['bull_power'], gauge={'bar':{'color':"#10b981" if metrics['bull_power']>50 else "#ef4444"}, 'axis':{'range':[0,100], 'tickfont': {'color': 'white'}}}))
        fig_gauge.update_layout(paper_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=10,r=10,t=30,b=10), font=dict(color='white'))
        st.plotly_chart(fig_gauge, use_container_width=True, theme=None)
        st.markdown("</div>", unsafe_allow_html=True)
    with r2_c4:
        st.markdown("<div class='metric-card'><div class='title-text'>🔟 預測路徑圖</div>", unsafe_allow_html=True)
        fig_pred = go.Figure(go.Scatter(x=[1,2,3,4], y=[c_price, c_price*(1+bias), c_price*(1+bias*1.5), c_price*(1+bias*2)], line=dict(dash='dash', color='#10b981' if bias>0 else '#ef4444')))
        fig_pred.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0,r=0,t=0,b=0), font=dict(color='white'))
        st.plotly_chart(fig_pred, use_container_width=True, theme=None)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🧮 核心三因子模型 (籌碼 40% / 技術 30% / 基本 30%)")
    r3_c1, r3_c2 = st.columns([1.5, 2])
    with r3_c1:
        st.markdown(f"""
            <div class='metric-card'>
                <div class='title-text'>🎯 系統綜合評分</div>
                <div class='score-badge' style='color: {metrics["status_color"]};'>{metrics['total_score']}<span style='font-size: 1.5rem;'>/100</span></div>
                <h3 style='text-align: center; color: {metrics["status_color"]};'>{metrics['status']}</h3>
            </div>
        """, unsafe_allow_html=True)
    with r3_c2:
        st.markdown("<div class='metric-card'><div class='title-text'>🧬 因子得分拆解</div>", unsafe_allow_html=True)
        p1, p2, p3 = st.columns(3)
        with p1:
            st.write("💰 **籌碼面**")
            st.progress(metrics['scores']['chips'] / 40)
            st.caption(f"得分: {metrics['scores']['chips']} / 40")
        with p2:
            st.write("📈 **技術面**")
            st.progress(metrics['scores']['tech'] / 30)
            st.caption(f"得分: {metrics['scores']['tech']} / 30")
        with p3:
            st.write("🏢 **基本面**")
            st.progress(metrics['scores']['fund'] / 30)
            st.caption(f"得分: {metrics['scores']['fund']} / 30")
            
        st.markdown("<div style='margin-top: 15px; display: flex; flex-wrap: wrap; gap: 10px;'>", unsafe_allow_html=True)
        for s in metrics['signals']: st.markdown(f"<div class='signal-item'>{s}</div>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

# ==================== 🚀 5. 主程式與擴充模組 ====================
def main():
    stock_dict = DataEngine.load_stock_dict()
    
    WATCHLIST_FILE, ETF_FILE = 'watchlist.json', 'etf_list.json'
    if 'watchlist' not in st.session_state:
        st.session_state.watchlist = json.load(open(WATCHLIST_FILE)) if os.path.exists(WATCHLIST_FILE) else ["2330", "2317", "3481"]
    if 'etf_list' not in st.session_state:
        st.session_state.etf_list = json.load(open(ETF_FILE)) if os.path.exists(ETF_FILE) else ["0050", "0056", "00878", "00713", "00919"]

    with st.sidebar:
        st.title("🛡️ TACTICAL COMMAND")
        new_code = st.text_input("➕ 新增主控標的")
        if st.button("加入清單", use_container_width=True) and new_code:
            code = new_code.strip().zfill(4)
            if code not in st.session_state.watchlist:
                st.session_state.watchlist.append(code)
                with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
                st.rerun()
                
        st.markdown("---")
        selected_code = st.selectbox("🎯 分析目標", st.session_state.watchlist, format_func=lambda x: f"{x} {stock_dict.get(x, '')}")
        if st.button("🗑️ 移除目前標的", type="secondary", use_container_width=True):
            if selected_code in st.session_state.watchlist:
                st.session_state.watchlist.remove(selected_code)
                with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
                st.rerun()
                
        st.markdown("---")
        auto_monitor = st.toggle("🚀 啟動循環監控", value=False)

    if selected_code:
        render_dashboard(selected_code, stock_dict)

    # ---------------- 擴充模組：ETF 自訂、新聞、多執行緒掃描 ----------------
    st.markdown("---")
    with st.expander("🌍 進階監控面板：多執行緒掃描 / 自訂 ETF / 國際新聞 / 實體籌碼", expanded=False):
        
        # 上半部：ETF 與 新聞
        top_c1, top_c2 = st.columns([1, 1])
        with top_c1:
            st.subheader("🏦 核心 ETF 監控 (可自訂)")
            with st.container(border=True):
                ec1, ec2 = st.columns(2)
                with ec1:
                    new_etf = st.text_input("➕ 新增 ETF", key="new_etf_input")
                    if st.button("加入", use_container_width=True) and new_etf:
                        if new_etf not in st.session_state.etf_list:
                            st.session_state.etf_list.append(new_etf)
                            with open(ETF_FILE, 'w') as f: json.dump(st.session_state.etf_list, f)
                            st.rerun()
                with ec2:
                    del_etf = st.selectbox("🗑️ 移除 ETF", st.session_state.etf_list)
                    if st.button("移除", use_container_width=True):
                        if del_etf in st.session_state.etf_list:
                            st.session_state.etf_list.remove(del_etf)
                            with open(ETF_FILE, 'w') as f: json.dump(st.session_state.etf_list, f)
                            st.rerun()

            etf_res = []
            for code in st.session_state.etf_list:
                d = DataEngine.fetch_stock_data(code)
                if not d.empty and len(d) >= 60:
                    curr = d['Close'].iloc[-1]
                    ma60 = d['MA60'].iloc[-1] if not pd.isna(d['MA60'].iloc[-1]) else curr
                    etf_res.append({"標的": f"{code} {stock_dict.get(code, '')}", "狀態": "🟢 季線上" if curr >= ma60 else "🔴 季線下"})
            if etf_res: st.table(pd.DataFrame(etf_res))
            
        with top_c2:
            st.subheader("🌍 國際重大財經新聞 (即時)")
            with st.container(border=True):
                news_items = DataEngine.fetch_global_news()
                if news_items:
                    for news in news_items:
                        st.markdown(f"📰 [{news['title']}]({news['link']})")
                else:
                    st.info("目前無法獲取即時新聞。")

        st.markdown("---")
        
        # 下半部：籌碼與全市場掃描
        bot_c1, bot_c2 = st.columns([1, 1.2])
        with bot_c1:
            st.subheader("📊 盤後實體籌碼數據 (證交所)")
            if st.button("🔄 獲取今日法人數據"):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
                    r = requests.get("https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999", headers=headers, timeout=10).json()
                    if 'data' in r and r['data']:
                        df_chip = pd.DataFrame(r['data'], columns=r['fields'])[['證券代號', '證券名稱', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
                        st.dataframe(df_chip.head(10))
                    else:
                        st.warning("⚠️ 無回傳資料 (可能為非交易日或尚未結算)。")
                except Exception as e: 
                    st.error(f"API 請求失敗: {e}")

        with bot_c2:
            st.subheader("🏆 全市場實時掃描 (漏斗過濾極速版)")
            max_scan = st.selectbox("掃描範圍限制 (越少越快)", [100, 300, 500, "全清單"], index=0)
            
            if st.button("🚀 啟動戰術掃描", type="primary", use_container_width=True):
                all_codes = list(stock_dict.keys())
                if not all_codes: all_codes = ["2330", "2317", "2454", "2308", "2881", "2603", "3481"]
                
                scan_limit = len(all_codes) if max_scan == "全清單" else max_scan
                codes_to_scan = all_codes[:scan_limit]
                
                found = []
                p_bar = st.progress(0)
                s_text = st.empty()
                start_time = time.time()
                completed = 0
                
                def scan_task(c):
                    # 💡 漏斗過濾機制：先看技術面，不及格直接剔除，省下呼叫籌碼與基本面 API 的時間
                    df_s = DataEngine.fetch_stock_data(c)
                    if df_s.empty or len(df_s) < 20: return None
                    c_price, ma20 = df_s['Close'].iloc[-1], df_s['MA20'].iloc[-1]
                    if c_price < ma20: return None # 均線空頭直接過濾
                    
                    df_chips = DataEngine.fetch_chips_data(c)
                    df_fund = DataEngine.fetch_fundamental_data(c)
                    res_s = StrategyEngine.analyze_metrics(c, df_s, df_chips, df_fund, source="全市場掃描")
                    
                    if res_s and res_s['is_buy']:
                        return {"代碼": c, "名稱": stock_dict.get(c, ""), "價位": res_s['price'], "評分": res_s['total_score'], "狀態": "🔥 放量強勢股"}
                    return None

                with ThreadPoolExecutor(max_workers=8) as executor:
                    future_map = {executor.submit(scan_task, c): c for c in codes_to_scan}
                    for future in as_completed(future_map):
                        completed += 1
                        res_s = future.result()
                        if res_s: found.append(res_s)
                        
                        if completed % 5 == 0 or completed == scan_limit:
                            elapsed = time.time() - start_time
                            eta = (elapsed / completed) * (scan_limit - completed)
                            p_bar.progress(completed / scan_limit)
                            s_text.markdown(f"**⏳ 正在掃描 ({completed}/{scan_limit}) | 已耗時: {elapsed:.1f}s | 預估剩餘: {eta:.1f}s | 尋獲標的: {len(found)}**")
                
                s_text.markdown(f"✅ **掃描完成！共耗時 {time.time()-start_time:.1f} 秒。**")
                if found:
                    st.dataframe(pd.DataFrame(found).sort_values("評分", ascending=False), use_container_width=True, hide_index=True)
                else:
                    st.info("目前無符合條件的三因子達標股票。")

    if auto_monitor:
        if HAS_AUTOREFRESH:
            st_autorefresh(interval=300000, limit=None, key="auto_refresh")
        else:
            time.sleep(300)
            st.rerun()

if __name__ == "__main__":
    main()