"""Studio C proposal lifecycle against a newly created isolated installation."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_editor_qa import prepare as prepare_director


def prepare(factory, qa, password):
    from app.models import User
    from app.security import hash_password
    prepare_director(factory, qa, password)
    with factory() as db:
        db.add(User(email='studio-admin@qa.invalid', full_name='QA Studio Administrator',
            first_name='QA', middle_name='Studio', last_name='Administrator', job_title='QA non-owner administrator',
            password_hash=hash_password(password), role='administrator', is_active=True, is_system_owner=False,
            profile_status='PROFILE_COMPLETE', preferred_language='bg', must_change_password=False))
        db.commit()

if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01c', prepare=prepare,
        browser_script=Path(__file__).with_name('document_studio_proposals.mjs')))
