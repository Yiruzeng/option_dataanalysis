import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf

# ==========================================
# 1. 系統初始化與大環境設定
# ==========================================
st.set_page_config(page_title="ProQuant 期貨多策略分析系統", page_icon="📊", layout="wide")

CONTRACT_MULTIPLIERS = {
    "大台 (TX)": 1.0, "小台 (MTX)": 0.25, "微台 (TMF)": 0.05,
    "小那 (NQ)": 1.0, "微那 (MNQ)": 0.1,
    "小標 (ES)": 1.0, "微標 (MES)": 0.1,
    "大阪小日經 (JNM)": 1.0, "大阪微日經 (Micro JNM)": 0.1
}

# 🌟 依據您的需求，更新日經系列保證金
DEFAULT_MARGINS = {
    "大台 (TX)": {"val": 348000, "curr": "TWD"},
    "小台 (MTX)": {"val": 87000, "curr": "TWD"},
    "微台 (TMF)": {"val": 17400, "curr": "TWD"},
    "小那 (NQ)": {"val": 36856, "curr": "USD"},
    "微那 (MNQ)": {"val": 3686, "curr": "USD"},
    "小標 (ES)": {"val": 24279, "curr": "USD"},
    "微標 (MES)": {"val": 2428, "curr": "USD"},
    "大阪小日經 (JNM)": {"val": 398595, "curr": "JPY"},      
    "大阪微日經 (Micro JNM)": {"val": 39860, "curr": "JPY"}   
}

@st.cache_data(ttl=3600)
def get_exchange_rates():
    rates = {'USD': 32.50, 'JPY': 0.2100}
    try:
        usd = yf.Ticker("TWD=X").fast_info['last_price']
        jpy = yf.Ticker("JPYTWD=X").fast_info['last_price']
        rates['USD'] = round(usd, 2)
        rates['JPY'] = round(jpy, 4)
    except:
        pass
    return rates

# ==========================================
# 2. 核心資料萃取與量化運算引擎
# ==========================================
def parse_tv_file(file):
    try:
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, sheet_name='List of trades')
        else:
            df = pd.read_csv(file)
            
        profit_col_candidates = [c for c in df.columns if ('Profit' in c or 'Net P&L' in c) and '%' not in c]
        if not profit_col_candidates:
            st.error(f"❌ 找不到獲利欄位，請確認 {file.name} 格式。")
            return None
        profit_col = profit_col_candidates[0]
        
        date_col_candidates = [c for c in df.columns if 'Date' in c]
        if not date_col_candidates:
            st.error(f"❌ 找不到時間欄位，請確認 {file.name} 格式。")
            return None
        date_col = date_col_candidates[0]
        
        if 'Type' in df.columns:
            df = df[df['Type'].astype(str).str.contains('Exit|出場|平倉', case=False, na=False)].copy()
        
        if df.empty:
            st.warning(f"⚠️ 檔案 {file.name} 中沒有有效的平倉紀錄，已自動略過。")
            return None
            
        df[date_col] = pd.to_datetime(df[date_col])
        
        if df[profit_col].dtype == object:
            df[profit_col] = df[profit_col].replace({',': ''}, regex=True).astype(float)
        else:
            df[profit_col] = df[profit_col].astype(float)
        
        clean_df = df[[date_col, profit_col]].rename(columns={date_col: 'Date', profit_col: 'Base_Profit'})
        clean_df = clean_df.sort_values('Date').reset_index(drop=True)
        return clean_df

    except Exception as e:
        st.error(f"檔案解析失敗 {file.name}: 系統錯誤訊息 {e}")
        return None

