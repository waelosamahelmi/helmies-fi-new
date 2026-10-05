"""Create/reset a CMS administrator on the server. Never pass passwords in shell arguments."""
import sys,getpass
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.core import initialize,db,hash_password
from app.integrations import valid_email
initialize()
address=valid_email(input('Admin email: ').strip())
password=getpass.getpass('New password (at least 14 characters): ')
if len(password)<14 or password!=getpass.getpass('Confirm password: '):raise SystemExit('Password too short or confirmation did not match.')
with db() as c:
 c.execute('INSERT INTO users(email,password) VALUES (?,?) ON CONFLICT(email) DO UPDATE SET password=excluded.password',(address,hash_password(password)))
 c.execute('DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)',(address,))
print('Administrator saved. Existing sessions for this account were revoked.')
