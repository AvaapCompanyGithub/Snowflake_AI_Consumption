use role SYSADMIN;
use UTIL_DB.COSTS;

-- IF NOT EXISTS: rerunning the script won't fail on, or replace, an existing quota.
-- Note the calls below still run against it: limits, emails and blocking are simply
-- set again, but EXCLUDE_USERS adds to the existing list, and the ADD_* calls may
-- error or duplicate entries that already exist.
create SNOWFLAKE.CORE.QUOTA if not exists AI_QUOTA();

-- Scope: all users (ALL_USERS is the default for a new quota), minus one named user
call AI_QUOTA!EXCLUDE_USERS('USER', ['LMANCINI']);

-- Per-user credit limits
call AI_QUOTA!SET_PER_USER_LIMIT(20, 'MONTHLY');
call AI_QUOTA!SET_PER_USER_LIMIT(10, 'WEEKLY');
call AI_QUOTA!SET_PER_USER_LIMIT(10, 'DAILY');

-- AI usage the quota counts
call AI_QUOTA!ADD_SHARED_RESOURCE('AI FUNCTION');
call AI_QUOTA!ADD_SHARED_RESOURCE('CORTEX AGENT');
call AI_QUOTA!ADD_SHARED_RESOURCE('SNOWFLAKE INTELLIGENCE');
call AI_QUOTA!ADD_SHARED_RESOURCE('CORTEX CODE');   -- domain names use spaces, not underscores
call AI_QUOTA!ADD_SHARED_RESOURCE('AI GATEWAY');

-- Notification thresholds (monthly cycle, users are notified)
call AI_QUOTA!ADD_NOTIFICATION_THRESHOLD(50,  'PROJECTED', TRUE, 'MONTHLY');
call AI_QUOTA!ADD_NOTIFICATION_THRESHOLD(80,  'ACTUAL',    TRUE, 'MONTHLY');
call AI_QUOTA!ADD_NOTIFICATION_THRESHOLD(90,  'ACTUAL',    TRUE, 'MONTHLY');
call AI_QUOTA!ADD_NOTIFICATION_THRESHOLD(100, 'ACTUAL',    TRUE, 'MONTHLY');

-- Admin emails
call AI_QUOTA!SET_ADMIN_EMAILS('snowflake_alerts@avaap.com');

-- Block users who go over a limit, and email them when they're blocked or unblocked
call AI_QUOTA!SET_BLOCK_ENFORCEMENT_ENABLED(TRUE, TRUE);