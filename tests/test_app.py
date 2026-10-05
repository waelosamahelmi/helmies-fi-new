import os,tempfile,importlib,secrets,json,socket
from pathlib import Path
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='helmies-test-')
os.environ['PUBLIC_URL']='https://cms.test'
from fastapi.testclient import TestClient
from app.main import app
from app import main,core,integrations
import pytest

@pytest.fixture(scope='module')
def client():
 with TestClient(app,base_url='https://cms.test') as c:
  with core.db() as db:db.execute('INSERT INTO users(email,password) VALUES (?,?)',('admin@example.com',core.hash_password('a-long-test-password-only')))
  yield c
@pytest.fixture
def auth(client):
 r=client.post('/api/login',json={'email':'admin@example.com','password':'a-long-test-password-only'})
 assert r.status_code==200,r.text
 return {'X-CSRF-Token':r.json()['csrf'],'Origin':'https://cms.test'}

def test_private_routes_and_csrf(client,auth):
 unauth=TestClient(app,base_url='https://cms.test')
 for route in ['/api/posts','/api/messages','/api/leads','/api/settings','/api/analytics']:
  assert unauth.get(route).status_code==401
 assert client.post('/api/logout').status_code==403
 assert client.post('/api/logout',headers={**auth,'Origin':'https://evil.example'}).status_code==403
 assert client.get('/admin/').headers['cache-control']=='no-store'

def test_seed_and_public_pages(client):
 assert len(core.rows('SELECT * FROM posts'))==12
 assert client.get('/').status_code==200
 assert client.get('/insights/').status_code==200
 assert 'cms.test' in client.get('/sitemap.xml').text
 assert '/admin/' not in client.get('/sitemap.xml').text
 assert client.get('/app/core.py').status_code==404
 assert client.get('/../app/core.py').status_code==404
 assert client.get('/assets/founder/wael-scroll.mp4',headers={'Range':'bytes=0-99'}).status_code==206

def test_post_lifecycle_revision_and_sanitizing(client,auth):
 p={'title':'A genuinely useful test article','slug':'test-new-guide','description':'A test description','category':'Digital','body':'## A useful heading\n\nA detailed paragraph for our new public guide. <script>alert(1)</script>\n\n[Bad link](javascript:alert(1))','status':'draft','updated':0}
 r=client.post('/api/posts',json=p,headers=auth);assert r.status_code==200,r.text
 draft=r.json();assert client.get('/insights/test-new-guide/').status_code==404
 assert 'test-new-guide' not in client.get('/search-index.json').text
 preview=client.get(f'/api/posts/{draft["id"]}/preview');assert preview.status_code==200
 assert '<script>alert(1)</script>' not in preview.text
 p['status']='published';p['updated']=draft['updated']
 r=client.put(f'/api/posts/{draft["id"]}',json=p,headers=auth);assert r.status_code==200,r.text
 published=r.json();assert client.get('/insights/test-new-guide/').status_code==200
 assert 'test-new-guide' in client.get('/search-index.json').text
 assert 'test-new-guide' in client.get('/insights/').text
 assert client.put(f'/api/posts/{draft["id"]}',json=p,headers=auth).status_code==409
 p['status']='draft';p['updated']=published['updated']
 assert client.put(f'/api/posts/{draft["id"]}',json=p,headers=auth).status_code==200
 assert client.get('/insights/test-new-guide/').status_code==404
 assert len(client.get(f'/api/revisions?kind=post&key={draft["id"]}').json())==2
 # Bundled seed pages cannot bypass unpublishing.
 original=core.one('SELECT * FROM posts WHERE slug=?',('website-brief-that-gets-results',))
 with core.db() as db:db.execute("UPDATE posts SET status='draft' WHERE id=?",(original['id'],))
 assert client.get('/insights/website-brief-that-gets-results/').status_code==404
 with core.db() as db:db.execute("UPDATE posts SET status='published' WHERE id=?",(original['id'],))

def test_page_copy_edit(client,auth):
 page=client.get('/api/page?path=/studio/').json();block=page['blocks'][0]
 body={k:page[k] for k in ['path','title','description','updated']};body['blocks']=[{'id':block['id'],'text':'A new studio headline <script>bad</script>'}]
 r=client.put('/api/page',json=body,headers=auth);assert r.status_code==200,r.text
 public=client.get('/studio/').text
 assert 'A new studio headline' in public and '<script>bad</script>' not in public
 assert client.put('/api/page',json=body,headers=auth).status_code==409

def make_lead(email='hello@example.org'):
 with core.db() as db:
  ident=db.execute('INSERT INTO leads(domain,url,name,email,email_source,evidence,score,created) VALUES (?,?,?,?,?,?,?,?)',(secrets.token_hex(5)+'.example','https://example.org','Example Company',email,'https://example.org/contact',json.dumps(['No mobile viewport declaration found in homepage HTML.']),20,core.now())).lastrowid
 return ident

