"""Template proposals and append-only review evidence; no template changes."""
import sqlalchemy as sa
from alembic import op
from app.document_studio.proposal_guards import TABLES, statements

revision = "20261023_0039"
down_revision = "20261019_0038"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'studio_proposals' not in existing:
        op.create_table('studio_proposals',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('document_templates.id'), nullable=False),
            sa.Column('target_version_id', sa.Integer(), sa.ForeignKey('document_template_versions.id'), nullable=False),
            sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('language', sa.String(2), nullable=False),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('status', sa.String(12), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('decided_at', sa.DateTime()),
            sa.Column('decided_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('decision_reason', sa.Text()),
            sa.CheckConstraint("status IN ('PENDING','ACCEPTED','REJECTED')", name='ck_proposal_status'),
            sa.CheckConstraint('revision > 0', name='ck_proposal_revision'),
            sa.CheckConstraint("(status = 'PENDING' AND decided_by_id IS NULL AND decided_at IS NULL AND decision_reason IS NULL) OR "
                "(status != 'PENDING' AND decided_by_id IS NOT NULL AND decided_at IS NOT NULL AND decision_reason IS NOT NULL AND length(trim(decision_reason)) >= 3)", name='ck_proposal_decision'))
        for column in ('template_id', 'author_id', 'status'):
            op.create_index('ix_studio_proposals_' + column, 'studio_proposals', [column])
    if 'studio_proposal_events' not in existing:
        op.create_table('studio_proposal_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('proposal_id', sa.Integer(), sa.ForeignKey('studio_proposals.id'), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(20), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('draft_id', sa.Integer(), sa.ForeignKey('document_editor_drafts.id')),
            sa.Column('version_id', sa.Integer(), sa.ForeignKey('document_template_versions.id')),
            sa.UniqueConstraint('proposal_id', 'revision', name='uq_proposal_event_revision'),
            sa.CheckConstraint("kind IN ('CREATED','COMMENT','ACCEPTED','REJECTED','DRAFT_CREATED','PUBLISHED')", name='ck_proposal_event_kind'))
        op.create_index('ix_studio_proposal_events_proposal_id', 'studio_proposal_events', ['proposal_id'])
    if 'studio_proposal_attachments' not in existing:
        op.create_table('studio_proposal_attachments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('proposal_id', sa.Integer(), sa.ForeignKey('studio_proposals.id'), nullable=False),
            sa.Column('content', sa.LargeBinary(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('width', sa.Integer(), nullable=False),
            sa.Column('height', sa.Integer(), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False))
        op.create_index('ix_studio_proposal_attachments_proposal_id', 'studio_proposal_attachments', ['proposal_id'])
    if 'studio_proposal_drafts' not in existing:
        op.create_table('studio_proposal_drafts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('proposal_id', sa.Integer(), sa.ForeignKey('studio_proposals.id'), nullable=False),
            sa.Column('draft_id', sa.Integer(), sa.ForeignKey('document_editor_drafts.id'), nullable=False, unique=True),
            sa.Column('base_version_id', sa.Integer(), sa.ForeignKey('document_template_versions.id'), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False))
        op.create_index('ix_studio_proposal_drafts_proposal_id', 'studio_proposal_drafts', ['proposal_id'])
    for statement in statements(op.get_bind().dialect.name):
        op.execute(sa.text(statement))


def downgrade():
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f'SELECT count(*) FROM {table}')) for table in ('studio_proposals', *TABLES)):
        raise RuntimeError('Proposal history cannot be discarded')
    for table in ('studio_proposals', *TABLES):
        for operation in ('update', 'delete'):
            name = f'freeze_{table}_{operation}'
            op.execute(sa.text(f'DROP TRIGGER IF EXISTS {name}' + (f' ON {table}' if connection.dialect.name == 'postgresql' else '')))
            if connection.dialect.name == 'postgresql':
                op.execute(sa.text(f'DROP FUNCTION IF EXISTS {name}()'))
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_table('studio_proposals')
