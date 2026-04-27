# Indexing Strategy — Auth Server v2

## Table of Contents

1. [Index Selection Theory](#index-selection-theory)
2. [The Three Selection Criteria](#the-three-selection-criteria)
3. [Composite Index Column Ordering](#composite-index-column-ordering)
4. [Index Types Beyond B-tree](#index-types-beyond-b-tree)
5. [Partial Indexes](#partial-indexes)
6. [Validating with EXPLAIN ANALYZE](#validating-with-explain-analyze)
7. [Decision Framework](#decision-framework)
8. [Current Index Coverage](#current-index-coverage)
9. [Gaps and Recommendations](#gaps-and-recommendations)

---

## Index Selection Theory

### The Core Problem

A database table stores rows in **heap order** (roughly insertion order). Without an index, every query does a **sequential scan** — it reads every row to find matches. An index is a separate, sorted data structure that maps column values to row locations, letting the database jump directly to matching rows.

The fundamental tradeoff:

> **Indexes speed up reads but slow down writes.**
>
> Every INSERT, UPDATE, and DELETE must also update every index on the table. So the question is always: *which columns justify the overhead?*

---

## The Three Selection Criteria

### 1. Selectivity — How Much Does the Index Narrow Down?

**Selectivity** = (number of distinct values) / (total rows). The closer to 1.0, the more selective the column is.

| Column            | Distinct Values | Rows   | Selectivity | Worth indexing?               |
|-------------------|-----------------|--------|-------------|-------------------------------|
| `user.id` (UUID)  | 10,000          | 10,000 | 1.0         | Yes — each lookup returns 1 row |
| `user.org_id`     | 50              | 10,000 | 0.005       | Depends on query pattern       |
| `user.is_org_admin`| 2 (true/false) | 10,000 | 0.0002      | Almost never on its own        |

**Rule of thumb**: if a query returns more than ~10-15% of the table, PostgreSQL will choose a sequential scan over an index scan anyway — it is cheaper to read the whole table than to bounce between the index and heap randomly.

#### Real Example — Role Dependency Check

From `manage_service.py`, the `delete_role` function checks if any users reference a role:

```python
# manage_service.py — delete_role
count = await conn.fetchval(
    f"SELECT count(*) FROM {pfx}_users WHERE role_id = $1", role_id
)
```

`role_id` has moderate selectivity (maybe 5-20 roles per platform, so each role holds 5-50% of users). But this is a **count query**, not a bulk fetch, and PostgreSQL can do an **index-only scan** — it walks the index without touching the heap. Even at low selectivity, the index avoids a full table scan.

---

### 2. Query Pattern — WHERE, JOIN, ORDER BY, GROUP BY

Indexes help in this priority order:

#### WHERE Equality (`=`) — Most Impactful

The B-tree narrows directly to an exact key range.

```sql
-- manage_service.py — list_users
SELECT u.id, u.email, u.user_uid, r.name AS role_name,
       o.name AS org_name, u.is_org_admin
FROM mlops_users u
JOIN mlops_roles r ON r.id = u.role_id    -- JOIN on role_id
JOIN mlops_orgs  o ON o.id = u.org_id
WHERE u.org_id = $1                        -- filter on org_id
ORDER BY u.email                           -- sort on email
```

This single query wants indexes on three columns. Which matter most?

| Column in query           | Usage          | Impact without index                          |
|---------------------------|----------------|-----------------------------------------------|
| `org_id` in WHERE         | Equality filter | **High** — Postgres scans every user row       |
| `role_id` in JOIN         | Join key        | **Medium** — each nested-loop iteration scans  |
| `email` in ORDER BY       | Sort            | **Low** — sorting tens to hundreds of rows in memory is fine |

#### WHERE Range (`<`, `>`, `BETWEEN`)

B-tree helps but only for the **first** range column in a composite index.

```sql
-- manage_service.py — audit log query
SELECT ... FROM audit_log
WHERE platform = $1 AND org_name = $2
ORDER BY timestamp DESC
LIMIT 50 OFFSET 0
```

The ideal index here is `(platform, org_name, timestamp DESC)`:
- Equality filters on the first two columns
- The index is already sorted by timestamp for the ORDER BY
- Postgres walks the index and stops at 50 rows — zero sort cost

Without timestamp in the index, Postgres finds all matching rows and then sorts them all just to return 50.

#### JOIN Columns

The inner table of a nested-loop join needs an index on the join column. Without it, every iteration of the outer loop triggers a full scan of the inner table.

---

### 3. Write Overhead — How Often Is the Table Mutated?

| Table           | Write Frequency                   | Read Frequency                 | Verdict                                      |
|-----------------|-----------------------------------|--------------------------------|----------------------------------------------|
| `audit_log`     | Every management mutation          | Occasional admin queries       | Be conservative — over-indexing slows every API write |
| `{pfx}_users`   | Rare (add/remove user)             | Every list, get, delete-check  | Index freely — write cost is negligible       |
| `{pfx}_perms`   | Infrequent (permission changes)    | Every role detail view + OPA bundle generation | Index freely                   |
| `{pfx}_orgs`    | Very rare (create/rename org)      | Every management query          | Index freely                                  |
| `{pfx}_roles`   | Rare (role CRUD)                   | Joins in user/perm queries      | Index freely                                  |

---

## Composite Index Column Ordering

For a composite index `(A, B, C)`, the B-tree sorts by A first, then B within each A, then C within each (A, B). This means:

| Query                        | Uses the index? | Why                                        |
|------------------------------|------------------|--------------------------------------------|
| `WHERE A = x`                | Yes              | Leftmost prefix                            |
| `WHERE A = x AND B = y`     | Yes              | First two columns of prefix                |
| `WHERE B = y`                | **No**           | Violates leftmost prefix rule              |
| `WHERE A = x ORDER BY B`    | Yes              | Filter on A, index already sorted by B     |
| `WHERE A = x AND B = y ORDER BY C` | Yes      | Full prefix used                           |

### Real Example — Audit Log Queries

The audit log currently has index `(platform, org_name)`. The query **without** `org_name`:

```sql
-- manage_service.py — get_audit_log (no org_name filter)
WHERE platform = $1
ORDER BY timestamp DESC
LIMIT 50
```

This uses the index to find rows for the platform, but then must **sort** all of them by timestamp. If there are 100K audit entries for one platform, that's sorting 100K rows to return 50.

With a separate index `(platform, timestamp DESC)`, Postgres walks the index in order and stops at 50. Zero sort cost.

---

## Index Types Beyond B-tree

| Type       | Best for                                  | Example in this system                    |
|------------|-------------------------------------------|-------------------------------------------|
| **B-tree** (default) | Equality, range, ORDER BY — 95% of cases | All current needs                         |
| **Hash**   | Pure equality, slightly smaller on disk    | Not needed — B-tree handles equality fine |
| **GIN**    | JSONB containment (`@>`), full-text search, array membership | Potentially on `audit_log.details` if you ever search inside JSON |
| **BRIN**   | Huge append-only tables where values correlate with physical row order | `audit_log.timestamp` — rows are inserted chronologically, so BRIN is very compact. Only useful at millions of rows. |

### When to Consider GIN

If you ever add a query like "find all audit entries where details contains a specific email":

```sql
SELECT * FROM audit_log
WHERE details @> '{"email": "jane@acme.com"}'::jsonb;
```

A GIN index on `details` would make this fast. Without it, Postgres parses every JSON blob in the table.

### When to Consider BRIN

BRIN (Block Range INdex) stores min/max values per block of heap pages instead of per row. For a table like `audit_log` where `timestamp` always increases, BRIN is:
- ~1000x smaller than a B-tree
- Slightly slower per query (it reads blocks, not individual rows)
- Only worthwhile at millions of rows where the B-tree itself becomes large

---

## Partial Indexes

A partial index only includes rows matching a WHERE clause. This makes the index smaller and faster.

```sql
-- Index only org admin users
CREATE INDEX idx_users_org_admins ON mlops_users(org_id)
    WHERE is_org_admin = true;
```

If you ever needed a "list org admins" query, this index would be tiny (only admin rows) and fast. The general rule:

> Do not create indexes for hypothetical queries. Index what you actually query.

Another practical example — if revoked tokens were tracked in a database table:

```sql
-- Only index non-expired revocations
CREATE INDEX idx_active_revocations ON revoked_tokens(jti)
    WHERE expires_at > now();
```

---

## Validating with EXPLAIN ANALYZE

Theory gives you candidates. `EXPLAIN ANALYZE` gives you proof.

```sql
EXPLAIN ANALYZE
SELECT count(*) FROM mlops_users WHERE role_id = 'some-uuid';
```

**Before index:**
```
Seq Scan on mlops_users  (cost=0.00..210.00 rows=10000 width=0)
                          (actual time=0.5..12.3ms rows=10000 loops=1)
  Filter: (role_id = 'some-uuid')
  Rows Removed by Filter: 9985
```

**After index:**
```
Index Only Scan using idx_mlops_users_role_id on mlops_users
                          (cost=0.28..4.30 rows=15 width=0)
                          (actual time=0.02..0.03ms rows=15 loops=1)
```

### What to Look For

| Indicator                    | Meaning                                                |
|------------------------------|--------------------------------------------------------|
| `Seq Scan` -> `Index Scan`  | The index is being used                                |
| `Sort` disappears            | ORDER BY is covered by the index                       |
| `Rows Removed by Filter` is high | The index is not selective enough for this query   |
| `Index Only Scan`            | Postgres reads only the index, never touches the heap — best case |
| `Bitmap Index Scan`          | Multiple index results combined — happens with OR conditions or low selectivity |

---

## Decision Framework

For each query in the application:

```
1. Is it slow or on a hot path?
   -> If no, skip.

2. What columns appear in WHERE / JOIN?
   -> Those are index candidates.

3. What is the selectivity of those columns?
   -> Low selectivity + small table = skip.
   -> Low selectivity + count/exists query = still useful (index-only scan).

4. Is ORDER BY causing a sort?
   -> Add the sort column to the tail of a composite index.

5. How often is the table written to?
   -> High write frequency = be conservative with index count.
   -> Low write frequency = index freely.

6. Can one composite index cover multiple queries?
   -> Prefer one composite over two single-column indexes.

7. Run EXPLAIN ANALYZE to confirm.
   -> Never guess. Measure before and after.
```

---

## Current Index Coverage

### What Exists Today

These indexes are created by `create_platform()` in `init.sql.tpl` and the audit log DDL:

| Table           | Index                            | Type              | Covers                                           |
|-----------------|----------------------------------|-------------------|--------------------------------------------------|
| `{pfx}_orgs`    | PK on `id`                       | B-tree (unique)   | `get_org` by id                                  |
| `{pfx}_orgs`    | UNIQUE on `name`                 | B-tree (unique)   | `list_orgs` ORDER BY name, name lookups           |
| `{pfx}_roles`   | PK on `id`                       | B-tree (unique)   | Role lookups by id                               |
| `{pfx}_roles`   | UNIQUE on `(org_id, name)`       | B-tree (unique)   | `list_roles` WHERE org_id, role lookup by org+name |
| `{pfx}_perms`   | PK on `(role_id, resource)`      | B-tree (unique)   | All permission queries, ON CONFLICT upsert        |
| `{pfx}_users`   | PK on `id`                       | B-tree (unique)   | `get_user` by id                                 |
| `{pfx}_users`   | UNIQUE on `email`                | B-tree (unique)   | User lookup by email                             |
| `audit_log`     | PK on `id`                       | B-tree (unique)   | —                                                |
| `audit_log`     | `idx_audit_log_timestamp`        | B-tree            | ORDER BY timestamp DESC                          |
| `audit_log`     | `idx_audit_log_platform_org`     | B-tree (composite)| WHERE platform AND org_name                      |

---

## Gaps and Recommendations

### Gap 1: `{pfx}_users` Has No Index on `org_id`

**Affected queries:**

| Query                    | File                 | Pattern                          |
|--------------------------|----------------------|----------------------------------|
| `list_users`             | `manage_service.py`  | `WHERE u.org_id = $1`           |
| `get_user`               | `manage_service.py`  | `WHERE u.id = $1 AND u.org_id = $2` |
| `update_user`            | `manage_service.py`  | `WHERE u.id = $1 AND u.org_id = $2` |
| `remove_user`            | `manage_service.py`  | `WHERE u.id = $1 AND u.org_id = $2` |

**Impact:** `list_users` does a sequential scan on the entire users table for the platform. At 10K users, this means reading all 10K rows to find the ~200 belonging to one org.

**Recommendation:**
```sql
CREATE INDEX idx_{pfx}_users_org_id ON {pfx}_users(org_id);
```

### Gap 2: `{pfx}_users` Has No Index on `role_id`

**Affected queries:**

| Query                    | File                 | Pattern                          |
|--------------------------|----------------------|----------------------------------|
| `delete_role` (guard)    | `manage_service.py`  | `SELECT count(*) FROM {pfx}_users WHERE role_id = $1` |
| `list_users` (JOIN)      | `manage_service.py`  | `JOIN {pfx}_roles r ON r.id = u.role_id` |
| `get_user` (JOIN)        | `manage_service.py`  | `JOIN {pfx}_roles r ON r.id = u.role_id` |

**Impact:** The `delete_role` guard query does a full table scan just to check if any user holds the role. The JOINs in list/get queries force nested-loop scans on each iteration.

**Recommendation:**
```sql
CREATE INDEX idx_{pfx}_users_role_id ON {pfx}_users(role_id);
```

### Gap 3: `audit_log` Platform-Only Queries Require a Sort

**Affected query:**

```sql
-- get_audit_log without org_name filter
SELECT ... FROM audit_log
WHERE platform = $1
ORDER BY timestamp DESC
LIMIT 50 OFFSET 0
```

The existing composite index `(platform, org_name)` helps filter by platform but does not help with the `ORDER BY timestamp DESC`. Postgres must collect all rows for the platform and sort them.

**Recommendation:**
```sql
CREATE INDEX idx_audit_log_platform_ts ON audit_log(platform, timestamp DESC);
```

This lets Postgres walk the index in order and stop at 50 rows — no sort step needed.

### Gap 4 (Optional): Covering Index for Audit Log with Org Filter

The existing index `(platform, org_name)` does not include `timestamp`, so even the filtered query path requires a sort after the index scan.

**Recommendation (replaces existing index):**
```sql
DROP INDEX IF EXISTS idx_audit_log_platform_org;
CREATE INDEX idx_audit_log_platform_org_ts
    ON audit_log(platform, org_name, timestamp DESC);
```

This single index covers both query paths:
- `WHERE platform = $1 AND org_name = $2 ORDER BY timestamp DESC` — full prefix match, pre-sorted
- `WHERE platform = $1 ORDER BY timestamp DESC` — leftmost prefix for platform (less optimal than the dedicated `(platform, timestamp DESC)` index, but serviceable)

If both query paths are equally hot, keep both indexes. If the org-filtered path dominates, a single three-column index may suffice.

### Summary of Recommended Changes

Add to `create_platform()` in `init.sql.tpl`:

```sql
EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(org_id)',
    v_prefix || '_users_org_id_idx', v_prefix || '_users');

EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(role_id)',
    v_prefix || '_users_role_id_idx', v_prefix || '_users');
```

Add to the audit log DDL:

```sql
CREATE INDEX IF NOT EXISTS idx_audit_log_platform_ts
    ON audit_log(platform, timestamp DESC);

-- Optionally replace the existing composite:
DROP INDEX IF EXISTS idx_audit_log_platform_org;
CREATE INDEX IF NOT EXISTS idx_audit_log_platform_org_ts
    ON audit_log(platform, org_name, timestamp DESC);
```
