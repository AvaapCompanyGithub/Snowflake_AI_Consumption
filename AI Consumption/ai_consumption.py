"""
AI Consumption Dashboard

Requires the app owner role to hold IMPORTED PRIVILEGES on database SNOWFLAKE.
Uses only packages bundled with Streamlit in Snowflake — no extra packages needed.
"""

import decimal
import math
from typing import Optional

import streamlit as st
import pandas as pd
import altair as alt
import json
from datetime import datetime, timedelta
from pathlib import Path
from snowflake.snowpark.context import get_active_session

# -------------------------------------------------
# Session
# -------------------------------------------------

try:
    session = get_active_session()
except Exception:
    conn = st.connection("snowflake")
    session = conn.session()
else:
    class _SessConn:
        def query(self, sql, ttl=300):
            return session.sql(sql).to_pandas()
    conn = _SessConn()

# -------------------------------------------------
# Page config
# -------------------------------------------------

st.set_page_config(
    page_title="AI Credit Consumption Dashboard",
    page_icon="📊",
    layout="wide",
)

# ----------------------------------------------------------------------
# Page settings
# Cache Snowflake queries for 1h; cast NUMBER/Decimal to float for charts.
# ----------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Querying ACCOUNT_USAGE...")

def _query(sql: str, start: str, end: str) -> pd.DataFrame:
    df = session.sql(sql, params=[start, end]).to_pandas()
    # Snowflake NUMBER(p,s) arrives as decimal.Decimal -> object dtype.
    for c in df.columns:
        if df[c].map(lambda v: isinstance(v, decimal.Decimal)).any():
            df[c] = df[c].astype(float)
    # Normalize column names so mixed-case Snowflake identifiers are stable.
    df.columns = [str(c).strip() for c in df.columns]
    return df


def run(sql: str, start: str, end: str) -> pd.DataFrame:
    """A missing view or column degrades one section, not the whole app."""
    try:
        return _query(sql, start, end)
    except Exception as e:
        st.warning(f"Query failed, section will be empty: {e}")
        return pd.DataFrame()

def run_optional(sql: str, start: str, end: str) -> pd.DataFrame:
    """Silent variant: these views are legitimately absent on many accounts."""
    try:
        return _query(sql, start, end)
    except Exception:
        return pd.DataFrame()

# ------------------------------------------------------------------
# Config from config.json (same folder as this app)
# ------------------------------------------------------------------

def _load_config():
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent / "config.json")
    except Exception:
        pass
    candidates.append(Path("config.json"))
    for path in candidates:
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config.json must contain a JSON object")
            return data, path
    raise FileNotFoundError(
        "config.json not found next to ai_consumption.py. "
        "Add config.json with default_date_range."
    )

# Credits only: AI services are billed at the contracted AI credit rate, not the
# compute rate, so no dollar conversion is applied here.
_cfg, _cfg_path = _load_config()
date_range = str(_cfg.get("default_date_range", "TODAY")).upper()

# ----------------------------------------------------------------------
# Colors
# ----------------------------------------------------------------------

NAVY = "#16324F"
NAVY_LIGHT = "#2A5F8F"
NAVY_DEEP = "#0F2438"
SNOW_BLUE = "#29B5E8"
BLUE_MID = "#5FC5EC"
BLUE_LIGHT = "#A7D8EF"
BLUE_PALE = "#CFE8F5"
PANEL = "#E9EEF2"
CARD_BG = "#FFFFFF"
INK = "#0F2438"
MUTED = "#6B7F92"
GREEN = "#1F9D6B"
RED = "#C23B3B"
WHITE = "#FFFFFF"
GOLD = "#D4A017"
CHART_BLUE = "#4C6EF5"
CHART_GOLD = "#D4A017"

service_colors = {
    "Cortex Agents": "#ff7f0e",          # orange
    "AI Functions": "#2ca02c",           # green
    "Cortex Analyst": "#d62728",         # red
    "Cortex Search": "#7f7f7f",          # gray
    "Cortex Code (Snowsight)": "#1f77b4",# blue
    "Cortex Code (CLI)": "#9467bd",      # purple
    "Cortex Code (Desktop)": "#17becf",  # teal
    "Snowflake CoWork": "#e377c2",       # pink
}

# ----------------------------------------------------------------------
# Style
# ----------------------------------------------------------------------

