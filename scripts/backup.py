"""Consistent SQLite snapshot, safe while the application is running."""
import sys,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.core import conn
path=Path(sys.argv[1] if len(sys.argv)>1 else '/data/helmies-backup.db')
with conn() as source, sqlite3.connect(path) as target:source.backup(target)
path.chmod(0o600)
print('Database snapshot created at',path)
