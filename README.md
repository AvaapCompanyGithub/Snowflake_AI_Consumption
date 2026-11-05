# AI_Consumption
AI Usage Dashboard

Streamlit in Snowflake app (`AI Consumption/`, deployed as `UTIL_DB.STREAMLIT.AI_CONSUMPTION`)
that reports AI credit consumption on the account, by service and by user, plus status against
a per-user AI quota.

## What it shows
- Credits by service, the change from the prior period, and the daily trend for the selected date range.
  Services: Cortex Agents, AI Functions (includes AISQL), Cortex Analyst, Cortex Search,
  Cortex Code (Snowsight, CLI, Desktop) and Snowflake CoWork.
- Cost per request and top users. Request units differ by service and are labelled.
- AI Quota Status: each user's spend against the quota's monthly, weekly and daily limits
  (UTC cycles), read from the quota itself. Hidden when the configured quota does not exist.

All values are in credits. Figures come from `SNOWFLAKE.ACCOUNT_USAGE`, which can lag by up to
about 3 hours, so they will not tie exactly to the invoice.

## Sources
- `SNOWFLAKE.ACCOUNT_USAGE`: `CORTEX_AGENT_USAGE_HISTORY`, `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`,
  `CORTEX_ANALYST_USAGE_HISTORY`, `CORTEX_SEARCH_DAILY_USAGE_HISTORY`,
  `CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY`, `CORTEX_CODE_CLI_USAGE_HISTORY`,
  `CORTEX_CODE_DESKTOP_USAGE_HISTORY`, `SNOWFLAKE_COWORK_USAGE_HISTORY`, `QUERY_HISTORY`, `USERS`.
- The quota's methods: `GET_CONFIG`, `GET_QUOTA_SCOPE`, `GET_SPENDING_DETAILS_BY_USERS`, `GET_ACTIVE_BLOCKS_V2`.

## Privileges
The app runs as its owner role (`execute_as: OWNER`), which needs:
- `IMPORTED PRIVILEGES` on database `SNOWFLAKE`
- the VIEWER role on the quota: `GRANT SNOWFLAKE.CORE.QUOTA ROLE <quota_fqn>!VIEWER TO ROLE <owner role>`
  (not needed if the owner role owns the quota)

## config.json
| Key | Required | Meaning |
|---|---|---|
| `default_date_range` | no | Initial range: `TODAY`, `WTD`, `MTD`, `QTD` or `YTD` |
| `quota_fqn` | no | Quota to report on, as `DB.SCHEMA.NAME`. Default `UTIL_DB.COSTS.AI_QUOTA` |
| `quota_url` | no | Direct https link to the quota page; overrides the link built from `quota_fqn` |

Other keys in `config.json` are ignored by this app.

## Deploying
Deploy from the workspace (Deploy button). Keep `idle_auto_shutdown_time_seconds: 86400` in
`snowflake.yml`; the workspace rejected other values. If the app looks unchanged after a deploy,
hard-refresh the browser or open it in a private window.