def test_campaign_requires_approval_and_blocks_duplicate_send(client,auth,monkeypatch):
 ident=make_lead();r=client.post('/api/campaigns/draft',json={'lead_id':ident,'use_ai':False},headers=auth);assert r.status_code==200,r.text;cid=r.json()['id']
 assert client.post(f'/api/campaigns/{cid}/approve',headers=auth).status_code==400
 review={'name':'Example','email':'hello@example.org','status':'eligible','eligibility':'Test record: consent for a relevant website proposal confirmed.','notes':'Verified business contact.'}
 assert client.put(f'/api/leads/{ident}',json=review,headers=auth).status_code==200
 core.put('company_address','Example business street 1, Helsinki')
 monkeypatch.setattr(main,'mail_config',lambda:('smtp.example','user','password','info@helmies.fi'))
 sent=[];monkeypatch.setattr(main,'smtp_send',lambda *a,**k:sent.append(a) or 'test-id')
 assert client.post(f'/api/campaigns/{cid}/send',headers=auth).status_code==409
 assert client.post(f'/api/campaigns/{cid}/approve',headers=auth).status_code==200
 assert client.post(f'/api/campaigns/{cid}/send',headers=auth).status_code==200
 assert client.post(f'/api/campaigns/{cid}/send',headers=auth).status_code==409
 assert len(sent)==1
 assert client.post('/api/campaigns/draft',json={'lead_id':ident,'use_ai':False},headers=auth).status_code==409

def test_unsubscribe_cancels_pending_and_edits_revoke_approval(client,auth):
 ident=make_lead('contact@example.net')
 with core.db() as db:db.execute("UPDATE leads SET status='eligible',eligibility='Consent confirmed for test campaign only.' WHERE id=?",(ident,))
 r=client.post('/api/campaigns/draft',json={'lead_id':ident,'use_ai':False},headers=auth);cid=r.json()['id']
 assert client.post(f'/api/campaigns/{cid}/approve',headers=auth).status_code==200
 assert client.put(f'/api/campaigns/{cid}',json={'subject':'Updated','body':'A revised and sufficiently detailed email offer.','template':'daylight'},headers=auth).status_code==200
 assert core.one('SELECT status FROM campaigns WHERE id=?',(cid,))['status']=='draft'
 token=core.one('SELECT token FROM campaigns WHERE id=?',(cid,))['token']
 assert client.get('/unsubscribe/'+token).status_code==200
 assert not core.one('SELECT * FROM suppression WHERE email=?',('contact@example.net',))
 assert client.post('/unsubscribe/'+token).status_code==200
 assert core.one('SELECT status FROM campaigns WHERE id=?',(cid,))['status']=='cancelled'
 assert client.post(f'/api/campaigns/{cid}/approve',headers=auth).status_code==409
 assert client.post('/api/campaigns/draft',json={'lead_id':ident,'use_ai':False},headers=auth).status_code==400

def test_private_ip_and_redirect_protection(monkeypatch):
 monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
 with pytest.raises(ValueError):integrations.safe_url('https://public-looking.example/')
 for url in ['file:///etc/passwd','http://user:pass@example.org','http://example.org:8080/']:
  with pytest.raises(ValueError):integrations.safe_url(url)

def test_aggregate_analytics_and_privacy_preferences(client):
 clean=TestClient(app,base_url='https://cms.test')
 before=sum(x['views'] for x in core.rows('SELECT * FROM metrics'))
 assert clean.get('/faq/',headers={'user-agent':'Real Browser','referer':'https://example.net/page?secret=123'}).status_code==200
 after=sum(x['views'] for x in core.rows('SELECT * FROM metrics'));assert after==before+1
 assert clean.get('/faq/',headers={'DNT':'1'}).status_code==200
 assert sum(x['views'] for x in core.rows('SELECT * FROM metrics'))==after
 fields=core.rows('PRAGMA table_info(metrics)');assert {x['name'] for x in fields}=={'day','path','referrer','device','views'}
 assert 'secret' not in str(core.rows('SELECT * FROM metrics'))

def test_mail_request_id_blocks_repeated_send(client,auth,monkeypatch):
 monkeypatch.setattr(main,'mail_config',lambda:('smtp.example','u','p','info@helmies.fi'))
 sent=[];monkeypatch.setattr(main,'smtp_send',lambda *a,**k:sent.append(a) or 'fake')
 payload={'recipient':'inbox@example.net','subject':'A test reply','body':'Message content','request_id':'unique-test-request-123456'}
 assert client.post('/api/mail/send',json=payload,headers=auth).status_code==200
 assert client.post('/api/mail/send',json=payload,headers=auth).status_code==409
 assert len(sent)==1

