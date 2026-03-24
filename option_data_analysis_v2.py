import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf

# ==========================================
# 1. 系統初始化與視覺樣式定義 (藍紫科技白底風格)
# ==========================================
st.set_page_config(page_title="ProQuant 旗艦戰情室", page_icon="🛡️", layout="wide")

# 注入自定義 CSS (修正 Emoji 滿版色塊問題)
st.markdown("""
<style>
    /* 整體背景色 (非常淺的灰白，凸顯白色圓角卡片) */
    .stApp {
        background-color: #F4F6F8;
        color: #333333;
    }
    
    /* 側邊欄背景改為純白 */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #EBEBEB;
    }

    /* 數據卡片、表格、擴展面板 - 白色大圓角卡片帶輕微陰影 */
    div[data-testid="stMetric"], div[data-testid="stDataFrame"], .stExpander {
        background-color: #FFFFFF !important;
        padding: 20px !important;
        border-radius: 16px !important; 
        border: 1px solid #F0F0F0 !important;
        box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.04) !important;
    }
    
    /* Metric 標籤顏色微調 */
    div[data-testid="stMetricLabel"] > div {
        color: #6B7280 !important;
        font-weight: 500;
    }
    
    /* Metric 數值改為單一科技藍 (移除漸層，保護 Emoji 原色) */
    div[data-testid="stMetricValue"] > div {
        color: #4F46E5 !important;
        font-weight: 400;
    }

    /* 藍紫色科技按鈕 (按鈕不含 Emoji 文字，保留漸層) */
    .stButton>button {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important; 
        padding: 0.5rem 1rem !important;
        font-weight: 600 !important;
        width: 100%;
        box-shadow: 0px 4px 10px rgba(79, 70, 229, 0.3) !important;
        transition: all 0.3s ease-in-out;
    }
    .stButton>button:hover {
        box-shadow: 0px 6px 15px rgba(124, 58, 237, 0.5) !important;
        transform: translateY(-1px);
    }

    /* 文字輸入框與下拉選單外框設計 */
    div[data-testid="stTextInput"] div[data-baseweb="input"], 
    .stSelectbox [data-testid="stSelectboxInput"], 
    .stNumberInput input, .stFileUploader section {
        border-radius: 8px !important;
        border: 1px solid #D1D5DB !important;
        background-color: #FFFFFF !important;
        transition: all 0.2s ease-in-out;
    }

    /* 標題改為單一科技藍 (移除漸層，保護 Emoji 原色) */
    h1, h2, h3, h4 {
        color: #4F46E5 !important;
        font-weight: bold;
    }
    
    /* 分隔線改為柔和灰色 */
    hr {
        border-color: #EBEBEB !important;
    }
</style>
""", unsafe_allow_html=True)

# 契約價值倍率設定
CONTRACT_MULTIPLIERS = {
    "大台 (TX)": 1.0, "小台 (MTX)": 0.25, "微台 (TMF)": 0.05,
    "小那 (NQ)": 1.0, "微那 (MNQ)": 0.1,
    "小標 (ES)": 1.0, "微標 (MES)": 0.1,
    "大阪小日經 (JNM)": 1.0, "大阪微日經 (Micro JNM)": 0.1,
    "黃金 (GC)": 1.0, "微黃金 (MGC)": 0.1 
}

# 原始保證金資訊
DEFAULT_MARGINS = {
    "大台 (TX)": {"val": 348000, "curr": "TWD"},
    "小台 (MTX)": {"val": 87000, "curr": "TWD"},
    "微台 (TMF)": {"val": 17400, "curr": "TWD"},
    "小那 (NQ)": {"val": 36856, "curr": "USD"},
    "微那 (MNQ)": {"val": 3686, "curr": "USD"},
    "小標 (ES)": {"val": 24279, "curr": "USD"},
    "微標 (MES)": {"val": 2428, "curr": "USD"},
    "大阪小日經 (JNM)": {"val": 380684, "curr": "JPY"},      
    "大阪微日經 (Micro JNM)": {"val": 37858, "curr": "JPY"},
    "黃金 (GC)": {"val": 32240, "curr": "USD"},      
    "微黃金 (MGC)": {"val": 3224, "curr": "USD"}     
}

