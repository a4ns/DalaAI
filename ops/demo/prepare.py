"""Human-run local secret bootstrap; never prints or rotates existing values.

Generated files only become credentials when the human starts the isolated stack.
CI may use the same command only for its disposable local test containers.
"""
import argparse
import os
from pathlib import Path
import re
import secrets
import stat
import json
import sys


def read_owned(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Existing private configuration is not a safe owned regular file')
    return path.read_text().strip()


def save_once(path,value):
    if path.exists() or path.is_symlink():
        if read_owned(path)!=value:
            raise ValueError('Existing private configuration differs; no automatic overwrite or credential rotation')
        return
    # The containing directory is0700. Read-only files permit only explicitly
    # mounted Docker services with another UID to read their assigned secrets.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
    os.fchmod(fd,0o444)  # independent of the operator's umask; parent stays0700
    with os.fdopen(fd,'w') as stream:
        stream.write(value+'\n')
        stream.flush();os.fsync(stream.fileno())


def new_pin(exclude):
    while True:
        value=f'{secrets.randbelow(100000000):08d}'
        if len(set(value))>=3 and value!='71426839' and value!=exclude:return value


def prepare(directory,domain,bind,http_port,https_port,workers=False):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',domain) or '..' in domain:
        raise ValueError('Use one lowercase DNS hostname, without a scheme/path/port')
    if bind not in {'127.0.0.1','0.0.0.0'} or not all(1<=p<=65535 for p in (http_port,https_port)):
        raise ValueError('Use an explicit supported bind address and valid ports')
    if directory.exists() or directory.is_symlink():
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
            raise ValueError('Existing private directory must be UID-owned with mode0700')
    else:directory.mkdir(mode=0o700)
    values={}
    for name in ('postgres_owner_password','postgres_runtime_password','master_pin','executor_pin'):
        path=directory/name
        value=read_owned(path) if path.exists() else (new_pin(values.get('master_pin')) if name.endswith('_pin') else secrets.token_urlsafe(32))
        if name.endswith('_pin'):
            if not re.fullmatch(r'[0-9]{8}',value) or len(set(value))<3 or value=='71426839' or (name=='executor_pin' and value==values.get('master_pin')):raise ValueError('Existing demo PIN file format differs; no reset')
        elif not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',value):raise ValueError('Existing database password format differs; no reset')
        save_once(path,value);values[name]=value
    save_once(directory/'owner_dsn',f"postgresql://naryadai_owner:{values['postgres_owner_password']}@db:5432/naryadai")
    save_once(directory/'runtime_dsn',f"postgresql://naryadai_api:{values['postgres_runtime_password']}@db:5432/naryadai")
    if workers:
        path=directory/'postgres_worker_password'
        password=read_owned(path) if path.exists() else secrets.token_urlsafe(32)
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',password):raise ValueError('Invalid worker password file')
        save_once(path,password)
        save_once(directory/'worker_dsn',f'postgresql://naryadai_worker:{password}@db:5432/naryadai')
        instance_path=directory/'model_instance'
        instance=read_owned(instance_path) if instance_path.exists() else 'demo-'+secrets.token_hex(16)
        save_once(instance_path,instance)
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
        from app.ai.demo_policy import build_interactive_demo_policy,PROCESSING_DISCLOSURE
        policy=build_interactive_demo_policy(project_id='DalaAI',instance_id=instance)
        save_once(directory/'model_policy.json',json.dumps(policy,ensure_ascii=False,sort_keys=True))
        save_once(directory/'workers.env','DALA_MODEL_PROJECT_ID=DalaAI\nDALA_MODEL_INSTANCE_ID='+instance)
        print(PROCESSING_DISCLOSURE)
    origin=f'https://{domain}'+(f':{https_port}' if https_port!=443 else '')
    save_once(directory/'env',f'DALA_DOMAIN={domain}\nDALA_ALLOWED_ORIGIN={origin}\nDALA_BIND_ADDRESS={bind}\nDALA_HTTP_PORT={http_port}\nDALA_HTTPS_PORT={https_port}')
    print('Prepared private local configuration; values are not printed. Existing credentials were preserved.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--domain',required=True)
    p.add_argument('--workers',action='store_true',help='Prepare the reviewed full worker profile and named-demo model policy')
    p.add_argument('--bind',default='127.0.0.1');p.add_argument('--http-port',type=int,default=8080);p.add_argument('--https-port',type=int,default=8443)
    a=p.parse_args()
    try:prepare(a.directory,a.domain,a.bind,a.http_port,a.https_port,a.workers)
    except (ValueError,OSError):raise SystemExit('Private demo configuration not prepared; inspect ownership/configuration. No values disclosed.') from None


if __name__=='__main__':main()
