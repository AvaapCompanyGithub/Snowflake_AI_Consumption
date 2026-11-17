-- LOCKDOWN AI
-- Removes AI from PUBLIC and gives it back through the AI_USER role (and directly to SYSADMIN).
-- Note: ACCOUNTADMIN always keeps AI access; these revokes do not affect it.

set AI_ROLE = 'AI_USER';
set WH_NAME = 'AI_WH'; --Warehouse - set to '' to skip the warehouse grant (warehouse must already exist)

--------------------------------------------------
-- DEFAULTS
use role ACCOUNTADMIN;

--Intelligence Object - Once per account
create SNOWFLAKE INTELLIGENCE if not exists SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT;

--SYSADMIN only
--Change the CoWork object: add or remove agents and change its settings
grant modify on SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT to role SYSADMIN;
--View AI Gateway activity and usage
grant monitor on AI GATEWAY SNOWFLAKE to role SYSADMIN;

--------------------------------------------------
-- NEW ROLE

use role SECURITYADMIN;

create role if not exists identifier($AI_ROLE)
    comment = 'Carries account-level AI privileges (Cortex, AI functions, Snowflake Intelligence) for grant to functional roles';

grant role identifier($AI_ROLE) to role SYSADMIN;

--------------------------------------------------
-- GRANT AI PERMS
-- Applied to SYSADMIN and AI_USER.
-- SYSADMIN is granted directly, so it keeps AI access even if AI_USER is changed or dropped.
-- ACCOUNTADMIN always has access and needs no grants.
use role ACCOUNTADMIN;

declare
    roles array default array_construct('SYSADMIN', $AI_ROLE);
    r string;
    wh_name string default $WH_NAME;
begin
    for i in 0 to array_size(roles) - 1 do
        r := roles[i]::string;

        -- Cortex AI features: CoCo, Cortex Agents, Cortex Search, AI functions
        execute immediate 'grant database role SNOWFLAKE.CORTEX_USER to role ' || r;
        -- Account-level permission to call AI functions (AI_COMPLETE, AI_CLASSIFY, etc.)
        execute immediate 'grant use AI FUNCTIONS on account to role ' || r;
        -- All current and future LLMs (model access is controlled only by model RBAC)
        execute immediate 'grant application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" to role ' || r;
        -- Route AI requests through Snowflake's AI Gateway (system grant shown as AI_GATEWAY / SNOWFLAKE)
        execute immediate 'grant usage on AI GATEWAY SNOWFLAKE to role ' || r;
        -- Create and run scheduled, unattended agent automations (CoWork/CoCo Automations)
        execute immediate 'grant EXECUTE AGENT TASK on account to role ' || r;
        -- See and use agents in CoWork
        execute immediate 'grant usage on SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT to role ' || r;

        if(length(wh_name) > 0) then
            execute immediate 'grant usage on warehouse ' || wh_name || ' to role ' || r;
        end if;
    end for;
end;

show grants to role identifier($AI_ROLE);

--------------------------------------------------
-- REVOKE PUBLIC

--Take AI off for PUBLIC - run once
use role ACCOUNTADMIN;

revoke database role SNOWFLAKE.CORTEX_USER from role PUBLIC;
revoke database role SNOWFLAKE.COPILOT_USER from role PUBLIC; --being retired by Snowflake, so not granted to the AI role above
revoke USE AI FUNCTIONS on account from role PUBLIC;
revoke application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" from role PUBLIC;
call SNOWFLAKE.LOCAL.REVOKE_FROM_PUBLIC_APPLICATION_ROLE('APP_ROLE', 'CORTEX-MODEL-ROLE-ALL');
revoke usage on ai gateway SNOWFLAKE from role PUBLIC; --System grant shown as AI_GATEWAY / SNOWFLAKE
revoke execute agent task on account from role PUBLIC; --CoWork and CoCo automations

--Check
show grants to role PUBLIC; -- no CORTEX_USER, AI_FUNCTIONS_USER, CORTEX_EMBED_USER, CORTEX_AGENT_USER, USE AI FUNCTION*
                            -- (these are removed only if PUBLIC received them through CORTEX_USER; direct grants must be revoked separately)
show grants to application role SNOWFLAKE.PUBLIC; -- CORTEX-MODEL-ROLE-ALL must be gone

--------------------------------------------------
-- TEST AI ROLE
-- Run after REVOKE PUBLIC; before that, every role still gets AI through PUBLIC.

use secondary roles none;
use role identifier($AI_ROLE);
use warehouse identifier($WH_NAME);
select AI_COMPLETE('llama3.1-70b', 'Hello'); --if this fails, confirm the model is offered in your region before checking grants
use secondary roles all;

--------------------------------------------------
-- RESTORE PUBLIC ACCESS (if needed)

/*
--Restore AI to PUBLIC (undo the revokes above) - every user gets AI again
use role ACCOUNTADMIN;

grant database role SNOWFLAKE.CORTEX_USER to role PUBLIC;
grant database role SNOWFLAKE.COPILOT_USER to role PUBLIC;
grant use ai functions on account to role PUBLIC;
grant application role SNOWFLAKE."CORTEX-MODEL-ROLE-ALL" to role PUBLIC;
grant usage on ai gateway SNOWFLAKE to role PUBLIC;
grant execute agent task on account to role PUBLIC;

--Undo REVOKE_FROM_PUBLIC_APPLICATION_ROLE (documented in BCR-2378)
call SNOWFLAKE.LOCAL.GRANT_TO_PUBLIC_APPLICATION_ROLE('APP_ROLE', 'CORTEX-MODEL-ROLE-ALL');

show grants to role PUBLIC;
show grants to application role SNOWFLAKE.PUBLIC;

*/