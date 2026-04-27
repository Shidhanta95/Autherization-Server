-- ============================================================
-- SETUP
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS authz;
SET search_path TO authz,public;

-- ============================================================
-- PLATFORM REGISTRY
-- ============================================================
CREATE TABLE platforms (
    id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name    VARCHAR(100) NOT NULL UNIQUE,
    prefix  VARCHAR(63) NOT NULL UNIQUE
);

-- ============================================================
-- CREATE PLATFORM
-- ============================================================
CREATE OR REPLACE FUNCTION create_platform(p_name VARCHAR, p_prefix VARCHAR DEFAULT NULL)
RETURNS VARCHAR AS $$
DECLARE
    v_prefix VARCHAR := COALESCE(p_prefix, lower(regexp_replace(p_name, '[^a-zA-Z0-9]', '_', 'g')));
BEGIN
    INSERT INTO platforms (name, prefix) VALUES (p_name, v_prefix) ON CONFLICT DO NOTHING;

    EXECUTE format('CREATE TABLE IF NOT EXISTS %I (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name VARCHAR(255) NOT NULL UNIQUE
    )', v_prefix || '_orgs');

    EXECUTE format('CREATE TABLE IF NOT EXISTS %I (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        org_id UUID NOT NULL REFERENCES %I(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL, global_access BOOLEAN DEFAULT false, bu_access BOOLEAN DEFAULT false,
        UNIQUE (org_id, name)
    )', v_prefix || '_roles', v_prefix || '_orgs');

    EXECUTE format('CREATE TABLE IF NOT EXISTS %I (
        role_id UUID REFERENCES %I(id) ON DELETE CASCADE,
        resource VARCHAR(50) NOT NULL,
        can_read BOOLEAN DEFAULT false, can_write BOOLEAN DEFAULT false, can_delete BOOLEAN DEFAULT false,
        PRIMARY KEY (role_id, resource)
    )', v_prefix || '_perms', v_prefix || '_roles');

    EXECUTE format('CREATE TABLE IF NOT EXISTS %I (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        email VARCHAR(255) NOT NULL UNIQUE,
        org_id UUID NOT NULL REFERENCES %I(id),
        role_id UUID NOT NULL REFERENCES %I(id),
        user_uid VARCHAR(255) NOT NULL, is_org_admin BOOLEAN DEFAULT false
    )', v_prefix || '_users', v_prefix || '_orgs', v_prefix || '_roles');

    -- Indexes for query performance
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(org_id)',
        v_prefix || '_users_org_id_idx', v_prefix || '_users');
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(role_id)',
        v_prefix || '_users_role_id_idx', v_prefix || '_users');

    -- Publication for CDC
    EXECUTE format('DROP PUBLICATION IF EXISTS %I', v_prefix || '_pub');
    EXECUTE format('CREATE PUBLICATION %I FOR TABLE %I, %I, %I, %I',
        v_prefix || '_pub', v_prefix || '_orgs', v_prefix || '_roles', v_prefix || '_perms', v_prefix || '_users');

    RETURN v_prefix;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- HELPERS
-- ============================================================
CREATE OR REPLACE FUNCTION get_prefix(p_platform VARCHAR)
RETURNS VARCHAR AS $$ SELECT prefix FROM platforms WHERE name = p_platform OR prefix = p_platform; $$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION add_org(p_platform VARCHAR, p_org VARCHAR) RETURNS UUID AS $$
DECLARE v_id UUID;
BEGIN
    EXECUTE format('INSERT INTO %I (name) VALUES ($1) RETURNING id', get_prefix(p_platform) || '_orgs') INTO v_id USING p_org;
    RETURN v_id;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION add_role(p_platform VARCHAR, p_org VARCHAR, p_role VARCHAR, p_global BOOLEAN DEFAULT false, p_bu BOOLEAN DEFAULT false) RETURNS UUID AS $$
DECLARE v_prefix VARCHAR := get_prefix(p_platform); v_org_id UUID; v_id UUID;
BEGIN
    EXECUTE format('SELECT id FROM %I WHERE name = $1', v_prefix || '_orgs') INTO v_org_id USING p_org;
    EXECUTE format('INSERT INTO %I (org_id, name, global_access, bu_access) VALUES ($1, $2, $3, $4) RETURNING id', v_prefix || '_roles')
    INTO v_id USING v_org_id, p_role, p_global, p_bu;
    RETURN v_id;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_perm(p_platform VARCHAR, p_org VARCHAR, p_role VARCHAR, p_resource VARCHAR, p_read BOOLEAN, p_write BOOLEAN, p_delete BOOLEAN) RETURNS VOID AS $$
