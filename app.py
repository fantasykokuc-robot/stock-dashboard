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

import threading

# ==================== ⚙️ 1. 系統配置與日誌 ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
DB_LOCK = threading.Lock()

class SystemDiagnostics:
    """系統自我檢查模組[cite: 4]"""
    @staticmethod
    def run_checks():
        results = []
        # 1. 檢查必要檔案
        required_files = {
            "twse_listed_codes.csv": "股票代碼對照表",
            "market_data.db": "SQLite 資料庫"
        }
        for file_path, desc in required_files.items():
            exists = os.path.exists(file_path)
            status = "✅ 找到" if exists else "❌ 缺失"
            results.append({"項目": desc, "路徑": file_path, "狀態": status})
        
        # 2. 檢查設定 (支援 Secrets)
        has_token = CONFIG.get("FINMIND_TOKEN") and len(CONFIG["FINMIND_TOKEN"]) > 10
        token_status = "✅ 已設定" if has_token else "⚠️ 未設定 (FinMind)"
        results.append({"項目": "FinMind Token", "路徑": "CONFIG/Secrets", "狀態": token_status})
        
        return results

# --- 獨立資料夾讀取邏輯 ---
CONFIG_FILE = os.path.join("config", "settings.json")
# Token 從環境變數或 Streamlit Secrets 讀取，不再硬編碼於原始碼中
FINMIND_TOKEN_DEFAULT = os.environ.get("FINMIND_TOKEN", "")

CONFIG = {
    "FINMIND_TOKEN": FINMIND_TOKEN_DEFAULT,
    "LINE_TOKENS": [],
    "LINE_BOTS": [],
    "TG_BOT_TOKEN": "",
    "TG_CHAT_IDS": []
}

# 優先順序：1. Streamlit Secrets (雲端) > 2. settings.json (本地) > 3. 預設值
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            CONFIG.update(json.load(f))
    except Exception as e:
        logging.warning(f"讀取設定檔失敗: {e}")

# 整合 Streamlit Secrets
try:
    if "FINMIND_TOKEN" in st.secrets: CONFIG["FINMIND_TOKEN"] = st.secrets["FINMIND_TOKEN"]
    if "LINE_TOKENS" in st.secrets: CONFIG["LINE_TOKENS"] = st.secrets["LINE_TOKENS"]
    if "LINE_BOTS" in st.secrets: CONFIG["LINE_BOTS"] = st.secrets["LINE_BOTS"]
    if "TG_BOT_TOKEN" in st.secrets: CONFIG["TG_BOT_TOKEN"] = st.secrets["TG_BOT_TOKEN"]
    if "TG_CHAT_IDS" in st.secrets: CONFIG["TG_CHAT_IDS"] = st.secrets["TG_CHAT_IDS"]
except:
    pass

st.set_page_config(page_title="TACTICAL COMMAND | PRO FUSION", page_icon="🛡️", layout="wide")

