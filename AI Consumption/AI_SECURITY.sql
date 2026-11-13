-- LOCKDOWN AI
-- Removes AI from PUBLIC and gives it back through the AI_USER role (and directly to SYSADMIN).
-- Note: ACCOUNTADMIN always keeps AI access; these revokes do not affect it.

set AI_ROLE = 'AI_USER';

--------------------------------------------------
-- DEFAULTS
use role ACCOUNTADMIN;

--Intelligence Object - Once per account
create SNOWFLAKE INTELLIGENCE if not exists SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT;

--SYSADMIN
--Granted directly, so SYSADMIN keeps AI access even if AI_USER is changed or dropped.
--ACCOUNTADMIN always has access and needs no grants.

grant database role SNOWFLAKE.CORTEX_USER to role SYSADMIN;
grant use AI FUNCTIONS on account to role SYSADMIN;
grant application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" to role SYSADMIN;
grant usage on AI GATEWAY SNOWFLAKE to role SYSADMIN;

--SYSADMIN (owner of the AI Consumption app) can read AI Gateway usage (ACCOUNT_USAGE.AI_GATEWAY_USAGE_HISTORY).
grant monitor on AI GATEWAY SNOWFLAKE to role SYSADMIN;

--SYSADMIN can use the Intelligence Object through AI_USER, but not modify it (modify lets holders add/remove agents for the whole account).
--grant modify on SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT to role SYSADMIN;

--Check
show grants to role SYSADMIN;

--------------------------------------------------
-- REVOKE PUBLIC

--Take AI off for PUBLIC - run once
use role ACCOUNTADMIN;

revoke database role SNOWFLAKE.CORTEX_USER from role PUBLIC;
revoke database role SNOWFLAKE.COPILOT_USER from role PUBLIC;  --being retired by Snowflake, so not granted to the AI role below
revoke USE AI FUNCTIONS on account from role PUBLIC;
revoke application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" from role PUBLIC;
call SNOWFLAKE.LOCAL.REVOKE_FROM_PUBLIC_APPLICATION_ROLE('APP_ROLE', 'CORTEX-MODEL-ROLE-ALL');
revoke usage on ai gateway SNOWFLAKE from role PUBLIC;  --system grant shown as AI_GATEWAY / SNOWFLAKE

--Check
show grants to role PUBLIC; -- no CORTEX_USER, AI_FUNCTIONS_USER, CORTEX_EMBED_USER, CORTEX_AGENT_USER, USE AI FUNCTION*
                            -- (AI_FUNCTIONS_USER, CORTEX_EMBED_USER and CORTEX_AGENT_USER come with CORTEX_USER, so revoking it removes them)
show grants to application role SNOWFLAKE.PUBLIC; -- CORTEX-MODEL-ROLE-ALL must be gone

/*
--Restore AI to PUBLIC (undo the revokes above) - every user gets AI again
use role ACCOUNTADMIN;

grant database role SNOWFLAKE.CORTEX_USER to role PUBLIC;
grant database role SNOWFLAKE.COPILOT_USER to role PUBLIC;
grant use ai functions on account to role PUBLIC;
grant application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" to role PUBLIC;
grant usage on ai gateway SNOWFLAKE to role PUBLIC;

--The REVOKE_FROM_PUBLIC_APPLICATION_ROLE call above has no documented undo procedure.
--The PUBLIC grant above gives the same model access. If a model is still blocked, check with Snowflake support.

show grants to role PUBLIC;
show grants to application role SNOWFLAKE.PUBLIC;

*/

--------------------------------------------------
-- GRANT NEW ROLE

--Create the new role

use role SECURITYADMIN;

create role if not exists identifier($AI_ROLE)
    comment = 'Carries account-level AI privileges (Cortex, AI functions, Snowflake Intelligence) for grant to functional roles';

grant role identifier($AI_ROLE) to role SYSADMIN;

--Add AI perms

use role ACCOUNTADMIN;

grant database role SNOWFLAKE.CORTEX_USER to role identifier($AI_ROLE);
grant use ai functions on account to role identifier($AI_ROLE);
grant application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" to role identifier($AI_ROLE);
grant usage on ai gateway SNOWFLAKE to role identifier($AI_ROLE);  --was revoked from PUBLIC above

grant usage on SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT to role identifier($AI_ROLE);

--MODIFY intentionally not granted: it lets holders add/remove agents in Snowflake Intelligence for the whole account.
--Grant it directly to a specific admin role if needed:
--grant modify on SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT to role <ROLE>;

--Check
show grants to role identifier($AI_ROLE);