DECLARE v_prefix VARCHAR := get_prefix(p_platform); v_role_id UUID;
BEGIN
    EXECUTE format('SELECT r.id FROM %I r JOIN %I o ON o.id = r.org_id WHERE o.name = $1 AND r.name = $2', v_prefix || '_roles', v_prefix || '_orgs')
    INTO v_role_id USING p_org, p_role;
    EXECUTE format('INSERT INTO %I (role_id, resource, can_read, can_write, can_delete) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (role_id, resource) DO UPDATE SET can_read = $3, can_write = $4, can_delete = $5', v_prefix || '_perms')
    USING v_role_id, p_resource, p_read, p_write, p_delete;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION add_user(p_platform VARCHAR, p_org VARCHAR, p_email VARCHAR, p_role VARCHAR, p_uid VARCHAR, p_admin BOOLEAN DEFAULT false) RETURNS UUID AS $$
DECLARE v_prefix VARCHAR := get_prefix(p_platform); v_org_id UUID; v_role_id UUID; v_id UUID;
BEGIN
    EXECUTE format('SELECT id FROM %I WHERE name = $1', v_prefix || '_orgs') INTO v_org_id USING p_org;
    EXECUTE format('SELECT id FROM %I WHERE org_id = $1 AND name = $2', v_prefix || '_roles') INTO v_role_id USING v_org_id, p_role;
    EXECUTE format('INSERT INTO %I (email, org_id, role_id, user_uid, is_org_admin) VALUES ($1, $2, $3, $4, $5) RETURNING id', v_prefix || '_users')
    INTO v_id USING p_email, v_org_id, v_role_id, p_uid, p_admin;
    RETURN v_id;
END; $$ LANGUAGE plpgsql;

-- ============================================================
-- GENERATE OPA BUNDLE
-- ============================================================
CREATE OR REPLACE FUNCTION generate_opa_bundle(p_platform VARCHAR) RETURNS JSONB AS $$
DECLARE v_prefix VARCHAR := get_prefix(p_platform); v_rbac JSONB; v_users JSONB;
BEGIN
    EXECUTE format('
        SELECT jsonb_object_agg(o.name, (
            SELECT jsonb_object_agg(r.name, (
                SELECT jsonb_object_agg(p.resource, jsonb_build_object(''read'', p.can_read, ''write'', p.can_write, ''delete'', p.can_delete))
                FROM %I p WHERE p.role_id = r.id
            ) || jsonb_build_object(''global_access'', r.global_access, ''bu_access'', r.bu_access))
            FROM %I r WHERE r.org_id = o.id
        )) FROM %I o', v_prefix || '_perms', v_prefix || '_roles', v_prefix || '_orgs') INTO v_rbac;

    EXECUTE format('
        SELECT jsonb_build_object(
            ''user_roles'', (SELECT jsonb_object_agg(u.email, r.name) FROM %I u JOIN %I r ON r.id = u.role_id),
            ''user_tenant'', (SELECT jsonb_object_agg(u.email, o.name) FROM %I u JOIN %I o ON o.id = u.org_id),
            ''user_ids'', (SELECT jsonb_object_agg(email, user_uid) FROM %I),
            ''org_admin_flag'', (SELECT jsonb_object_agg(email, CASE WHEN is_org_admin THEN 1 ELSE 0 END) FROM %I)
        )', v_prefix || '_users', v_prefix || '_roles', v_prefix || '_users', v_prefix || '_orgs', v_prefix || '_users', v_prefix || '_users') INTO v_users;

    RETURN jsonb_build_object('rbac', v_rbac, 'users', v_users);
END; $$ LANGUAGE plpgsql;


-- ============================================================
-- AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_email VARCHAR(255) NOT NULL,
    platform    VARCHAR(50) NOT NULL,
    org_name    VARCHAR(100),
    action      VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id   UUID,
    details     JSONB,
    ip_address  VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_platform_ts ON audit_log(platform, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_platform_org_ts ON audit_log(platform, org_name, timestamp DESC);


-- ============================================================
-- GLOBAL PUBLICATION FOR ALL TABLES
-- ============================================================
DROP PUBLICATION IF EXISTS authz_pub;
CREATE PUBLICATION authz_pub FOR ALL TABLES;


-- ============================================================
-- PLATFORM BOOTSTRAP (CI/CD INJECTED)
-- ============================================================
SELECT create_platform('mlops', NULL);
SELECT create_platform('analytics', NULL);
SELECT create_platform('vision', NULL);
SELECT create_platform('DC', NULL);