@st.cache_data(ttl=3600)
def get_exchange_rates():
    rates = {'USD': 32.50, 'JPY': 0.2100}
    try:
        usd = yf.Ticker("TWD=X").fast_info['last_price']
        jpy = yf.Ticker("JPYTWD=X").fast_info['last_price']
        rates['USD'] = round(usd, 2)
        rates['JPY'] = round(jpy, 4)
    except: pass
    return rates

# ==========================================
# 2. 核心量化解析與邏輯診斷引擎
# ==========================================
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
    except Exception as e:
        st.error(f"解析失敗: {e}"); return None

def calculate_strategy_metrics(df, sim_contract, sim_qty, margin_per_contract, exchange_rate, safety_multiplier):
    multiplier = CONTRACT_MULTIPLIERS.get(sim_contract, 1.0)
    df['Sim_Profit_TWD'] = df['Base_Profit'] * multiplier * sim_qty * exchange_rate
    margin_twd = margin_per_contract * sim_qty * exchange_rate

    df['Cum_Profit_TWD'] = df['Sim_Profit_TWD'].cumsum()
    df['HWM_TWD'] = df['Cum_Profit_TWD'].cummax()
    df['Drawdown_TWD'] = df['Cum_Profit_TWD'] - df['HWM_TWD']
    
    total_net_profit = df['Sim_Profit_TWD'].sum()
    wins = df[df['Sim_Profit_TWD'] > 0]['Sim_Profit_TWD']
    losses = df[df['Sim_Profit_TWD'] < 0]['Sim_Profit_TWD']
    
    profit_factor = (wins.sum() / abs(losses.sum())) if not losses.empty else 1.0
    win_rate = (len(wins) / len(df) * 100) if not df.empty else 0
    
    is_loss = (df['Sim_Profit_TWD'] <= 0).astype(int)
    max_consecutive_losses = is_loss * (is_loss.groupby((is_loss != is_loss.shift()).cumsum()).cumcount() + 1)

    is_new_high = df['Cum_Profit_TWD'] >= df['HWM_TWD']
    avg_rec_days = 0
    curr_under_days = 0
    if sim_qty > 0:
        recovery_times = df.groupby(is_new_high.cumsum())['Date'].apply(lambda x: (x.max() - x.min()).days)
        valid_rec = recovery_times.iloc[:-1][recovery_times.iloc[:-1] > 0]
        avg_rec_days = valid_rec.mean() if not valid_rec.empty else 0
        curr_under_days = (df['Date'].max() - df[is_new_high]['Date'].max()).days if any(is_new_high) else 0

    mdd_abs = abs(df['Drawdown_TWD'].min())
    initial_capital_needed = margin_twd + (mdd_abs * safety_multiplier)
    
    df['Date_Only'] = df['Date'].dt.normalize()
    full_range = pd.date_range(start=df['Date_Only'].min(), end=df['Date_Only'].max(), freq='D')
    daily_p = df.groupby('Date_Only')['Sim_Profit_TWD'].sum().reindex(full_range, fill_value=0)
    
    if initial_capital_needed > 0 and daily_p.std() != 0:
        daily_returns = daily_p / initial_capital_needed
        sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(365))
    else:
        sharpe = 0
    
    current_dd = df['Drawdown_TWD'].iloc[-1]
    dd_ratio = (abs(current_dd) / mdd_abs) if mdd_abs > 0 else 0
    if sim_qty == 0:
        status = '⚪ 不列入分析'
    elif dd_ratio >= 1.5: status = '🔴 策略失效'
    elif dd_ratio >= 1.0: status = '🟠 進入未知'
    elif dd_ratio >= 0.8 or (not pd.isna(avg_rec_days) and curr_under_days > (avg_rec_days * 2)): status = '🟡 性能鈍化'
    else: status = '🟢 穩定運行'
    
    return {
        'df': df, 'margin_twd': margin_twd,
        'metrics': {
            '策略名稱': '', '設定口數': f"{sim_qty}口",
            '獲利因子': f"{profit_factor:.2f}",
            '勝率': f"{win_rate:.1f}%",
            '夏普值': f"{sharpe:.2f}",
            '歷史 MDD': mdd_abs,
            '目前回撤': current_dd,
            'MDD佔比': f"{(dd_ratio*100):.1f}%",
            '均恢復期': f"{int(avg_rec_days) if not pd.isna(avg_rec_days) else 0}天",
            '目前套牢': f"{int(curr_under_days)}天",
            '系統建議資金': initial_capital_needed,
            '狀態': status
        }
    }

