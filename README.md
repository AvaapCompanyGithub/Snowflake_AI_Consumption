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
| Efficiency | Cost per request by service and by user (request units are labelled per service); the user panels show the top `top_users` unless "Show all" is ticked |
| Quota | Each user's spend against the quota's monthly, weekly and daily limits (UTC cycles; weeks start Sunday), read from the quota itself. Shown when `quota_fqn` is set in `config.json` (with a warning if the quota can't be read), or when the default quota exists |
| Admin | Change the quota's limits and blocking setting. Shown only to users listed in `quota_admins`, and only when the Quota tab is shown |

Services covered: Cortex Agents, AI Functions (includes AISQL), Cortex Analyst, Cortex Search,
Cortex Code (Snowsight, CLI, Desktop), Snowflake CoWork, AI Gateway and the Cortex REST API.

The Cortex REST API has no credits in its usage view, so it is taken from `METERING_DAILY_HISTORY`:
service type `AI_INFERENCE` (which covers both the REST API and AI Gateway) minus AI Gateway credits.
It appears in the Overview totals and trend, but not in the per-user tables, and its days are UTC.

Figures come from `SNOWFLAKE.ACCOUNT_USAGE`, which can lag by up to about 3 hours, so they will
not tie exactly to the invoice.

## Costs
Costs are estimates: credits multiplied by the rates in `config.json`. They appear in the KPI cards
(Total AI Cost, cost per day), the Credit Summary table and the Users tables. Charts, Efficiency and
Quota stay in credits.
- AI services are billed in AI Credits, priced the same for every edition but by routing. On each
  load (cached for 1 hour) the app runs `SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT`:
  `ANY_REGION`, `AWS_GLOBAL`, `GCP_GLOBAL` or `AZURE_GLOBAL` uses `ai_credit_rate_global`; anything
  else (`DISABLED`, a region group such as `AWS_US`) uses `ai_credit_rate_regional`. If the setting
  can't be read, the regional rate is used and the page says so.
- The standalone Cortex Analyst API is still billed in Platform Credits, so Cortex Analyst uses
  `platform_credit_rate`. Analyst called by Cortex Agents is counted under Cortex Agents.
- Set the rates to your contracted prices; contract discounts are not applied by the app. If a rate is
  missing or invalid, the app uses the list price shown below and shows a warning.

## Admin tab
- Visible only when the viewer's Snowflake username (`st.user.user_name`) is in `quota_admins`.
  The app runs with its owner's rights, so this list is what stops other viewers from changing the quota.
- Can set or clear the monthly, weekly and daily per-user limits (whole numbers, 1 to 1,000,000,000;
  one limit per cycle for everyone in the quota) and turn blocking and block emails on or off.
- Changes need a confirmation tick; only fields that differ from the live values are sent.
- Below the form, a view-only section shows what the form can't change, read live from the quota:
  tracked services and resources, who is covered (included users, user tags, exclusions), alert
  thresholds, custom actions and notification integrations. A button opens the quota in Snowsight,
  where these are edited with the SYSADMIN role. Summary emails (admin notification addresses) have
  no documented getter, so the app takes them from `GET_CONFIG` if it returns them, otherwise from the
  last successful `SET_ADMIN_EMAILS` call in `QUERY_HISTORY` (last 365 days).

## Sources
- `SNOWFLAKE.ACCOUNT_USAGE`: `CORTEX_AGENT_USAGE_HISTORY`, `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`,
  `CORTEX_ANALYST_USAGE_HISTORY`, `CORTEX_SEARCH_DAILY_USAGE_HISTORY`,
  `CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY`, `CORTEX_CODE_CLI_USAGE_HISTORY`,
  `CORTEX_CODE_DESKTOP_USAGE_HISTORY`, `SNOWFLAKE_COWORK_USAGE_HISTORY`, `AI_GATEWAY_USAGE_HISTORY`,
  `METERING_DAILY_HISTORY` (Cortex REST API, and the metered-credits check), `QUERY_HISTORY`, `USERS`.
- The quota's methods: `GET_CONFIG`, `GET_QUOTA_SCOPE`, `GET_SPENDING_DETAILS_BY_USERS`,
  `GET_ACTIVE_BLOCKS_V2`, `GET_USERS`; from the Admin tab also `GET_NOTIFICATION_THRESHOLDS`,
  `GET_CUSTOM_ACTIONS`, `GET_NOTIFICATION_INTEGRATIONS` (view only) and `SET_PER_USER_LIMIT`,
  `UNSET_PER_USER_LIMIT`, `SET_BLOCK_ENFORCEMENT_ENABLED`.

## Privileges
The app runs as its owner role (`execute_as: OWNER`), which needs:
- `IMPORTED PRIVILEGES` on database `SNOWFLAKE`
- `MONITOR` on AI gateway `SNOWFLAKE` (for `AI_GATEWAY_USAGE_HISTORY`; without it the usage queries fail;
  granted in `AI_SECURITY.sql`)
- the VIEWER role on the quota for the Quota tab, and the ADMIN role for the Admin tab:
  `GRANT SNOWFLAKE.CORE.QUOTA ROLE <quota_fqn>!ADMIN TO ROLE <owner role>`
  (neither is needed if the owner role owns the quota, as SYSADMIN does today)

## config.json
| Key | Required | Meaning |
|---|---|---|
| `default_date_range` | no | Initial range: `TODAY`, `WTD`, `MTD`, `QTD` or `YTD` |
| `week_start` | no | First day of the week for the Week to Date range, e.g. `SUNDAY` or `MONDAY`. Default `SUNDAY`. The Quota tab's weekly cycle always starts Sunday (set by Snowflake) |
| `quota_fqn` | no | Quota to report on, as `DB.SCHEMA.NAME`. Default `UTIL_DB.COSTS.AI_QUOTA`. When set, the Quota tab always shows and reports any read failure; the default quota is hidden if it can't be found |
| `quota_url` | no | Direct https link to the quota page; overrides the link built from `quota_fqn` |
| `quota_admins` | no | Snowflake usernames allowed to use the Admin tab, e.g. `["LMANCINI"]`. Empty or missing means no Admin tab |
| `quota_warning_pct` | no | Quota tab flags a user as Warning at this % of any limit (above 0, below 100). Default `80` |
| `top_users` | no | Rows shown in the Quota tab and in each Efficiency panel before "Show all" is ticked. Default `10` |
| `ai_credit_rate_global` | no | Price per AI Credit with global routing. Default `2.00` (list price) |
| `ai_credit_rate_regional` | no | Price per AI Credit with regional routing. Default `2.20` (list price) |
| `platform_credit_rate` | no | Price per Platform Credit, used for the Cortex Analyst API. Default `3.00` (Enterprise list price) |

Other keys in `config.json` are ignored by this app.

## Setup scripts
Run once, in this order. They are not deployed with the app.
1. `AI Consumption/AI_SECURITY.sql` (as SECURITYADMIN and ACCOUNTADMIN) creates the `AI_USER` role,
   removes AI access from PUBLIC and gives it to `AI_USER`, and grants SYSADMIN, the app's owner role,
   `MONITOR ON AI GATEWAY SNOWFLAKE` so the app can read AI Gateway usage. `IMPORTED PRIVILEGES` on
   database `SNOWFLAKE` is granted outside these scripts.
2. `AI Consumption/QUOTA.sql` (as SYSADMIN) creates the quota `UTIL_DB.COSTS.AI_QUOTA` (if it doesn't
   exist) and sets its exclusions, limits, tracked services, alert thresholds, admin email and blocking.

## Deploying
Deploy from the workspace (Deploy button). Keep `idle_auto_shutdown_time_seconds: 86400` in
`snowflake.yml`; the workspace rejected other values. If the app looks unchanged after a deploy,
hard-refresh the browser or open it in a private window.
