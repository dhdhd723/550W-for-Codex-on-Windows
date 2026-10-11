"""Create two portable editions from one frozen runtime, without local evidence."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
BASE = DIST / 'Codex550CLauncher'
EDITION_DATA = (
    {'name': '550W简洁版', 'mode': 'brief', 'sound': False, 'data_folder': '550WBrief', 'fixed_mode': True},
    {'name': '550W完整版', 'mode': 'full', 'sound': True, 'data_folder': '550WFull', 'fixed_mode': True},
)


def package():
    assert (BASE / 'Codex550CLauncher.exe').is_file()
    sums = []
    for edition in EDITION_DATA:
        name = edition['name']
        target = (DIST / name).resolve()
        # Only remove exactly these generated directories below this project.
        assert target.parent == DIST.resolve() and target.name in ('550W简洁版', '550W完整版')
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        for directory in ('_internal', 'licenses', 'third_party'):
            shutil.copytree(BASE / directory, target / directory)
        shutil.copy2(BASE / 'Codex550CLauncher.exe', target / (name + '.exe'))
        (target / '_internal/edition.json').write_text(json.dumps(edition, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        media = target / '_internal/web/audio'
        if not edition['sound'] and media.exists():
            assert media.resolve().is_relative_to(target)
            shutil.rmtree(media)
        if edition['sound'] and not (media / 'boot.mp3').is_file():
            raise RuntimeError('The full edition requires web/audio/boot.mp3; use audio you have permission to distribute.')
        for document in ('README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'PRIVACY.md'):
            if (ROOT / document).is_file():
                shutil.copy2(ROOT / document, target / document)
        for document in ('LICENSING.md', 'VERIFICATION.md', 'RELEASE-NOTES.md'):
            source = ROOT / 'docs' / document
            if source.is_file():
                (target / 'docs').mkdir(exist_ok=True)
                shutil.copy2(source, target / 'docs' / document)
        (target / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/create-shortcut.ps1', target / 'scripts/create-shortcut.ps1')
        shutil.copy2(ROOT / 'Create-Shortcut.cmd', target / 'Create-Shortcut.cmd')
        for filename, option in (('Run', ''), ('Preview', ' --preview'), ('Settings', ' --settings'), ('diagnostics', ' --diagnose')):
            script = '@echo off\r\nchcp 65001 >nul\r\nstart "" "%~dp0' + name + '.exe"' + option + ' %*\r\n'
            (target / (filename + '.cmd')).write_bytes(script.encode('utf-8'))
        asset_hashes = {}
        for relative in ('web/index.html', 'web/animation.js', 'web/launcher.js', 'web/animation.css', 'web/launcher.css', 'web/palettes.css'):
            asset_hashes[relative] = hashlib.sha256((target / '_internal' / relative).read_bytes()).hexdigest()
        metadata = {'version': '0.3.2', 'edition': edition, 'asset_sha256': asset_hashes,
                    'audio_included': edition['sound'], 'local_user_records_included': False,
                    'license_scope': 'New launcher code MIT; animation/audio redistribution permission not confirmed'}
        (target / 'RELEASE.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        archive = DIST / (name + '.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for file in sorted(target.rglob('*')):
                if file.is_file():
                    output.write(file, str(Path(name) / file.relative_to(target)))
        with zipfile.ZipFile(archive) as output:
            assert output.testzip() is None
            assert len(output.namelist()) == len(set(output.namelist()))
            mp3s = [p for p in output.namelist() if p.lower().endswith('.mp3')]
            assert len(mp3s) == (1 if edition['sound'] else 0)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        sums.append(f'{digest}  {archive.name}\n')
        print(f'Packaged {name}: ZIP CRC verified; audio={edition["sound"]}', flush=True)
    (DIST / 'SHA256SUMS.txt').write_text(''.join(sums), encoding='utf-8')


if __name__ == '__main__':
    # Piped Python output otherwise uses cp1252 on English Windows runners.
    # The edition names remain Unicode on disk and in GitHub release assets.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    package()
