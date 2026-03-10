package authz

import future.keywords.if
import future.keywords.in

# ============================================================
# DEFAULT DENY
# ============================================================
default allow := false

# ============================================================
# USER EXISTENCE CHECK
# ============================================================
# Check if user exists in the system
user_exists if {
    data.users.user_roles[input.user]
}

# ============================================================
# PERMISSION CHECK (WITH PLATFORM DIMENSION)
# ============================================================
# Allow if user has the required permission for the resource
allow if {
    # Get user's role and tenant
    role := data.users.user_roles[input.user]
    tenant := data.users.user_tenant[input.user]
    
    # Look up permissions: rbac[platform][tenant][role][resource]
    perms := data.rbac[input.platform][tenant][role][input.resource]
    
    # Check if the specific action is allowed
    perms[input.action] == true
}

# ============================================================
# ORG ADMIN CHECK
# ============================================================
# Check if user is an organization admin
is_org_admin if {
    data.users.org_admin_flag[input.user] == 1
}

# ============================================================
# USER CONTEXT (FOR JWT CREATION)
# ============================================================
# Returns user context for embedding in JWT
user_context := {
    "user_id": user_id,
    "role": role,
    "organization": tenant,
    "is_org_admin": org_admin_flag
} if {
    user_id := data.users.user_ids[input.user]
    role := data.users.user_roles[input.user]
    tenant := data.users.user_tenant[input.user]
    org_admin_flag := data.users.org_admin_flag[input.user]
}

# ============================================================
# USER PERMISSIONS (FOR JWT EMBEDDING)
# ============================================================
# Returns all permissions for a user on a specific platform
user_permissions := result if {
    role := data.users.user_roles[input.user]
    tenant := data.users.user_tenant[input.user]
    
    # Get all permissions for this role
    role_perms := data.rbac[input.platform][tenant][role]
    
    # Build permissions object excluding metadata fields
    result := {resource: perms |
        some resource
        perms := role_perms[resource]
        resource != "global_access"
        resource != "bu_access"
    }
}

# ============================================================
# ROLE METADATA (GLOBAL_ACCESS, BU_ACCESS)
# ============================================================
# Returns role metadata flags
role_metadata := {
    "global_access": global_access,
    "bu_access": bu_access
} if {
    role := data.users.user_roles[input.user]
    tenant := data.users.user_tenant[input.user]
    
    role_data := data.rbac[input.platform][tenant][role]
    global_access := role_data.global_access
    bu_access := role_data.bu_access
}

# ============================================================
# FULL AUTHORIZATION RESPONSE
# ============================================================
# Returns complete authorization response with context
authorization_response := {
    "allowed": allow,
    "user_id": data.users.user_ids[input.user],
    "organization": data.users.user_tenant[input.user],
    "role": data.users.user_roles[input.user],
    "is_org_admin": data.users.org_admin_flag[input.user]
}
