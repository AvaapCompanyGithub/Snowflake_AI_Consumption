"""
AI Consumption Dashboard

Requires the app owner role to hold IMPORTED PRIVILEGES on database SNOWFLAKE.
Uses only packages bundled with Streamlit in Snowflake — no extra packages needed.
"""

import decimal
import html
import re
from typing import Optional

import streamlit as st
import pandas as pd
import altair as alt
import json
from datetime import datetime, timedelta
from pathlib import Path
from snowflake.snowpark.context import get_active_session

# -------------------------------------------------
# Page config (must be the first Streamlit call)
# -------------------------------------------------

st.set_page_config(
    page_title="AI Credit Consumption Dashboard",
    page_icon="📊",
    layout="wide",
)

# -------------------------------------------------
# Session
# -------------------------------------------------

try:
    session = get_active_session()
except Exception:
    session = st.connection("snowflake").session()

# ----------------------------------------------------------------------
# Page settings
# Cache Snowflake queries for 1h; cast NUMBER/Decimal to float for charts.
# ----------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Querying ACCOUNT_USAGE...")

def _query(sql: str, start: str, end: str) -> pd.DataFrame:
    # The dates are already written into `sql`; start/end are not bound (the SQL has
    # no ? placeholders) and only label the cache entry.
    df = session.sql(sql).to_pandas()
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


@st.cache_data(ttl=60, show_spinner=False)
def _snowflake_now() -> tuple:
    """Today's date and the current time in the Snowflake session's time zone, which is
    the zone the date filters are applied in. The container clock is UTC."""
    row = session.sql(
        "SELECT CURRENT_DATE() AS TODAY, "
        "TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS') AS NOW_TXT"
    ).collect()[0]
    return row["TODAY"], row["NOW_TXT"]


def snowflake_now() -> tuple:
    try:
        return _snowflake_now()
    except Exception:
        now = datetime.now().astimezone()
        return now.date(), now.strftime("%Y-%m-%d %H:%M:%S") + " (app server clock)"

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

_cfg, _cfg_path = _load_config()
date_range = str(_cfg.get("default_date_range", "TODAY")).strip().upper()
if date_range not in ("TODAY", "WTD", "MTD", "QTD", "YTD"):
    st.warning(
        f"config.json: default_date_range {date_range!r} is not one of "
        "TODAY, WTD, MTD, QTD, YTD; using YTD."
    )
    date_range = "YTD"

# Prices per credit, used to show costs (see the Pricing section below for which
# rate applies). Set them to your contracted prices.
def _rate(key: str, default: float) -> float:
    if key not in _cfg:
        st.warning(f"config.json: {key} is missing; using the list price {default:.2f}.")
        return default
    try:
        value = float(_cfg.get(key, default))
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    st.warning(f"config.json: {key} must be a number of 0 or more; using {default:.2f}.")
    return default


ai_rate_global = _rate("ai_credit_rate_global", 2.00)
ai_rate_regional = _rate("ai_credit_rate_regional", 2.20)
platform_rate = _rate("platform_credit_rate", 3.00)

# First day of the week for the Week to Date preset.
_WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
week_start_day = str(_cfg.get("week_start", "SUNDAY")).strip().upper()
if week_start_day not in _WEEKDAYS:
    st.warning(f"config.json: week_start {week_start_day!r} is not a day name; using SUNDAY.")
    week_start_day = "SUNDAY"

# Quota tab: a user is flagged Warning at this % of any limit.
try:
    quota_warning_pct = float(_cfg.get("quota_warning_pct", 80))
    if not 0 < quota_warning_pct < 100:
        raise ValueError
except (TypeError, ValueError):
    st.warning("config.json: quota_warning_pct must be a number between 0 and 100; using 80.")
    quota_warning_pct = 80.0

# Users listed in the Quota and Efficiency tabs before "Show all" is ticked.
try:
    top_users = int(_cfg.get("top_users", 10))
    if top_users < 1:
        raise ValueError
except (TypeError, ValueError):
    st.warning("config.json: top_users must be a whole number of 1 or more; using 10.")
    top_users = 10

# Optional quota to report against. Validated as a plain DB.SCHEMA.NAME
# identifier because it is interpolated into CALL statements.
_FQN_RE = r"[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){2}"
quota_fqn = str(_cfg.get("quota_fqn", "UTIL_DB.COSTS.AI_QUOTA")).strip()
if not re.fullmatch(_FQN_RE, quota_fqn):
    quota_fqn = ""

# Optional direct link to the quota's Snowsight page (copy it from the browser).
# Only https URLs are accepted because the value is rendered as an HTML link.
quota_url = str(_cfg.get("quota_url", "") or "").strip()
if not re.fullmatch(r"https://[^\s\"'<>]+", quota_url):
    quota_url = ""

# Users allowed to change quota settings from the Admin tab. The app runs with
# its owner's rights, so this list is the only thing stopping other viewers.
_admins_cfg = _cfg.get("quota_admins") or []
if isinstance(_admins_cfg, str):
    _admins_cfg = [_admins_cfg]
quota_admins = {
    u.strip().upper()
    for u in _admins_cfg
    if isinstance(u, str) and u.strip()
}


def viewer_name() -> str:
    """The viewer's Snowflake username (st.user), or "" if unavailable."""
    try:
        return str(st.user.user_name or "").strip().upper()
    except Exception:
        return ""


def is_quota_admin() -> bool:
    name = viewer_name()
    return bool(name) and name in quota_admins

# ----------------------------------------------------------------------
# Pricing
# AI services are billed in AI Credits, priced the same for every edition but
# differently by routing (CORTEX_ENABLED_CROSS_REGION): global routing is cheaper
# than keeping requests in a region. The standalone Cortex Analyst API is still
# billed in Platform Credits at the edition rate. Rates come from config.json.
# ----------------------------------------------------------------------

# Settings that send AI requests to any region (global routing). Anything else,
# including DISABLED or a region group such as AWS_US, is regional routing.
_GLOBAL_ROUTING = {"ANY_REGION", "AWS_GLOBAL", "GCP_GLOBAL", "AZURE_GLOBAL"}


@st.cache_data(ttl=3600, show_spinner=False)
def _cross_region_setting() -> str:
    rows = session.sql("SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT").collect()
    return str(rows[0].as_dict().get("value", "")).strip().upper() if rows else ""


try:
    cross_region = _cross_region_setting()
except Exception:
    cross_region = ""
if cross_region:
    ai_routing = "global" if {t.strip() for t in cross_region.split(",")} & _GLOBAL_ROUTING else "regional"
else:
    ai_routing = "unknown"  # couldn't read the setting: price at the higher regional rate
ai_credit_rate = ai_rate_global if ai_routing == "global" else ai_rate_regional

# Services billed in Platform Credits; everything else is billed in AI Credits.
PLATFORM_CREDIT_SERVICES = {"Cortex Analyst"}  # standalone Analyst API (legacy pricing)


def rate_for(service: str) -> float:
    return platform_rate if service in PLATFORM_CREDIT_SERVICES else ai_credit_rate


def pricing_text() -> str:
    """One sentence describing the rates in use, for notes under tables."""
    if ai_routing == "unknown":
        routing = ("regional rate assumed, because CORTEX_ENABLED_CROSS_REGION could not be read")
    else:
        routing = f"{ai_routing} routing, CORTEX_ENABLED_CROSS_REGION = {cross_region}"
    return (
        f"Costs use ${ai_credit_rate:,.2f} per AI Credit ({routing}) and "
        f"${platform_rate:,.2f} per Platform Credit for the Cortex Analyst API, from config.json."
    )