# ==========================================
# 3. UI 控制台 (側邊欄)
# ==========================================
st.sidebar.title("💎 ProQuant 控制中心")
uploaded_files = st.sidebar.file_uploader("📂 1. 匯入 TV 策略檔案", accept_multiple_files=True)

rates = get_exchange_rates()
st.sidebar.markdown("### 📊 參數對齊設定")
usd_rate = st.sidebar.number_input("USD/TWD 匯率", value=float(rates['USD']), step=0.1)
jpy_rate = st.sidebar.number_input("JPY/TWD 匯率", value=float(rates['JPY']), step=0.001, format="%.4f")
rate_map = {'TWD': 1.0, 'USD': usd_rate, 'JPY': jpy_rate}

st.sidebar.markdown("---")
st.sidebar.header("💰 2. 實戰資金配置")
ui_total_cap = st.sidebar.number_input("目前可用總資金 (TWD)", min_value=0, value=1000000, step=10000)
ui_safety_mult = st.sidebar.slider("風險防禦倍數 (MDD * X)", 1.0, 5.0, 2.0, 0.5)

with st.sidebar.expander("🛡️ 3. 商品保證金調整"):
    ui_margins = {c: st.number_input(f"{c}", value=v['val'], step=100) for c, v in DEFAULT_MARGINS.items()}

sim_configs = {}
if uploaded_files:
    st.sidebar.markdown("---")
    for file in uploaded_files:
        st.sidebar.markdown(f"📝 {file.name}")
        c1, c2 = st.sidebar.columns([3, 2])
        sim_contract = c1.selectbox("轉換合約", list(DEFAULT_MARGINS.keys()), key=f"c_{file.name}")
        sim_qty = c2.number_input("實戰口數", min_value=0, value=1, step=1, key=f"q_{file.name}")
        sim_configs[file.name] = {'file': file, 'contract': sim_contract, 'qty': sim_qty, 'rate': rate_map[DEFAULT_MARGINS[sim_contract]['curr']]}
    
    run_btn = st.sidebar.button("🚀 開始執行邏輯診斷", type="primary", use_container_width=True)

