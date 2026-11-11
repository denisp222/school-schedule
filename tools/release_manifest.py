"""Create and sign a public update manifest. Private key is never packaged."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.updates import canonical, channel, checksum, validate_manifest
from app.version import VERSION


def configure(repository, keyfile):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    keyfile=Path(keyfile)
    if keyfile.exists():
        key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(keyfile.read_text().strip(),validate=True))
    else:
        keyfile.parent.mkdir(parents=True,exist_ok=True)
        key=Ed25519PrivateKey.generate()
        with keyfile.open('x',encoding='ascii') as stream:
            stream.write(base64.b64encode(key.private_bytes_raw()).decode('ascii'))
    public=base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')
    from app.updates import CHANNEL
    previous=CHANNEL.read_text(encoding='utf-8')
    CHANNEL.write_text(json.dumps({'repository':repository,'publicKey':public},indent=2)+'\n',encoding='utf-8')
    try:channel()
    except Exception:
        CHANNEL.write_text(previous,encoding='utf-8')
        raise
    print('Update channel configured. Signing key remains in the private local directory.')


def sign(installer, output):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    config=channel()
    if not config:raise ValueError('Configure the repository and verification key first.')
    installer=Path(installer)
    payload={'schema':1,'repository':config['repository'],'version':VERSION,
             'asset':{'name':'ScheduleSetup.exe','size':installer.stat().st_size,
                      'sha256':checksum(installer),
                      'url':f"https://github.com/{config['repository']}/releases/download/v{VERSION}/ScheduleSetup.exe"}}
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(os.environ['UPDATE_SIGNING_KEY'].strip(),validate=True))
    envelope={'payload':payload,'signature':base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    validate_manifest(envelope,config,installed='0.0.0')
    Path(output).write_bytes(canonical(envelope))
    print('Signed update manifest created for '+VERSION)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository')
    parser.add_argument('--key-file',default=str(ROOT/'.private/update-signing-key.txt'))
    parser.add_argument('--installer')
    parser.add_argument('--output',default=str(ROOT/'dist/update.json'))
    args=parser.parse_args()
    if args.repository:configure(args.repository,args.key_file)
    elif args.installer:sign(args.installer,args.output)
    else:parser.error('Specify --repository to configure, or --installer to sign.')
