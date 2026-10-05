import os, sqlite3, json, time, secrets, hashlib, hmac
from pathlib import Path
from contextlib import contextmanager
from fastapi import HTTPException, Request

ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.getenv('DATA_DIR',str(ROOT/'data')))
SITE=ROOT/'site'
ORIGIN=os.getenv('PUBLIC_URL','http://localhost:8088').rstrip('/')
COOKIE_SECURE=ORIGIN.startswith('https://')

def now():return int(time.time())
def conn():
 DATA.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DATA/'helmies.db',timeout=30);c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');return c
@contextmanager
def db():
 c=conn()
 try:yield c;c.commit()
 except: c.rollback();raise
 finally:c.close()
def rows(sql,args=()):
 with db() as c:return [dict(r) for r in c.execute(sql,args).fetchall()]
def one(sql,args=()):
 result=rows(sql,args);return result[0] if result else None
def setting(key,default=None):
 r=one('SELECT value FROM settings WHERE key=?',(key,));return json.loads(r['value']) if r else default
def put(key,value):
 with db() as c:c.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
def audit(action,detail=''):
 with db() as c:c.execute('INSERT INTO audit(action,detail,created) VALUES (?,?,?)',(action,detail[:1000],now()))
def initialize():
 with db() as c:
  c.executescript('''
 CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER NOT NULL,until INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS pages(path TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,html TEXT NOT NULL,updated INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,category TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',created INTEGER NOT NULL,updated INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,object_key TEXT NOT NULL,content TEXT NOT NULL,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,external_id TEXT UNIQUE,direction TEXT NOT NULL,sender TEXT NOT NULL,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,created INTEGER NOT NULL,status TEXT NOT NULL,reply_to TEXT DEFAULT '',message_id TEXT DEFAULT '');
 CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,domain TEXT UNIQUE NOT NULL,url TEXT NOT NULL,name TEXT NOT NULL,email TEXT DEFAULT '',email_source TEXT DEFAULT '',evidence TEXT NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'review',eligibility TEXT DEFAULT '',notes TEXT DEFAULT '',created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY,lead_id INTEGER NOT NULL REFERENCES leads(id),recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,template TEXT NOT NULL DEFAULT 'midnight',status TEXT NOT NULL DEFAULT 'draft',token TEXT UNIQUE NOT NULL,created INTEGER NOT NULL,sent_at INTEGER,error TEXT DEFAULT '');
 CREATE UNIQUE INDEX IF NOT EXISTS campaign_active_recipient ON campaigns(recipient) WHERE status!='cancelled';
 CREATE TABLE IF NOT EXISTS suppression(email TEXT PRIMARY KEY,reason TEXT NOT NULL,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS metrics(day TEXT NOT NULL,path TEXT NOT NULL,referrer TEXT NOT NULL DEFAULT '',device TEXT NOT NULL,views INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(day,path,referrer,device));
 CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,detail TEXT DEFAULT '',created INTEGER NOT NULL,finished INTEGER);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL);
 ''')
 for key,value in {'auto_draft':True,'prospecting_enabled':False,'prospecting_hour':9,'daily_target':50,'queries':['small business Helsinki contact','local services Lahti contact'],'offer_scope':'Up to 5 pages, responsive design, supplied content, one revision round. Hosting, ongoing maintenance, e-commerce, and custom integrations excluded. Final scope agreed before work begins.','offer_price':'€1,000','tax_note':'Tax treatment to be confirmed in the proposal.','sender_name':'Wael Helmi · Helmies','company_address':'','daily_send_limit':10,'analytics_enabled':True,'retention_days':90,'mail_sync_enabled':False}.items():
  if setting(key) is None:put(key,value)

def hash_password(password):
 salt=secrets.token_hex(16);return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
def check_password(password,stored):
 try:
  salt,value=stored.split(':');return hmac.compare_digest(value,hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex())
 except ValueError:return False

def admin(request:Request):
 token=request.cookies.get('helmies_admin','')
 session=one('SELECT * FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),now()))
 if not session:raise HTTPException(401,'Sign in to continue.')
 if request.method not in ('GET','HEAD'):
  if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']):raise HTTPException(403,'Refresh the page and try again.')
  if request.headers.get('origin') not in (None,ORIGIN):raise HTTPException(403,'Origin not allowed.')
 return session

def rate_limit(key,limit=10,seconds=900):
 # Hashed identifiers only. The reverse proxy must overwrite forwarded addresses.
 digest=hashlib.sha256(key.encode()).hexdigest()
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute('SELECT * FROM attempts WHERE key=?',(digest,)).fetchone()
  if r and r['until']>now() and r['count']>=limit:raise HTTPException(429,'Too many attempts. Please try again later.')
  if not r or r['until']<=now():c.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',(digest,1,now()+seconds))
  else:c.execute('UPDATE attempts SET count=count+1 WHERE key=?',(digest,))
  c.execute('DELETE FROM attempts WHERE until<?',(now()-3600,))
