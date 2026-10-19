"""Studio A screenshots and acceptance in a newly created loopback QA DB."""

from pathlib import Path

from run_catalog_durable_review_qa import main


def prepare(factory, qa, password):
    from app.models import User
    from app.security import hash_password
    with factory() as db:
        db.add(User(email='studio-director@qa.invalid', full_name='QA Studio Director',
            first_name='QA', middle_name='Studio', last_name='Director', job_title='QA director',
            password_hash=hash_password(password), role='director', is_active=True,
            profile_status='PROFILE_COMPLETE', preferred_language='bg', must_change_password=False))
        db.commit()


if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01a', prepare=prepare,
                          browser_script=Path(__file__).with_name('document_studio.mjs')))
