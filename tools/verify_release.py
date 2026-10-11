"""Offline public subset, provenance, history and sensitive-file checks."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check():
    index = json.loads((ROOT / 'provenance/source-index.json').read_text())
    for record in index['records']:
        path = ROOT / record['public_path']
        assert not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], record['public_path']
    patterns = [r'/Users/', r'/home/[^/]+/', r'-----BEGIN .*PRIVATE KEY-----',
                r'gh[pousr]_[A-Za-z0-9]{30,}', r'AKIA[0-9A-Z]{16}',
                r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
                r'(?i)(?:api_key|access_token|refresh_token|password)\s*[=:]\s*[\"\x27][A-Za-z0-9_+/=-]{16,}[\"\x27]']
    # Pattern literals in this verifier are a reviewed non-secret exception.
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    release_index = json.loads((ROOT / 'provenance/release-index.json').read_text())
    allowlist = {entry['path'] for entry in release_index['records']}
    assert set(filter(None, files)) == allowlist | {'provenance/release-index.json'}, 'FILE_SET_CHANGED'
    for entry in release_index['records']:
        path = ROOT / entry['path']
        assert path.stat().st_size == entry['bytes'], entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['path']
    scanned = 0
    for name in filter(None, files):
        path = ROOT / name
        assert not path.is_symlink(), name
        assert path.stat().st_size < 1024 * 1024, 'LARGE_FILE:' + name
        assert Path(name).parts[0] not in {'config', 'data', 'datasets', 'artifacts',
                                         'logs', '.venv'}, 'PROTECTED_CLASS:' + name
        assert path.suffix.lower() not in {'.parquet', '.csv', '.db', '.sqlite', '.zip', '.pdf', '.png'}, name
        text = path.read_text(encoding='utf-8')
        if name != 'tools/verify_release.py':
            assert not any(re.search(pattern, text) for pattern in patterns), 'REVIEW_REQUIRED:' + name
        if path.suffix == '.py':
            compile(text, str(path), 'exec')
        elif path.suffix == '.json':
            json.loads(text)
        if path.suffix == '.md':
            for destination in re.findall(r'\]\(([^)]+)\)', text):
                if destination.startswith(('http:', 'https:', '#', 'mailto:')):
                    continue
                target = destination.split('#')[0]
                assert (path.parent / target).exists(), 'BROKEN_LINK:' + name + ':' + target
        scanned += 1
    alternates = ROOT / '.git/objects/info/alternates'
    assert not alternates.exists(), 'EXTERNAL_GIT_OBJECTS'
    roots = subprocess.check_output(['git', 'rev-list', '--max-parents=0', 'HEAD'], cwd=ROOT,
                                   text=True).splitlines()
    if (ROOT / 'provenance/release-root.json').exists():
        assert roots == [json.loads((ROOT / 'provenance/release-root.json').read_text())['root_commit']]
    assert index['archive_head'] not in subprocess.check_output(['git', 'rev-list', 'HEAD'],
                                                               cwd=ROOT, text=True).splitlines()
    emails = subprocess.check_output(['git', 'log', '--all', '--format=%ae%n%ce'],
                                     cwd=ROOT, text=True).splitlines()
    assert all(email.endswith('@users.noreply.github.com') or email == 'noreply@github.com'
               for email in emails), 'PRIVATE_COMMIT_EMAIL_REQUIRES_REVIEW'
    history_blobs = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT,
                                           text=True).splitlines()
    history_checks = 0
    for item in history_blobs:
        oid, _, name = item.partition(' ')
        kind = subprocess.check_output(['git', 'cat-file', '-t', oid], cwd=ROOT, text=True).strip()
        if kind != 'blob':
            continue
        data = subprocess.check_output(['git', 'cat-file', '-p', oid], cwd=ROOT)
        assert len(data) < 1024 * 1024, 'HISTORY_LARGE_BLOB'
        text = data.decode('utf-8')
        if name != 'tools/verify_release.py':
            assert not any(re.search(pattern, text) for pattern in patterns), 'HISTORY_REVIEW_REQUIRED:' + name
        history_checks += 1
    return {'status': 'PASS', 'original_or_adapted_files_verified': len(index['records']),
            'tracked_files_scanned': scanned, 'history_blobs_scanned': history_checks,
            'root_commit': roots[0], 'secret_scan': 'HEURISTIC_NO_MATCH_NOT_A_FORENSIC_GUARANTEE',
            'commit_identity_scan': 'PUBLIC_NOREPLY_ONLY',
            'original_history_imported': False, 'actual_market_data_tested': False}


if __name__ == '__main__':
    print(json.dumps(check(), sort_keys=True, indent=2))
