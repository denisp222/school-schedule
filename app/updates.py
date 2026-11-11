"""Signed, download-only public releases. Never reads or uploads school data."""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from .version import VERSION

CHANNEL = Path(__file__).with_name('update_channel.json')
MAX_DOWNLOAD = 800 * 1024 * 1024
CHECK_SECONDS = 3


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', value):
        raise ValueError('Некорректная версия обновления.')
    return tuple(map(int, value.split('.')))


def channel():
    value = json.loads(CHANNEL.read_text(encoding='utf-8'))
    repo = value.get('repository', '')
    if not repo:
        return None
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo):
        raise ValueError('Некорректный источник обновлений.')
    if len(base64.b64decode(value['publicKey'], validate=True)) != 32:
        raise ValueError('Некорректный ключ обновлений.')
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')


def validate_manifest(envelope, config, installed=VERSION):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    payload = envelope['payload']
    Ed25519PublicKey.from_public_bytes(base64.b64decode(config['publicKey'], validate=True)).verify(
        base64.b64decode(envelope['signature'], validate=True), canonical(payload))
    if payload.get('schema') != 1 or payload.get('repository') != config['repository']:
        raise ValueError('Обновление предназначено для другого приложения.')
    if version(payload['version']) <= version(installed):
        return None
    asset = payload['asset']
    if asset.get('name') != 'ScheduleSetup.exe' or not re.fullmatch(r'[0-9a-f]{64}', asset['sha256']):
        raise ValueError('Некорректный файл обновления.')
    if type(asset['size']) is not int or not 1 <= asset['size'] <= MAX_DOWNLOAD:
        raise ValueError('Некорректный размер обновления.')
    expected = f"https://github.com/{config['repository']}/releases/download/v{payload['version']}/ScheduleSetup.exe"
    if asset['url'] != expected:
        raise ValueError('Адрес обновления не совпадает с доверенным источником.')
    return payload


def trusted_url(url):
    parts = urlsplit(str(url))
    return (parts.scheme == 'https' and parts.hostname in
            {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
            and parts.port in (None, 443) and not parts.username and not parts.password)


def get_stream(client, url):
    """Validate every redirect before following it, not after sending a request."""
    for _ in range(6):
        if not trusted_url(url):
            raise ValueError('Недоверенный адрес обновления.')
        response = client.send(client.build_request('GET', url), stream=True)
        if response.is_redirect:
            from urllib.parse import urljoin
            next_url = urljoin(str(response.url), response.headers.get('location', ''))
            response.close()
            url = next_url
            continue
        try:response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response
    raise ValueError('Слишком много перенаправлений обновления.')


def fetch_manifest(client, config):
    url = f"https://github.com/{config['repository']}/releases/latest/download/update.json"
    response = get_stream(client, url)
    try:
        chunks = bytearray()
        for block in response.iter_bytes():
            chunks.extend(block)
            if len(chunks) > 64 * 1024:
                raise ValueError('Описание обновления слишком большое.')
        return validate_manifest(json.loads(chunks), config)
    finally:
        response.close()


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download(client, payload, cache, progress=None):
    folder = Path(cache) / payload['version']
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'ScheduleSetup.exe'
    asset = payload['asset']
    if target.is_file() and target.stat().st_size == asset['size'] and checksum(target) == asset['sha256']:
        return target
    if shutil.disk_usage(folder).free < asset['size'] + 512 * 1024 * 1024:
        raise ValueError('Для обновления недостаточно свободного места.')
    temporary = folder / 'ScheduleSetup.part'
    response = get_stream(client, asset['url'])
    try:
        digest = hashlib.sha256()
        size = 0
        with temporary.open('wb') as stream:
            for block in response.iter_bytes(1024 * 1024):
                size += len(block)
                if size > asset['size']:
                    raise ValueError('Размер обновления не совпадает.')
                stream.write(block)
                digest.update(block)
                if progress:
                    progress(size, asset['size'])
        if size != asset['size'] or digest.hexdigest() != asset['sha256']:
            raise ValueError('Файл обновления повреждён. Текущая версия сохранена.')
        temporary.replace(target)
        return target
    finally:
        response.close()
        temporary.unlink(missing_ok=True)


def preserve_templates(data, resources):
    """Private legacy templates stay on this PC, outside replaceable binaries."""
    source = Path(resources) / 'app/templates'
    if not source.is_dir():
        return
    target = Path(data) / 'templates'
    target.mkdir(exist_ok=True)
    for path in source.glob('*.docx'):
        if not path.name.startswith('~$') and not (target / path.name).exists():
            shutil.copy2(path, target / path.name)


def backup_before_update(data):
    """SQLite backup includes WAL; never replaces the working database."""
    data = Path(data)
    source = data / 'schedule.sqlite3'
    if not source.exists():
        return
    folder = data / 'before-update'
    folder.mkdir(exist_ok=True)
    temporary = folder / 'schedule.tmp'
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as live:
        with closing(sqlite3.connect(temporary)) as saved:
            live.backup(saved)
            if saved.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Не удалось проверить резервную копию. Обновление отложено.')
    temporary.replace(folder / 'schedule.sqlite3')


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def install_script(installer, folder, pid, expected_hash):
    """Separate Windows process waits for all executable locks to be released."""
    # No network access or school paths are passed to this helper.
    return f"""$ErrorActionPreference = 'Stop'
$setup = {ps_quote(installer)}
$folder = {ps_quote(folder)}
Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue
if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne {ps_quote(expected_hash)}) {{ exit 2 }}
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', '/UPDATE=1', ('/DIR="' + $folder + '"'))
$process = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -eq 0) {{ Start-Process -FilePath (Join-Path $folder 'Расписание.exe') -WorkingDirectory $folder }}
else {{ Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Не удалось установить обновление. Откройте приложение обычным ярлыком. Расписание сохранено.', 'Расписание') | Out-Null }}
"""


def launch_installer(installer, folder, payload):
    installer = Path(installer).resolve()
    if checksum(installer) != payload['asset']['sha256']:
        raise ValueError('Файл обновления изменился. Обновление отменено.')
    script = install_script(installer, folder, os.getpid(), payload['asset']['sha256'])
    # EncodedCommand avoids shell interpolation and PowerShell path quoting bugs.
    command = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    system = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(system), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                      '-EncodedCommand', command], cwd=str(folder),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)


def status(data):
    try:
        config = channel()
    except Exception:
        config = None
    return {'configured': bool(config), 'version': VERSION,
            'enabled': not (Path(data) / 'updates-disabled').exists()}


def startup_update(data, resources, folder):
    """Check before opening; offline startup has a fixed short deadline."""
    preserve_templates(data, resources)
    if (Path(data) / 'updates-disabled').exists():
        return False
    config = channel()
    if not config:
        return False
    found = []

    def check():
        try:
            with httpx.Client(timeout=2, follow_redirects=False, headers={'User-Agent': 'SchoolSchedule-Updates'}) as client:
                found.append(fetch_manifest(client, config))
        except Exception:
            logging.info('Update check unavailable; opening installed version')

    worker = threading.Thread(target=check, daemon=True)
    worker.start()
    worker.join(CHECK_SECONDS)
    if not found or not found[0]:
        return False
    payload = found[0]
    # A small native window; no WebView or recognition model needs loading yet.
    from .update_window import obtain_update
    installer = obtain_update(data, payload)
    if installer is None:
        return False
    backup_before_update(data)
    launch_installer(installer, folder, payload)
    return True
