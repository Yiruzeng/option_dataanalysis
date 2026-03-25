import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf

# ==========================================
# 1. 系統初始化與【UI 視覺強勢鎖定】
# ==========================================
st.set_page_config(page_title="ProQuant 旗艦戰情室", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    /* 1. 全域背景與基礎深灰文字鎖定 */
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #F4F6F8 !important;
        color: #333333 !important;
    }

    /* 2. 側邊欄與內部標籤鎖定 */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #EBEBEB !important;
    }
    [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span {
        color: #333333 !important;
    }

    /* 3. 白色圓角卡片容器鎖定 */
    div[data-testid="stMetric"], div[data-testid="stDataFrame"], .stExpander {
        background-color: #FFFFFF !important;
        padding: 20px !important;
        border-radius: 16px !important; 
        border: 1px solid #F0F0F0 !important;
        box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.04) !important;
    }
    
    /* 4. 科技藍紫數字與指標數值鎖定 */
    div[data-testid="stMetricValue"] > div,
    div[data-testid="stMetricValue"] span,
    div[data-testid="stMetricValue"] p {
        color: #4F46E5 !important;
        font-weight: 400 !important;
        background: none !important;
        -webkit-text-fill-color: initial !important; 
    }
    
    /* 5. 強制純白按鈕文字鎖定 */
    .stButton>button, .stButton>button div, .stButton>button p, .stButton>button span {
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }
    .stButton>button {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%) !important;
        border: none !important;
        border-radius: 12px !important; 
        padding: 0.5rem 1rem !important;
        width: 100% !important;
        box-shadow: 0px 4px 10px rgba(79, 70, 229, 0.3) !important;
    }

    /* 6. 科技藍紫標題鎖定 */
    h1, h2, h3, h4, h1 span, h2 span, h3 span, h4 span {
        color: #4F46E5 !important;
        font-weight: bold !important;
    }
    
    /* 7. 其他文字鎖定深灰 */
    .stMarkdown p, .stMarkdown li, span[data-testid="stMarkdownContainer"] p {
        color: #333333 !important;
    }
    
    hr { border-color: #EBEBEB !important; }
</style>
""", unsafe_allow_html=True)

# 核心設定與匯率
CONTRACT_MULTIPLIERS = {
    "大台 (TX)": 1.0, "小台 (MTX)": 0.25, "微台 (TMF)": 0.05,
    "小那 (NQ)": 1.0, "微那 (MNQ)": 0.1, "大阪小日經 (JNM)": 1.0, "大阪微日經 (Micro JNM)": 0.1
}
DEFAULT_MARGINS = {
    "大台 (TX)": {"val": 348000, "curr": "TWD"}, "小台 (MTX)": {"val": 87000, "curr": "TWD"},
    "微台 (TMF)": {"val": 17400, "curr": "TWD"}, "小那 (NQ)": {"val": 36856, "curr": "USD"},
    "大阪小日經 (JNM)": {"val": 380684, "curr": "JPY"}
}

@st.cache_data(ttl=3600)
def get_exchange_rates():
    rates = {'USD': 32.50, 'JPY': 0.2100}
    try:
        usd = yf.Ticker("TWD=X").fast_info['last_price']
        jpy = yf.Ticker("JPYTWD=X").fast_info['last_price']
        rates['USD'] = round(usd, 2); rates['JPY'] = round(jpy, 4)
    except: pass
    return rates

# 2. 核心運算引擎
def parse_tv_file(file):
    try:
        df = pd.read_excel(file, sheet_name='List of trades') if file.name.endswith('.xlsx') else pd.read_csv(file)
        p_col = [c for c in df.columns if ('Profit' in c or 'Net P&L' in c) and '%' not in c][0]
        d_col = [c for c in df.columns if 'Date' in c][0]
        if 'Type' in df.columns:
            df = df[df['Type'].astype(str).str.contains('Exit|出場|平倉', case=False, na=False)].copy()
        df[d_col] = pd.to_datetime(df[d_col]).dt.tz_localize(None)
        if df[p_col].dtype == object:
            df[p_col] = df[p_col].replace({',': ''}, regex=True).astype(float)
        else:
            df[p_col] = df[p_col].astype(float)
        return df[[d_col, p_col]].rename(columns={d_col: 'Date', p_col: 'Base_Profit'}).sort_values('Date').reset_index(drop=True)
    except: return None

def calculate_strategy_metrics(df, sim_contract, sim_qty, margin_per_contract, exchange_rate, safety_multiplier, date_range):
    mask = (df['Date'].dt.date >= date_range[0]) & (df['Date'].dt.date <= date_range[1])
    df = df.loc[mask].copy()
    if sim_qty == 0:
        return {'df': pd.DataFrame(), 'margin_twd': 0, 'metrics': {'策略名稱': '', '設定口數': "0口", '歷史 MDD': 0, '目前回撤': 0, '系統建議資金': 0, '狀態': '⚪ 不列入分析'}}
    if df.empty: return None

    multiplier = CONTRACT_MULTIPLIERS.get(sim_contract, 1.0)
    df['Sim_Profit_TWD'] = df['Base_Profit'] * multiplier * sim_qty * exchange_rate
    margin_twd = margin_per_contract * sim_qty * exchange_rate
    df['Cum_Profit_TWD'] = df['Sim_Profit_TWD'].cumsum()
    mdd_abs = abs((df['Cum_Profit_TWD'] - df['Cum_Profit_TWD'].cummax()).min())
    suggested_cap = margin_twd + (mdd_abs * safety_multiplier)
    current_dd = (df['Cum_Profit_TWD'] - df['Cum_Profit_TWD'].cummax()).iloc[-1]
    
    return {
        'df': df, 'margin_twd': margin_twd,
        'metrics': {
            '策略名稱': '', '設定口數': f"{sim_qty}口", '歷史 MDD': mdd_abs, '目前回撤': current_dd,
            '系統建議資金': suggested_cap, '狀態': '🟢 穩定運行' if (abs(current_dd) < mdd_abs or mdd_abs == 0) else '🟠 壓力警戒'
        }
    }

# 3. UI 渲染
st.sidebar.title("💎 ProQuant 控制中心")
uploaded_files = st.sidebar.file_uploader("📂 1. 匯入 TV 策略檔案", accept_multiple_files=True)
rates = get_exchange_rates()
usd_rate = st.sidebar.number_input("USD/TWD 匯率", value=float(rates['USD']), step=0.1)
jpy_rate = st.sidebar.number_input("JPY/TWD 匯率", value=float(rates['JPY']), step=0.001, format="%.4f")
rate_map = {'TWD': 1.0, 'USD': usd_rate, 'JPY': jpy_rate}

st.sidebar.markdown("---")
st.sidebar.header("💰 2. 實戰資金與時空設定")
ui_total_cap = st.sidebar.number_input("目前可用總資金 (TWD)", min_value=0, value=1000000, step=10000)
ui_safety_mult = st.sidebar.slider("風險防禦倍數 (MDD * X)", 1.0, 5.0, 2.0, 0.5)

sim_configs = {}
global_min_date, global_max_date = None, None

if uploaded_files:
    for file in uploaded_files:
        df = parse_tv_file(file)
        if df is not None:
            f_min, f_max = df['Date'].min().date(), df['Date'].max().date()
            global_min_date = min(global_min_date, f_min) if global_min_date else f_min
            global_max_date = max(global_max_date, f_max) if global_max_date else f_max
    
    if global_min_date and global_max_date:
        ui_date_range = st.sidebar.date_input("⏳ 模擬時間軸區間", value=(global_min_date, global_max_date))
        for file in uploaded_files:
            st.sidebar.markdown(f"📝 {file.name}")
            c1, c2 = st.sidebar.columns([3, 2])
            sim_contract = c1.selectbox("合約", list(DEFAULT_MARGINS.keys()), key=f"c_{file.name}")
            sim_qty = c2.number_input("口數", min_value=0, value=1, step=1, key=f"q_{file.name}")
            sim_configs[file.name] = {'file': file, 'contract': sim_contract, 'qty': sim_qty, 'rate': rate_map[DEFAULT_MARGINS[sim_contract]['curr']]}
        run_btn = st.sidebar.button("🚀 開始執行時空邏輯診斷", type="primary", use_container_width=True)

if uploaded_files and ('run_btn' in locals() and run_btn) and len(ui_date_range) == 2:
    st.header(f"📊 跨商品多策略壓力監控 ({ui_date_range[0]} ~ {ui_date_range[1]})")
    all_metrics, all_trade_logs, total_port_margin_twd = [], [], 0
    
    for filename, config in sim_configs.items():
        df = parse_tv_file(config['file'])
        if df is not None:
            res = calculate_strategy_metrics(df, config['contract'], config['qty'], DEFAULT_MARGINS[config['contract']]['val'], config['rate'], ui_safety_mult, ui_date_range)
            if res:
                total_port_margin_twd += res['margin_twd']
                res['metrics']['策略名稱'] = filename.split('.')[0][:15]
                all_metrics.append(res['metrics'])
                if config['qty'] > 0 and not res['df'].empty:
                    temp = res['df'][['Date', 'Sim_Profit_TWD']].copy()
                    temp['Source'] = res['metrics']['策略名稱']; all_trade_logs.append(temp)

    if all_trade_logs:
        comb_raw = pd.concat(all_trade_logs).sort_values('Date').reset_index(drop=True)
        comb_raw['Portfolio_Cum'] = comb_raw['Sim_Profit_TWD'].cumsum()
        comb_raw['Port_Drawdown'] = comb_raw['Portfolio_Cum'] - comb_raw['Portfolio_Cum'].cummax()
        
        # 戰情卡片顯示
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏆 組合總淨利", f"${comb_raw['Portfolio_Cum'].iloc[-1]:,.0f}")
        c2.metric("📉 組合歷史最大回撤", f"-${abs(comb_raw['Port_Drawdown'].min()):,.0f}")
        c3.metric("💰 目前投入總資金", f"${ui_total_cap:,.0f}")
        c4.metric("🛡️ 組合資金狀態", "✅ 充裕" if ui_total_cap >= pd.DataFrame(all_metrics)['系統建議資金'].sum() else "🚨 警訊")

        # 🌟 核心：藍橘熱力圖 🌟
        with st.expander("📅 歷年每月損益熱力分析 (Heatmap) - 藍橘專業版", expanded=True):
            df_h = comb_raw.copy()
            df_h['Year'] = df_h['Date'].dt.year; df_h['Month'] = df_h['Date'].dt.month
            month_pivot = df_h.pivot_table(index='Year', columns='Month', values='Sim_Profit_TWD', aggfunc='sum').fillna(0)
            for m in range(1, 13): 
                if m not in month_pivot.columns: month_pivot[m] = 0
            month_pivot = month_pivot[sorted(month_pivot.columns)]
            month_pivot.columns = [f"{m}月" for m in month_pivot.columns]
            month_pivot['TOTAL'] = month_pivot.sum(axis=1)
            
            abs_max = month_pivot.replace(0, np.nan).abs().max().max()
            def style_heatmap(val):
                if val == 0 or pd.isna(val): return 'background-color: #F3F4F6; color: #9CA3AF; text-align: center;'
                alpha = min(abs(val) / abs_max * 0.7 + 0.1, 0.9) if abs_max > 0 else 0.5
                color = f'rgba(79, 70, 229, {alpha})' if val > 0 else f'rgba(249, 115, 22, {alpha})'
                return f'background-color: {color}; color: #FFFFFF; font-weight: 500; text-align: center;'
            st.dataframe(month_pivot.style.applymap(style_heatmap).format("${:,.0f}"), use_container_width=True)

        # 策略明細表 (含反灰)
        st.markdown("#### 📋 策略詳細診斷明細表")
        display_df = pd.DataFrame(all_metrics)
        for col in ['系統建議資金', '歷史 MDD', '目前回撤']: 
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}")
        st.dataframe(display_df.style.apply(lambda r: ['color: #9CA3AF; background-color: #F9FAFB;' if r['設定口數'] == "0口" else '' for _ in r], axis=1), use_container_width=True, hide_index=True)

else:
    st.markdown('<div style="text-align: center; margin-top: 10vh;"><h1>Welcome to ProQuant</h1><p>請上傳策略檔案並設定模擬條件以啟動戰情室。</p></div>', unsafe_allow_html=True)