# ==========================================
# 4. 儀表板渲染 (包含空白狀態的歡迎畫面)
# ==========================================
if uploaded_files and ('run_btn' in locals() and run_btn):
    # --- 戰情室主畫面 ---
    st.header("📊 跨商品多策略壓力監控儀表板")

    with st.expander("📘 系統指標與安全定義說明", expanded=False):
        st.markdown("""
        ### 1. 策略壓力紅綠燈 (單一策略有效性)
        * **🟢 穩定運行**：目前回撤 < 歷史 MDD 的 80%。
        * **🟡 性能鈍化**：目前回撤達 80%~100%，或套牢天數 > 均恢復期 × 2。
        * **🟠 進入未知**：目前回撤達 100%~150% (破底)。建議減碼。
        * **🔴 策略失效**：目前回撤 > 150%。建議強制停機。

        ### 2. 組合資金安全狀態 (對比您的可用資金)
        * **🛡️ 極度安全 (Robust)**：目前總資金 > 建議資金的 1.5 倍。
        * **✅ 資金充裕 (Safe)**：目前總資金 >= 系統建議資金。
        * **⚠️ 緩衝不足 (Warning)**：目前總資金 < 建議資金，但能覆蓋 (組合MDD + 保證金)。
        * **🚨 斷頭風險 (Danger)**：目前總資金 < 組合MDD + 基本保證金。
        """)

    all_metrics, all_trade_logs, total_port_margin_twd = [], [], 0
    strategy_names = []
    
    for filename, config in sim_configs.items():
        df = parse_tv_file(config['file'])
        if df is not None:
            res = calculate_strategy_metrics(df, config['contract'], config['qty'], ui_margins[config['contract']], config['rate'], ui_safety_mult)
            total_port_margin_twd += res['margin_twd']
            s_name = filename.split('.')[0][:15]
            res['metrics']['策略名稱'] = s_name
            strategy_names.append(s_name)
            all_metrics.append(res['metrics'])
            if config['qty'] > 0:
                temp = res['df'][['Date', 'Sim_Profit_TWD']].copy()
                temp['Source'] = s_name
                all_trade_logs.append(temp)
    
    if all_trade_logs:
        comb_full = pd.concat(all_trade_logs).sort_values('Date').reset_index(drop=True)
        comb_full['Portfolio_Cum_Profit'] = comb_full['Sim_Profit_TWD'].cumsum()
        comb_full['Port_HWM'] = comb_full['Portfolio_Cum_Profit'].cummax()
        comb_full['Port_Drawdown'] = comb_full['Portfolio_Cum_Profit'] - comb_full['Port_HWM']
        
        total_profit = comb_full['Portfolio_Cum_Profit'].iloc[-1]
        total_mdd = abs(comb_full['Port_Drawdown'].min())
        metrics_df = pd.DataFrame(all_metrics)
        total_suggested_cap = metrics_df['系統建議資金'].sum()
        
        comb_full['Date_Only'] = comb_full['Date'].dt.normalize()
        port_daily = comb_full.groupby('Date_Only')['Sim_Profit_TWD'].sum()
        f_range = pd.date_range(start=comb_full['Date_Only'].min(), end=comb_full['Date_Only'].max(), freq='D')
        port_daily_aligned = port_daily.reindex(f_range, fill_value=0)
        
        if total_suggested_cap > 0 and port_daily_aligned.std() != 0:
            port_returns = port_daily_aligned / total_suggested_cap
            port_sharpe = (port_returns.mean() / port_returns.std() * np.sqrt(365))
        else:
            port_sharpe = 0
            
        p_current_dd = comb_full['Port_Drawdown'].iloc[-1]
        p_dd_dist = (abs(p_current_dd) / total_mdd * 100) if total_mdd != 0 else 0

        if ui_total_cap >= total_suggested_cap * 1.5: s_status = "🛡️ 極度安全 (Robust)"
        elif ui_total_cap >= total_suggested_cap: s_status = "✅ 資金充裕 (Safe)"
        elif ui_total_cap >= (total_mdd + total_port_margin_twd): s_status = "⚠️ 緩衝不足 (Warning)"
        else: s_status = "🚨 斷頭風險 (Danger)"

        st.markdown("<h4 style='color: #333333;'>🏆 綜合資金水位戰情室</h4>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏆 組合總淨利", f"${total_profit:,.0f}")
        c2.metric("📉 組合歷史最大回撤", f"-${total_mdd:,.0f}")
        c3.metric("💰 目前投入總資金", f"${ui_total_cap:,.0f}")
        c4.metric("🛡️ 組合資金狀態", s_status)

        st.markdown("<br>", unsafe_allow_html=True)
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("🔥 實戰總報酬率", f"{(total_profit/ui_total_cap*100):.1f}%" if ui_total_cap > 0 else "0%")
        c6.metric("🚨 目前最新回撤", f"${p_current_dd:,.0f}", f"距離破底: {p_dd_dist:.1f}%", delta_color="inverse")
        c7.metric("💡 系統建議資金", f"${total_suggested_cap:,.0f}", help="基於 (保證金 + MDD * 倍數) 算出的科學建議金額")
        c8.metric("📊 綜合夏普值 (Sharpe)", f"{port_sharpe:.2f}")

        st.markdown("<h4 style='margin-top: 30px; color: #333333;'>📋 策略風險診斷明細表</h4>", unsafe_allow_html=True)
        display_df = metrics_df.copy()
        for col in ['系統建議資金', '歷史 MDD', '目前回撤']:
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)
        col_pie, col_chart = st.columns([1, 2.2])
        with col_pie:
            st.markdown("<h4 style='color: #333333;'>🛡️ 風險貢獻佔比 (基於 MDD)</h4>", unsafe_allow_html=True)
            pie_fig = px.pie(metrics_df[metrics_df['歷史 MDD']>0], values='歷史 MDD', names='策略名稱', hole=0.4, color_discrete_sequence=px.colors.sequential.Purp)
            pie_fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color="#333333", margin=dict(t=30, b=0, l=0, r=0))
            st.plotly_chart(pie_fig, use_container_width=True)

        with col_chart:
            st.markdown("<h4 style='color: #333333;'>📈 組合與單一策略結算對比</h4>", unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=comb_full['Date'], y=comb_full['Portfolio_Cum_Profit'], name='⭐ 組合總淨利', line=dict(color='#4F46E5', width=4)))
            fig.add_trace(go.Scatter(x=comb_full['Date'], y=comb_full['Port_Drawdown'], name='🔻 組合總回撤', fill='tozeroy', line=dict(width=0), fillcolor='rgba(239, 68, 68, 0.15)', yaxis='y2'))
            
            colors = px.colors.qualitative.Prism
            for idx, name in enumerate(strategy_names):
                strat_raw = comb_full[comb_full['Source'] == name]
                if not strat_raw.empty:
                    fig.add_trace(go.Scatter(x=strat_raw['Date'], y=strat_raw['Sim_Profit_TWD'].cumsum(), name=f'🔹 {name}', visible='legendonly', line=dict(width=1.5, color=colors[idx % len(colors)])))
            
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font_color="#333333", height=480,
                hovermode="x unified",
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor='#E5E7EB', title="淨值 (TWD)"),
                yaxis2=dict(overlaying='y', side='right', showgrid=False, title="回撤 (TWD)"),
                margin=dict(t=30, b=20, l=20, r=20)
            )
            st.plotly_chart(fig, use_container_width=True)

