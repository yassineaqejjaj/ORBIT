"""Initial ORBIT schema (ARCHITECTURE §5): every table, CHECK constraint, index and foreign key.

Revision ID: 0001
Revises:
Create Date: 2026-09-23 12:29:27.695525+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('full_name', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('clearance', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('avatar_color', sa.Text(), server_default=sa.text("'#4f46e5'"), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('clearance BETWEEN 0 AND 3', name=op.f('ck_users_clearance_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('uq_users_email', 'users', ['email'], unique=True)
    op.create_table('projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_projects_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index('uq_projects_slug', 'projects', ['slug'], unique=True)
    op.create_table('agents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('clearance', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('api_key_prefix', sa.Text(), nullable=False),
    sa.Column('api_key_hash', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('product', 'design', 'engineering', 'research', 'custom')", name=op.f('ck_agents_kind')),
    sa.CheckConstraint('clearance BETWEEN 0 AND 3', name=op.f('ck_agents_clearance_range')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_agents_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_agents_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents'))
    )
    op.create_index('ix_agents_project_id', 'agents', ['project_id'], unique=False)
    op.create_index('uq_agents_api_key_prefix', 'agents', ['api_key_prefix'], unique=True)
    op.create_table('audit_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_label', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('target_type', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('user', 'agent', 'system')", name=op.f('ck_audit_log_actor_type')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_audit_log_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_action', 'audit_log', ['action'], unique=False)
    op.create_index('ix_audit_log_project_id_created_at', 'audit_log', ['project_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('memory_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('lineage_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('confidence', sa.REAL(), server_default=sa.text('0.7'), nullable=False),
    sa.Column('classification', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('acl_principals', postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY['project:*']::text[]"), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('subject_user_id', sa.UUID(), nullable=True),
    sa.Column('session_id', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('created_by_type', sa.Text(), server_default=sa.text("'system'"), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("created_by_type IN ('user', 'agent', 'system')", name=op.f('ck_memory_items_created_by_type')),
    sa.CheckConstraint("kind IN ('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk')", name=op.f('ck_memory_items_kind')),
    sa.CheckConstraint("scope IN ('short_term', 'project', 'user', 'long_term')", name=op.f('ck_memory_items_scope')),
    sa.CheckConstraint("status IN ('proposed', 'validated', 'superseded', 'obsolete', 'forgotten')", name=op.f('ck_memory_items_status')),
    sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_memory_items_classification_range')),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_memory_items_confidence_range')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_memory_items_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subject_user_id'], ['users.id'], name=op.f('fk_memory_items_subject_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['memory_items.id'], name=op.f('fk_memory_items_superseded_by_id_memory_items'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['memory_items.id'], name=op.f('fk_memory_items_supersedes_id_memory_items'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_items'))
    )
    op.create_index('ix_memory_items_lineage_id', 'memory_items', ['lineage_id'], unique=False)
    op.create_index('ix_memory_items_project_id_scope_status', 'memory_items', ['project_id', 'scope', 'status'], unique=False)
    op.create_index('ix_memory_items_session_id', 'memory_items', ['session_id'], unique=False)
    op.create_index('ix_memory_items_subject_user_id', 'memory_items', ['subject_user_id'], unique=False)
    op.create_index('uq_memory_items_lineage_id_version', 'memory_items', ['lineage_id', 'version'], unique=True)
    op.create_table('project_members',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name=op.f('ck_project_members_role')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_members_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_project_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'user_id', name=op.f('pk_project_members'))
    )
    op.create_index('ix_project_members_user_id', 'project_members', ['user_id'], unique=False)
    op.create_table('relations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('src_type', sa.Text(), nullable=False),
    sa.Column('src_id', sa.UUID(), nullable=False),
    sa.Column('rel_type', sa.Text(), nullable=False),
    sa.Column('dst_type', sa.Text(), nullable=False),
    sa.Column('dst_id', sa.UUID(), nullable=False),
    sa.Column('confidence', sa.REAL(), server_default=sa.text('1'), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("dst_type IN ('chunk', 'memory', 'document')", name=op.f('ck_relations_dst_type')),
    sa.CheckConstraint("rel_type IN ('supersedes', 'contradicts', 'derived_from', 'mentions', 'constrains', 'relates_to')", name=op.f('ck_relations_rel_type')),
    sa.CheckConstraint("src_type IN ('chunk', 'memory', 'document')", name=op.f('ck_relations_src_type')),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_relations_confidence_range')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_relations_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_relations'))
    )
    op.create_index('ix_relations_dst_id', 'relations', ['dst_id'], unique=False)
    op.create_index('ix_relations_project_id_rel_type', 'relations', ['project_id', 'rel_type'], unique=False)
    op.create_index('uq_relations_src_id_rel_type_dst_id', 'relations', ['src_id', 'rel_type', 'dst_id'], unique=True)
    op.create_table('sources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('default_classification', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('default_acl', postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY['project:*']::text[]"), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('last_ingested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('document', 'note', 'ticket', 'crm', 'feedback', 'agent_trace', 'url')", name=op.f('ck_sources_kind')),
    sa.CheckConstraint('default_classification BETWEEN 0 AND 3', name=op.f('ck_sources_default_classification_range')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_sources_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources'))
    )
    op.create_index('ix_sources_project_id_kind', 'sources', ['project_id', 'kind'], unique=False)
    op.create_table('tombstones',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('target_type', sa.Text(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=True),
    sa.Column('propagated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("target_type IN ('document', 'memory', 'chunk')", name=op.f('ck_tombstones_target_type')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_tombstones_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_tombstones_requested_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tombstones'))
    )
    op.create_index('ix_tombstones_project_id_target_type_target_id', 'tombstones', ['project_id', 'target_type', 'target_id'], unique=False)
    op.create_table('context_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('trace_id', sa.Text(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('requested_by_type', sa.Text(), nullable=False),
    sa.Column('requested_by_id', sa.UUID(), nullable=True),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('intent', sa.Text(), server_default=sa.text("'general'"), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'succeeded'"), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('timings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('candidates_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('included_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('excluded_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('tokens_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('token_budget', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('cost_estimate', sa.Numeric(precision=12, scale=6), server_default=sa.text('0'), nullable=False),
    sa.Column('snapshot_id', sa.UUID(), nullable=True),
    sa.Column('context_text', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("intent IN ('general', 'specification', 'design', 'engineering', 'research', 'analysis', 'validation')", name=op.f('ck_context_requests_intent')),
    sa.CheckConstraint("requested_by_type IN ('user', 'agent')", name=op.f('ck_context_requests_requested_by_type')),
    sa.CheckConstraint("status IN ('succeeded', 'failed')", name=op.f('ck_context_requests_status')),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_context_requests_agent_id_agents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_context_requests_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_context_requests_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_requests'))
    )
    op.create_index('ix_context_requests_agent_id', 'context_requests', ['agent_id'], unique=False)
    op.create_index('ix_context_requests_project_id_created_at', 'context_requests', ['project_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_context_requests_trace_id', 'context_requests', ['trace_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('uri', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.Text(), server_default=sa.text("'text/plain'"), nullable=False),
    sa.Column('author', sa.Text(), nullable=True),
    sa.Column('classification', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('acl_principals', postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY['project:*']::text[]"), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True),
    sa.Column('current_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('pii_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('forgotten_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('forgotten_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'processing', 'indexed', 'failed', 'forgotten')", name=op.f('ck_documents_status')),
    sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_documents_classification_range')),
    sa.ForeignKeyConstraint(['forgotten_by'], ['users.id'], name=op.f('fk_documents_forgotten_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_documents_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_documents_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    op.create_index('ix_documents_project_id_status', 'documents', ['project_id', 'status'], unique=False)
    op.create_index('ix_documents_source_id', 'documents', ['source_id'], unique=False)
    op.create_index('uq_documents_project_id_source_id_external_id', 'documents', ['project_id', 'source_id', 'external_id'], unique=True, postgresql_where=sa.text('external_id IS NOT NULL'))
    op.create_table('memory_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('memory_item_id', sa.UUID(), nullable=False),
    sa.Column('lineage_id', sa.UUID(), nullable=False),
    sa.Column('event', sa.Text(), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('user', 'agent', 'system')", name=op.f('ck_memory_events_actor_type')),
    sa.CheckConstraint("event IN ('created', 'edited', 'validated', 'superseded', 'obsoleted', 'forgotten', 'restored', 'conflict_detected')", name=op.f('ck_memory_events_event')),
    sa.ForeignKeyConstraint(['memory_item_id'], ['memory_items.id'], name=op.f('fk_memory_events_memory_item_id_memory_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_events'))
    )
    op.create_index('ix_memory_events_lineage_id_created_at', 'memory_events', ['lineage_id', 'created_at'], unique=False)
    op.create_index('ix_memory_events_memory_item_id', 'memory_events', ['memory_item_id'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('text_redacted', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('section', sa.Text(), nullable=True),
    sa.Column('char_start', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('char_end', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('pii', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('classification', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('acl_principals', postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY['project:*']::text[]"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'superseded', 'forgotten')", name=op.f('ck_chunks_status')),
    sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_chunks_classification_range')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_chunks_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chunks'))
    )
    op.create_index('ix_chunks_document_id_version', 'chunks', ['document_id', 'version'], unique=False)
    op.create_index('ix_chunks_project_id_status', 'chunks', ['project_id', 'status'], unique=False)
    op.create_table('context_decisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('candidate_type', sa.Text(), nullable=False),
    sa.Column('candidate_id', sa.Text(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('memory_item_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('excerpt', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('source_kind', sa.Text(), nullable=True),
    sa.Column('classification', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('included', sa.Boolean(), nullable=False),
    sa.Column('reason_code', sa.Text(), nullable=False),
    sa.Column('reason_detail', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('citation', sa.Text(), nullable=True),
    sa.CheckConstraint("candidate_type IN ('chunk', 'memory', 'session')", name=op.f('ck_context_decisions_candidate_type')),
    sa.CheckConstraint("reason_code IN ('INCLUDED_RELEVANT', 'INCLUDED_PINNED', 'EXCLUDED_ACL', 'EXCLUDED_CLASSIFICATION', 'EXCLUDED_SCOPE', 'EXCLUDED_STALE', 'EXCLUDED_EXPIRED', 'EXCLUDED_SUPERSEDED', 'EXCLUDED_CONFLICT', 'EXCLUDED_DUPLICATE', 'EXCLUDED_LOW_SCORE', 'EXCLUDED_BUDGET', 'EXCLUDED_FORGOTTEN')", name=op.f('ck_context_decisions_reason_code')),
    sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_context_decisions_classification_range')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_context_decisions_document_id_documents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['memory_item_id'], ['memory_items.id'], name=op.f('fk_context_decisions_memory_item_id_memory_items'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['context_requests.id'], name=op.f('fk_context_decisions_request_id_context_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_decisions'))
    )
    op.create_index('ix_context_decisions_document_id', 'context_decisions', ['document_id'], unique=False)
    op.create_index('ix_context_decisions_memory_item_id', 'context_decisions', ['memory_item_id'], unique=False)
    op.create_index('ix_context_decisions_request_id', 'context_decisions', ['request_id'], unique=False)
    op.create_table('context_feedback',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('rating', sa.SmallInteger(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('item_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('user', 'agent')", name=op.f('ck_context_feedback_actor_type')),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name=op.f('ck_context_feedback_rating_range')),
    sa.ForeignKeyConstraint(['request_id'], ['context_requests.id'], name=op.f('fk_context_feedback_request_id_context_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_feedback'))
    )
    op.create_index('ix_context_feedback_request_id', 'context_feedback', ['request_id'], unique=False)
    op.create_table('context_snapshots',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('request_id', sa.UUID(), nullable=True),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('intent', sa.Text(), server_default=sa.text("'general'"), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_by_type', sa.Text(), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("created_by_type IN ('user', 'agent', 'system')", name=op.f('ck_context_snapshots_created_by_type')),
    sa.CheckConstraint("intent IN ('general', 'specification', 'design', 'engineering', 'research', 'analysis', 'validation')", name=op.f('ck_context_snapshots_intent')),
    sa.ForeignKeyConstraint(['parent_id'], ['context_snapshots.id'], name=op.f('fk_context_snapshots_parent_id_context_snapshots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_context_snapshots_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['request_id'], ['context_requests.id'], name=op.f('fk_context_snapshots_request_id_context_requests'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_snapshots'))
    )
    op.create_index('uq_context_snapshots_project_id_name_version', 'context_snapshots', ['project_id', 'name', 'version'], unique=True)
    # context_requests.snapshot_id <-> context_snapshots.request_id form a cycle: add this FK last.
    op.create_foreign_key(
        op.f('fk_context_requests_snapshot_id_context_snapshots'),
        'context_requests',
        'context_snapshots',
        ['snapshot_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('extracted_text', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_versions_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_versions'))
    )
    op.create_index('uq_document_versions_document_id_version', 'document_versions', ['document_id', 'version'], unique=True)
    op.create_table('ingestion_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default=sa.text('3'), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('locked_by', sa.Text(), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory')", name=op.f('ck_ingestion_jobs_kind')),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name=op.f('ck_ingestion_jobs_status')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_ingestion_jobs_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_ingestion_jobs_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingestion_jobs'))
    )
    op.create_index('ix_ingestion_jobs_document_id', 'ingestion_jobs', ['document_id'], unique=False)
    op.create_index('ix_ingestion_jobs_project_id_created_at', 'ingestion_jobs', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_ingestion_jobs_status_run_after', 'ingestion_jobs', ['status', 'run_after'], unique=False)
    op.create_table('memory_provenance',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('memory_item_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('chunk_id', sa.UUID(), nullable=True),
    sa.Column('context_request_id', sa.UUID(), nullable=True),
    sa.Column('source_label', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('excerpt', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['chunks.id'], name=op.f('fk_memory_provenance_chunk_id_chunks'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['context_request_id'], ['context_requests.id'], name=op.f('fk_memory_provenance_context_request_id_context_requests'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_memory_provenance_document_id_documents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['memory_item_id'], ['memory_items.id'], name=op.f('fk_memory_provenance_memory_item_id_memory_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_provenance'))
    )
    op.create_index('ix_memory_provenance_chunk_id', 'memory_provenance', ['chunk_id'], unique=False)
    op.create_index('ix_memory_provenance_document_id', 'memory_provenance', ['document_id'], unique=False)
    op.create_index('ix_memory_provenance_memory_item_id', 'memory_provenance', ['memory_item_id'], unique=False)


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_context_requests_snapshot_id_context_snapshots'), 'context_requests', type_='foreignkey'
    )
    op.drop_index('ix_memory_provenance_memory_item_id', table_name='memory_provenance')
    op.drop_index('ix_memory_provenance_document_id', table_name='memory_provenance')
    op.drop_index('ix_memory_provenance_chunk_id', table_name='memory_provenance')
    op.drop_table('memory_provenance')
    op.drop_index('ix_ingestion_jobs_status_run_after', table_name='ingestion_jobs')
    op.drop_index('ix_ingestion_jobs_project_id_created_at', table_name='ingestion_jobs')
    op.drop_index('ix_ingestion_jobs_document_id', table_name='ingestion_jobs')
    op.drop_table('ingestion_jobs')
    op.drop_index('uq_document_versions_document_id_version', table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index('uq_context_snapshots_project_id_name_version', table_name='context_snapshots')
    op.drop_table('context_snapshots')
    op.drop_index('ix_context_feedback_request_id', table_name='context_feedback')
    op.drop_table('context_feedback')
    op.drop_index('ix_context_decisions_request_id', table_name='context_decisions')
    op.drop_index('ix_context_decisions_memory_item_id', table_name='context_decisions')
    op.drop_index('ix_context_decisions_document_id', table_name='context_decisions')
    op.drop_table('context_decisions')
    op.drop_index('ix_chunks_project_id_status', table_name='chunks')
    op.drop_index('ix_chunks_document_id_version', table_name='chunks')
    op.drop_table('chunks')
    op.drop_index('ix_memory_events_memory_item_id', table_name='memory_events')
    op.drop_index('ix_memory_events_lineage_id_created_at', table_name='memory_events')
    op.drop_table('memory_events')
    op.drop_index('uq_documents_project_id_source_id_external_id', table_name='documents', postgresql_where=sa.text('external_id IS NOT NULL'))
    op.drop_index('ix_documents_source_id', table_name='documents')
    op.drop_index('ix_documents_project_id_status', table_name='documents')
    op.drop_table('documents')
    op.drop_index('ix_context_requests_trace_id', table_name='context_requests')
    op.drop_index('ix_context_requests_project_id_created_at', table_name='context_requests')
    op.drop_index('ix_context_requests_agent_id', table_name='context_requests')
    op.drop_table('context_requests')
    op.drop_index('ix_tombstones_project_id_target_type_target_id', table_name='tombstones')
    op.drop_table('tombstones')
    op.drop_index('ix_sources_project_id_kind', table_name='sources')
    op.drop_table('sources')
    op.drop_index('uq_relations_src_id_rel_type_dst_id', table_name='relations')
    op.drop_index('ix_relations_project_id_rel_type', table_name='relations')
    op.drop_index('ix_relations_dst_id', table_name='relations')
    op.drop_table('relations')
    op.drop_index('ix_project_members_user_id', table_name='project_members')
    op.drop_table('project_members')
    op.drop_index('uq_memory_items_lineage_id_version', table_name='memory_items')
    op.drop_index('ix_memory_items_subject_user_id', table_name='memory_items')
    op.drop_index('ix_memory_items_session_id', table_name='memory_items')
    op.drop_index('ix_memory_items_project_id_scope_status', table_name='memory_items')
    op.drop_index('ix_memory_items_lineage_id', table_name='memory_items')
    op.drop_table('memory_items')
    op.drop_index('ix_audit_log_project_id_created_at', table_name='audit_log')
    op.drop_index('ix_audit_log_action', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index('uq_agents_api_key_prefix', table_name='agents')
    op.drop_index('ix_agents_project_id', table_name='agents')
    op.drop_table('agents')
    op.drop_index('uq_projects_slug', table_name='projects')
    op.drop_table('projects')
    op.drop_index('uq_users_email', table_name='users')
    op.drop_table('users')
