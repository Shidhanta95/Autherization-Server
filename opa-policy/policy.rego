package authz

import future.keywords.if
import future.keywords.in

default allow := false

# Check permission
allow if {
    user := data.users.user_roles[input.user]
    tenant := data.users.user_tenant[input.user]
    perms := data.rbac[tenant][user][input.resource]
    perms[input.action] == true
}

# Check if org admin
is_org_admin if {
    data.users.org_admin_flag[input.user] == 1
}

# Get user context
user_context := {
    "role": data.users.user_roles[input.user],
    "tenant": data.users.user_tenant[input.user],
    "user_id": data.users.user_ids[input.user],
    "is_org_admin": data.users.org_admin_flag[input.user]
}