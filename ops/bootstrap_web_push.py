#!/usr/bin/env python3
"""HUMAN-RUN ONLY after explicit approval: create persistent VAPID credentials.

Never called by app startup/Compose/install/tests. No key values are printed.
"""
import argparse
from base64 import urlsafe_b64encode
import os
from pathlib import Path
import stat
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject',required=True,help='VAPID mailto: contact; shared with push provider')
    parser.add_argument('--approve-create-persistent-vapid-key',action='store_true',required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = root/'secrets'
    destination = directory/'webpush.env'
    # An explicit ignored folder and fixed filename; never accept arbitrary paths.
    if directory.is_symlink() or destination.exists() or destination.is_symlink():
        raise SystemExit('Refusing symlink or existing credentials')
    if 'secrets/' not in (root/'.gitignore').read_text().splitlines():
        raise SystemExit('Refusing a path that is not explicitly ignored')
    directory.mkdir(mode=0o700,exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise SystemExit('Secret directory must have mode 0700')
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    sys.path.insert(0,str(root/'backend'))
    from app.push.settings import PushSettings
    key = ec.generate_private_key(ec.SECP256R1())
    public = urlsafe_b64encode(key.public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint)).decode().rstrip('=')
    private = urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32,'big')).decode().rstrip('=')
    PushSettings(True,public,private,args.subject)
    body = ('DALA_WEB_PUSH_ENABLED=true\nDALA_VAPID_PUBLIC_KEY='+public+
            '\nDALA_VAPID_PRIVATE_KEY='+private+'\nDALA_VAPID_SUBJECT='+args.subject+'\n')
    fd = os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    print('Created ignored secrets/webpush.env (0600). Keep private; do not commit or print its contents.')


if __name__ == '__main__':
    main()
