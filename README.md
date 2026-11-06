# AI_Consumption
AI Usage Dashboard

Streamlit in Snowflake app (`AI Consumption/`, deployed as `UTIL_DB.STREAMLIT.AI_CONSUMPTION`)
that reports AI credit consumption on the account, by service and by user, shows status against
a per-user AI quota, and lets named admins change that quota's limits.

## Layout
The date range and KPI cards sit at the top; everything else is in tabs:

| Tab | Contents |
|---|---|
| Overview | Credits by service, service distribution, credit summary, daily trend |
| Users | Top users by AI credits, in total and per service |
| Efficiency | Cost per request by service and by user (request units are labelled per service) |
| Quota | Each user's spend against the quota's monthly, weekly and daily limits (UTC cycles), read from the quota itself. Shown only when the configured quota exists |
| Admin | Change the quota's limits and blocking setting. Shown only to users listed in `quota_admins`, and only when the quota exists |

Services covered: Cortex Agents, AI Functions (includes AISQL), Cortex Analyst, Cortex Search,
Cortex Code (Snowsight, CLI, Desktop) and Snowflake CoWork.

All values are in credits. Figures come from `SNOWFLAKE.ACCOUNT_USAGE`, which can lag by up to
about 3 hours, so they will not tie exactly to the invoice.

## Admin tab
- Visible only when the viewer's Snowflake username (`st.user.user_name`) is in `quota_admins`.
  The app runs with its owner's rights, so this list is what stops other viewers from changing the quota.
- Can set or clear the monthly, weekly and daily per-user limits (whole numbers, 1 to 1,000,000,000;
  one limit per cycle for everyone in the quota) and turn blocking and block emails on or off.
- Changes need a confirmation tick; only fields that differ from the live values are sent.
- Every attempt, successful or failed, is written to `quota_change_log` with who made it.
  If that table is missing, changes are disabled. The 20 most recent entries are shown in the tab.
- Users in scope, exclusions and tracked services are managed in Snowsight (link in the Quota tab).

## Sources
- `SNOWFLAKE.ACCOUNT_USAGE`: `CORTEX_AGENT_USAGE_HISTORY`, `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`,
  `CORTEX_ANALYST_USAGE_HISTORY`, `CORTEX_SEARCH_DAILY_USAGE_HISTORY`,
  `CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY`, `CORTEX_CODE_CLI_USAGE_HISTORY`,
  `CORTEX_CODE_DESKTOP_USAGE_HISTORY`, `SNOWFLAKE_COWORK_USAGE_HISTORY`, `QUERY_HISTORY`, `USERS`.
- The quota's methods: `GET_CONFIG`, `GET_QUOTA_SCOPE`, `GET_SPENDING_DETAILS_BY_USERS`,
  `GET_ACTIVE_BLOCKS_V2`; from the Admin tab also `SET_PER_USER_LIMIT`, `UNSET_PER_USER_LIMIT`,
  `SET_BLOCK_ENFORCEMENT_ENABLED`.
- Change log table `UTIL_DB.COSTS.AI_QUOTA_CHANGE_LOG`
  (`CHANGED_AT, CHANGED_BY, QUOTA_FQN, SETTING, OLD_VALUE, NEW_VALUE, STATUS, ERROR`).

## Privileges
The app runs as its owner role (`execute_as: OWNER`), which needs:
- `IMPORTED PRIVILEGES` on database `SNOWFLAKE`
- the VIEWER role on the quota for the Quota tab, and the ADMIN role for the Admin tab:
  `GRANT SNOWFLAKE.CORE.QUOTA ROLE <quota_fqn>!ADMIN TO ROLE <owner role>`
  (neither is needed if the owner role owns the quota, as SYSADMIN does today)
- `SELECT` and `INSERT` on the change log table

## config.json
| Key | Required | Meaning |
|---|---|---|
| `default_date_range` | no | Initial range: `TODAY`, `WTD`, `MTD`, `QTD` or `YTD` |
| `quota_fqn` | no | Quota to report on, as `DB.SCHEMA.NAME`. Default `UTIL_DB.COSTS.AI_QUOTA` |
| `quota_url` | no | Direct https link to the quota page; overrides the link built from `quota_fqn` |
| `quota_admins` | no | Snowflake usernames allowed to use the Admin tab, e.g. `["LMANCINI"]`. Empty or missing means no Admin tab |
| `quota_change_log` | no | Audit table for Admin changes, as `DB.SCHEMA.NAME`. Default `UTIL_DB.COSTS.AI_QUOTA_CHANGE_LOG` |

Other keys in `config.json` are ignored by this app.

## Deploying
Deploy from the workspace (Deploy button). Keep `idle_auto_shutdown_time_seconds: 86400` in
`snowflake.yml`; the workspace rejected other values. If the app looks unchanged after a deploy,
hard-refresh the browser or open it in a private window.
