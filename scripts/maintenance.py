"""Maintenance commands. Show usage with --help. Make a backup before erasing contact data."""
import sys,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.core import initialize,db,now
from app.integrations import valid_email
p=argparse.ArgumentParser();p.add_argument('command',choices=['erase-contact']);p.add_argument('email');args=p.parse_args()
address=valid_email(args.email);initialize()
if input('Erase messages and prospect/campaign records for this address? Type ERASE: ')!='ERASE':raise SystemExit('Cancelled.')
with db() as c:
 c.execute('DELETE FROM campaigns WHERE recipient=? OR lead_id IN (SELECT id FROM leads WHERE email=?)',(address,address))
 c.execute('DELETE FROM leads WHERE email=?',(address,))
 c.execute('DELETE FROM messages WHERE sender=? OR recipient=?',(address,address))
 c.execute('INSERT OR REPLACE INTO suppression VALUES (?,?,?)',(address,'Do not contact after erasure request',now()))
print('App records removed. Minimal suppression record retained to prevent further campaigns. Review provider mailboxes and backups separately.')