# Show COST columns as currency.
COST_COLUMN = {"COST": st.column_config.NumberColumn("COST", format="$%.2f")}


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
    "AI Gateway": "#bcbd22",             # olive
    "Cortex REST API": "#8c564b",        # brown
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
      /* Cost dashboard: spend rising is red, spend falling is green. */
      .card .delta-pill.rise {{ background: #FDE8E8; color: {RED}; }}
      .card .delta-pill.fall {{ background: #D8F3E7; color: {GREEN}; }}
      .card .delta-pill.flat {{ background: #E6EBF0; color: {MUTED}; }}
      .card.primary .delta-pill.rise {{ background: rgba(255,180,180,.22); color: #FFB4B4; }}
      .card.primary .delta-pill.fall {{ background: rgba(125,255,179,.22); color: #7DFFB3; }}
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

      /* Small notes around the KPI cards (comparison window, rates). */
      .kpi-note, .kpi-note * {{
        color: {MUTED} !important; font-size: .75rem !important;
        line-height: 1.4 !important; margin: 0;
      }}

      .note {{
        text-align: left; color: {MUTED}; font-size: .75rem;
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


def info_text(text: str) -> None:
    """Informational text in the page's subhead style ("Overview of usage on the account.").
    Text is escaped because it can contain user names and object names."""
    st.markdown(f'<div class="subhead">{html.escape(text)}</div>', unsafe_allow_html=True)


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
        offset = (today.weekday() - _WEEKDAYS.index(week_start_day)) % 7
        return today - timedelta(days=offset), today
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

# "Today" comes from Snowflake so the presets line up with the date filters in SQL.
today, _now_txt = snowflake_now()
if "last_refreshed" not in st.session_state:
    st.session_state.last_refreshed = _now_txt
if "date_preset" not in st.session_state:
    st.session_state.date_preset = LABEL_BY_CODE[date_range]
if "custom_range" not in st.session_state:
    st.session_state.custom_range = dates_for(date_range, today)

title_col, range_col = st.columns([3.2, 1.3])
with title_col:
    st.markdown(
        f'<div class="masthead">{_logo_html}<h1>AI Consumption Dashboard</h1></div>'
        '<div class="subhead">Overview of usage on the account.</div>'
        f'<div style="color:{MUTED};font-size:.75rem;margin:-0.35rem 0 0.15rem 0;">'
        f"Page opened: {html.escape(str(st.session_state.last_refreshed))} · "
        "usage data is cached for up to 1 hour, quota status for 15 minutes</div>",
        unsafe_allow_html=True,
    )

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
elif isinstance(picked, (tuple, list)) and len(picked) == 1:
    # Custom range half-picked (only the start date chosen so far): show that one day.
    start_date = end_date = picked[0]
else:
    start_date = end_date = today

with range_col:
    st.markdown(
        f'<div style="color:{MUTED};font-size:.75rem;margin-top:-0.35rem;">'
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
),
gateway AS (
    SELECT 'AI Gateway' AS service, ROUND(SUM(CREDITS), 4) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY
    WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
),
-- AI_INFERENCE metering covers both the Cortex REST API and AI Gateway. The REST API
-- view has no credits column, so REST API = metered AI_INFERENCE minus Gateway credits.
-- Metering days are UTC while Gateway rows are filtered in the session time zone, so the
-- two windows differ slightly; once Gateway has usage, REST API can be a little off near
-- the range edges (GREATEST stops it going negative).
rest_api AS (
    SELECT 'Cortex REST API' AS service,
           ROUND(GREATEST(
               (SELECT COALESCE(SUM(CREDITS_USED), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
                 WHERE SERVICE_TYPE = 'AI_INFERENCE' AND USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}')
             - (SELECT COALESCE(SUM(CREDITS), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY
                 WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'),
           0), 4) AS credits
)
SELECT * FROM agent UNION ALL SELECT * FROM ai_func
UNION ALL SELECT * FROM analyst UNION ALL SELECT * FROM search
UNION ALL SELECT * FROM code_ss UNION ALL SELECT * FROM code_cli
UNION ALL SELECT * FROM code_desktop UNION ALL SELECT * FROM cowork
UNION ALL SELECT * FROM gateway UNION ALL SELECT * FROM rest_api
"""

df_summary = run(summary_sql, p_start, p_end)
if df_summary.empty:  # query failed; run() has shown the error
    df_summary = pd.DataFrame(columns=["SERVICE", "CREDITS"])
#Calculate some totals
df_summary["CREDITS"] = df_summary["CREDITS"].fillna(0)
df_summary["COST"] = df_summary["CREDITS"].astype(float) * df_summary["SERVICE"].map(rate_for).astype(float)
total_credits = df_summary["CREDITS"].sum()
total_cost = float(df_summary["COST"].sum())
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
    ), gateway AS (
        SELECT ROUND(SUM(CREDITS), 4) AS credits FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'
    ), rest_api AS (
        -- Metered AI_INFERENCE minus Gateway credits (see summary_sql)
        SELECT ROUND(GREATEST(
            (SELECT COALESCE(SUM(CREDITS_USED), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
              WHERE SERVICE_TYPE = 'AI_INFERENCE' AND USAGE_DATE >= '{prev_start}' AND USAGE_DATE < '{prev_end}')
          - (SELECT COALESCE(SUM(CREDITS), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY
              WHERE START_TIME >= '{prev_start}' AND START_TIME < '{prev_end}'),
        0), 4) AS credits
    )
    SELECT COALESCE(SUM(credits), 0) AS total FROM (
        SELECT * FROM agent UNION ALL SELECT * FROM ai_func
        UNION ALL SELECT * FROM analyst UNION ALL SELECT * FROM search
        UNION ALL SELECT * FROM code_ss UNION ALL SELECT * FROM code_cli
        UNION ALL SELECT * FROM code_desktop UNION ALL SELECT * FROM cowork
        UNION ALL SELECT * FROM gateway UNION ALL SELECT * FROM rest_api
    )
    """
    df_prev = run(prev_sql, p_start, p_end)
    prev_credits = df_prev["TOTAL"].iloc[0] if not df_prev.empty else None
    if prev_credits is None:  # query failed; run() has shown the error
        delta_str = "N/A"
    elif prev_credits > 0:
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
avg_daily_cost = total_cost / num_days

#Count total requests
total_code_requests_sql = f"""
SELECT
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') +
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') +
    (SELECT COUNT(DISTINCT REQUEST_ID) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY WHERE USAGE_TIME >= '{p_start}' AND USAGE_TIME < '{p_end}') AS TOTAL_REQUESTS
"""
df_code_requests = run(total_code_requests_sql, p_start, p_end)
total_code_requests = int(df_code_requests["TOTAL_REQUESTS"].iloc[0]) if not df_code_requests.empty else 0

def _kpi_delta_pill(delta_str: str) -> str:
    """Map the prior-period string onto the cost-summary pill."""
    if delta_str in (None, "", "N/A"):
        return ""
    if delta_str == "New":
        return '<span class="delta-pill rise">↑ new</span>'
    raw = str(delta_str).strip().rstrip("%")
    try:
        pct = float(raw)
    except ValueError:
        return f'<span class="delta-pill flat">{html.escape(str(delta_str))} vs prior</span>'
    if pct > 0:
        return f'<span class="delta-pill rise">↑ {pct:+.1f}%</span>'
    if pct < 0:
        return f'<span class="delta-pill fall">↓ {pct:+.1f}%</span>'
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

# Name the actual comparison window, and flag that a range ending today is partial.
_prior_text = (
    f"Change vs the previous {num_days:,} day{'s' if num_days != 1 else ''} "
    f"({(start_date - timedelta(days=num_days)):%Y-%m-%d} → {(start_date - timedelta(days=1)):%Y-%m-%d})."
)
if end_date >= today:
    _prior_text += " Today is partial (and usage data can lag by hours), so the change reads low."
st.markdown(
    f'<div class="kpi-note" style="margin:-1rem 0 0 0;padding:0 0 0.65rem 0;">'
    f'{_prior_text}'
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
        "label": "Total AI Cost",
        "value": f"${total_cost:,.2f}",
        "delta": "",
        "foot": [],
        "primary": False,
        # Shown under the card. "&#36;" is "$" written so markdown can't read $...$ as math.
        "caption": [
            f"&#36;{ai_credit_rate:,.2f}/AI Credit ({'regional, assumed' if ai_routing == 'unknown' else ai_routing})",
            f"&#36;{platform_rate:,.2f}/Platform Credit (Analyst API)",
        ],
    },
    {
        "label": "Avg Daily Burn",
        "value": f"{avg_daily:,.4f}",
        "delta": "",
        "foot": [f"${avg_daily_cost:,.2f} per day"],
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
k = st.columns(len(cards))
for col, c in zip(k, cards):
    with col:
        st.markdown(
            card_html(c["label"], c["value"], c["delta"], c["foot"], c["primary"]),
            unsafe_allow_html=True,
        )
        if c.get("caption"):
            # Same style as the "Change vs the previous ..." note above the cards.
            st.markdown(
                f'<div class="kpi-note" style="margin-top:.35rem;">'
                + "<br>".join(c["caption"])
                + "</div>",
                unsafe_allow_html=True,
            )

# ----------------------------------------------------------------------
# Tabs
# Quota and Admin tabs appear only when the quota exists; Admin only for
# users listed in quota_admins (see the Admin section below).
# ----------------------------------------------------------------------

def _collect_df(sql: str) -> pd.DataFrame:
    # Build from collected rows: to_pandas() does not pick up the result
    # schema of CALL / SHOW statements and fails with a column-count mismatch.
    rows = session.sql(sql).collect()
    df = pd.DataFrame([r.as_dict() for r in rows])
    for c in df.columns:
        if df[c].map(lambda v: isinstance(v, decimal.Decimal)).any():
            df[c] = df[c].astype(float)
    df.columns = [str(c).strip().strip('"').upper() for c in df.columns]
    return df


@st.cache_data(ttl=900, show_spinner="Reading quota...")
def _sql_cached(sql: str) -> pd.DataFrame:
    return _collect_df(sql)


def quota_page_url(fqn: str) -> str:
    """The quota's Snowsight page (Admin » Cost management » Budgets).
    quota_url in config.json overrides the URL built from quota_fqn."""
    if quota_url:
        return quota_url
    acct = _sql_cached("SELECT LOWER(CURRENT_ORGANIZATION_NAME()) AS ORG, LOWER(CURRENT_ACCOUNT_NAME()) AS ACCT")
    db, schema, name = fqn.split(".")
    return (
        f"https://app.snowflake.com/{acct['ORG'].iloc[0]}/{acct['ACCT'].iloc[0]}"
        f"/#/account/usage/quota/{db.upper()}/{schema.upper()}/{name.upper()}"
    )


def quota_state(fqn: str, explicit: bool) -> tuple:
    """Return ("ok" | "absent" | "error", detail).

    Reading the quota is the existence test. SHOW lists only quotas the owner role can
    see, and Snowflake reports "does not exist or not authorized" for both cases, so
    "not found" can mean a missing privilege. When quota_fqn is set in config.json
    (explicit), every failure is therefore reported. Only the built-in default quota is
    hidden ("absent") when it cannot be found.

    A successful read is cached for 15 minutes (shared with the Quota tab, cleared by the
    Admin tab after a change). Streamlit never caches a failed call, so failures are
    re-checked on every run and a one-off error can't stick.
    """
    db, schema, name = fqn.split(".")
    try:
        _sql_cached(f"CALL {fqn}!GET_CONFIG()")
        return "ok", None
    except Exception as call_err:
        try:
            rows = session.sql(f"SHOW SNOWFLAKE.CORE.QUOTA INSTANCES LIKE '{name}' IN SCHEMA {db}.{schema}").collect()
        except Exception as show_err:
            # Missing (or invisible) database or schema.
            if not explicit and "does not exist" in str(show_err).lower():
                return "absent", None
            return "error", f"GET_CONFIG failed: {call_err} | SHOW failed: {show_err}"
        # LIKE treats "_" as a wildcard, so confirm the exact name.
        if any(str(r.as_dict().get("name", "")).upper() == name.upper() for r in rows):
            return "error", f"The quota exists but could not be read: {call_err}"
        if explicit:
            return "error", f"Quota not found, or the app's owner role cannot see it. Details: {call_err}"
        return "absent", None


_quota_explicit = bool(str(_cfg.get("quota_fqn") or "").strip())
_quota_state, _quota_detail = quota_state(quota_fqn, _quota_explicit) if quota_fqn else ("absent", None)

_show_quota_tab = _quota_state != "absent"
_show_admin_tab = _show_quota_tab and is_quota_admin()
_tab_names = ["Overview", "Users", "Efficiency"]
if _show_quota_tab:
    _tab_names.append("Quota")
if _show_admin_tab:
    _tab_names.append("Admin")
st.divider()  # separates the KPI cards from the tabs
_main_tabs = dict(zip(_tab_names, st.tabs(_tab_names)))
# Each tab shows a loading message until its section has finished, so tabs further
# down the script don't look empty while the page is still running.
_loading = {name: tab.empty() for name, tab in _main_tabs.items()}
for _ph in _loading.values():
    _ph.info("Loading data for this tab…")


with _main_tabs["Overview"]:
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
                color=alt.Color("SERVICE:N", title="Service", scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
                tooltip=["SERVICE", "CREDITS"]
            ).properties(height=300)
            st.altair_chart(pie, use_container_width=True)
        else:
            st.info("No data.")

    # ----------------------------------------------------------------------
    # Credit Summary
    # ----------------------------------------------------------------------

    #Credit Summary
    st.divider()
    st.subheader("Credit Summary Table")
    st.dataframe(df_summary.sort_values("CREDITS", ascending=False).reset_index(drop=True),
                 use_container_width=True, hide_index=True, column_config=COST_COLUMN)
    info_text(
        "AI Functions includes all AISQL function calls (AI_COMPLETE, AI_CLASSIFY, etc.). "
        "Cortex Agents includes Cortex Analyst tool calls made by agents; those are not in Cortex Analyst. "
        "Snowflake CoWork (formerly Snowflake Intelligence) excludes Cortex Agent requests, so the two do not overlap. "
        "Cortex REST API comes from metering (AI_INFERENCE minus AI Gateway), which is by UTC day and not by user; "
        "its cost assumes it is billed in AI Credits, so treat it as an estimate until your invoice confirms this. "
        + pricing_text()
    )

    # ----------------------------------------------------------------------
    # Check against metered credits (what Snowflake bills from)
    # Account-level daily totals by SERVICE_TYPE; used only as a cross-check, because
    # service types get renamed (e.g. CORTEX_CODE_CLI -> SNOWFLAKE_COCO_CLI) and
    # AI_SERVICES groups several services. Service types the app does not read are flagged.
    # ----------------------------------------------------------------------

    st.markdown('<div class="panel-title">Check against metered credits</div>', unsafe_allow_html=True)
    df_meter = run(f"""
        SELECT SERVICE_TYPE, ROUND(SUM(CREDITS_USED), 4) AS CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}'
          AND SERVICE_TYPE RLIKE '^(CORTEX_|AI_|SNOWFLAKE_COCO|SNOWFLAKE_COWORK|SNOWFLAKE_INTELLIGENCE).*'
        GROUP BY 1
        HAVING SUM(CREDITS_USED) <> 0
        ORDER BY 2 DESC
    """, p_start, p_end)
    # Service types whose usage the app already reads through its per-service views.
    COVERED_TYPES = {
        "AI_SERVICES", "AI_FUNCTIONS", "CORTEX_AGENTS", "CORTEX_SEARCH",
        "CORTEX_CODE_CLI", "CORTEX_CODE_SNOWSIGHT", "CORTEX_CODE_DESKTOP",
        "SNOWFLAKE_COCO", "SNOWFLAKE_COCO_CLI", "SNOWFLAKE_COCO_SNOWSIGHT", "SNOWFLAKE_COCO_DESKTOP",
        "SNOWFLAKE_INTELLIGENCE", "SNOWFLAKE_COWORK",
        "AI_INFERENCE",  # Cortex REST API + AI Gateway (both shown in the app)
    }
    # Note: the app's Cortex REST API line is itself derived from AI_INFERENCE metering, so
    # it always matches here. This check verifies the other services, not the REST API.
    if df_meter.empty:
        st.info("No metered AI credits in the selected period.")
    else:
        df_meter["CREDITS"] = df_meter["CREDITS"].astype(float)
        df_meter["IN_APP"] = df_meter["SERVICE_TYPE"].isin(COVERED_TYPES).map({True: "Yes", False: "No"})
        metered_total = float(df_meter["CREDITS"].sum())
        metered_covered = float(df_meter.loc[df_meter["IN_APP"] == "Yes", "CREDITS"].sum())
        diff = metered_covered - total_credits
        meter_cards = [
            card_html("App total (usage views)", f"{total_credits:,.4f}",
                      foot_lines=["Total AI Credits above"], primary=True),
            card_html("Metered, services the app covers", f"{metered_covered:,.4f}",
                      foot_lines=[f"{diff:+,.2f} vs app total"]),
            card_html("Metered, all AI service types", f"{metered_total:,.4f}",
                      foot_lines=[f"{metered_total - metered_covered:,.2f} not shown in the app"]),
        ]
        for col, card in zip(st.columns(3), meter_cards):
            with col:
                st.markdown(card, unsafe_allow_html=True)
        st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)  # space below the cards
        with st.expander("Metered credits by service type"):
            st.dataframe(df_meter.reset_index(drop=True), use_container_width=True, hide_index=True)
        info_text(
            "Source: SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY, CREDITS_USED (UTC days, before billing adjustments). "
            "Small differences from the app total are expected: metering and the usage views refresh "
            "at different times, and metering days are UTC while the date filter uses your session time zone."
        )

    # ----------------------------------------------------------------------
    # Daily Credit Trend
    # ----------------------------------------------------------------------

    st.divider()
    st.subheader("Daily Credit Trend")

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
                -- Limit the QUERY_HISTORY scan to the range; one extra day keeps queries
                -- that started before midnight but used AI credits inside the range.
                AND q.START_TIME >= DATEADD(day, -1, '{p_start}'::DATE) AND q.START_TIME < '{p_end}'
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
            UNION ALL
            SELECT DATE(START_TIME), 'AI Gateway', SUM(CREDITS)
            FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY
            WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}' GROUP BY DATE(START_TIME)
            UNION ALL
            -- Cortex REST API: metered AI_INFERENCE minus Gateway credits, per day (see summary_sql)
            SELECT m.USAGE_DATE, 'Cortex REST API', GREATEST(m.CREDITS - COALESCE(g.CREDITS, 0), 0)
            FROM (
                SELECT USAGE_DATE, SUM(CREDITS_USED) AS CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
                WHERE SERVICE_TYPE = 'AI_INFERENCE' AND USAGE_DATE >= '{p_start}' AND USAGE_DATE < '{p_end}'
                GROUP BY USAGE_DATE
            ) m
            LEFT JOIN (
                SELECT DATE(START_TIME) AS USAGE_DATE, SUM(CREDITS) AS CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY
                WHERE START_TIME >= '{p_start}' AND START_TIME < '{p_end}'
                GROUP BY DATE(START_TIME)
            ) g ON g.USAGE_DATE = m.USAGE_DATE
        )
        SELECT USAGE_DATE, SERVICE AS DIMENSION, ROUND(CREDITS, 4) AS CREDITS FROM daily_data ORDER BY USAGE_DATE
        """
        color_field = "DIMENSION"
        chart_title = "Daily Credits by Service"

    df_trend = run(trend_sql, p_start, p_end)

    #Line chart with series    
    if not df_trend.empty:
        # Service colors only apply to services; warehouses and databases use the
        # default palette so the legend lists them, not the service names.
        if trend_view == "All Services":
            trend_scale = alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))
        else:
            trend_scale = alt.Scale()
        stacked = alt.Chart(df_trend).mark_area(opacity=0.7).encode(
            x=alt.X("USAGE_DATE:T", title="Date"),
            y=alt.Y("CREDITS:Q", stack="zero", title="Credits"),
            color=alt.Color(f"{color_field}:N", title=chart_title.split("by ")[-1], scale=trend_scale),
            tooltip=["USAGE_DATE:T", f"{color_field}:N", "CREDITS:Q"]
        ).properties(height=350)
        st.altair_chart(stacked, use_container_width=True)
        if trend_view == "By Warehouse (AI Functions)":
            info_text(
                "AI Functions only, and only queries that ran on a warehouse, so this chart won't add up to "
                "the totals above. Warehouses come from QUERY_HISTORY, which can make long ranges slow to load."
            )
    else:
        st.info("No daily trend data in selected period.")

_loading["Overview"].empty()

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
    "AI Gateway": "Gateway request",
    "AI Functions": "SQL query",
}
INTERACTIVE_SERVICES = ["Cortex Agents", "Cortex Analyst", "Cortex Code (Snowsight)", "Cortex Code (CLI)",
                        "Cortex Code (Desktop)", "Snowflake CoWork", "AI Gateway"]
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

    UNION ALL
    SELECT COALESCE(u.NAME, IFF(h.USER_ID = 0, 'SYSTEM', 'USER_ID ' || h.USER_ID)), 'AI Gateway', h.CREDITS, NULL,
           h.REQUEST_ID::VARCHAR, 0
    FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON h.USER_ID = u.USER_ID
    WHERE h.START_TIME >= '{p_start}' AND h.START_TIME < '{p_end}'
)
"""

# Requests = distinct request keys + pre-aggregated Analyst request counts.
REQUESTS_EXPR = "COUNT(DISTINCT request_key) + COALESCE(SUM(request_n), 0)"

# One query at user + service level feeds every table on the Users and Efficiency
# tabs; each table is built from this result in pandas (see sum_by and the tabs).
# Request keys never repeat across services (agent/Code/CoWork request IDs, AI
# Functions query IDs), so adding up per-service request counts gives the same total
# as counting distinct keys across services.
user_service_sql = f"""
{user_usage_cte}
SELECT user_name AS USER_NAME,
       service AS SERVICE,
       SUM(credits) AS TOTAL_CREDITS,
       SUM(tokens) AS TOTAL_TOKENS,
       {REQUESTS_EXPR} AS TOTAL_REQUESTS
FROM user_usage
GROUP BY 1, 2
"""
_US_COLS = ["USER_NAME", "SERVICE", "TOTAL_CREDITS", "TOTAL_TOKENS", "TOTAL_REQUESTS"]
try:
    df_user_service = _query(user_service_sql, p_start, p_end)
    _user_service_err = None
except Exception as e:
    df_user_service = pd.DataFrame(columns=_US_COLS)
    _user_service_err = e  # shown in the Users and Efficiency tabs
for _c in ["TOTAL_CREDITS", "TOTAL_TOKENS", "TOTAL_REQUESTS"]:
    df_user_service[_c] = pd.to_numeric(df_user_service[_c], errors="coerce")
# Cost per row at its service's rate, so totals by user add up across services.
df_user_service["COST"] = df_user_service["TOTAL_CREDITS"] * df_user_service["SERVICE"].map(rate_for).astype(float)


def user_service_warning() -> None:
    if _user_service_err is not None:
        st.warning(f"Query failed, section will be empty: {_user_service_err}")


def sum_by(df: pd.DataFrame, keys: list) -> pd.DataFrame:
    """Add up credits, cost, tokens and requests by `keys`. Tokens stay blank when every
    row is blank (AI Functions and Analyst report none), as SQL SUM does."""
    if df.empty:
        return pd.DataFrame(columns=keys + ["TOTAL_CREDITS", "COST", "TOTAL_TOKENS", "TOTAL_REQUESTS"])
    return df.groupby(keys, as_index=False, dropna=False).agg(
        TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
        COST=("COST", "sum"),
        TOTAL_TOKENS=("TOTAL_TOKENS", lambda s: s.sum(min_count=1)),
        TOTAL_REQUESTS=("TOTAL_REQUESTS", "sum"),
    )


def add_cost_per_request(df: pd.DataFrame) -> pd.DataFrame:
    df["TOTAL_CREDITS"] = df["TOTAL_CREDITS"].fillna(0)
    df["TOTAL_REQUESTS"] = df["TOTAL_REQUESTS"].fillna(0).astype(int)
    df = df[df["TOTAL_REQUESTS"] > 0].copy()
    df["UNIT"] = df["SERVICE"].map(SERVICE_UNITS)
    df["CREDITS_PER_REQUEST"] = (df["TOTAL_CREDITS"] / df["TOTAL_REQUESTS"]).round(6)
    return df.sort_values("CREDITS_PER_REQUEST", ascending=False)


def cpr_chart(df: pd.DataFrame, y_field: str, x_title: str, height: int, show_legend: bool = False):
    # One legend per section: the scale domain lists every service, so the
    # legend on one chart also covers its neighbour.
    legend = alt.Legend(title="Service") if show_legend else None
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("CREDITS_PER_REQUEST:Q", title=x_title),
        y=alt.Y(f"{y_field}:N", sort="-x", title=""),
        color=alt.Color("SERVICE:N", legend=legend, scale=alt.Scale(domain=list(service_colors.keys()), range=list(service_colors.values()))),
        tooltip=[c for c in ["USER_NAME", "SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "CREDITS_PER_REQUEST"] if c in df.columns],
    ).properties(height=height)


with _main_tabs["Efficiency"]:
    # ----------------------------------------------------------------------
    # Cost Efficiency
    # ----------------------------------------------------------------------

    st.subheader("Cost Efficiency by Service")
    user_service_warning()

    # From user_service_sql: services other than Search, added up across users.
    df_eff = sum_by(df_user_service[df_user_service["SERVICE"] != "Cortex Search"], ["SERVICE"])
    df_eff = df_eff.drop(columns="TOTAL_TOKENS")
    df_eff["TOTAL_CREDITS"] = pd.to_numeric(df_eff["TOTAL_CREDITS"]).round(6)
    if not df_eff.empty:
        df_eff = add_cost_per_request(df_eff)

    if not df_eff.empty:
        eff_cols = ["SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "CREDITS_PER_REQUEST"]
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
        info_text(
            "Units differ by service. An AI Functions query can process many rows, so its cost per query "
            "is not comparable to a single agent or Code request. Cortex Search has no request count and is excluded."
        )
    else:
        st.info("No request data in selected period.")

with _main_tabs["Users"]:
    # ----------------------------------------------------------------------
    # Users by credit
    # ----------------------------------------------------------------------

    st.subheader("Top Users by AI Credits")
    user_service_warning()

    TAB_SERVICES = ["Cortex Agents", "Snowflake CoWork", "AI Functions", "Cortex Analyst",
                    "Cortex Code (Snowsight)", "Cortex Code (CLI)", "Cortex Code (Desktop)", "AI Gateway"]
    tabs = st.tabs(["Total AI Use"] + TAB_SERVICES)

    def users_table(df: pd.DataFrame) -> pd.DataFrame:
        """From user_service_sql: one row per user, highest credits first."""
        t = sum_by(df, ["USER_NAME"]).rename(columns={"TOTAL_REQUESTS": "REQUESTS"})
        t["TOTAL_CREDITS"] = pd.to_numeric(t["TOTAL_CREDITS"]).round(4)
        return t.sort_values("TOTAL_CREDITS", ascending=False).reset_index(drop=True)

    with tabs[0]:
        st.dataframe(users_table(df_user_service), use_container_width=True, hide_index=True,
                     column_config=COST_COLUMN)
        info_text(
            "Includes every service except Cortex REST API (metered for the account, not per user), so the "
            "column totals match Total AI Credits and Total AI Cost less any REST API spend. "
            "Cortex Search is billed per service, not per user. SYSTEM is Snowflake's internal user (USER_ID 0). "
            "Requests mix units across services; see Cost Efficiency for per-service units. "
            "AI Functions does not report tokens. " + pricing_text()
        )

    for tab, svc in zip(tabs[1:], TAB_SERVICES):
        with tab:
            st.dataframe(users_table(df_user_service[df_user_service["SERVICE"] == svc]),
                         use_container_width=True, hide_index=True, column_config=COST_COLUMN)
            info_text(f"Requests counted per {SERVICE_UNITS[svc]}. Cost at ${rate_for(svc):,.2f} per credit.")

_loading["Users"].empty()

# ----------------------------------------------------------------------
# AI Quota Status
# Read from the quota's own API so the figures match what it enforces.
# Quota cycles are UTC and independent of the date range selected above.
# Hidden entirely when quota_fqn is invalid or the quota does not exist.
# ----------------------------------------------------------------------


def _limit(cfg: pd.DataFrame, col: str) -> Optional[float]:
    if col not in cfg.columns or pd.isna(cfg[col].iloc[0]):
        return None
    return float(cfg[col].iloc[0])


@st.cache_data(ttl=900, show_spinner=False)
def _unlimited_spend(names: tuple, since_utc: str) -> pd.DataFrame:
    """Hourly AI spend from ACCOUNT_USAGE for users the quota excludes, in every domain
    (the caller keeps only the quota's domains). Names are bound as parameters;
    since_utc is an app-generated timestamp."""
    ph = ", ".join("?" for _ in names)
    sql = f"""
        WITH u AS (
            SELECT USER_NAME AS n, 'CORTEX AGENT' AS d, TOKEN_CREDITS AS c, START_TIME::TIMESTAMP_TZ AS t
              FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
             WHERE START_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT x.NAME, 'AI FUNCTION', h.CREDITS, h.START_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY h
              JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS x ON h.USER_ID = x.USER_ID
             WHERE h.START_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT USER_NAME, 'SNOWFLAKE INTELLIGENCE', TOKEN_CREDITS, START_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY
             WHERE START_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT x.NAME, 'CORTEX CODE', h.TOKEN_CREDITS, h.USAGE_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY h
              JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS x ON h.USER_ID = x.USER_ID
             WHERE h.USAGE_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT x.NAME, 'CORTEX CODE', h.TOKEN_CREDITS, h.USAGE_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY h
              JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS x ON h.USER_ID = x.USER_ID
             WHERE h.USAGE_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT USER_NAME, 'CORTEX CODE', TOKEN_CREDITS, USAGE_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
             WHERE USAGE_TIME >= '{since_utc}'::TIMESTAMP_TZ
            UNION ALL
            SELECT x.NAME, 'AI GATEWAY', h.CREDITS, h.START_TIME::TIMESTAMP_TZ
              FROM SNOWFLAKE.ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY h
              JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS x ON h.USER_ID = x.USER_ID
             WHERE h.START_TIME >= '{since_utc}'::TIMESTAMP_TZ
        )
        SELECT n AS USER_NAME, d AS ENTITY_TYPE, SUM(c) AS CREDITS_SPEND,
               DATE_TRUNC('hour', CONVERT_TIMEZONE('UTC', t)) AS HOUR_UTC
          FROM u WHERE n IN ({ph})
         GROUP BY 1, 2, 4
    """
    rows = session.sql(sql, params=list(names)).collect()
    df = pd.DataFrame([r.as_dict() for r in rows])
    if df.empty:
        return pd.DataFrame(columns=["USER_NAME", "ENTITY_TYPE", "CREDITS_SPEND", "TS"])
    df.columns = [str(c).upper() for c in df.columns]
    df["CREDITS_SPEND"] = df["CREDITS_SPEND"].astype(float)
    df["TS"] = pd.to_datetime(df["HOUR_UTC"], utc=True)
    return df


def quota_status_section(fqn: str) -> None:
    now_utc = pd.Timestamp.now(tz="UTC")
    day_start = now_utc.normalize()
    # The quota's weekly cycle starts on Sunday (UTC). That's set by Snowflake, so it
    # deliberately ignores config week_start, which only moves the Week to Date range.
    # (dayofweek: Monday=0 ... Sunday=6)
    week_start = day_start - pd.Timedelta(days=(day_start.dayofweek + 1) % 7)
    month_start = day_start.replace(day=1)
    fetch_start = min(week_start, month_start)  # a week can start in the previous month
    # End date is tomorrow so today's spend is always included, whether the method
    # treats its end date as inclusive or exclusive.
    fetch_end = day_start + pd.Timedelta(days=1)

    cfg = _sql_cached(f"CALL {fqn}!GET_CONFIG()")
    scope = json.loads(_sql_cached(f"CALL {fqn}!GET_QUOTA_SCOPE()").iloc[0, 0])
    spend = _sql_cached(
        f"CALL {fqn}!GET_SPENDING_DETAILS_BY_USERS("
        f"'{fetch_start:%Y-%m-%d}'::DATE, '{fetch_end:%Y-%m-%d}'::DATE)"
    )
    blocks = _sql_cached(f"CALL {fqn}!GET_ACTIVE_BLOCKS_V2()")

    limits = {
        "MONTH": _limit(cfg, "PER_USER_LIMIT"),
        "WEEK": _limit(cfg, "PER_USER_LIMIT_WEEKLY"),
        "DAY": _limit(cfg, "PER_USER_LIMIT_DAILY"),
    }
    enforcement = bool(cfg["BLOCK_ENFORCEMENT_ENABLED"].iloc[0]) if "BLOCK_ENFORCEMENT_ENABLED" in cfg.columns else False
    domains = [r.get("domain", "") for r in scope.get("shared_resources", [])]
    excluded = [u.get("user_name", "") for u in scope.get("excluded_users", [])]

    def fmt_limit(v):
        return "not set" if v is None else f"{v:,.0f}"

    # Link straight to the quota's page under Admin » Cost management » Budgets.
    docs_link = '<a href="https://docs.snowflake.com/en/user-guide/budgets/per-user-quotas" target="_blank">docs</a>'
    target = quota_page_url(fqn)
    link_html = f'<a href="{html.escape(target, quote=True)}" target="_blank">Open quota {html.escape(fqn)}</a> · {docs_link}'

    st.markdown(
        f'<div class="note" style="margin-top:0">'
        f"{link_html}<br>"
        f"<b>{fqn}</b> · per-user limits: month {fmt_limit(limits['MONTH'])}, "
        f"week {fmt_limit(limits['WEEK'])}, day {fmt_limit(limits['DAY'])} credits · "
        f"block enforcement {'ON' if enforcement else 'OFF'} · "
        f"counts: {html.escape(', '.join(domains)) or 'nothing (no shared resources)'} · "
        f"not limited: {html.escape(', '.join(excluded)) or 'none'}<br>"
        f"Cycles are UTC: month from {month_start:%Y-%m-%d}, week from {week_start:%Y-%m-%d}, "
        f"day {day_start:%Y-%m-%d}. The date range at the top of the page does not apply here."
        f"</div>",
        unsafe_allow_html=True,
    )

    if not spend.empty:
        spend["TS"] = pd.to_datetime(spend["USAGE_TIMESTAMP"], utc=True)
        spend["CREDITS_SPEND"] = spend["CREDITS_SPEND"].astype(float)
        in_month = spend[spend["TS"] >= month_start]
        per_user = pd.DataFrame({
            "MONTH": in_month.groupby("USER_NAME")["CREDITS_SPEND"].sum(),
            "WEEK": spend[spend["TS"] >= week_start].groupby("USER_NAME")["CREDITS_SPEND"].sum(),
            "DAY": spend[spend["TS"] >= day_start].groupby("USER_NAME")["CREDITS_SPEND"].sum(),
        }).fillna(0.0)
        by_domain = in_month.groupby(["USER_NAME", "ENTITY_TYPE"])["CREDITS_SPEND"].sum().reset_index()
        by_domain["TXT"] = by_domain["ENTITY_TYPE"] + " " + by_domain["CREDITS_SPEND"].map("{:,.2f}".format)
        per_user["MONTH_BY_DOMAIN"] = by_domain.groupby("USER_NAME")["TXT"].agg(", ".join)
    else:
        per_user = pd.DataFrame(columns=["MONTH", "WEEK", "DAY", "MONTH_BY_DOMAIN"])
    # Quota-counted spend only; "not limited" rows added below are not part of it.
    quota_total = float(per_user["MONTH"].sum()) if not per_user.empty else 0.0

    # Blocked users appear even if their spend falls outside the fetched window.
    block_text = {}
    if not blocks.empty:
        for _, b in blocks.iterrows():
            until = pd.to_datetime(b["BLOCKED_UNTIL"], utc=True)
            block_text.setdefault(b["USER_NAME"], []).append(f"{b['CYCLE'].title()} until {until:%Y-%m-%d %H:%M} UTC")
        for u in block_text:
            if u not in per_user.index:
                per_user.loc[u] = [0.0, 0.0, 0.0, ""]

    # Full roster: every user the quota covers, at 0 if they have no spend. GET_USERS also
    # returns internal RESOURCE_PLACEHOLDER entries and users dropped this month, so keep
    # only active account users.
    roster = _sql_cached(f"CALL {fqn}!GET_USERS()")
    active = set(_sql_cached(
        "SELECT UPPER(NAME) AS NAME FROM SNOWFLAKE.ACCOUNT_USAGE.USERS WHERE DELETED_ON IS NULL"
    ).get("NAME", pd.Series(dtype=str)))
    roster_names = sorted({
        n for n in roster.get("USER_NAME", pd.Series(dtype=str)).dropna()
        if n != "RESOURCE_PLACEHOLDER" and n.upper() in active
    })
    for u in roster_names:
        if u not in per_user.index:
            per_user.loc[u] = [0.0, 0.0, 0.0, ""]

    # Excluded users: the quota does not track them, so their spend comes from ACCOUNT_USAGE
    # for the same domains and cycles, shown for comparison with status EXCLUDED.
    unlimited = [u for u in excluded if u]
    if unlimited:
        unl = _unlimited_spend(tuple(unlimited), f"{fetch_start:%Y-%m-%d %H:%M:%S} +00:00")
        # Count only the domains this quota tracks, so EXCLUDED rows compare like for like.
        def _dom(v) -> str:
            return str(v).replace("_", " ").strip().upper()
        tracked = {_dom(d) for d in domains if d}
        if not unl.empty:
            unl = unl[unl["ENTITY_TYPE"].map(_dom).isin(tracked)]
        for u in unlimited:
            rows = unl[unl["USER_NAME"] == u] if not unl.empty else unl
            m = rows[rows["TS"] >= month_start] if not rows.empty else rows
            dom = (
                m.groupby("ENTITY_TYPE")["CREDITS_SPEND"].sum()
                if not m.empty else pd.Series(dtype=float)
            )
            per_user.loc[u] = [
                float(m["CREDITS_SPEND"].sum()) if not m.empty else 0.0,
                float(rows[rows["TS"] >= week_start]["CREDITS_SPEND"].sum()) if not rows.empty else 0.0,
                float(rows[rows["TS"] >= day_start]["CREDITS_SPEND"].sum()) if not rows.empty else 0.0,
                ", ".join(f"{e} {c:,.2f}" for e, c in dom.items()),
            ]

    if per_user.empty:
        st.info("No users in scope and no quota-counted spend in the current cycles.")
    else:
        for cyc, lim in limits.items():
            spent = per_user[cyc].astype(float)
            if lim is None:
                per_user[f"{cyc}_PCT"] = None
            else:
                per_user[f"{cyc}_PCT"] = (spent / lim * 100).round(1)

        def status(row):
            if row.name in unlimited:
                return "EXCLUDED"
            if row.name in block_text:
                return "Blocked: " + "; ".join(block_text[row.name])
            pcts = [row[f"{c}_PCT"] for c in limits if limits[c] is not None and pd.notna(row[f"{c}_PCT"])]
            worst = max(pcts) if pcts else 0
            if worst >= 100:
                return "Over limit"
            if worst >= quota_warning_pct:
                return f"Warning ({quota_warning_pct:g}%+)"
            return "OK"

        per_user["STATUS"] = per_user.apply(status, axis=1)
        table = (
            per_user.reset_index().rename(columns={"index": "USER_NAME"})
            .sort_values(["MONTH", "USER_NAME"], ascending=[False, True])  # month credits, highest first, any status
        )
        for cyc in limits:
            table[cyc] = table[cyc].astype(float).round(4)
        # Top users (config top_users) by month credits unless "show all" is ticked.
        # Blocked and excluded users are always kept so they are never hidden.
        total_users = len(table)
        top_n = top_users
        show_all = st.checkbox(f"Show all {total_users} users", value=False, key="quota_show_all")
        table = table.reset_index(drop=True)
        if not show_all:
            keep = table["STATUS"].str.startswith("Blocked") | (table["STATUS"] == "EXCLUDED")
            table = table[(table.index < top_n) | keep]
        cols = ["USER_NAME", "STATUS", "MONTH", "MONTH_PCT", "WEEK", "WEEK_PCT", "DAY", "DAY_PCT", "MONTH_BY_DOMAIN"]
        table = table[cols].reset_index(drop=True)

        # Readable headers; % columns show the limit they are measured against.
        def pct_label(cyc, title):
            lim = limits[cyc]
            return f"{title} % of {lim:,.0f}" if lim is not None else f"{title} % (no limit)"

        headers = {
            "USER_NAME": "User", "STATUS": "Status",
            "MONTH": "Month credits", "MONTH_PCT": pct_label("MONTH", "Month"),
            "WEEK": "Week credits", "WEEK_PCT": pct_label("WEEK", "Week"),
            "DAY": "Today credits", "DAY_PCT": pct_label("DAY", "Today"),
            "MONTH_BY_DOMAIN": "Month by domain",
        }
        table = table.rename(columns=headers)
        pct_cols = [headers[f"{c}_PCT"] for c in limits]
        credit_cols = [headers[c] for c in limits]

        def highlight(row):
            s = row["Status"]
            # Over the quota (at or above a limit, or blocked): red text on a red tint.
            # EXCLUDED users aren't blocked, but still flag them if their spend exceeds a limit.
            over_excluded = s == "EXCLUDED" and any(
                pd.notna(row[c]) and row[c] >= 100 for c in pct_cols
            )
            if s.startswith("Blocked") or s == "Over limit" or over_excluded:
                return [f"background-color: #FDE8E8; color: {RED}; font-weight: 700"] * len(row)
            if s.startswith("Warning"):
                return ["background-color: #FFF4D6"] * len(row)
            return [""] * len(row)

        styled = (
            table.style.apply(highlight, axis=1)
            .format(lambda v: "—" if pd.isna(v) else f"{v:.1f}%", subset=pct_cols)
            .format("{:,.4f}", subset=credit_cols)
        )
        # Wide enough for "Warning (50%+)" and "EXCLUDED"; longer "Blocked: ..." text can be widened by dragging.
        st.dataframe(styled, use_container_width=True, hide_index=True,
                     column_config={"Status": st.column_config.TextColumn("Status", width="medium")})
        if total_users > len(table):
            info_text(
                f"Showing the top {top_n} of {total_users} users by month credits "
                "(plus any blocked or excluded users). Tick 'Show all' to see everyone, including users at 0."
            )

    # Reconcile with the rest of the app: AI credits this UTC month that the quota does not count.
    ms = f"{month_start:%Y-%m-%d %H:%M:%S} +00:00"
    mtd = _sql_cached(f"""
        SELECT
            (SELECT COALESCE(SUM(CREDITS), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
              WHERE USAGE_DATE >= '{month_start:%Y-%m-%d}') AS SEARCH_CREDITS,
            (SELECT COALESCE(SUM(CREDITS), 0) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
              WHERE START_TIME >= '{ms}'::TIMESTAMP_TZ) AS ANALYST_CREDITS
    """)
    info_text(
        f"Quota-counted spend this UTC month: {quota_total:,.2f} credits. Not counted by the quota: "
        f"Cortex Search {float(mtd['SEARCH_CREDITS'].iloc[0]):,.2f}, Cortex Analyst API "
        f"{float(mtd['ANALYST_CREDITS'].iloc[0]):,.2f}, and spend by users marked EXCLUDED "
        f"({', '.join(excluded) or 'none'}); their rows come from ACCOUNT_USAGE, which can lag by hours. "
        "EXCLUDED users are never blocked; their % shows spend against the limits for comparison. "
        "Users at 0 are active users the quota covers with no spend this month. "
        "Figures refresh every 15 minutes; quota evaluation itself lags spend."
    )


if _show_quota_tab:
    with _main_tabs["Quota"]:
        st.subheader("AI Quota Status")
        if _quota_state == "error":
            st.warning(
                f"Could not read quota {quota_fqn}. The app runs as its owner role, which needs VIEWER on the quota "
                f"(GRANT SNOWFLAKE.CORE.QUOTA ROLE {quota_fqn}!VIEWER TO ROLE <owner role>). Details: {_quota_detail}"
            )
        else:
            try:
                quota_status_section(quota_fqn)
            except Exception as e:
                st.warning(f"Could not display quota {quota_fqn}. Details: {e}")


if _show_quota_tab:
    _loading["Quota"].empty()

with _main_tabs["Efficiency"]:
    # ----------------------------------------------------------------------
    # Users by Highest Service/Cost
    # ----------------------------------------------------------------------

    st.divider()
    st.subheader("Highest Credits per Request by User")

    # From user_service_sql: already one row per user + service; drop Search.
    df_user_eff = df_user_service[df_user_service["SERVICE"] != "Cortex Search"].drop(columns="TOTAL_TOKENS").copy()
    df_user_eff["TOTAL_CREDITS"] = df_user_eff["TOTAL_CREDITS"].round(6)
    if not df_user_eff.empty:
        df_user_eff = add_cost_per_request(df_user_eff)

    if not df_user_eff.empty:
        df_user_eff["LABEL"] = df_user_eff["USER_NAME"].fillna("Unknown") + " (" + df_user_eff["SERVICE"] + ")"
        user_cols = ["USER_NAME", "SERVICE", "UNIT", "TOTAL_CREDITS", "TOTAL_REQUESTS", "CREDITS_PER_REQUEST"]
        # Top users (config top_users) in each panel unless "Show all" is ticked.
        eff_show_all = st.checkbox("Show all users", value=False, key="efficiency_show_all")
        eff_n = len(df_user_eff) if eff_show_all else top_users
        eff_label = "all" if eff_show_all else f"top {top_users}"
        u1, u2 = st.columns(2)
        with u1:
            st.markdown(f'<div class="panel-title">Interactive services: credits per request ({eff_label})</div>', unsafe_allow_html=True)
            df_u_int = df_user_eff[df_user_eff["SERVICE"].isin(INTERACTIVE_SERVICES)].head(eff_n)
            if not df_u_int.empty:
                st.altair_chart(cpr_chart(df_u_int, "LABEL", "Credits per Request", max(400, 24 * len(df_u_int)), show_legend=True), use_container_width=True)
                st.dataframe(df_u_int[user_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
            else:
                st.info("No interactive requests in selected period.")
        with u2:
            st.markdown(f'<div class="panel-title">AI Functions: credits per SQL query ({eff_label})</div>', unsafe_allow_html=True)
            df_u_batch = df_user_eff[df_user_eff["SERVICE"].isin(BATCH_SERVICES)].head(eff_n)
            if not df_u_batch.empty:
                st.altair_chart(cpr_chart(df_u_batch, "LABEL", "Credits per SQL Query", max(400, 24 * len(df_u_batch))), use_container_width=True)
                st.dataframe(df_u_batch[user_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
            else:
                st.info("No AI Function queries in selected period.")
    else:
        st.info("No user request data in selected period.")

_loading["Efficiency"].empty()

# ----------------------------------------------------------------------
# Admin: change quota limits and blocking (allow-listed users only)
# Values are validated and passed as numbers/booleans, never text.
# ----------------------------------------------------------------------

_CYCLES = {"MONTH": ("MONTHLY", "PER_USER_LIMIT"), "WEEK": ("WEEKLY", "PER_USER_LIMIT_WEEKLY"), "DAY": ("DAILY", "PER_USER_LIMIT_DAILY")}
_MAX_LIMIT = 1_000_000_000


_EMAIL_RE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"


def summary_emails(fqn: str) -> tuple:
    """The quota's summary (admin) email addresses and where they were found, or ([], "")."""
    # 1. GET_CONFIG, in case it returns them (any column with EMAIL in its name).
    try:
        cfg = _sql_cached(f"CALL {fqn}!GET_CONFIG()")
        found = []
        for col in [c for c in cfg.columns if "EMAIL" in c and "ENABLED" not in c]:
            found += re.findall(_EMAIL_RE, str(cfg[col].iloc[0]))
        if found:
            return sorted(set(found), key=found.index), "GET_CONFIG"
    except Exception:
        pass
    # 2. The last successful SET_ADMIN_EMAILS call, which replaces the whole list.
    name = fqn.split(".")[-1]
    hist = _sql_cached(f"""
        SELECT START_TIME, USER_NAME, QUERY_TEXT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -365, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND QUERY_TYPE = 'CALL'
          AND QUERY_TEXT ILIKE '%{name}!SET_ADMIN_EMAILS%'
        ORDER BY START_TIME DESC
        LIMIT 1
    """)
    if not hist.empty:
        found = re.findall(_EMAIL_RE, str(hist["QUERY_TEXT"].iloc[0]))
        if found:
            when = pd.to_datetime(hist["START_TIME"].iloc[0])
            return (sorted(set(found), key=found.index),
                    f"last SET_ADMIN_EMAILS call, by {hist['USER_NAME'].iloc[0]} on {when:%Y-%m-%d}")
    return [], ""


def _fmt(v) -> str:
    return "no limit" if v is None else f"{v:,.0f}"


def admin_section() -> bool:
    """Render the Admin tab. Returns True when changes were applied and the page should rerun."""
    st.subheader("Quota settings")
    info_text(
        f"Signed in as {viewer_name()}. Changes apply to {quota_fqn} for every user it covers "
        "(one limit per cycle for everyone). "
        "Scope, alerts and notification emails are shown further down (view only) and are changed in Snowsight."
    )

    for msg_type, msg in st.session_state.pop("quota_admin_results", []):
        (st.success if msg_type == "ok" else st.error)(msg)

    # Read current settings fresh (not cached) so the form compares against the live values.
    cur = session.sql(f"CALL {quota_fqn}!GET_CONFIG()").collect()[0].as_dict()
    cur = {str(k).upper(): v for k, v in cur.items()}
    current = {c: (None if cur.get(col) is None else float(cur[col])) for c, (_, col) in _CYCLES.items()}
    cur_enf = bool(cur.get("BLOCK_ENFORCEMENT_ENABLED"))
    cur_mail = bool(cur.get("PER_USER_BLOCK_NOTIFICATIONS_ENABLED"))

    with st.form("quota_admin_form"):
        # Widget keys include the live value, so a change made elsewhere (e.g. in Snowsight)
        # resets the form instead of letting a stale value be re-applied.
        cols = st.columns(3)
        new_vals = {}
        for col, (cyc, label) in zip(cols, [("MONTH", "Monthly"), ("WEEK", "Weekly"), ("DAY", "Daily")]):
            with col:
                st.markdown(f"**{label} limit** · current: {_fmt(current[cyc])}")
                no_limit = st.checkbox("No limit", value=current[cyc] is None, key=f"qa_none_{cyc}_{current[cyc]}")
                # Snowflake accepts limits from 1 to 1,000,000,000.
                val = st.number_input(
                    "Credits per user", min_value=1, max_value=_MAX_LIMIT, step=1,
                    value=int(current[cyc]) if current[cyc] is not None else 1,
                    key=f"qa_val_{cyc}_{current[cyc]}",
                )
                new_vals[cyc] = None if no_limit else int(val)
        st.markdown(f"**Blocking** · current: enforcement {'ON' if cur_enf else 'OFF'}, "
                    f"block emails {'ON' if cur_mail else 'OFF'}")
        new_enf = st.checkbox("Block users who reach a limit", value=cur_enf, key=f"qa_enf_{cur_enf}")
        new_mail = st.checkbox("Email users when they are blocked or unblocked", value=cur_mail, key=f"qa_mail_{cur_mail}")
        confirm = st.checkbox("I understand these limits apply to everyone in the quota and take effect immediately", key="qa_confirm")
        submitted = st.form_submit_button("Apply changes")

    if submitted:
        # Re-check on submit: the allow-list is the only guard on owner's-rights calls.
        if not is_quota_admin():
            st.error("You are not allowed to change quota settings.")
            return False
        changes = []
        for cyc, (cycle, _) in _CYCLES.items():
            old, new = current[cyc], new_vals[cyc]
            if (old is None and new is None) or (old is not None and new is not None and int(old) == new):
                continue
            if new is None:
                changes.append((f"{cycle} limit", _fmt(old), "no limit",
                                f"CALL {quota_fqn}!UNSET_PER_USER_LIMIT('{cycle}')"))
            else:
                if not 1 <= new <= _MAX_LIMIT:
                    st.error(f"{cycle} limit must be a whole number from 1 to {_MAX_LIMIT:,}.")
                    return False
                changes.append((f"{cycle} limit", _fmt(old), f"{new:,}",
                                f"CALL {quota_fqn}!SET_PER_USER_LIMIT({int(new)}, '{cycle}')"))
        if (new_enf, new_mail) != (cur_enf, cur_mail):
            # Always pass both arguments; the one-argument form turns block emails off.
            changes.append(("Block enforcement / emails",
                            f"{'ON' if cur_enf else 'OFF'} / {'ON' if cur_mail else 'OFF'}",
                            f"{'ON' if new_enf else 'OFF'} / {'ON' if new_mail else 'OFF'}",
                            f"CALL {quota_fqn}!SET_BLOCK_ENFORCEMENT_ENABLED({'TRUE' if new_enf else 'FALSE'}, "
                            f"{'TRUE' if new_mail else 'FALSE'})"))

        if not changes:
            st.info("Nothing to change: the form matches the current settings.")
        elif not confirm:
            st.warning("Tick the confirmation box to apply the changes.")
        else:
            results = []
            for setting, old, new, sql in changes:
                try:
                    session.sql(sql).collect()
                    results.append(("ok", f"{setting}: {old} → {new}"))
                except Exception as e:
                    results.append(("err", f"{setting}: failed to change {old} → {new}. Details: {e}"))
            _sql_cached.clear()  # so the Quota tab shows the new limits
            st.session_state["quota_admin_results"] = results
            st.session_state.pop("qa_confirm", None)
            return True  # caller reruns outside any try/except
    return False


def quota_readonly_section() -> None:
    """Settings the Admin form can't change, read live from the quota, with a link to
    edit them in Snowsight. Each part is read separately so one failure doesn't hide
    the rest."""
    st.subheader("Scope, alerts and notifications (view only)")
    info_text(
        "To change these, open the quota in Snowsight with the SYSADMIN role: "
        f"Admin » Cost management » Budgets, then select {quota_fqn}."
    )
    try:
        st.link_button(f"Open {quota_fqn} in Snowsight", quota_page_url(quota_fqn))
    except Exception as e:
        st.warning(f"Could not build the Snowsight link. Details: {e}")

    def read(what: str, sql: str) -> Optional[pd.DataFrame]:
        try:
            return _collect_df(sql)  # live, not cached
        except Exception as e:
            st.warning(f"Could not read {what}. Details: {e}")
            return None

    def show(df: Optional[pd.DataFrame], none_text: str) -> None:
        if df is None:
            return
        if df.empty:
            info_text(none_text)
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Scope: tracked services/resources and who is covered (GET_QUOTA_SCOPE) ---
    st.markdown("**Quota scope**")
    scope_df = read("the quota scope", f"CALL {quota_fqn}!GET_QUOTA_SCOPE()")
    if scope_df is not None and not scope_df.empty:
        raw = scope_df.iloc[0, 0]
        scope = json.loads(raw) if isinstance(raw, str) else (raw or {})

        resources = pd.DataFrame([
            {
                "Service": r.get("domain", ""),
                "Resource": r.get("name", ""),
                # id -1 means the whole service (e.g. [ALL-AGENTS]), not one resource.
                "Covers": "Every resource in the service" if str(r.get("id")) == "-1" else "This resource only",
            }
            for r in scope.get("shared_resources") or []
        ])
        st.markdown("Tracked services and resources")
        show(resources, "No services or resources attached, so the quota counts nothing.")

        def names(key: str) -> str:
            return ", ".join(u.get("user_name", "") for u in scope.get(key) or [] if u.get("user_name")) or "none"

        user_tags = scope.get("user_tags") or {}
        tag_rules = []
        for t in user_tags.get("tags") or []:
            values = t.get("tag_values")
            values = ", ".join(map(str, values)) if isinstance(values, list) else str(values or "")
            tag_rules.append(f"{t.get('tag_database', '')}.{t.get('tag_schema', '')}.{t.get('tag_key', '')} = {values}")
        tag_text = "; ".join(tag_rules) or "none"
        if len(tag_rules) > 1 and user_tags.get("operator"):
            tag_text += f" (combined with {user_tags['operator']})"

        st.markdown("Who is covered")
        st.dataframe(
            pd.DataFrame([
                {"Rule": "Included by name", "Value": names("included_users")},
                {"Rule": "Included by user tag", "Value": tag_text},
                {"Rule": "Excluded by name (never limited)", "Value": names("excluded_users")},
            ]),
            use_container_width=True, hide_index=True,
        )

    # --- Alerts: notification thresholds and custom actions ---
    st.markdown("**Alert thresholds**")
    show(read("alert thresholds", f"CALL {quota_fqn}!GET_NOTIFICATION_THRESHOLDS()"),
         "No alert thresholds configured.")
    st.markdown("**Custom actions**")
    info_text(
        "Stored procedures the quota runs automatically when spending reaches a threshold, "
        "for example to notify a channel or suspend something. Optional; most quotas have none."
    )
    show(read("custom actions", f"CALL {quota_fqn}!GET_CUSTOM_ACTIONS()"),
         "No custom actions configured.")

    # --- Summary emails (Snowsight's name for the admin notification addresses) ---
    # Snowflake documents only a setter (SET_ADMIN_EMAILS). The app looks for them in
    # GET_CONFIG first, then falls back to the last successful SET_ADMIN_EMAILS call in
    # QUERY_HISTORY (kept for 1 year), which records the addresses it was given.
    st.markdown("**Summary emails**")
    emails, source = summary_emails(quota_fqn)
    if emails:
        st.dataframe(pd.DataFrame({"Email": emails}), use_container_width=True, hide_index=True)
        info_text(
            f"Notified when custom alerts trigger or users are blocked. Source: {source}. "
            "Users themselves are also emailed for alert thresholds where NOTIFY_USER is TRUE, "
            "and when blocked or unblocked if block emails are on."
        )
    else:
        info_text(
            "Could not find the summary email addresses: they aren't returned by GET_CONFIG, and no "
            "SET_ADMIN_EMAILS call with readable addresses was found in the last year of QUERY_HISTORY. "
            "Check them in Snowsight with the button above."
        )
    integrations = read("notification integrations", f"CALL {quota_fqn}!GET_NOTIFICATION_INTEGRATIONS()")
    if integrations is not None and not integrations.empty:
        st.markdown("Notification integrations")
        st.dataframe(integrations, use_container_width=True, hide_index=True)


if _show_admin_tab:
    _admin_rerun = False
    with _main_tabs["Admin"]:
        try:
            _admin_rerun = admin_section()
        except Exception as e:
            st.warning(f"Could not load quota settings. Details: {e}")
        if not _admin_rerun:
            try:
                quota_readonly_section()
            except Exception as e:
                st.warning(f"Could not load the view-only quota settings. Details: {e}")
    _loading["Admin"].empty()
    if _admin_rerun:
        st.rerun()  # outside the try so Streamlit's rerun signal is not swallowed

# -------------------------------------------------
# Notes
# -------------------------------------------------

st.divider()

st.markdown(
    """
    <div class="note">
    ACCOUNT_USAGE views are not real time. Cortex usage views can lag by up to
    about 3 hours (Cortex Code up to about 1 hour), so ranges that include today or
    yesterday may be incomplete, and the most recent day is always partial.<br><br>
    Figures are drawn from ACCOUNT_USAGE and are for internal analysis only -
    they will not tie exactly to your Snowflake invoice. Use ORGANIZATION_USAGE
    or the billing statement for figures of record.<br><br>
    Costs are estimates: credits multiplied by the rates in config.json. AI services are
    billed in AI Credits, priced the same for every edition but by routing (global or
    regional, from the account's CORTEX_ENABLED_CROSS_REGION setting); the standalone
    Cortex Analyst API is billed in Platform Credits at the edition rate. Set the rates to
    your contracted prices, since discounts are not applied here. Charts and the Efficiency
    and Quota tabs are in credits. Date ranges include both the start and end day.
    </div>
    """,
    unsafe_allow_html=True,
)