st.markdown("""
    <style>
    .stApp { background: linear-gradient(135deg, #0b101e 0%, #1a1f2e 50%, #0f172a 100%); color: #E0E0E0; font-family: 'Microsoft JhengHei', sans-serif; }
    .metric-card { background: linear-gradient(135deg, #121826 0%, #1a1f2e 100%); border: 1px solid #1f2937; border-radius: 12px; padding: 15px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); transition: all 0.3s ease;}
    @media (max-width: 768px) {
        .metric-card { padding: 10px; margin-bottom: 8px; }
        .score-badge { font-size: 2.2rem !important; }
        h2 { font-size: 1.2rem !important; }
    }
    .metric-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.6); }
    .title-text { color: #60a5fa; font-weight: bold; border-bottom: 2px solid #1f2937; padding-bottom: 8px; margin-bottom: 15px; font-size: 1.1rem; }
    .score-badge { font-size: 3rem; font-weight: bold; text-align: center; padding: 10px; border-radius: 15px; text-shadow: 0 0 10px rgba(96, 165, 250, 0.5); }
    .signal-item { padding: 6px 10px; margin: 4px 0; background: rgba(31, 41, 55, 0.5); border-radius: 6px; border-left: 3px solid #60a5fa; font-size: 0.85rem; }
    div[data-baseweb="input"] input, div[data-baseweb="select"] > div { background-color: #1f2937 !important; color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
    .stDataFrame, table { color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

DB_CONN = sqlite3.connect("market_data.db", check_same_thread=False)
try:
    DB_CONN.execute("PRAGMA journal_mode=WAL;")
except Exception as e:
    logging.warning(f"WAL 模式啟用失敗: {e}")

def _safe_table_name(prefix, stock_id):
    """防止 SQL 注入：僅保留英數字元"""
    clean_id = ''.join(c for c in str(stock_id) if c.isalnum())
    return f"{prefix}_{clean_id}"

# ==================== 💾 2. 數據引擎 ====================
class DataEngine:
    @staticmethod
    def update_stock_list_if_needed(force=False):
        file_path = 'twse_listed_codes.csv'
        needs_update = force
        
        # 檢查檔案是否超過 7 天
        if not needs_update and os.path.exists(file_path):
            file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            if (datetime.datetime.now() - file_mtime).days < 7:
                needs_update = False
            else:
                needs_update = True
                
        if needs_update:
            try:
                logging.info("開始更新股票代碼清單...")
                url = "https://api.finmindtrade.com/api/v4/data"
                resp = requests.get(url, params={"dataset": "TaiwanStockInfo", "token": CONFIG["FINMIND_TOKEN"]}, timeout=10)
                if resp.status_code == 200 and 'data' in resp.json():
                    data = resp.json()['data']
                    if len(data) > 1000:
                        df = pd.DataFrame(data)
                        df_to_save = df[['stock_id', 'stock_name', 'industry_category']].rename(columns={'stock_id': 'code', 'stock_name': 'name', 'industry_category': 'category'})
                        df_to_save.to_csv(file_path, index=False, encoding='utf-8-sig')
                        logging.info("✅ 股票代碼清單更新完成！")
                        st.cache_data.clear() 
            except Exception as e:
                logging.error(f"❌ 自動更新股票清單失敗: {e}")

    @staticmethod
    @st.cache_data(ttl=3600)
    def load_stock_dict():
        for path in ['twse_listed_codes.csv', 'data/twse_listed_codes.csv']:
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path, encoding='utf-8-sig', header=0) # header=0 to skip the 'code,name,category' row
                    return dict(zip(df.iloc[:,0].astype(str).str.strip().str.zfill(4), df.iloc[:,1].astype(str).str.strip()))
                except: pass
        return {}

    @staticmethod
    def fetch_stock_data(stock_id, force_refresh=False):
        stock_id = str(stock_id).strip().zfill(4)
        table_name = _safe_table_name("price", stock_id)
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        # 取得目前時間資訊
        now = datetime.datetime.now()
        is_trading_time = now.weekday() < 5 and (9 <= now.hour < 14)
        
        if not force_refresh:
            try:
                with DB_LOCK:
                    df = pd.read_sql(f"SELECT * FROM {table_name}", DB_CONN, index_col="Date", parse_dates=["Date"])
                if not df.empty and all(col in df.columns for col in required_cols):
                    last_date = df.index.max().date()
                    # 如果資料是昨天的或更早，或者今天是交易時間且資料是今天的（但可能需要更新），則不直接回傳
                    if last_date < now.date() or (last_date == now.date() and is_trading_time):
                        pass # 繼續往下抓取新資料
                    else:
                        return DataEngine._precompute_indicators(df)
            except: pass

        df = pd.DataFrame()
        start_date = (datetime.datetime.now() - datetime.timedelta(days=250)).strftime("%Y-%m-%d")

        # 嘗試從 FinMind 獲取
        try:
            time.sleep(random.uniform(0.2, 0.5))
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

        # 如果 FinMind 失敗或沒資料，嘗試 yfinance
        if df.empty or 'Close' not in df.columns or (df.index.max().date() < now.date() and is_trading_time):
            for suffix in ['.TW', '.TWO']:
                try:
                    df_yf = yf.download(f"{stock_id}{suffix}", period="1y", progress=False)
                    if not df_yf.empty and len(df_yf) > 5:
                        if isinstance(df_yf.columns, pd.MultiIndex):
                            df_yf.columns = df_yf.columns.get_level_values(0)
                        df_yf.index = df_yf.index.tz_localize(None)
                        # 如果 yfinance 有更新的資料，則採用
                        if df.empty or df_yf.index.max() >= df.index.max():
                            df = df_yf
                            break
                except: continue

        if df.empty: return pd.DataFrame()
        
        # 確保必要的欄位存在且格式正確
        for col in required_cols:
            if col not in df.columns:
                # 嘗試修復常見欄位名稱問題
                for alt in [col.lower(), col.upper()]:
                    if alt in df.columns:
                        df[col] = df[alt]
                        break
        
        if not all(col in df.columns for col in required_cols): 
            return pd.DataFrame()
            
        df = df[required_cols].astype(float).ffill().dropna(subset=['Close'])
        try:
            with DB_LOCK:
                df.to_sql(table_name, DB_CONN, if_exists="replace", index=True)
        except: pass
        
        return DataEngine._precompute_indicators(df)

    @staticmethod
    def fetch_chips_data(stock_id, force_refresh=False):
        stock_id = str(stock_id).strip().zfill(4)
        table_name = _safe_table_name("chips", stock_id)
        
        if not force_refresh:
            try:
                with DB_LOCK:
                    df = pd.read_sql(f"SELECT * FROM {table_name}", DB_CONN, index_col="date", parse_dates=["date"])
                if not df.empty:
                    last_date = df.index.max().date()
                    now = datetime.datetime.now()
                    days_diff = (now.date() - last_date).days
                    # 修正週末快取失效問題：3 天內 (涵蓋六日) 且下午 5 點前視為有效
                    if days_diff == 0 or (days_diff <= 3 and now.hour < 17):
                        return df
            except: pass

        start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            time.sleep(random.uniform(0.2, 0.5))
            url = "https://api.finmindtrade.com/api/v4/data"
            resp = requests.get(url, params={"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": stock_id, "start_date": start_date, "token": CONFIG["FINMIND_TOKEN"]}, timeout=5)
            if resp.status_code == 200 and 'data' in resp.json() and len(resp.json()['data']) > 0:
                df = pd.DataFrame(resp.json()['data'])
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
                try:
                    with DB_LOCK:
                        df.to_sql(table_name, DB_CONN, if_exists="replace", index=True)
                except: pass
                return df
        except: pass
        return pd.DataFrame()

    @staticmethod
    def fetch_fundamental_data(stock_id, force_refresh=False):
        stock_id = str(stock_id).strip().zfill(4)
        table_name = _safe_table_name("fund", stock_id)
        
        if not force_refresh:
            try:
                with DB_LOCK:
                    df = pd.read_sql(f"SELECT * FROM {table_name}", DB_CONN, index_col="date", parse_dates=["date"])
                if not df.empty:
                    last_date = df.index.max()
                    if (datetime.datetime.now() - last_date).days < 40:
                        return df
            except: pass

        start_date = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
        try:
            time.sleep(random.uniform(0.2, 0.5))
            url = "https://api.finmindtrade.com/api/v4/data"
            resp = requests.get(url, params={"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date, "token": CONFIG["FINMIND_TOKEN"]}, timeout=5)
            if resp.status_code == 200 and 'data' in resp.json() and len(resp.json()['data']) > 0:
                df = pd.DataFrame(resp.json()['data'])
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
                try:
                    with DB_LOCK:
                        df.to_sql(table_name, DB_CONN, if_exists="replace", index=True)
                except: pass
                return df
        except: pass
        return pd.DataFrame()

    @staticmethod
    def fetch_global_news():
        url = "https://news.google.com/rss/search?q=%E5%9C%8B%E9%9A%9B%E8%B2%A1%E7%B6%93&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        try:
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.content)
            news_list = []
            for item in root.findall('.//item')[:5]:
                news_list.append({"title": item.find('title').text, "link": item.find('link').text})
            return news_list
        except: return []

    @staticmethod
    def _precompute_indicators(df):
        # 確保欄位名稱唯一，避免出現多個 'Close' 導致運算錯誤
        df = df.loc[:, ~df.columns.duplicated()].copy()
        
        # 強制轉換為 Series，避免 yfinance MultiIndex 導致選出 DataFrame
        def get_series(name):
            col = df[name]
            return col.iloc[:, 0] if isinstance(col, pd.DataFrame) else col

        try:
            close_s = get_series('Close')
            vol_s = get_series('Volume')
            high_s = get_series('High')
            low_s = get_series('Low')

            df['MA5'] = close_s.rolling(5).mean()
            df['MA20'] = close_s.rolling(20).mean()
            df['MA60'] = close_s.rolling(60).mean()
            df['VolMA5'] = vol_s.rolling(5).mean()
            
            # 計算壓力與支撐區間 (近20日高低點)
            df['Resistance'] = high_s.rolling(20).max()
            df['Support'] = low_s.rolling(20).min()
            
            # 計算買賣點訊號 (MA5 與 MA20 黃金交叉與死亡交叉)
            df['Signal'] = 0
            df.loc[(df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1)), 'Signal'] = 1 # 買入訊號
            df.loc[(df['MA5'] < df['MA20']) & (df['MA5'].shift(1) >= df['MA20'].shift(1)), 'Signal'] = -1 # 賣出訊號
            
            # RSI (14)
            delta = close_s.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            # 波動率 ATR (14)
            high_low = high_s - low_s
            high_close = (high_s - close_s.shift()).abs()
            low_close = (low_s - close_s.shift()).abs()
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            df['ATR'] = true_range.rolling(14).mean()
        except Exception as e:
            logging.error(f"指標計算失敗: {e}")
            
        return df

    @staticmethod
    @st.cache_data(ttl=3600)
    def fetch_index_data():
        try:
            df = yf.download("^TWII", period="1y", progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            return df['Close'].ffill()
        except: return pd.Series()

    # 🛡️ 整合 Telegram 與 LINE 發送引擎
    @staticmethod
    def broadcast_message(message):
        # 1. 發送 LINE Notify
        line_tokens = CONFIG.get("LINE_TOKENS", [])
        for token in line_tokens:
            try:
                requests.post(
                    "https://notify-api.line.me/api/notify",
                    headers={"Authorization": f"Bearer {token}"},
                    data={"message": message},
                    timeout=10
                )
            except Exception as e:
                logging.error(f"LINE Notify 推播失敗: {e}")
                
        # 1.5 發送 LINE Messaging API (官方帳號 Bot)
        line_bots = CONFIG.get("LINE_BOTS", [])
        for bot in line_bots:
            try:
                token = bot.get("channel_access_token", "")
                to_id = bot.get("to", "")
                if token and to_id:
                    requests.post(
                        "https://api.line.me/v2/bot/message/push",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"to": to_id, "messages": [{"type": "text", "text": message}]},
                        timeout=10
                    )
            except Exception as e:
                logging.error(f"LINE Bot 推播失敗: {e}")
            
        # 2. 發送 Telegram
        tg_token = CONFIG.get("TG_BOT_TOKEN")
        if tg_token:
            for chat_id in CONFIG.get("TG_CHAT_IDS", []):
                try:
                    tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                    requests.post(tg_url, json={"chat_id": str(chat_id), "text": message}, timeout=5)
                except Exception as e:
                    logging.error(f"Telegram 推播失敗: {e}")

# ==================== 📈 3. 策略與指標運算引擎 ====================
class StrategyEngine:
    @staticmethod
    def analyze_metrics(code, df_price, df_chips, df_fund, source="系統"):
        if df_price.empty or len(df_price) < 20: return None
        
        def safe_get(val, default): return default if pd.isna(val) else val
        
        latest = df_price.iloc[-1]
        c_price = latest['Close']
        c_vol = latest['Volume']
        rsi = latest.get('RSI', 50)
        ma5 = safe_get(latest.get('MA5'), c_price)
        ma20 = safe_get(latest.get('MA20'), c_price)
        ma60 = safe_get(latest.get('MA60'), c_price)
        vol_ma5 = safe_get(latest.get('VolMA5'), c_vol)
        
        scores = {'tech': 0, 'chips': 0, 'fund': 0}
        signals = []
        
        # --- 1. 技術面 (最高約 31 pts) ---
        # 趨勢與均線 (15 pts)
        if c_price > ma60 and ma20 > ma60: scores['tech'] += 5; signals.append("✅ 完美多頭排列")
        elif c_price > ma20: scores['tech'] += 3; signals.append("🟡 價格站上月線")
        
        if c_price > ma5: scores['tech'] += 3; signals.append("🚀 短線強勢 (MA5)")
        
        # 量能 (10 pts)
        if c_vol > vol_ma5 * 2.0: scores['tech'] += 10; signals.append("💥 成交量巨量爆發")
        elif c_vol > vol_ma5 * 1.3: scores['tech'] += 5; signals.append("📈 量能增溫")
        
        # 指標 (10 pts)
        if 35 < rsi < 65: scores['tech'] += 5; signals.append("🟢 RSI 健康 (未過熱)")
        elif rsi < 30: scores['tech'] += 8; signals.append("🛡️ RSI 超賣區 (潛在反彈)")
        elif rsi >= 80: scores['tech'] -= 10; signals.append("⚠️ RSI 嚴重超買")

        # 相對強度 RS (5 pts)
        df_index = DataEngine.fetch_index_data()
        if not df_index.empty:
            stock_ret = (c_price - df_price['Close'].iloc[-20]) / df_price['Close'].iloc[-20] if len(df_price) >= 20 else 0
            idx_ret = (df_index.iloc[-1] - df_index.iloc[-20]) / df_index.iloc[-20] if len(df_index) >= 20 else 0
            if stock_ret > idx_ret:
                scores['tech'] += 5; signals.append("📈 強於大盤 (RS)")
            
        # --- 2. 籌碼面優化 (35%) ---
        if not df_chips.empty and 'name' in df_chips.columns:
            df_foreign = df_chips[df_chips['name'].str.contains('外資', na=False)]
            df_trust = df_chips[df_chips['name'].str.contains('投信', na=False)]
            
            # 連買邏輯 (25 pts)
            f_buy_days = 0
            for i in range(1, min(len(df_foreign)+1, 6)):
                if df_foreign.iloc[-i]['buy'] > df_foreign.iloc[-i]['sell']: f_buy_days += 1
                else: break
            
            t_buy_days = 0
            for i in range(1, min(len(df_trust)+1, 6)):
                if df_trust.iloc[-i]['buy'] > df_trust.iloc[-i]['sell']: t_buy_days += 1
                else: break

            if f_buy_days >= 3: scores['chips'] += 15; signals.append(f"🌍 外資連買 {f_buy_days} 日")
            elif f_buy_days >= 1: scores['chips'] += 5; signals.append("🌍 外資今日買超")
            
            if t_buy_days >= 3: scores['chips'] += 20; signals.append(f"🏦 投信連買 {t_buy_days} 日")
            elif t_buy_days >= 1: scores['chips'] += 10; signals.append("🏦 投信今日買超")
            
            # 集中度 (10 pts) - 簡化判斷
            total_buy = df_chips['buy'].sum()
            total_sell = df_chips['sell'].sum()
            if total_buy > total_sell * 1.2: scores['chips'] += 10; signals.append("💎 籌碼高度集中")
        else: 
            # 數據缺失時給予中性分 (15 pts)，避免因 API 失敗導致評分過低
            scores['chips'] = 15
            signals.append("⚪ 籌碼數據不足 (中性)")

        # --- 3. 基本面優化 (30%) ---
        if not df_fund.empty and 'revenue_year_on_year_growth_rate' in df_fund.columns:
            latest_yoy = df_fund['revenue_year_on_year_growth_rate'].iloc[-1]
            # 營收成長 (20 pts)
            if latest_yoy > 50: scores['fund'] += 20; signals.append(f"🚀 營收爆發 ({latest_yoy}%)")
            elif latest_yoy > 20: scores['fund'] += 15; signals.append(f"📈 營收高成長 ({latest_yoy}%)")
            elif latest_yoy > 0: scores['fund'] += 10; signals.append(f"穩 營收正成長")
            
            # 趨勢 (10 pts)
            if len(df_fund) >= 3 and df_fund['revenue_year_on_year_growth_rate'].iloc[-1] > df_fund['revenue_year_on_year_growth_rate'].iloc[-2]:
                scores['fund'] += 10; signals.append("📈 成長動能轉強")
        else: 
            # 數據缺失時給予中性分 (10 pts)
            scores['fund'] = 10
            signals.append("⚪ 基本面數據不足 (中性)")

        total_score = sum(scores.values())
        
        # 調整閾值：更符合實戰觀察
        if total_score >= 75: status, status_color = "🔥🔥 強力買入", "#34d399"
        elif total_score >= 60: status, status_color = "🔥 買入訊號", "#10b981"
        elif total_score >= 40: status, status_color = "👀 觀察中", "#fbbf24"
        else: status, status_color = "⏸️ 觀望", "#9ca3af"
        
        # --- 4. 終極買點判斷 ---
        high_10 = df_price['High'].iloc[-11:-1].max() if len(df_price) >= 11 else df_price['High'].max()
        
        bias_20 = (c_price - ma20) / ma20 if ma20 > 0 else 0
        vol_ma5_yesterday = df_price['VolMA5'].iloc[-2] if len(df_price) > 1 else c_vol
        vol_yesterday = df_price['Volume'].iloc[-2] if len(df_price) > 1 else c_vol
        is_vol_contracted = vol_yesterday < vol_ma5_yesterday
        
        is_breakout = (c_price > high_10) and (c_vol > vol_ma5 * 1.8) and (c_price > ma5) and (rsi < 75) and (bias_20 < 0.15) and is_vol_contracted
        is_buy = is_breakout and (total_score >= 70)
        
        if is_buy:
            today = datetime.date.today().isoformat()
            if st.session_state.get('notified', {}).get(code) != today:
                msg = f"\n🎯 【{source}】精選買點通報\n標的：{code}\n現價：{round(c_price, 2)}\n評分：{total_score}/100\n戰術：🛡️ 高分放量突破"
                DataEngine.broadcast_message(msg)
                st.session_state.notified[code] = today

        high_5, low_5 = df_price['High'].tail(5).max(), df_price['Low'].tail(5).min()
        bull_power = max(10, min(90, int(((c_price - low_5) / (high_5 - low_5)) * 100) if high_5 != low_5 else 50))
        risk_score = min(int((c_vol / vol_ma5) * 35), 95) if vol_ma5 > 0 else 50
        up_prob = min(max(int(35 + bias_20 * 200), 15), 75) 
        
        df_vp = df_price.tail(60).copy()
        if df_vp['Close'].nunique() > 1:
            bins = pd.cut(df_vp['Close'], bins=4)
            vp_data = df_vp.groupby(bins, observed=False)['Volume'].sum()
            vp_labels, vp_values = [f"{b.left:.1f}-{b.right:.1f}" for b in vp_data.index], vp_data.values
        else:
            vp_labels, vp_values = [f"{c_price:.1f}"], [df_vp['Volume'].sum()]

        win_5d, total_5d, win_10d, total_10d = 0, 0, 0, 0
        if 'Signal' in df_price.columns:
            buy_signals = df_price[df_price['Signal'] == 1]
            for idx, row in buy_signals.iterrows():
                buy_idx = df_price.index.get_loc(idx)
                if buy_idx + 5 < len(df_price):
                    total_5d += 1
                    if df_price['Close'].iloc[buy_idx + 5] > row['Close']: win_5d += 1
                if buy_idx + 10 < len(df_price):
                    total_10d += 1
                    if df_price['Close'].iloc[buy_idx + 10] > row['Close']: win_10d += 1
        wr_5 = round(win_5d / total_5d * 100, 1) if total_5d > 0 else 0
        wr_10 = round(win_10d / total_10d * 100, 1) if total_10d > 0 else 0

        atr = df_price['ATR'].iloc[-1] if not pd.isna(df_price['ATR'].iloc[-1]) else c_price * 0.02
        stop_loss = round(c_price - 1.5 * atr, 2)
        take_profit = round(c_price + 2 * atr, 2)
        
        if c_price > ma5 and ma5 > ma20 and ma20 > ma60: trend_desc = "📈 強勢多頭創高"
        elif c_price < ma5 and ma5 > ma20: trend_desc = "🔄 多頭漲多回檔"
        elif c_price < ma20 and c_price > ma60: trend_desc = "⚠️ 跌破月線整理"
        elif c_price < ma60 and rsi < 30: trend_desc = "🛡️ 空頭跌深反彈"
        else: trend_desc = "📉 偏空弱勢格局"

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
            "vp_labels": vp_labels, "vp_values": vp_values, "df": df_price, "is_buy": is_buy,
            "stop_loss": stop_loss, "take_profit": take_profit, "trend_desc": trend_desc,
            "wr_5": wr_5, "wr_10": wr_10, "total_5d": total_5d, "total_10d": total_10d
        }

# ==================== 🏗️ 4. ETF 與產業分析引擎 ====================
class ETFEngine:
    # 產業翻譯對照表
    INDUSTRY_MAP = {
        "Semiconductors": "半導體",
        "Electronic Components": "電子零組件",
        "Computers & Peripheral Equipment": "電腦及週邊設備",
        "Communication & Networking": "通信網路",
        "Optoelectronics": "光電",
        "Other Electronics": "其他電子",
        "Electronic Products Distribution": "電子通路",
        "Information Service": "資訊服務",
        "Semiconductor Equipment & Materials": "半導體設備",
        "Banks": "銀行業",
        "Financial Services": "金融服務",
        "Insurance": "保險業",
        "Shipping": "航運",
        "Steel": "鋼鐵",
        "Chemicals": "化學",
        "Plastics": "塑膠",
        "Textiles": "紡織",
        "Food": "食品",
        "Automobiles": "汽車",
        "Retail": "零售",
        "Real Estate": "房地產",
        "Construction": "建材營造",
        "Trading & Consumer Goods": "貿易百貨",
        "Other": "其他"
    }

    @staticmethod
    def fetch_stock_industry(stock_id):
        """獲取股票所屬產業分類 (並翻譯為中文)"""
        stock_id = str(stock_id).strip().zfill(4)
        try:
            ticker = yf.Ticker(f"{stock_id}.TW")
            info = ticker.info
            industry_en = info.get('industryDisp', info.get('industry', 'Other'))
            return ETFEngine.INDUSTRY_MAP.get(industry_en, industry_en)
        except:
            return "電子/其他"

    @staticmethod
    def get_etf_holdings_mock(etf_id):
        """模擬熱門主動式/主題式 ETF 持股"""
        holdings = {
            "0050": ["2330", "2317", "2454", "2308", "2881", "2303", "2882", "3711", "2412", "2891"],
            "0056": ["2317", "2382", "2357", "3231", "2449", "2301", "3034", "3037", "2379", "6239"],
            "00878": ["2357", "2382", "3231", "2301", "2891", "2881", "2324", "2409", "2882", "2356"],
            "00919": ["2303", "2603", "2379", "3034", "2454", "2377", "2385", "6176", "3005", "5483"],
            "00929": ["2454", "2379", "3034", "2385", "3037", "2408", "2344", "3231", "2317", "2303"],
            "ACTIVE_AI": ["2330", "2317", "2382", "3231", "6669", "2357", "3017", "2376", "2454", "3515"]
        }
        return holdings.get(str(etf_id), [])

    @staticmethod
    def analyze_etf_sector_dist(etf_id):
        codes = ETFEngine.get_etf_holdings_mock(etf_id)
        if not codes: return None
        
        dist = {}
        stock_details = []
        for code in codes:
            industry = ETFEngine.fetch_stock_industry(code)
            dist[industry] = dist.get(industry, 0) + 1
            stock_details.append({"代碼": code, "產業": industry})
        
        return {"dist": dist, "details": stock_details}

# ==================== 🎨 5. 單頁視覺儀表板 ====================
def render_dashboard(code, stock_dict):
    with st.sidebar:
        with st.expander("🛠️ 系統診斷自檢", expanded=False):
            diag_results = SystemDiagnostics.run_checks()
            st.table(pd.DataFrame(diag_results))
            if any("❌" in r["狀態"] for r in diag_results):
                st.error("⚠️ 偵測到關鍵檔案缺失，請確認路徑。")
    
    with st.spinner(f"🔄 分析 {code} 戰情數據中..."):
        df_price = DataEngine.fetch_stock_data(code)
        df_chips = DataEngine.fetch_chips_data(code)
        df_fund = DataEngine.fetch_fundamental_data(code)
        metrics = StrategyEngine.analyze_metrics(code, df_price, df_chips, df_fund)
    
    if not metrics:
        st.error(f"⚠️ 無法獲取 {code} 的完整數據。請由左側切換標的。")
        return

    df = metrics['df']
    last_update_time = df.index.max().strftime("%Y-%m-%d %H:%M")
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

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"<h2>{full_name} <span style='color:{status_color}; font-size:1.5rem;'>{c_price:.2f} ({chg_pct:+.2f}%)</span></h2>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<p style='text-align:right; color:#888; margin-top:1.5rem;'>🕒 最後更新: {last_update_time}</p>", unsafe_allow_html=True)

    r1_c1, r1_c2, r1_c3 = st.columns([2, 1, 1])
    with r1_c1:
        st.markdown("<div class='metric-card'><div class='title-text'>1️⃣ 6️⃣ 主力意圖與成本分析</div>", unsafe_allow_html=True)
        fig_k = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線')])
        if not df['MA5'].isna().all(): fig_k.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#eab308', width=1), name='5MA'))
        if not df['MA20'].isna().all(): fig_k.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#60a5fa', width=1), name='20MA'))
        
        # 繪製壓力與支撐線
        if 'Resistance' in df.columns and not pd.isna(df['Resistance'].iloc[-1]):
            fig_k.add_hline(y=df['Resistance'].iloc[-1], line_dash="dash", line_color="#ef4444", annotation_text="近期壓力", annotation_position="top left", annotation_font_color="#ef4444")
        if 'Support' in df.columns and not pd.isna(df['Support'].iloc[-1]):
            fig_k.add_hline(y=df['Support'].iloc[-1], line_dash="dash", line_color="#10b981", annotation_text="近期支撐", annotation_position="bottom left", annotation_font_color="#10b981")
            
        # 標註買賣訊號點
        if 'Signal' in df.columns:
            buy_points = df[df['Signal'] == 1]
            if not buy_points.empty:
                fig_k.add_trace(go.Scatter(x=buy_points.index, y=buy_points['Low'] * 0.98, mode='markers', marker=dict(symbol='triangle-up', size=12, color='#10b981'), name='買入訊號'))
            sell_points = df[df['Signal'] == -1]
            if not sell_points.empty:
                fig_k.add_trace(go.Scatter(x=sell_points.index, y=sell_points['High'] * 1.02, mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ef4444'), name='賣出訊號'))

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
    st.markdown("### 🎯 實戰策略指引與回測")
    r_s1, r_s2, r_s3 = st.columns([1, 1, 1])
    with r_s1:
        st.markdown(f"""
            <div class='metric-card'>
                <div class='title-text'>📍 買賣點與趨勢</div>
                <p style='margin-bottom: 5px;'><strong>趨勢研判:</strong> {metrics['trend_desc']}</p>
                <p style='margin-bottom: 5px;'><strong>防守止損:</strong> <span style='color:#ef4444'>{metrics['stop_loss']}</span> (-1.5 ATR)</p>
                <p style='margin-bottom: 5px;'><strong>短期停利:</strong> <span style='color:#10b981'>{metrics['take_profit']}</span> (+2.0 ATR)</p>
            </div>
        """, unsafe_allow_html=True)
    with r_s2:
        st.markdown(f"""
            <div class='metric-card'>
                <div class='title-text'>🏆 歷史買入勝率 (5日)</div>
                <h2 style='text-align:center; margin: 5px 0; color:{"#10b981" if metrics["wr_5"] >= 50 else "#ef4444"};'>{metrics['wr_5']}%</h2>
                <p style='text-align:center; color:#888; font-size: 0.9rem;'>交易次數: {metrics['total_5d']} 次</p>
            </div>
        """, unsafe_allow_html=True)
    with r_s3:
        st.markdown(f"""
            <div class='metric-card'>
                <div class='title-text'>🏆 歷史買入勝率 (10日)</div>
                <h2 style='text-align:center; margin: 5px 0; color:{"#10b981" if metrics["wr_10"] >= 50 else "#ef4444"};'>{metrics['wr_10']}%</h2>
                <p style='text-align:center; color:#888; font-size: 0.9rem;'>交易次數: {metrics['total_10d']} 次</p>
            </div>
        """, unsafe_allow_html=True)

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
            st.progress(min(max(metrics['scores']['chips'] / 40, 0), 1.0))
            st.caption(f"得分: {metrics['scores']['chips']} / 40")
        with p2:
            st.write("📈 **技術面**")
            st.progress(min(max(metrics['scores']['tech'] / 30, 0), 1.0))
            st.caption(f"得分: {metrics['scores']['tech']} / 30")
        with p3:
            st.write("🏢 **基本面**")
            st.progress(min(max(metrics['scores']['fund'] / 30, 0), 1.0))
            st.caption(f"得分: {metrics['scores']['fund']} / 30")
            
        st.markdown("<div style='margin-top: 15px; display: flex; flex-wrap: wrap; gap: 10px;'>", unsafe_allow_html=True)
        for s in metrics['signals']: st.markdown(f"<div class='signal-item'>{s}</div>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

# ==================== 🚀 5. 主程式與擴充模組 ====================
def main():
    stock_dict = DataEngine.load_stock_dict()
    if 'notified' not in st.session_state: st.session_state.notified = {}
    
    WATCHLIST_FILE, ETF_FILE = 'watchlist.json', 'etf_list.json'

    def _load_json_file(path, default):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"讀取 {path} 失敗: {e}")
        return default

    if 'watchlist' not in st.session_state:
        st.session_state.watchlist = _load_json_file(WATCHLIST_FILE, ["2330", "2317", "3481"])
    if 'etf_list' not in st.session_state:
        st.session_state.etf_list = _load_json_file(ETF_FILE, ["0050", "0056", "00878", "00713", "00919"])

    with st.sidebar:
        st.title("🛡️ TACTICAL COMMAND")
        
        with st.expander("⚙️ 系統維護", expanded=False):
            if st.button("🔄 手動更新股票清單", use_container_width=True):
                with st.spinner("正在從 FinMind 獲取最新清單..."):
                    DataEngine.update_stock_list_if_needed(force=True)
                    st.success("清單更新完成，請重整頁面。")
                    st.rerun()
            st.caption("每週會自動檢查一次，亦可手動觸發。")

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
        if auto_monitor:
            st.success("✅ 循環監控已開啟 (每 5 分鐘掃描)")

    # --- 循環監控執行邏輯 ---
    if auto_monitor:
        st.markdown("### 📡 循環監控戰報 (自選股即時掃描)")
        m_col1, m_col2 = st.columns([2, 1])
        
        with m_col1:
            found_monitor = []
            codes_to_monitor = st.session_state.watchlist
            
            def monitor_task(c):
                # 強制更新以確保即時性 (在 DataEngine.fetch_stock_data 已有盤中邏輯)
                df_s = DataEngine.fetch_stock_data(c)
                if df_s.empty or len(df_s) < 20: return None
                
                df_chips = DataEngine.fetch_chips_data(c)
                df_fund = DataEngine.fetch_fundamental_data(c)
                res_s = StrategyEngine.analyze_metrics(c, df_s, df_chips, df_fund, source="循環監控")
                
                if res_s:
                    # 計算漲跌
                    last_c = df_s['Close'].iloc[-2] if len(df_s) > 1 else res_s['price']
                    chg = ((res_s['price'] - last_c) / last_c) * 100 if last_c > 0 else 0
                    return {"代碼": c, "名稱": stock_dict.get(c, ""), "現價": res_s['price'], "漲跌%": round(chg, 2), "評分": res_s['total_score'], "狀態": res_s['status']}
                return None

            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(monitor_task, codes_to_monitor))
                found_monitor = [r for r in results if r is not None]
            
            if found_monitor:
                monitor_df = pd.DataFrame(found_monitor)
                # 美化表格顯示
                def color_chg(val):
                    color = '#ef4444' if val > 0 else '#10b981' if val < 0 else 'white'
                    return f'color: {color}'
                
                # 解決 Pandas 版本相容性問題 (Styler.applymap -> Styler.map)
                styler = monitor_df.style
                if hasattr(styler, 'map'):
                    styled_df = styler.map(color_chg, subset=['漲跌%'])
                else:
                    styled_df = styler.applymap(color_chg, subset=['漲跌%'])
                    
                st.dataframe(styled_df, use_container_width=True, hide_index=True)
            else:
                st.info("⌛ 正在獲取監控數據...")
        
        with m_col2:
            st.markdown(f"""
                <div class='metric-card' style='padding: 15px;'>
                    <div class='title-text' style='margin-bottom:10px;'>⏱️ 監控狀態</div>
                    <p>監控數量: {len(st.session_state.watchlist)}</p>
                    <p>最後掃描: {datetime.datetime.now().strftime("%H:%M:%S")}</p>
                    <p style='font-size:0.8rem; color:#888;'>自動頻率: 300s</p>
                </div>
            """, unsafe_allow_html=True)

    if selected_code:
        render_dashboard(selected_code, stock_dict)

    with st.sidebar:
        with st.expander("☁️ 雲端同步與備份 (解決重啟消失)", expanded=False):
            st.caption("Streamlit Cloud 重啟後資料會還原。請將自選名單複製存檔，或在此貼回。")
            current_watchlist_str = ",".join(st.session_state.watchlist)
            new_watchlist_str = st.text_area("自選股代碼 (逗號隔開)", value=current_watchlist_str, help="例如: 2330,2317,2454")
            if st.button("🔄 同步名單", use_container_width=True):
                codes = [c.strip().zfill(4) for c in new_watchlist_str.split(",") if c.strip()]
                st.session_state.watchlist = codes
                with open(WATCHLIST_FILE, 'w') as f: json.dump(st.session_state.watchlist, f)
                st.success("同步成功！")
                st.rerun()

    st.markdown("---")
    
    # --- 新增：主動式 ETF 與產業分析分頁 ---
    st.subheader("🕵️ 主動式 ETF 與產業深度解析")
    etf_tab1, etf_tab2 = st.tabs(["📊 ETF 成分產業分佈", "🔍 產業連動掃描"])
    
    with etf_tab1:
        c1, c2 = st.columns([1, 2])
        with c1:
            target_etf = st.selectbox("選擇監測 ETF", ["0050", "0056", "00878", "00919", "00929", "ACTIVE_AI"])
            if st.button("🚀 啟動成分解析", use_container_width=True):
                with st.spinner("正在解析成分股產業分類..."):
                    res = ETFEngine.analyze_etf_sector_dist(target_etf)
                    if res:
                        st.session_state.etf_analysis = res
        
        if 'etf_analysis' in st.session_state:
            res = st.session_state.etf_analysis
            with c2:
                fig_pie = go.Figure(data=[go.Pie(labels=list(res['dist'].keys()), values=list(res['dist'].values()), hole=.3)])
                fig_pie.update_layout(template='plotly_dark', title=f"🎯 {target_etf} 持股產業權重分佈", height=400, margin=dict(t=50, b=20, l=20, r=20))
                st.plotly_chart(fig_pie, use_container_width=True)
            
            st.markdown("#### 📄 詳細成分清單")
            st.dataframe(pd.DataFrame(res['details']), use_container_width=True)

    with etf_tab2:
        st.info("💡 此功能將根據選定 ETF 的主要持股產業，自動掃描全市場中同產業且「三因子模型」達標的潛在飆股。")
        if 'etf_analysis' in st.session_state:
            top_sectors = sorted(st.session_state.etf_analysis['dist'].items(), key=lambda x: x[1], reverse=True)[:2]
            st.write(f"當前重點關注產業：**{', '.join([s[0] for s in top_sectors])}**")
            if st.button("🔍 執行產業連動篩選"):
                st.warning("功能開發中：將結合全市場掃描引擎進行過濾。")

    st.markdown("---")
    with st.expander("🌍 進階監控面板：多執行緒掃描 / 自訂 ETF / 國際新聞 / 實體籌碼", expanded=False):
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
                    df_s = DataEngine.fetch_stock_data(c)
                    if df_s.empty or len(df_s) < 20: return None
                    c_price, ma20 = df_s['Close'].iloc[-1], df_s['MA20'].iloc[-1]
                    if c_price < ma20: return None
                    
                    df_chips = DataEngine.fetch_chips_data(c)
                    df_fund = DataEngine.fetch_fundamental_data(c)
                    res_s = StrategyEngine.analyze_metrics(c, df_s, df_chips, df_fund, source="全市場掃描")
                    
                    if res_s and res_s['is_buy']:
                        return {"代碼": c, "名稱": stock_dict.get(c, ""), "價位": res_s['price'], "評分": res_s['total_score'], "狀態": "🔥 放量強勢股"}
                    return None

                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_map = {executor.submit(scan_task, c): c for c in codes_to_scan}
                    for future in as_completed(future_map):
                        completed += 1
                        try:
                            res_s = future.result()
                        except Exception as e:
                            logging.warning(f"掃描任務異常: {e}")
                            res_s = None
                        if res_s: found.append(res_s)
                        
                        if completed % 5 == 0 or completed == scan_limit:
                            elapsed = time.time() - start_time
                            eta = (elapsed / completed) * (scan_limit - completed)
                            p_bar.progress(completed / scan_limit)
                            s_text.markdown(f"**⏳ 正在掃描 ({completed}/{scan_limit}) | 耗時: {elapsed:.1f}s | 剩餘: {eta:.1f}s | 尋獲標的: {len(found)}**")
                
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