def calculate_strategy_metrics(df, sim_contract, sim_qty, margin_per_contract, exchange_rate, contract_curr, target_return_pct):
    start_date = pd.to_datetime(df['Date']).min().strftime('%Y-%m-%d')
    end_date = pd.to_datetime(df['Date']).max().strftime('%Y-%m-%d')
    
    multiplier = CONTRACT_MULTIPLIERS.get(sim_contract, 1.0)
    df['Sim_Profit_Native'] = df['Base_Profit'] * multiplier * sim_qty
    df['Sim_Profit_TWD'] = df['Sim_Profit_Native'] * exchange_rate
    margin_twd = margin_per_contract * sim_qty * exchange_rate

    df['Cum_Profit_TWD'] = df['Sim_Profit_TWD'].cumsum()
    df['HWM_TWD'] = df['Cum_Profit_TWD'].cummax()
    df['Drawdown_TWD'] = df['Cum_Profit_TWD'] - df['HWM_TWD']
    
    # --- 新增：套牢時間與歷史恢復期計算 ---
    # 只要 Cum_Profit_TWD >= HWM_TWD，就代表創新高 (未套牢)
    is_new_high = df['Cum_Profit_TWD'] >= df['HWM_TWD']
    
    # 利用 cumsum() 將不同的「回撤區間」分組
    dd_groups = is_new_high.cumsum()
    
    # 計算每個區間的持續天數
    recovery_times = df.groupby(dd_groups)['Date'].apply(lambda x: (x.max() - x.min()).days)
    
    # 歷史平均恢復天數 (排除目前正在進行的最後一個區間，並過濾掉 0 天的雜訊)
    completed_recoveries = recovery_times.iloc[:-1]
    completed_recoveries = completed_recoveries[completed_recoveries > 0]
    avg_recovery_days = completed_recoveries.mean() if not completed_recoveries.empty else 0
    
    # 目前套牢天數 (從最後一次創新高的日期到今天的距離)
    last_high_date = df[is_new_high]['Date'].max()
    current_date = df['Date'].max()
    current_underwater_days = (current_date - last_high_date).days if pd.notna(last_high_date) else 0
    # -----------------------------------

    mdd_twd_abs = abs(df['Drawdown_TWD'].min())
    total_profit_twd = df['Cum_Profit_TWD'].iloc[-1] if not df.empty else 0
    
    days = max((pd.to_datetime(df['Date']).max() - pd.to_datetime(df['Date']).min()).days, 1)
    years = max(days / 365.25, 0.1)
    annual_profit_twd = total_profit_twd / years
    
    safe_margin_twd = mdd_twd_abs + margin_twd
    
    # 修正 1：如果策略虧損，初始成本預設為至少要準備的「安全保證金」
    target_capital_twd = (annual_profit_twd / target_return_pct) if annual_profit_twd > 0 else safe_margin_twd
    total_return_pct_val = (total_profit_twd / target_capital_twd * 100) if target_capital_twd > 0 else 0
    
    # 修正 2：強制將起訖時間的時分秒歸零，確保夏普值日曆對齊
    start_date_val = df['Date'].dt.normalize().min()
    end_date_val = df['Date'].dt.normalize().max()
    date_range = pd.date_range(start=start_date_val, end=end_date_val, freq='D')
    
    daily_profit = df.groupby(df['Date'].dt.date)['Sim_Profit_TWD'].sum()
    daily_profit.index = pd.to_datetime(daily_profit.index)
    daily_profit = daily_profit.reindex(date_range, fill_value=0)
    
    if target_capital_twd > 0:
        daily_returns = daily_profit / target_capital_twd
        sharpe_ratio = (daily_returns.mean() / daily_returns.std() * np.sqrt(365)) if daily_returns.std() != 0 else 0
    else:
        sharpe_ratio = 0
        
    current_dd = df['Drawdown_TWD'].iloc[-1] if not df.empty else 0
    dd_distance_pct = (abs(current_dd) / mdd_twd_abs * 100) if mdd_twd_abs != 0 else 0
    
    # 🌟 核心新增：時空維度的四色燈號邏輯
    dd_ratio = abs(current_dd) / mdd_twd_abs if mdd_twd_abs > 0 else 0
    
    if dd_ratio >= 1.5:
        status_signal = '🔴 策略失效 (破底>120%)'
    elif avg_recovery_days > 5 and current_underwater_days > (avg_recovery_days * 2):
        status_signal = '🟠 警急警戒 (套牢過久)'
    elif dd_ratio >= 0.7:
        status_signal = '🟡 壓力測試 (DD>70%)'
    else:
        status_signal = '🟢 穩定運行'
    
    return {
        'df': df,
        'margin_twd': margin_twd,
        'metrics': {
            '回測區間': f"{start_date} ~ {end_date}",
            '設定口數': f"{sim_qty}口 {sim_contract.split(' ')[0]}",
            '初始成本(TWD)': target_capital_twd,
            '整體報酬率': f"{total_return_pct_val:.1f}%",
            '夏普值': f"{sharpe_ratio:.2f}",
            '歷史 MDD': mdd_twd_abs,
            '目前回撤': current_dd,
            'MDD佔比': f"{dd_distance_pct:.1f}%",
            '均恢復期': f"{int(avg_recovery_days)}天",
            '目前套牢': f"{current_underwater_days}天",
            '安全保證金': safe_margin_twd,
            '狀態': status_signal
        }
    }

