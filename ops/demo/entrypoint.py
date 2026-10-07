"""Read a mounted runtime DSN without logging it, then exec one API worker."""
import os
from pathlib import Path


def main():
    file = os.environ.get('DALA_RUNTIME_DSN_FILE')
    if file:
        if os.environ.get('DATABASE_URL'):
            raise SystemExit('Configure exactly one runtime DSN source')
        value = Path(file).read_text().strip()
        if not value:
            raise SystemExit('Runtime DSN file is empty')
        os.environ['DATABASE_URL'] = value
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('Runtime DSN is required')
    os.execvp('python', ['python','-m','uvicorn','app.main:app','--host','0.0.0.0',
                        '--port','8000','--workers','1','--no-access-log','--no-proxy-headers'])


if __name__ == '__main__':
    main()
