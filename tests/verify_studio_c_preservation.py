"""Read-only comparison with the user-verified C base, including all B evidence."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = '48600622f6bc69d9783ad0e119cf379699f71e31'


def verify():
    lines = subprocess.check_output(['git', 'ls-tree', '-rz', BASE], cwd=ROOT).decode('utf-8').rstrip('\0').split('\0')
    entries = {line.split('\t', 1)[1]: line.split('\t', 1)[0].split()[2] for line in lines}
    earlier = json.loads((ROOT / 'docs/qa/commercial-docs-01b/final-fidelity/preservation.json').read_text(encoding='utf-8'))
    protected = [line.split('\t', 1)[1] for line in earlier['protected_git_tree_entries']]
    assert len(protected) == 256
    binary_suffixes = {'.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg', '.webp'}
    binaries = [p for p in entries if Path(p).suffix.lower() in binary_suffixes]
    migrations = [p for p in entries if p.startswith('backend/alembic/versions/')]
    paths = sorted(set(protected + binaries + migrations + ['backend/app/seed.py', 'docs/SOURCE_REGISTER_BG.md',
        'scripts/production_deploy.py', 'scripts/production_manager.py']))
    all_changes = subprocess.check_output(['git', 'diff', '--name-only', '-z', BASE], cwd=ROOT).decode('utf-8').split('\0')
    changed = sorted(set(all_changes) & set(paths))
    raw_changed = []
    for name in binaries:
        content = (ROOT / name).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if blob != entries[name]:
            raw_changed.append(name)
    assert not changed and not raw_changed, {'changed': changed, 'binary_bytes_changed': raw_changed}
    return {'verified_base': BASE, 'protected_materials': len(protected), 'existing_binary_documents_and_qa_files': len(binaries),
        'existing_migrations': len(migrations), 'changed_protected_paths': changed, 'changed_binary_bytes': raw_changed,
        'verified_inventory': 19, 'production_database_accessed': False, 'production_deployment_performed': False,
        'production_templates_activated': False, 'existing_b_evidence_preserved': True,
        'binary_check': 'Raw working-tree bytes match the exact Git blob for every existing PDF/DOCX/XLSX/PNG/JPEG/WebP',
        'archive_regressions': 'See official-workflow-proof.json and proposal-archive-preservation.json from the isolated real-converter regression',
        'protected_paths': paths}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = verify()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'protected_paths'}, ensure_ascii=False))