# ==========================================
# 3. 系統 UI (左側控制台)
# ==========================================
if 'run_dashboard' not in st.session_state:
    st.session_state.run_dashboard = False

st.sidebar.title("🎛️ 參數與模擬控制台")

uploaded_files = st.sidebar.file_uploader("📂 1. 匯入 TV 策略檔 (.csv/.xlsx)", accept_multiple_files=True)

rates = get_exchange_rates()
st.sidebar.header("🌍 2. 外幣對台幣 即時匯率")
usd_twd_rate = st.sidebar.number_input("USD/TWD 匯率 (美金)", value=float(rates['USD']), step=0.1)
jpy_twd_rate = st.sidebar.number_input("JPY/TWD 匯率 (日圓)", value=float(rates['JPY']), step=0.001, format="%.4f")

rate_map = {'TWD': 1.0, 'USD': usd_twd_rate, 'JPY': jpy_twd_rate}

with st.sidebar.expander("🛡️ 3. 展開設定各商品最新保證金", expanded=False):
    ui_margins = {}
    for contract, info in DEFAULT_MARGINS.items():
        ui_margins[contract] = st.number_input(f"{contract} ({info['curr']})", value=info['val'], step=100)

st.sidebar.header("🎯 4. 目標資金管理設定")
ui_target_return = st.sidebar.slider("設定您的「目標年化報酬率」", min_value=5, max_value=100, value=15, step=1)

sim_configs = {}
if uploaded_files:
    st.sidebar.header("🕹️ 5. 開倉口數與合約模擬")
    all_options = list(DEFAULT_MARGINS.keys())
    
    for file in uploaded_files:
        st.sidebar.markdown(f"**📝 {file.name}**")
        col1, col2 = st.sidebar.columns([3, 2])
        
        file_upper = file.name.upper()
        def_idx = 0
        if any(x in file_upper for x in ['NQ', 'MNQ']): def_idx = all_options.index("小那 (NQ)")
        elif any(x in file_upper for x in ['ES', 'MES']): def_idx = all_options.index("小標 (ES)")
        elif any(x in file_upper for x in ['NK', 'NI', 'JNM', 'JP']): def_idx = all_options.index("大阪小日經 (JNM)")
        elif any(x in file_upper for x in ['TX', 'MTX', 'TMF']): def_idx = all_options.index("大台 (TX)")
        
        sim_contract = col1.selectbox("轉換合約", all_options, index=def_idx, key=f"c_{file.name}")
        sim_qty = col2.number_input("實戰口數", min_value=1, value=1, key=f"q_{file.name}")
        
        contract_curr = DEFAULT_MARGINS[sim_contract]['curr']
        
        sim_configs[file.name] = {
            'file': file, 
            'contract': sim_contract, 
            'qty': sim_qty, 
            'curr': contract_curr,
            'rate': rate_map[contract_curr]
        }
    
    run_btn = st.sidebar.button("🚀 執行精算與壓力測試", type="primary", use_container_width=True)
    if run_btn:
        st.session_state.run_dashboard = True
else:
    st.info("👈 請先從左側上傳 TradingView 回測檔案。")
    st.session_state.run_dashboard = False
    st.stop()