else:
    # ==========================================
    # --- 歡迎與引導畫面 (Empty State) ---
    # ==========================================
    st.markdown("""
    <div style="text-align: center; margin-top: 5vh; margin-bottom: 30px;">
        <h1 style="font-size: 3rem;">Welcome to ProQuant</h1>
        <p style="color: #6B7280; font-size: 1.1rem; font-weight: 500;">
            期貨多策略風險防禦與績效統計分析<br>
            結合部位資金控管，打造穩健的量化交易護城河。
        </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info("💡 **系統準備就緒，請依照以下步驟啟動您的戰情室：**")
        
        # 🌟 修正縮排：將 HTML 標籤全部靠左，避免 Markdown 誤判為程式碼區塊
        st.markdown("""
<div style="background-color: #FFFFFF; padding: 30px; border-radius: 16px; box-shadow: 0px 4px 12px rgba(0,0,0,0.04); border: 1px solid #F0F0F0;">
<h4 style="margin-top: 0;">Step 1. 匯入策略檔案</h4>
<p style="color: #6B7280; margin-bottom: 20px; line-height: 1.6;">請從左側面板上傳由 TradingView 匯出的交易清單 (支援 <code>.csv</code> 或 <code>.xlsx</code> 格式)。您可同時上傳多個策略進行投資組合分析。</p>

<h4>Step 2. 實戰資金與風險設定</h4>
<p style="color: #6B7280; margin-bottom: 20px; line-height: 1.6;">輸入您準備投入的「目前可用總資金」，並調整「風險防禦倍數」。系統將以此評估您的帳戶斷頭風險與安全狀態。</p>

<h4>Step 3. 調整商品與口數</h4>
<p style="color: #6B7280; margin-bottom: 20px; line-height: 1.6;">檔案讀取後，左側會出現策略列表。請為每個策略選擇正確的「期貨合約」，並設定預計的「實戰口數」（設為 0 則不計入組合）。</p>

<h4>Step 4. 執行邏輯診斷</h4>
<p style="color: #6B7280; margin-bottom: 0; line-height: 1.6;">確認設定無誤後，點擊左側下方的 <b>「開始執行邏輯診斷」</b> 按鈕，即可生成您的專屬壓力測試儀表板！</p>
</div>
        """, unsafe_allow_html=True)