def test_mail_sync_deduplication_and_remote_html_not_preserved(client,monkeypatch):
 from email.message import EmailMessage
 msg=EmailMessage();msg['From']='Customer <customer@example.com>';msg['To']='info@helmies.fi';msg['Subject']='Website enquiry';msg['Message-ID']='<test-inbox-id@example.com>';msg.set_content('<p>Hello Wael</p><img src="https://tracker.example/x">',subtype='html');raw=msg.as_bytes()
 class Mailbox:
  def __init__(self,*a,**k):pass
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def login(self,*a):return 'OK',[]
  def select(self,*a,**k):assert k.get('readonly');return 'OK',[]
  def response(self,*a):return 'UIDVALIDITY',[b'100']
  def uid(self,action,*args):
   if action=='search':return 'OK',[b'7']
   if args[1]=='(RFC822.SIZE)':return 'OK',[b'7 (RFC822.SIZE 1000)']
   assert args[1]=='(BODY.PEEK[])';return 'OK',[(b'7',raw),b')']
 monkeypatch.setattr(integrations.imaplib,'IMAP4_SSL',Mailbox)
 monkeypatch.setenv('IMAP_HOST','imap.example');monkeypatch.setenv('MAIL_USERNAME','info@helmies.fi');monkeypatch.setenv('MAIL_PASSWORD','fake-test-secret')
 assert integrations.sync_mail()==1
 assert integrations.sync_mail()==0
 record=core.one('SELECT * FROM messages WHERE message_id=?',('<test-inbox-id@example.com>',))
 assert record['body']=='Hello Wael' and '<img' not in record['body']

def test_smtp_branded_alternative_and_unsubscribe_headers(client,monkeypatch):
 sent=[]
 class SMTP:
  def __init__(self,*a,**k):pass
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def login(self,*a):pass
  def send_message(self,msg):sent.append(msg)
 monkeypatch.setattr(integrations.smtplib,'SMTP_SSL',SMTP)
 for key,value in {'SMTP_HOST':'smtp.example','MAIL_USERNAME':'info@helmies.fi','MAIL_PASSWORD':'fake-test-secret','MAIL_FROM':'info@helmies.fi','IMAP_SENT_FOLDER':''}.items():monkeypatch.setenv(key,value)
 integrations.smtp_send('client@example.com','A considered offer','Hello\n\nA website proposal.','midnight','random-test-unsubscribe-token')
 msg=sent[0];assert msg['List-Unsubscribe-Post']=='List-Unsubscribe=One-Click'
 assert 'cms.test/unsubscribe/random-test-unsubscribe-token' in msg['List-Unsubscribe']
 assert msg.get_body(preferencelist=('plain',)) and msg.get_body(preferencelist=('html',))
 markup=msg.get_body(preferencelist=('html',)).get_content();assert 'helmies' in markup and 'Unsubscribe from offers' in markup
 with pytest.raises(ValueError):integrations.smtp_send('client@example.com','Hello\nBcc: another@example.com','Body')

def test_discovery_prepares_drafts_but_never_sends(client,monkeypatch):
 class Result:
  def raise_for_status(self):pass
  def json(self):return {'web':{'results':[{'url':'https://discovery-test.example','title':'Discovery Test'}]}}
 monkeypatch.setenv('BRAVE_SEARCH_API_KEY','fake-test-search-key')
 monkeypatch.delenv('OPENAI_API_KEY',raising=False)
 monkeypatch.setattr(integrations.httpx,'get',lambda *a,**k:Result())
 monkeypatch.setattr(integrations.time,'sleep',lambda *a:None)
 monkeypatch.setattr(integrations,'inspect_site',lambda *a,**k:{'domain':'discovery-test.example','url':'https://discovery-test.example','name':'Discovery Test','email':'info@discovery-test.example','email_source':'https://discovery-test.example/contact','evidence':json.dumps(['No mobile viewport declaration found in homepage HTML.']),'score':20})
 sent=[];monkeypatch.setattr(integrations,'smtp_send',lambda *a,**k:sent.append(a))
 core.put('daily_target',1);core.put('auto_draft',True)
 with core.db() as db:job=db.execute("INSERT INTO jobs(kind,status,created) VALUES ('prospecting','running',?)",(core.now(),)).lastrowid
 integrations.discover(job)
 campaign=core.one('SELECT * FROM campaigns WHERE recipient=?',('info@discovery-test.example',))
 assert campaign and campaign['status']=='draft'
 assert len(sent)==0
 assert core.one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='done'
