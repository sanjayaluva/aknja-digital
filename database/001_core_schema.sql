-- Starter schema only; Alembic migrations are authoritative after implementation.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant_memberships (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE clients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  display_name text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);
CREATE INDEX ix_clients_tenant_created ON clients(tenant_id, created_at DESC);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL,
  name text NOT NULL,
  lifecycle_state text NOT NULL DEFAULT 'DISCOVERY',
  hosting_mode text NOT NULL DEFAULT 'CLIENT_OWNED',
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id),
  UNIQUE (tenant_id, id)
);
CREATE INDEX ix_projects_tenant_state ON projects(tenant_id, lifecycle_state);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  project_id uuid NOT NULL,
  title text NOT NULL,
  status text NOT NULL DEFAULT 'BACKLOG',
  idempotency_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, id),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  tenant_id uuid REFERENCES tenants(id),
  actor_type text NOT NULL,
  actor_id text,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  payload_hash text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_tenant_created ON audit_events(tenant_id, created_at DESC);

CREATE TABLE quota_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_product_id text NOT NULL,
  metric_key text NOT NULL,
  allowance numeric,
  provider_reported_usage numeric,
  locally_metered_usage numeric,
  effective_usage numeric,
  confidence text NOT NULL,
  observed_at timestamptz NOT NULL,
  reset_at timestamptz
);

CREATE TABLE quota_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_product_id text NOT NULL,
  task_id uuid REFERENCES tasks(id),
  quantity numeric NOT NULL CHECK (quantity >= 0),
  unit text NOT NULL,
  status text NOT NULL DEFAULT 'RESERVED',
  idempotency_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);