st.markdown(
    f"""
    <style>
      .stApp {{ background: #F4F6F8; }}
      .block-container {{ padding-top: 1.4rem; max-width: 1600px; }}
      #MainMenu, footer {{ visibility: hidden; }}

      .masthead {{ display: flex; align-items: baseline; gap: .55rem; margin-bottom: .1rem; }}
      .masthead h1 {{
        font-size: 1.65rem; font-weight: 800; color: {INK};
        margin: 0; letter-spacing: -.02em;
      }}
      .masthead .logo {{
        height: 28px; width: auto; object-fit: contain;
        display: block;
      }}
      .masthead .logo-fallback {{
        width: 28px; height: 28px; border-radius: 6px;
        background: linear-gradient(135deg, {SNOW_BLUE}, {NAVY_LIGHT});
        flex-shrink: 0;
      }}
      .subhead {{ color: {MUTED}; font-size: .75rem; margin: .1rem 0 .8rem 0; }}

      .card {{
        border-radius: 12px; padding: .75rem .9rem 0.85rem .9rem; height: 100%;
        text-align: center; background: #EEF2F6;
        border: 1px solid #E2E8EE;
      }}
      .card.primary {{
        background: {NAVY_LIGHT}; color: #FFFFFF; text-align: left;
        padding: .85rem 1rem; border: none;
      }}
      .card .label {{
        font-size: .62rem; font-weight: 600; letter-spacing: .01em;
        opacity: .85; margin-bottom: .2rem; line-height: 1.2;
        color: {MUTED};
      }}
      .card.primary .label {{ color: rgba(255,255,255,.85); }}
      .card .value {{
        font-size: 1.25rem; font-weight: 800; letter-spacing: -.03em;
        line-height: 1.15; font-variant-numeric: tabular-nums;
        color: {INK};
        word-break: break-word;
      }}
      .card.primary .value {{ color: #FFFFFF; font-size: 1.42rem; }}
      .card .delta-pill {{
        display: inline-block; margin-top: .35rem; margin-bottom: .25rem;
        padding: .12rem .5rem; border-radius: 999px;
        font-size: .62rem; font-weight: 600;
      }}
      .card .delta-pill.up {{ background: #D8F3E7; color: {GREEN}; }}
      .card .delta-pill.down {{ background: #FDE8E8; color: {RED}; }}
      .card .delta-pill.flat {{ background: #E6EBF0; color: {MUTED}; }}
      .card.primary .delta-pill.up {{ background: rgba(125,255,179,.22); color: #7DFFB3; }}
      .card.primary .delta-pill.down {{ background: rgba(255,180,180,.22); color: #FFB4B4; }}
      .card.primary .delta-pill.flat {{ background: rgba(255,255,255,.16); color: rgba(255,255,255,.85); }}
      .card .foot {{
        font-size: .78rem; color: {MUTED}; margin-top: .15rem;
        line-height: 1.35;
      }}
      .card.primary .foot {{ color: rgba(255,255,255,.78); }}

      .section-title {{
        font-size: 1.28rem; font-weight: 800; color: {INK};
        margin: 0.15rem 0 0.75rem 0; letter-spacing: -.02em;
      }}
      .panel-title {{
        font-size: .92rem; font-weight: 700; color: {INK};
        margin: 0 0 .45rem .05rem;
      }}
      .chart-box {{
        background: {WHITE};
        border: 1px solid #E2E8EE;
        border-radius: 12px;
        padding: .7rem .8rem .55rem .8rem;
        height: 100%;
      }}
      .table-box {{
        background: {WHITE};
        border: 1px solid #E2E8EE;
        border-radius: 12px;
        padding: .7rem .8rem .85rem .8rem;
      }}

      .note {{
        text-align: left; color: {MUTED}; font-size: .66rem;
        margin: .55rem 0 1rem 0; line-height: 1.4;
      }}
      div[data-testid="stSelectbox"] label,
      div[data-testid="stDateInput"] label {{
        color: {MUTED}; font-size: .72rem;
      }}

      div[data-testid="stDataFrame"] {{
        font-size: 0.72rem;
      }}
      div[data-testid="stDataFrame"] table {{
        font-size: 0.72rem;
      }}
      div[data-testid="stDataFrame"] th {{
        font-size: 0.68rem !important;
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
      }}
      div[data-testid="stDataFrame"] td {{
        font-size: 0.72rem !important;
        padding-top: 0.2rem !important;
        padding-bottom: 0.2rem !important;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------
# Logo
# ----------------------------------------------------------------------

_logo_html = '<div class="logo-fallback" title="Add logo.png or logo.jpg"></div>'
try:
    import base64 as _b64

    _logo_dir = Path(__file__).resolve().parent
    _logo_path = None
    _mime = None
    for _name, _m in (
        ("logo.png", "image/png"),
        ("logo.jpg", "image/jpeg"),
        ("logo.jpeg", "image/jpeg"),
    ):
        _candidate = _logo_dir / _name
        if _candidate.is_file():
            _logo_path, _mime = _candidate, _m
            break
    if _logo_path is not None:
        _b64data = _b64.b64encode(_logo_path.read_bytes()).decode("ascii")
        _logo_html = (
            f'<img class="logo" alt="Logo" '
            f'src="data:{_mime};base64,{_b64data}"/>'
        )
except Exception:
    pass

# ----------------------------------------------------------------------
# Page Header
# ----------------------------------------------------------------------

DATE_PRESET_MAP = {
    "Today": "TODAY",
    "Week to Date": "WTD",
    "Month to Date": "MTD",
    "Quarter to Date": "QTD",
    "Year to Date": "YTD",
}
DATE_PRESETS = list(DATE_PRESET_MAP.keys()) + ["Custom"]
LABEL_BY_CODE = {code: label for label, code in DATE_PRESET_MAP.items()}

def dates_for(code, today):
    if code == "TODAY":
        return today, today
    if code == "WTD":
        return today - timedelta(days=today.weekday()), today
    if code == "MTD":
        return today.replace(day=1), today
    if code == "QTD":
        month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=month, day=1), today
    return today.replace(month=1, day=1), today

def on_range_change():
    preset = DATE_PRESET_MAP.get(st.session_state.get("date_preset"), "CUSTOM")
    key = "calendar_custom" if preset == "CUSTOM" else f"calendar_{preset}"
    picked = st.session_state.get(key)
    if not (isinstance(picked, (tuple, list)) and len(picked) == 2):
        for candidate in list(st.session_state.keys()):
            if str(candidate).startswith("calendar_"):
                value = st.session_state[candidate]
                if isinstance(value, (tuple, list)) and len(value) == 2:
                    picked = value
                    break
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        st.session_state.custom_range = tuple(picked)
    st.session_state.date_preset = "Custom"

if "last_refreshed" not in st.session_state:
    st.session_state.last_refreshed = datetime.now()
if "date_preset" not in st.session_state:
    st.session_state.date_preset = LABEL_BY_CODE[date_range]
if "custom_range" not in st.session_state:
    st.session_state.custom_range = dates_for(date_range, datetime.now().date())

title_col, range_col = st.columns([3.2, 1.3])
with title_col:
    st.markdown(
        f'<div class="masthead">{_logo_html}<h1>AI Consumption Dashboard</h1></div>'
        '<div class="subhead">Overview of usage on the account.</div>'
        f'<div style="color:{MUTED};font-size:.72rem;margin:-0.35rem 0 0.15rem 0;">'
        f"Last refreshed: {st.session_state.last_refreshed.strftime('%Y-%m-%d %H:%M:%S')}</div>",
        unsafe_allow_html=True,
    )

today = datetime.now().date()
preset = DATE_PRESET_MAP.get(st.session_state.get("date_preset", "Year to Date"), "CUSTOM")

with range_col:
    st.selectbox("Date Range", DATE_PRESETS, key="date_preset")
    if preset == "CUSTOM":
        st.date_input(
            "Custom range",
            key="calendar_custom",
            value=st.session_state.custom_range,
            max_value=today,
            format="YYYY-MM-DD",
            label_visibility="collapsed",
            on_change=on_range_change,
        )
        picked = st.session_state.calendar_custom
    else:
        forced = dates_for(preset, today)
        st.date_input(
            "Custom range",
            key=f"calendar_{preset}",
            value=forced,
            max_value=today,
            format="YYYY-MM-DD",
            label_visibility="collapsed",
            on_change=on_range_change,
        )
        picked = forced

if isinstance(picked, (tuple, list)) and len(picked) == 2:
    start_date, end_date = picked
else:
    start_date = end_date = today

with range_col:
    st.markdown(
        f'<div style="color:{MUTED};font-size:0.72rem;margin-top:-0.35rem;">'
        f'{start_date.strftime("%Y-%m-%d")} → {end_date.strftime("%Y-%m-%d")}'
        f'</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ACCOUNT_USAGE ranges are half-open; end bound is exclusive.
p_start = start_date.strftime("%Y-%m-%d")
p_end = (end_date + timedelta(days=1)).isoformat()

# ----------------------------------------------------------------------
# Summary/Counts
# ----------------------------------------------------------------------

#Query: Get Service/Credits
# CORTEX_AISQL_USAGE_HISTORY is a subset of CORTEX_AI_FUNCTIONS_USAGE_HISTORY
# (same QUERY_IDs), so only the AI Functions view is counted.
summary_sql = f"""
WITH agent AS (
    SELECT 'Cortex Agents' AS service, ROUND(SUM(TOKEN_CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
    WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
),
ai_func AS (
    SELECT 'AI Functions' AS service, ROUND(SUM(CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
    WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
),
analyst AS (
    SELECT 'Cortex Analyst' AS service, ROUND(SUM(CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
    WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
),
search AS (
    SELECT 'Cortex Search' AS service, ROUND(SUM(CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
    WHERE USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}'
),
code_ss AS (
    SELECT 'Cortex Code (Snowsight)' AS service, ROUND(SUM(TOKEN_CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
    WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}'
),
code_cli AS (
    SELECT 'Cortex Code (CLI)' AS service, ROUND(SUM(TOKEN_CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
    WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}'
),
code_desktop AS (
    SELECT 'Cortex Code (Desktop)' AS service, ROUND(SUM(TOKEN_CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
    WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}'
),
cowork AS (
    SELECT 'Snowflake CoWork' AS service, ROUND(SUM(TOKEN_CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY
    WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
)
SELECT * FROM agent UNION ALL SELECT * FROM ai_func
UNION ALL SELECT * FROM analyst UNION ALL SELECT * FROM search
UNION ALL SELECT * FROM code_ss UNION ALL SELECT * FROM code_cli
UNION ALL SELECT * FROM code_desktop UNION ALL SELECT * FROM cowork
"""

#df_summary = run_query(summary_sql)
df_summary = run(summary_sql, p_start, p_end)
#Calculate some totals
df_summary["CREDITS"] = df_summary["CREDITS"].fillna(0)
total_credits = df_summary["CREDITS"].sum()
top_service = df_summary.loc[df_summary["CREDITS"].idxmax(), "SERVICE"] if total_credits > 0 else "N/A"
active_services = (df_summary["CREDITS"] > 0).sum()

#Compare to previous: same number of days, ending the day before start_date.
# Both dates are inclusive, so a range covers (end - start) + 1 days.
num_days = (end_date - start_date).days + 1
prev_days = num_days
if prev_days > 0:
    prev_start = (start_date - timedelta(days=prev_days)).strftime("%Y-%m-%d")
    prev_end = p_start
    prev_sql = f"""
    WITH agent AS (
        SELECT ROUND(SUM(TOKEN_CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'
    ), ai_func AS (
        SELECT ROUND(SUM(CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'
    ), analyst AS (
        SELECT ROUND(SUM(CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'
    ), search AS (
        SELECT ROUND(SUM(CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY WHERE USAGE_DATE >= '{prev_start}' AND USAGE_DATE < '{prev_end}'
    ), code_ss AS (
        SELECT ROUND(SUM(TOKEN_CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY WHERE USAGE_TIME >= '{prev_start}' AND USAGE_TIME < '{prev_end}'
    ), code_cli AS (
        SELECT ROUND(SUM(TOKEN_CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY WHERE USAGE_TIME >= '{prev_start}' AND USAGE_TIME < '{prev_end}'
    ), code_desktop AS (
        SELECT ROUND(SUM(TOKEN_CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY WHERE USAGE_TIME >= '{prev_start}' AND USAGE_TIME < '{prev_end}'
    ), cowork AS (
        SELECT ROUND(SUM(TOKEN_CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'
    )
    SELECT COALESCE(SUM(credits), 0) AS total FROM (
        SELECT * FROM agent UNION ALL SELECT * FROM ai_func
        UNION ALL SELECT * FROM analyst UNION ALL SELECT * FROM search
        UNION ALL SELECT * FROM code_ss UNION ALL SELECT * FROM code_cli
        UNION ALL SELECT * FROM code_desktop UNION ALL SELECT * FROM cowork
    )
    """
    #prev_credits = run_query(prev_sql)["TOTAL"].iloc[0]
    prev_credits = run(prev_sql, p_start, p_end)["TOTAL"].iloc[0]
    if prev_credits > 0:
        growth_pct = round(((total_credits - prev_credits) / prev_credits) * 100, 1)
        delta_str = f"{growth_pct}%"
    elif total_credits > 0:
        delta_str = "New"
    else:
        delta_str = "0%"
else:
    delta_str = "N/A"

#Avg daily (num_days is inclusive of both ends)
avg_daily = total_credits / num_days

#Count total requests
total_code_requests_sql = f"""
SELECT
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') +
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') +
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') AS TOTAL_REQUESTS
"""
#total_code_requests = run_query(total_code_requests_sql)["TOTAL_REQUESTS"].iloc[0]
total_code_requests = run(total_code_requests_sql, p_start, p_end)["TOTAL_REQUESTS"].iloc[0]

def _kpi_delta_pill(delta_str: str) -> str:
    """Map the prior-period string onto the cost-summary pill."""
    if delta_str in (None, "", "N/A"):
        return ""
    if delta_str == "New":
        return '<span class="delta-pill up">new</span>'
    raw = str(delta_str).strip().rstrip("%")
    try:
        pct = float(raw)
    except ValueError:
        return f'<span class="delta-pill flat">{delta_str} vs prior</span>'
    if pct > 0:
        return f'<span class="delta-pill up">↑ {pct:+.1f}%</span>'
    if pct < 0:
        return f'<span class="delta-pill down">↓ {pct:+.1f}%</span>'
    return '<span class="delta-pill flat">0.0%</span>'


def card_html(label: str, value: str, delta_html: str = "", foot_lines=None, primary: bool = False) -> str:
    cls = "card primary" if primary else "card"
    foot = "".join(f'<div class="foot">{line}</div>' for line in (foot_lines or []) if line)
    return (
        f'<div class="{cls}">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{value}</div>'
        f'{delta_html}'
        f'{foot}'
        f'</div>'
    )

st.markdown(
    f'<div style="color:{MUTED};font-size:0.72rem;margin:-1rem 0 0 0;padding:0 0 0.65rem 0;">'
    f'Change vs prior period ({preset}).'
    f'</div>',
    unsafe_allow_html=True,
)

delta_html = _kpi_delta_pill(delta_str)
cards = [
    {
        "label": "Total AI Credits",
        "value": f"{total_credits:,.4f}",
        "delta": delta_html,
        "foot": [],
        "primary": True,
    },
    {
        "label": "Avg Daily Burn",
        "value": f"{avg_daily:,.4f}",
        "delta": "",
        "foot": [],
        "primary": False,
    },
    {
        "label": "Top Service",
        "value": str(top_service),
        "delta": "",
        "foot": [],
        "primary": False,
    },
    {
        "label": "Active Services",
        "value": f"{int(active_services)}",
        "delta": "",
        "foot": [],
        "primary": False,
    },
    {
        "label": "Code Requests",
        "value": f"{total_code_requests:,}",
        "delta": "",
        "foot": [],
        "primary": False,
    },
]
k = st.columns(5)
for col, c in zip(k, cards):
    with col:
        st.markdown(
            card_html(c["label"], c["value"], c["delta"], c["foot"], c["primary"]),
            unsafe_allow_html=True,
        )

st.divider()

# ----------------------------------------------------------------------
# Credits by Service Pie Chart (left) and Service Distribution (right)
# ----------------------------------------------------------------------

left, right = st.columns(2)
with left:
    st.subheader("Credits by Service")
    df_bar = df_summary[df_summary["CREDITS"] > 0].sort_values("CREDITS", ascending=False)
    if not df_bar.empty:
        chart = alt.Chart(df_bar).mark_bar().encode(
            x=alt.X("CREDITS:Q", title="Credits"),
            y=alt.Y("SERVICE:N", sort="-x", title=""),
            #color=alt.Color("SERVICE:N", legend=None),
            color=alt.Color("SERVICE:N", legend=None, scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
            tooltip=["SERVICE", "CREDITS"]
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No AI credit usage in selected period.")
with right:
    st.subheader("Service Distribution")
    df_pie = df_summary[df_summary["CREDITS"] > 0]
    if not df_pie.empty:
        pie = alt.Chart(df_pie).mark_arc(innerRadius=50).encode(
            theta=alt.Theta("CREDITS:Q"),
            #color=alt.Color("SERVICE:N", title="Service"),
            color=alt.Color("SERVICE:N", title="Service", scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
            tooltip=["SERVICE", "CREDITS"]
        ).properties(height=300)
        st.altair_chart(pie, use_container_width=True)
    else:
        st.info("No data.")

# ----------------------------------------------------------------------
# Credit Summay
# ----------------------------------------------------------------------

#Credit Summary
st.divider()
st.subheader("Credit Summary Table")
st.dataframe(df_summary.sort_values("CREDITS", ascending=False).reset_index(drop=True), use_container_width=True, hide_index=True)
st.caption(
    "AI Functions includes all AISQL function calls (AI_COMPLETE, AI_CLASSIFY, etc.). "
    "Cortex Agents includes Cortex Analyst tool calls made by agents; those are not in Cortex Analyst. "
    "Snowflake CoWork (formerly Snowflake Intelligence) excludes Cortex Agent requests, so the two do not overlap."
)

# ----------------------------------------------------------------------
# Daily Credit Trend
# ----------------------------------------------------------------------

st.divider()
st.subheader("Daily Credit Trend (All Services)")

#Filter by Services, Warehouse, Database
fil1, _ = st.columns(2)
with fil1:
    trend_view = st.selectbox("Filter Trend By", ["All Services", "By Warehouse (AI Functions)", "By Database (Agents & Search)"])
if trend_view == "By Warehouse (AI Functions)":
    trend_sql = f"""
    WITH wh_data AS (
        SELECT DATE(h.START_TIME) AS usage_date, q.WAREHOUSE_NAME AS dimension, SUM(h.CREDITS) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY h
        JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q ON h.QUERY_ID = q.QUERY_ID
        WHERE h.START_TIME >= '{p_start}' AND h.START_TIME < '{p_end}' AND q.WAREHOUSE_NAME IS NOT NULL
        GROUP BY 1, 2
    )
    SELECT USAGE_DATE, DIMENSION, ROUND(SUM(CREDITS), 4) AS CREDITS FROM wh_data GROUP BY 1, 2 ORDER BY 1
    """
    color_field = "DIMENSION"
    chart_title = "Daily Credits by Warehouse"
elif trend_view == "By Database (Agents & Search)":
    trend_sql = f"""
    WITH db_data AS (
        SELECT DATE(START_TIME) AS usage_date, AGENT_DATABASE_NAME AS dimension, SUM(TOKEN_CREDITS) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
        WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' AND AGENT_DATABASE_NAME IS NOT NULL
        GROUP BY 1, 2
        UNION ALL
        SELECT DATE(USAGE_DATE), DATABASE_NAME, SUM(CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
        WHERE USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}' AND DATABASE_NAME IS NOT NULL
        GROUP BY 1, 2
    )
    SELECT USAGE_DATE, DIMENSION, ROUND(SUM(CREDITS), 4) AS CREDITS FROM db_data GROUP BY 1, 2 ORDER BY 1
    """
    color_field = "DIMENSION"
    chart_title = "Daily Credits by Database"
else:
    trend_sql = f"""
    WITH daily_data AS (
        SELECT DATE(START_TIME) AS usage_date, 'Cortex Agents' AS service, SUM(TOKEN_CREDITS) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
        WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' GROUP BY DATE(START_TIME)
        UNION ALL
        SELECT DATE(START_TIME), 'AI Functions', SUM(CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
        WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' GROUP BY DATE(START_TIME)
        UNION ALL
        SELECT DATE(START_TIME), 'Cortex Analyst', SUM(CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
        WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' GROUP BY DATE(START_TIME)
        UNION ALL
        SELECT DATE(USAGE_DATE), 'Cortex Search', SUM(CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
        WHERE USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}' GROUP BY DATE(USAGE_DATE)
        UNION ALL
        SELECT DATE(USAGE_TIME), 'Cortex Code (Snowsight)', SUM(TOKEN_CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
        WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}' GROUP BY DATE(USAGE_TIME)
        UNION ALL
        SELECT DATE(USAGE_TIME), 'Cortex Code (CLI)', SUM(TOKEN_CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
        WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}' GROUP BY DATE(USAGE_TIME)
        UNION ALL
        SELECT DATE(USAGE_TIME), 'Cortex Code (Desktop)', SUM(TOKEN_CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
        WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}' GROUP BY DATE(USAGE_TIME)
        UNION ALL
        SELECT DATE(START_TIME), 'Snowflake CoWork', SUM(TOKEN_CREDITS)
        FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY
        WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' GROUP BY DATE(START_TIME)
    )
    SELECT USAGE_DATE, SERVICE AS DIMENSION, ROUND(CREDITS, 4) AS CREDITS FROM daily_data ORDER BY USAGE_DATE
    """
    color_field = "DIMENSION"
    chart_title = "Daily Credits by Service"

df_trend = run(trend_sql, p_start, p_end)

#Line chart with series    
if not df_trend.empty:
    stacked = alt.Chart(df_trend).mark_area(opacity=0.7).encode(
        x=alt.X("USAGE_DATE:T", title="Date"),
        y=alt.Y("CREDITS:Q", stack="zero", title="Credits"),
        #color=alt.Color(f"{color_field}:N", title=chart_title.split("by ")[-1]),
        color=alt.Color(f"{color_field}:N", title=chart_title.split("by ")[-1], scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
        tooltip=["USAGE_DATE:T", f"{color_field}:N", "CREDITS:Q"]
    ).properties(height=350)
    st.altair_chart(stacked, use_container_width=True)
else:
    st.info("No daily trend data in selected period.")

# ----------------------------------------------------------------------
# Per-user usage (shared by Cost Efficiency, Top Users, Cost-per-Request)
# One row per usage record with a resolved user name, a request key and a
# request count, so every section below sums the same credits as the headline.
# ----------------------------------------------------------------------

# Requests are not the same unit across services, so each service is labelled
# and interactive services are never ranked against batch SQL queries.
SERVICE_UNITS = {
    "Cortex Agents": "agent request",
    "Cortex Analyst": "Analyst request",
    "Cortex Code (Snowsight)": "Code request",
    "Cortex Code (CLI)": "Code request",
    "Cortex Code (Desktop)": "Code request",
    "Snowflake CoWork": "CoWork request",
    "AI Functions": "SQL query",
}
INTERACTIVE_SERVICES = ["Cortex Agents", "Cortex Analyst", "Cortex Code (Snowsight)", "Cortex Code (CLI)",
                        "Cortex Code (Desktop)", "Snowflake CoWork"]
BATCH_SERVICES = ["AI Functions"]

# USER_ID 0 is Snowflake's internal SYSTEM user (QUERY_HISTORY reports it as SYSTEM).
# Cortex Analyst records the login name (often an email), so it is mapped via LOGIN_NAME.
user_usage_cte = f"""
WITH login_map AS (
    SELECT UPPER(LOGIN_NAME) AS login_key, NAME
    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
    QUALIFY ROW_NUMBER() OVER (PARTITION BY UPPER(LOGIN_NAME) ORDER BY DELETED_ON IS NULL DESC, CREATED_ON DESC) = 1
),
user_usage AS (
    SELECT COALESCE(h.USER_NAME, u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)) AS user_name,
           'Cortex Agents' AS service, h.TOKEN_CREDITS AS credits, h.TOKENS AS tokens,
           h.REQUEST_ID::VARCHAR AS request_key, 0 AS request_n
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.START_TIME >= '{p_start}' AND h.START_TIME < '{p_end}'

    UNION ALL
    SELECT COALESCE(u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'AI Functions', h.CREDITS, NULL,
           h.QUERY_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.START_TIME >= '{p_start}' AND h.START_TIME < '{p_end}'

    UNION ALL
    SELECT COALESCE(m.NAME, a.USERNAME), 'Cortex Analyst', a.CREDITS, NULL, NULL, a.REQUEST_COUNT
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY a
    LEFT JOIN login_map m ON m.login_key = UPPER(a.USERNAME)
    WHERE a.START_TIME >= '{p_start}' AND a.START_TIME < '{p_end}'

    UNION ALL
    SELECT 'Cortex Search (service)', 'Cortex Search', CREDITS, TOKENS, NULL, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
    WHERE USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}'

    UNION ALL
    SELECT COALESCE(u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'Cortex Code (Snowsight)', h.TOKEN_CREDITS, h.TOKENS,
           h.REQUEST_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.USAGE_TIME >= '{p_start}' AND h.USAGE_TIME < '{p_end}'

    UNION ALL
    SELECT COALESCE(u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'Cortex Code (CLI)', h.TOKEN_CREDITS, h.TOKENS,
           h.REQUEST_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.USAGE_TIME >= '{p_start}' AND h.USAGE_TIME < '{p_end}'

    UNION ALL
    SELECT COALESCE(h.USER_NAME, u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'Cortex Code (Desktop)', h.TOKEN_CREDITS, h.TOKENS,
           h.REQUEST_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.USAGE_TIME >= '{p_start}' AND h.USAGE_TIME < '{p_end}'

    UNION ALL
    SELECT COALESCE(h.USER_NAME, u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'Snowflake CoWork', h.TOKEN_CREDITS, h.TOKENS,
           h.REQUEST_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.START_TIME >= '{p_start}' AND h.START_TIME < '{p_end}'
)
"""

# Requests = distinct request keys + pre-aggregated Analyst request counts.
REQUESTS_EXPR = "COUNT(DISTINCT request_key) + COALESCE(SUM(request_n), 0)"


def add_cost_per_request(df: pd.DataFrame) -> pd.DataFrame:
    df["TOTAL_CREDITS"] = df["TOTAL_CREDITS"].fillna(0)
    df["TOTAL_REQUESTS"] = df["TOTAL_REQUESTS"].fillna(0).astype(int)
    df = df[df["TOTAL_REQUESTS"] > 0].copy()
    df["UNIT"] = df["SERVICE"].map(SERVICE_UNITS)
    df["COST_PER_REQUEST"] = (df["TOTAL_CREDITS"] / df["TOTAL_REQUESTS"]).round(6)
    return df.sort_values("COST_PER_REQUEST", ascending=False)


def cpr_chart(df: pd.DataFrame, y_field: str, x_title: str, height: int, show_legend: bool = False):
    # One legend per section: the scale domain lists every service, so the
    # legend on one chart also covers its neighbour.
    legend = alt.Legend(title="Service") if show_legend else None
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("COST_PER_REQUEST:Q", title=x_title),
        y=alt.Y(f"{y_field}:N", sort="-x", title=""),
        color=alt.Color("SERVICE:N", legend=legend, scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
        tooltip=[c for c in ["USER_NAME", "SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "COST_PER_REQUEST"] if c in df.columns],
    ).properties(height=height)


# ----------------------------------------------------------------------
# Cost Efficiency
# ----------------------------------------------------------------------

st.divider()
st.subheader("Cost Efficiency by Service")

efficiency_sql = f"""
{user_usage_cte}
SELECT service AS SERVICE, ROUND(SUM(credits), 6) AS TOTAL_CREDITS, {REQUESTS_EXPR} AS TOTAL_REQUESTS
FROM user_usage
WHERE service <> 'Cortex Search'
GROUP BY 1
"""

df_eff = run(efficiency_sql, p_start, p_end)
if not df_eff.empty:
    df_eff = add_cost_per_request(df_eff)

if not df_eff.empty:
    eff_cols = ["SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "COST_PER_REQUEST"]
    e1, e2 = st.columns([2, 1])
    with e1:
        st.markdown('<div class="panel-title">Interactive services: credits per request</div>', unsafe_allow_html=True)
        df_int = df_eff[df_eff["SERVICE"].isin(INTERACTIVE_SERVICES)]
        if not df_int.empty:
            st.altair_chart(cpr_chart(df_int, "SERVICE", "Credits per Request", 220, show_legend=True), use_container_width=True)
        else:
            st.info("No interactive requests in selected period.")
    with e2:
        st.markdown('<div class="panel-title">AI Functions: credits per SQL query</div>', unsafe_allow_html=True)
        df_batch = df_eff[df_eff["SERVICE"].isin(BATCH_SERVICES)]
        if not df_batch.empty:
            st.altair_chart(cpr_chart(df_batch, "SERVICE", "Credits per SQL Query", 220), use_container_width=True)
        else:
            st.info("No AI Function queries in selected period.")
    st.dataframe(df_eff[eff_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
    st.caption(
        "Units differ by service. An AI Functions query can process many rows, so its cost per query "
        "is not comparable to a single agent or Code request. Cortex Search has no request count and is excluded."
    )
else:
    st.info("No request data in selected period.")

# ----------------------------------------------------------------------
# Users by credit
# ----------------------------------------------------------------------

st.divider()
st.subheader("Top Users by AI Credits")

TAB_SERVICES = ["Cortex Agents", "Snowflake CoWork", "AI Functions", "Cortex Analyst",
                "Cortex Code (Snowsight)", "Cortex Code (CLI)", "Cortex Code (Desktop)"]
tabs = st.tabs(["Total AI Use"] + TAB_SERVICES)

with tabs[0]:
    st.dataframe(run(f"""
    {user_usage_cte}
    SELECT user_name AS USER_NAME,
           ROUND(SUM(credits), 4) AS TOTAL_CREDITS,
           SUM(tokens) AS TOTAL_TOKENS,
           {REQUESTS_EXPR} AS REQUESTS
    FROM user_usage
    GROUP BY 1
    ORDER BY TOTAL_CREDITS DESC
    """, p_start, p_end), use_container_width=True, hide_index=True)
    st.caption(
        "Includes every service, so the column total matches Total AI Credits. "
        "Cortex Search is billed per service, not per user. SYSTEM is Snowflake's internal user (USER_ID 0). "
        "Requests mix units across services; see Cost Efficiency for per-service units. "
        "AI Functions does not report tokens."
    )

for tab, svc in zip(tabs[1:], TAB_SERVICES):
    with tab:
        st.dataframe(run(f"""
        {user_usage_cte}
        SELECT user_name AS USER_NAME,
               ROUND(SUM(credits), 4) AS TOTAL_CREDITS,
               SUM(tokens) AS TOTAL_TOKENS,
               {REQUESTS_EXPR} AS REQUESTS
        FROM user_usage
        WHERE service = '{svc}'
        GROUP BY 1
        ORDER BY TOTAL_CREDITS DESC
        """, p_start, p_end), use_container_width=True, hide_index=True)
        st.caption(f"Requests counted per {SERVICE_UNITS[svc]}.")

# ----------------------------------------------------------------------
# Users by Highest Service/Cost
# ----------------------------------------------------------------------

st.divider()
st.subheader("Highest Cost-per-Request by User")

user_eff_sql = f"""
{user_usage_cte}
SELECT user_name AS USER_NAME, service AS SERVICE, ROUND(SUM(credits), 6) AS TOTAL_CREDITS, {REQUESTS_EXPR} AS TOTAL_REQUESTS
FROM user_usage
WHERE service <> 'Cortex Search'
GROUP BY 1, 2
"""

df_user_eff = run(user_eff_sql, p_start, p_end)
if not df_user_eff.empty:
    df_user_eff = add_cost_per_request(df_user_eff)

if not df_user_eff.empty:
    df_user_eff["LABEL"] = df_user_eff["USER_NAME"].fillna("Unknown") + " (" + df_user_eff["SERVICE"] + ")"
    user_cols = ["USER_NAME", "SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "COST_PER_REQUEST"]
    u1, u2 = st.columns(2)
    with u1:
        st.markdown('<div class="panel-title">Interactive services: credits per request (top 15)</div>', unsafe_allow_html=True)
        df_u_int = df_user_eff[df_user_eff["SERVICE"].isin(INTERACTIVE_SERVICES)].head(15)
        if not df_u_int.empty:
            st.altair_chart(cpr_chart(df_u_int, "LABEL", "Credits per Request", 400, show_legend=True), use_container_width=True)
            st.dataframe(df_u_int[user_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.info("No interactive requests in selected period.")
    with u2:
        st.markdown('<div class="panel-title">AI Functions: credits per SQL query (top 15)</div>', unsafe_allow_html=True)
        df_u_batch = df_user_eff[df_user_eff["SERVICE"].isin(BATCH_SERVICES)].head(15)
        if not df_u_batch.empty:
            st.altair_chart(cpr_chart(df_u_batch, "LABEL", "Credits per SQL Query", 400), use_container_width=True)
            st.dataframe(df_u_batch[user_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.info("No AI Function queries in selected period.")
else:
    st.info("No user request data in selected period.")

# -------------------------------------------------
# Notes
# -------------------------------------------------

st.divider()

st.markdown(
    f"""
    <div class="note">
    ACCOUNT_USAGE views are not real time. Cortex usage lags
    by about 5 minutes. Ranges that include today or yesterday will therefore
    understate actual consumption, and the most recent day is always partial.<br><br>
    Figures are drawn from ACCOUNT_USAGE and are for internal analysis only -
    they will not tie exactly to your Snowflake invoice. Use ORGANIZATION_USAGE
    or the billing statement for figures of record.<br><br>
    All values are in credits. AI services are billed at your contracted AI credit
    rate (see the Snowflake Service Consumption Table), which differs from the compute
    rate, so no dollar conversion is shown. Date ranges include both the start and end day.
    </div>
    """,
    unsafe_allow_html=True,
)