# ==========================================
# 4. 儀表板渲染 (主畫面)
# ==========================================
if st.session_state.run_dashboard and uploaded_files:
    st.header("📈 實戰部位模擬與壓力測試儀表板", divider="rainbow")
    
    all_metrics = []
    portfolio_series = []
    strategy_names = []
    total_port_margin_twd = 0 
    
    target_return_pct_val = ui_target_return / 100.0 
    
    with st.spinner("🧠 正在解析資料與進行多維度時空對齊..."):
        for filename, config in sim_configs.items():
            df = parse_tv_file(config['file'])
            if df is not None:
                margin = ui_margins[config['contract']]
                result = calculate_strategy_metrics(
                    df, config['contract'], config['qty'], margin, 
                    config['rate'], config['curr'], target_return_pct_val
                )
                
                strat_name = filename.split('.')[0][:15] 
                strategy_names.append(strat_name)
                total_port_margin_twd += result['margin_twd'] 
                
                row_data = {'策略名稱': strat_name}
                row_data.update(result['metrics'])
                all_metrics.append(row_data)
                
                strat_ts = result['df'][['Date', 'Sim_Profit_TWD']].groupby('Date').sum()
                strat_ts.columns = [strat_name]
                portfolio_series.append(strat_ts)
        
        if portfolio_series:
            port_df = pd.concat(portfolio_series, axis=1).fillna(0)
            port_df.index = pd.to_datetime(port_df.index)
            port_df = port_df.resample('D').sum().fillna(0)
            
            port_df['Total_Daily_Profit'] = port_df.sum(axis=1)
            port_df['Portfolio_Cum_Profit'] = port_df['Total_Daily_Profit'].cumsum()
            port_df['Port_HWM'] = port_df['Portfolio_Cum_Profit'].cummax()
            port_df['Port_Drawdown'] = port_df['Portfolio_Cum_Profit'] - port_df['Port_HWM']
            
            for name in strategy_names:
                port_df[f"{name}_Cum"] = port_df[name].cumsum()
            
            total_port_mdd = abs(port_df['Port_Drawdown'].min())
            total_days = max((port_df.index[-1] - port_df.index[0]).days, 1)
            total_port_profit = port_df['Portfolio_Cum_Profit'].iloc[-1]
            port_annual_profit = total_port_profit / max(total_days / 365.25, 0.1)
            
            metrics_df = pd.DataFrame(all_metrics)
            total_target_capital = metrics_df['初始成本(TWD)'].sum()
            
            port_total_return = (total_port_profit / total_target_capital * 100) if total_target_capital > 0 else 0
            
            port_safe_margin = total_port_mdd + total_port_margin_twd
            port_real_annual_return = (port_annual_profit / port_safe_margin * 100) if port_safe_margin > 0 else 0
            
            # 修正綜合夏普
            if total_target_capital > 0:
                port_daily_returns = port_df['Total_Daily_Profit'] / total_target_capital
                port_sharpe = (port_daily_returns.mean() / port_daily_returns.std() * np.sqrt(365)) if port_daily_returns.std() != 0 else 0
            else:
                port_sharpe = 0
            
            port_current_dd = port_df['Port_Drawdown'].iloc[-1]
            port_dd_dist = (port_current_dd / -total_port_mdd * 100) if total_port_mdd != 0 else 0

    st.subheader("🏆 綜合資金水位戰情室 (統一折算為 TWD)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🏆 組合總淨利", f"${total_port_profit:,.0f}")
    c2.metric("📈 組合年均淨利", f"${port_annual_profit:,.0f}")
    c3.metric("🔥 組合整體報酬率", f"{port_total_return:,.1f}%", help="基於您設定的目標年化反推出來的整體投報率")
    c4.metric("🚀 真實歷史年化報酬", f"{port_real_annual_return:.1f}%", help="如果只準備『組合歷史最大回撤 + 期交所保證金』下去跑，所能創造的極限年化報酬率")

    st.markdown("<br>", unsafe_allow_html=True)
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("📊 綜合夏普值 (Sharpe)", f"{port_sharpe:.2f}")
    c6.metric("📉 組合歷史最大回撤金額", f"-${total_port_mdd:,.0f}")
    
    dd_color = "inverse" if port_dd_dist > 80 else "off"
    c7.metric("🚨 目前最新回撤", f"${port_current_dd:,.0f}", f"距離破底: {port_dd_dist:.1f}%", delta_color=dd_color)
    c8.metric("🛡️ 組合資金狀態", "🟢 安全 (Pass)" if total_target_capital >= port_safe_margin else "🔴 危險 (Fail)")

    st.subheader("📋 策略詳細資料與模擬風控表")
    display_df = metrics_df.copy()
    
    # 格式化數字
    for col in ['初始成本(TWD)', '歷史 MDD', '目前回撤', '安全保證金']:
        display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x)
        
    # 🌟 顏色引擎：同步處理 MDD 佔比 與 狀態燈號
    def highlight_mdd(val):
        try:
            num = float(str(val).replace('%', ''))
            if num >= 120: return 'color: white; background-color: #ff4b4b; font-weight: bold;'
            elif num >= 80: return 'color: white; background-color: #ff9f43; font-weight: bold;'
            elif num >= 70: return 'color: black; background-color: #feca57; font-weight: bold;'
        except:
            pass
        return ''

    def highlight_status(val):
        val_str = str(val)
        if '🔴' in val_str: return 'color: white; background-color: #ff4b4b; font-weight: bold;'
        elif '🟠' in val_str: return 'color: white; background-color: #ff9f43; font-weight: bold;'
        elif '🟡' in val_str: return 'color: black; background-color: #feca57; font-weight: bold;'
        elif '🟢' in val_str: return 'color: white; background-color: #1dd1a1; font-weight: bold;'
        return ''
    
    # 套用樣式
    try:
        styled_df = display_df.style.map(highlight_mdd, subset=['MDD佔比']).map(highlight_status, subset=['狀態'])
    except AttributeError:
        styled_df = display_df.style.applymap(highlight_mdd, subset=['MDD佔比']).applymap(highlight_status, subset=['狀態'])
        
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    st.divider()
    col_pie, col_chart = st.columns([1.2, 2.5])
    
    with col_pie:
        pie_mode = st.radio(
            "請選擇圓餅圖分析視角：", 
            [f"🎯 獲利導向 (基於預期 {ui_target_return}%)", "🛡️ 風險導向 (安全保證金佔比)"],
            horizontal=True
        )
        
        if "獲利" in pie_mode:
            pie_data = metrics_df[metrics_df['初始成本(TWD)'] > 0]
            if not pie_data.empty:
                # 把初始成本轉為數字再畫圖
                pie_data['Initial_Cost_Num'] = pie_data['初始成本(TWD)'].replace('[\$,]', '', regex=True).astype(float)
                fig_pie = px.pie(pie_data, values='Initial_Cost_Num', names='策略名稱', title=f"🎯 初始資金佔比 (為達成 {ui_target_return}% 目標)", hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
        else:
            pie_data = metrics_df[metrics_df['安全保證金'].replace('[\$,]', '', regex=True).astype(float) > 0].copy()
            if not pie_data.empty:
                pie_data['Safe_Margin_Num'] = pie_data['安全保證金'].replace('[\$,]', '', regex=True).astype(float)
                fig_pie = px.pie(pie_data, values='Safe_Margin_Num', names='策略名稱', title="🛡️ 風險防禦佔比 (基於歷史MDD+保證金)", hole=0.4, color_discrete_sequence=px.colors.sequential.YlOrRd)
                st.plotly_chart(fig_pie, use_container_width=True)
            
    with col_chart:
        st.markdown("### 📈 組合與單一策略淨值疊加對比圖")
        st.caption("💡 **操作提示**：點擊圖表右側的「圖例標籤」，可以隨時隱藏/顯示單一策略的淨值曲線！")
        
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=port_df.index, y=port_df['Portfolio_Cum_Profit'], mode='lines', name='⭐ 組合總淨值', line=dict(color='#00b4d8', width=3.5)))
        fig_eq.add_trace(go.Scatter(x=port_df.index, y=port_df['Port_Drawdown'], mode='lines', fill='tozeroy', name='🔻 組合總回撤', line=dict(color='red', width=0), fillcolor='rgba(255,0,0,0.3)', yaxis='y2'))
        
        colors = px.colors.qualitative.Pastel
        for idx, name in enumerate(strategy_names):
            fig_eq.add_trace(go.Scatter(x=port_df.index, y=port_df[f"{name}_Cum"], mode='lines', name=f'🔹 {name}', line=dict(width=1.5, color=colors[idx % len(colors)]), visible='legendonly'))
        
        fig_eq.update_layout(hovermode="x unified", height=450, yaxis=dict(title="淨值 (TWD)"), yaxis2=dict(title="回撤 (TWD)", overlaying='y', side='right'), legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.05))
        st.plotly_chart(fig_eq, use_container_width=True)