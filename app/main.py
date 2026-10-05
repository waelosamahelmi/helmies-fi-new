import asyncio,threading,logging,re,json,secrets,hashlib,os,time
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from html import escape
from fastapi import FastAPI,Request,Depends,HTTPException,BackgroundTasks
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse,Response
from pydantic import BaseModel,Field
from .core import *
from .content import *
from .integrations import *

log=logging.getLogger('helmies');research_lock=threading.Lock();mail_lock=threading.Lock()

def start_research():
 if not research_lock.acquire(blocking=False):raise ValueError('A research run is already active.')
 with db() as c:job=c.execute('INSERT INTO jobs(kind,status,created) VALUES (?,?,?)',('prospecting','running',now())).lastrowid
 def run():
  try:discover(job)
  finally:research_lock.release()
 threading.Thread(target=run,daemon=True).start();return job

def run_sync():
 if not mail_lock.acquire(blocking=False):raise ValueError('Mailbox sync is already running.')
 try:return sync_mail()
 finally:mail_lock.release()

async def scheduler():
 tick=0
 while True:
  try:
   local=datetime.now(ZoneInfo('Europe/Helsinki'));day=local.date().isoformat()
   if setting('prospecting_enabled') and local.hour>=setting('prospecting_hour',9) and setting('last_prospect_day')!=day:
    put('last_prospect_day',day)
    try:start_research()
    except ValueError:pass
   if setting('mail_sync_enabled') and tick%5==0:
    try:await asyncio.to_thread(run_sync)
    except Exception:put('mail_sync_error','Mailbox sync failed; check connection settings. No credentials are displayed.')
   if tick%60==0:
    cutoff=(local.date()-timedelta(days=setting('retention_days',90))).isoformat()
    with db() as c:
     c.execute('DELETE FROM metrics WHERE day<?',(cutoff,));c.execute('DELETE FROM sessions WHERE expires<?',(now(),))
   tick+=1
  except Exception:log.exception('Background task failed')
  await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
 initialize();seed()
 with db() as c:
  c.execute("UPDATE jobs SET status='failed',detail='Interrupted by application restart.',finished=? WHERE status='running'",(now(),))
  c.execute("UPDATE campaigns SET status='uncertain',error='Interrupted during send. Check delivery with the mail provider before taking further action.' WHERE status='sending'")
  c.execute("UPDATE messages SET status='uncertain' WHERE status='sending'")
 task=asyncio.create_task(scheduler())
 yield
 task.cancel()
 try:await task
 except asyncio.CancelledError:pass

app=FastAPI(title='Helmies Studio CMS',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
@app.middleware('http')
async def headers(request,call_next):
 if int(request.headers.get('content-length','0') or 0)>1_000_000:return JSONResponse({'detail':'Request too large.'},413)
 response=await call_next(request)
 response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='strict-origin-when-cross-origin';response.headers['X-Frame-Options']='SAMEORIGIN'
 if request.url.path.startswith(('/admin','/api','/unsubscribe')):response.headers['Cache-Control']='no-store';response.headers['X-Robots-Tag']='noindex, nofollow'
 if request.url.path.startswith('/admin'):response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
 return response

class Login(BaseModel):email:str=Field(max_length=254);password:str=Field(max_length=256)
@app.post('/api/login')
def login(body:Login,request:Request):
 rate_limit('login-ip:'+request.client.host,20);rate_limit('login-user:'+body.email.lower(),10)
 if request.headers.get('origin') not in (None,ORIGIN):raise HTTPException(403,'Origin not allowed.')
 user=one('SELECT * FROM users WHERE email=?',(body.email.lower(),))
 if not user or not check_password(body.password,user['password']):raise HTTPException(401,'Email or password is incorrect.')
 token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
 with db() as c:c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,now()+43200))
 response=JSONResponse({'csrf':csrf,'email':user['email']});response.set_cookie('helmies_admin',token,httponly=True,secure=COOKIE_SECURE,samesite='strict',max_age=43200,path='/');return response
@app.get('/api/me')
def me(session=Depends(admin)):return {'email':one('SELECT email FROM users WHERE id=?',(session['user_id'],))['email'],'csrf':session['csrf']}
@app.post('/api/logout')
def logout(session=Depends(admin)):
 with db() as c:c.execute('DELETE FROM sessions WHERE token=?',(session['token'],))
 response=JSONResponse({'ok':True});response.delete_cookie('helmies_admin',path='/');return response
@app.get('/api/status')
def status(session=Depends(admin)):
 return {'public_url':ORIGIN,'mail':bool(os.getenv('SMTP_HOST') and os.getenv('MAIL_USERNAME') and os.getenv('MAIL_PASSWORD')),'imap':bool(os.getenv('IMAP_HOST') and os.getenv('MAIL_USERNAME') and os.getenv('MAIL_PASSWORD')),'ai':bool(os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL')),'search':bool(os.getenv('BRAVE_SEARCH_API_KEY')),'posts':one('SELECT count(*) n FROM posts')['n'],'leads':one('SELECT count(*) n FROM leads')['n'],'drafts':one("SELECT count(*) n FROM campaigns WHERE status='draft'")['n'],'messages':one("SELECT count(*) n FROM messages WHERE direction='in'")['n'],'last_mail_sync':setting('last_mail_sync'),'jobs':rows('SELECT * FROM jobs ORDER BY id DESC LIMIT 10'),'activity':rows('SELECT * FROM audit ORDER BY id DESC LIMIT 12')}

class PostBody(BaseModel):
 title:str=Field(min_length=1,max_length=180);slug:str=Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',max_length=100);description:str=Field(max_length=320);category:str=Field(min_length=1,max_length=40);body:str=Field(max_length=100000);status:str=Field(pattern='^(draft|published)$');updated:int=0
@app.get('/api/posts')
def posts(session=Depends(admin)):return rows('SELECT * FROM posts ORDER BY updated DESC')
@app.post('/api/posts')
def new_post(body:PostBody,session=Depends(admin)):
 if body.status=='published' and len(body.body.strip())<40:raise HTTPException(400,'Add article content before publishing.')
 try:
  with db() as c:ident=c.execute('INSERT INTO posts(slug,title,description,category,body,status,created,updated) VALUES (?,?,?,?,?,?,?,?)',(body.slug,body.title,body.description,body.category,body.body,body.status,now(),now())).lastrowid
 except sqlite3.IntegrityError:raise HTTPException(409,'This article URL is already in use.')
 audit('Post created',body.title);return one('SELECT * FROM posts WHERE id=?',(ident,))
@app.put('/api/posts/{ident}')
def update_post(ident:int,body:PostBody,session=Depends(admin)):
 if body.status=='published' and len(body.body.strip())<40:raise HTTPException(400,'Add article content before publishing.')
 try:
  with db() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM posts WHERE id=?',(ident,)).fetchone()
   if not old:raise HTTPException(404,'Article not found.')
   if old['updated']!=body.updated:raise HTTPException(409,'This article changed in another window. Reload before saving.')
   if old['status']=='published' and body.slug!=old['slug']:raise HTTPException(400,'Unpublish before changing the URL; existing links will no longer work.')
   c.execute('INSERT INTO revisions(kind,object_key,content,created) VALUES (?,?,?,?)',('post',str(ident),json.dumps(dict(old)),now()))
   c.execute('UPDATE posts SET slug=?,title=?,description=?,category=?,body=?,status=?,updated=? WHERE id=?',(body.slug,body.title,body.description,body.category,body.body,body.status,max(now(),old['updated']+1),ident))
 except sqlite3.IntegrityError:raise HTTPException(409,'This article URL is already in use.')
 audit('Post saved',body.title);return one('SELECT * FROM posts WHERE id=?',(ident,))
@app.get('/api/posts/{ident}/preview',response_class=HTMLResponse)
def preview_post(ident:int,session=Depends(admin)):
 post=one('SELECT * FROM posts WHERE id=?',(ident,))
 if not post:raise HTTPException(404)
 return render_post(post)
class AIPost(BaseModel):topic:str=Field(min_length=5,max_length=2000)
@app.post('/api/ai/post')
def ai_post(body:AIPost,session=Depends(admin)):
 try:
  result=ai('Write an original practical Helmies blog draft on this topic: '+body.topic+'. Return JSON with title, slug (lowercase-hyphenated), description, category (Design, Digital, Intelligence or Film), body (Markdown, 500-800 words). Do not invent facts, personal experiences or citations. Mark uncertain factual claims for review.')
  result['status']='draft';return PostBody(**result).model_dump()
 except Exception:raise HTTPException(502,'AI drafting failed. Check your model, key and provider quota; no article was published.')
@app.get('/api/pages')
def pages(session=Depends(admin)):return rows('SELECT path,title,description,updated FROM pages ORDER BY path')
@app.get('/api/page')
def page(path:str,session=Depends(admin)):
 p=one('SELECT * FROM pages WHERE path=?',(path,))
 if not p:raise HTTPException(404)
 return {k:p[k] for k in ('path','title','description','updated')}|{'blocks':editable_blocks(p)}
class Block(BaseModel):id:int;text:str=Field(max_length=10000)
class PageBody(BaseModel):path:str;title:str=Field(min_length=1,max_length=180);description:str=Field(max_length=320);updated:int;blocks:list[Block]=Field(max_length=500)
@app.put('/api/page')
def page_save(body:PageBody,session=Depends(admin)):
 with db() as c:
  c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM pages WHERE path=?',(body.path,)).fetchone()
  if not old:raise HTTPException(404)
  old=dict(old)
  if old['updated']!=body.updated:raise HTTPException(409,'The page changed. Reload before saving.')
  try:markup=edit_blocks(old,[b.model_dump() for b in body.blocks])
  except ValueError as ex:raise HTTPException(400,str(ex))
  c.execute('INSERT INTO revisions(kind,object_key,content,created) VALUES (?,?,?,?)',('page',body.path,json.dumps(old),now()))
  c.execute('UPDATE pages SET title=?,description=?,html=?,updated=? WHERE path=?',(body.title,body.description,markup,max(now(),old['updated']+1),body.path))
 audit('Page updated',body.path);return {'ok':True}
@app.get('/api/revisions')
def revisions(kind:str,key:str,session=Depends(admin)):return rows('SELECT * FROM revisions WHERE kind=? AND object_key=? ORDER BY id DESC LIMIT 20',(kind,key))

@app.get('/api/messages')
def messages(session=Depends(admin)):return rows('SELECT * FROM messages ORDER BY created DESC LIMIT 300')
@app.post('/api/mail/sync')
def mail_sync(session=Depends(admin)):
 try:return {'received':run_sync()}
 except Exception:raise HTTPException(502,'Mailbox sync failed. Check IMAP settings and credentials. Messages on your mail server were not changed.')
class Compose(BaseModel):recipient:str=Field(max_length=254);subject:str=Field(min_length=1,max_length=250);body:str=Field(min_length=1,max_length=50000);reply_id:int|None=None;request_id:str=Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
@app.post('/api/mail/send')
def send_mail(body:Compose,session=Depends(admin)):
 try:recipient=valid_email(body.recipient);mail_config()
 except ValueError as ex:raise HTTPException(400,str(ex))
 external='out:'+body.request_id
 with db() as c:
  if c.execute('SELECT id FROM messages WHERE external_id=?',(external,)).fetchone():raise HTTPException(409,'This send was already attempted. Check Sent mail.')
  ident=c.execute('INSERT INTO messages(external_id,direction,sender,recipient,subject,body,created,status) VALUES (?,?,?,?,?,?,?,?)',(external,'out',os.getenv('MAIL_FROM',os.getenv('MAIL_USERNAME','')),recipient,body.subject,body.body,now(),'sending')).lastrowid
 parent=one('SELECT message_id FROM messages WHERE id=?',(body.reply_id,)) if body.reply_id else None
 try:
  mid=smtp_send(recipient,body.subject,body.body,in_reply_to=parent['message_id'] if parent else '',outbox_id=ident)
 except Exception:
  with db() as c:c.execute("UPDATE messages SET status='uncertain' WHERE id=?",(ident,))
  raise HTTPException(502,'Delivery could not be confirmed. Check your mail provider before sending again to avoid duplicates.')
 audit('Email sent',recipient);return {'ok':True}

@app.get('/api/leads')
def leads(session=Depends(admin)):return rows('SELECT * FROM leads ORDER BY created DESC LIMIT 1000')
class LeadInput(BaseModel):url:str=Field(max_length=2000)
@app.post('/api/leads/inspect')
def inspect(body:LeadInput,session=Depends(admin)):
 try:item=inspect_site(body.url)
 except Exception as ex:raise HTTPException(400,str(ex) if isinstance(ex,ValueError) else 'The public website could not be inspected.')
 with db() as c:c.execute('INSERT OR IGNORE INTO leads(domain,url,name,email,email_source,evidence,score,created) VALUES (?,?,?,?,?,?,?,?)',(*[item[k] for k in ('domain','url','name','email','email_source','evidence','score')],now()))
 return one('SELECT * FROM leads WHERE domain=?',(item['domain'],))
class LeadUpdate(BaseModel):email:str=Field(max_length=254);name:str=Field(max_length=180);status:str=Field(pattern='^(review|eligible|rejected|replied)$');eligibility:str=Field(max_length=2000);notes:str=Field(max_length=5000)
@app.put('/api/leads/{ident}')
def lead_update(ident:int,body:LeadUpdate,session=Depends(admin)):
 if not one('SELECT id FROM leads WHERE id=?',(ident,)):raise HTTPException(404)
 try:address=valid_email(body.email) if body.email else ''
 except ValueError as ex:raise HTTPException(400,str(ex))
 if body.status=='eligible' and (not address or len(body.eligibility.strip())<15):raise HTTPException(400,'Record the contact basis and why this business is eligible before marking it eligible.')
 with db() as c:
  c.execute('UPDATE leads SET email=?,name=?,status=?,eligibility=?,notes=? WHERE id=?',(address,body.name,body.status,body.eligibility,body.notes,ident))
  c.execute("UPDATE campaigns SET status='draft' WHERE lead_id=? AND status='approved'",(ident,))
 audit('Prospect reviewed',str(ident));return {'ok':True}
@app.post('/api/research/run')
def research(session=Depends(admin)):
 if not os.getenv('BRAVE_SEARCH_API_KEY'):raise HTTPException(400,'Connect the search API key first.')
 try:return {'job_id':start_research()}
 except ValueError as ex:raise HTTPException(409,str(ex))

@app.get('/api/campaigns')
def campaigns(session=Depends(admin)):return rows('SELECT c.*,l.name,l.url,l.eligibility,l.evidence FROM campaigns c JOIN leads l ON l.id=c.lead_id ORDER BY c.created DESC LIMIT 1000')
class DraftRequest(BaseModel):lead_id:int;use_ai:bool=True
@app.post('/api/campaigns/draft')
def campaign_draft(body:DraftRequest,session=Depends(admin)):
 lead=one('SELECT * FROM leads WHERE id=?',(body.lead_id,))
 if not lead:raise HTTPException(404)
 try:return {'id':build_campaign_draft(lead,body.use_ai)}
 except ValueError as ex:raise HTTPException(400,str(ex))
 except sqlite3.IntegrityError:raise HTTPException(409,'A campaign already exists for this contact.')
 except Exception:raise HTTPException(502,'AI drafting failed. Check AI settings or choose a standard draft.')
class CampaignEdit(BaseModel):subject:str=Field(min_length=1,max_length=250);body:str=Field(min_length=20,max_length=20000);template:str=Field(pattern='^(midnight|daylight)$')
@app.put('/api/campaigns/{ident}')
def campaign_edit(ident:int,body:CampaignEdit,session=Depends(admin)):
 with db() as c:
  cur=c.execute("UPDATE campaigns SET subject=?,body=?,template=?,status='draft' WHERE id=? AND status IN ('draft','approved')",(body.subject,body.body,body.template,ident))
  if not cur.rowcount:raise HTTPException(409,'This campaign is no longer editable.')
 return {'ok':True}
@app.get('/api/campaigns/{ident}/preview',response_class=HTMLResponse)
def campaign_preview(ident:int,session=Depends(admin)):
 campaign=one('SELECT * FROM campaigns WHERE id=?',(ident,))
 if not campaign:raise HTTPException(404)
 return email_html(campaign['body'],campaign['template'],campaign['token'])

def check_campaign(campaign):
 lead=one('SELECT * FROM leads WHERE id=?',(campaign['lead_id'],))
 if lead['status']!='eligible' or len(lead['eligibility'].strip())<15:raise HTTPException(400,'Review and mark this business eligible first.')
 if lead['email']!=campaign['recipient']:raise HTTPException(409,'Contact address changed. Cancel this draft and create a new one.')
 if one('SELECT email FROM suppression WHERE email=?',(campaign['recipient'],)):raise HTTPException(400,'Contact has opted out.')
 if not setting('company_address','').strip():raise HTTPException(400,'Add your business postal address in campaign settings first.')
 if not ORIGIN.startswith('https://'):raise HTTPException(400,'Configure the public HTTPS domain so unsubscribe links work.')

@app.post('/api/campaigns/{ident}/approve')
def approve(ident:int,session=Depends(admin)):
 campaign=one('SELECT * FROM campaigns WHERE id=?',(ident,))
 if not campaign or campaign['status']!='draft':raise HTTPException(409,'Only a draft can be approved.')
 check_campaign(campaign)
 with db() as c:c.execute("UPDATE campaigns SET status='approved' WHERE id=? AND status='draft'",(ident,))
 audit('Campaign approved',str(ident));return {'ok':True}
@app.post('/api/campaigns/{ident}/cancel')
def cancel(ident:int,session=Depends(admin)):
 with db() as c:c.execute("UPDATE campaigns SET status='cancelled' WHERE id=? AND status IN ('draft','approved')",(ident,))
 return {'ok':True}
@app.post('/api/campaigns/{ident}/send')
def campaign_send(ident:int,session=Depends(admin)):
 campaign=one('SELECT * FROM campaigns WHERE id=?',(ident,))
 if not campaign:raise HTTPException(404)
 check_campaign(campaign)
 try:mail_config()
 except ValueError as ex:raise HTTPException(400,str(ex))
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  campaign=dict(c.execute('SELECT * FROM campaigns WHERE id=?',(ident,)).fetchone())
  check_campaign(campaign)
  used=c.execute("SELECT count(*) FROM campaigns WHERE sent_at>? AND status IN ('sending','sent','uncertain')",(now()-86400,)).fetchone()[0]
  if used>=setting('daily_send_limit',10):raise HTTPException(429,'The rolling 24-hour campaign limit has been reached.')
  updated=c.execute("UPDATE campaigns SET status='sending',sent_at=? WHERE id=? AND status='approved'",(now(),ident))
  if not updated.rowcount:raise HTTPException(409,'This campaign is not approved or was already attempted.')
 try:smtp_send(campaign['recipient'],campaign['subject'],campaign['body'],campaign['template'],campaign['token'])
 except Exception:
  with db() as c:c.execute("UPDATE campaigns SET status='uncertain',error='Check provider Sent mail. Delivery may have occurred; automatic retry is disabled.' WHERE id=?",(ident,))
  raise HTTPException(502,'Delivery could not be confirmed. Check the provider before taking further action.')
 with db() as c:c.execute("UPDATE campaigns SET status='sent' WHERE id=?",(ident,))
 audit('Approved campaign sent',str(ident));return {'ok':True}

class Suppress(BaseModel):email:str;reason:str=Field(min_length=1,max_length=500)
@app.get('/api/suppression')
def suppression(session=Depends(admin)):return rows('SELECT * FROM suppression ORDER BY created DESC')
def suppress(address,reason):
 with db() as c:
  c.execute('INSERT OR REPLACE INTO suppression VALUES (?,?,?)',(address,reason,now()))
  c.execute("UPDATE campaigns SET status='cancelled' WHERE recipient=? AND status IN ('draft','approved')",(address,))
@app.post('/api/suppression')
def add_suppression(body:Suppress,session=Depends(admin)):
 try:suppress(valid_email(body.email),body.reason)
 except ValueError as ex:raise HTTPException(400,str(ex))
 return {'ok':True}
@app.get('/unsubscribe/{token}',response_class=HTMLResponse)
def unsubscribe_form(token:str):
 if not one('SELECT id FROM campaigns WHERE token=?',(token,)):raise HTTPException(404)
 return '<!doctype html><html><meta name="viewport" content="width=device-width"><title>Helmies email preferences</title><body style="background:#090b12;color:white;font:18px Arial;padding:10vw"><h1>No more offers?</h1><p>Confirm to stop future Helmies marketing emails to this address.</p><form method="post"><button style="padding:16px 24px">Unsubscribe</button></form></body></html>'
@app.post('/unsubscribe/{token}',response_class=HTMLResponse)
def unsubscribe(token:str):
 record=one('SELECT recipient FROM campaigns WHERE token=?',(token,))
 if not record:raise HTTPException(404)
 suppress(record['recipient'],'Unsubscribed');return '<html><title>Unsubscribed</title><body><h1>You are unsubscribed.</h1><p>You will not receive further Helmies campaign emails at this address.</p></body></html>'

@app.get('/api/analytics')
def analytics(session=Depends(admin)):
 cutoff=(datetime.now(ZoneInfo('Europe/Helsinki')).date()-timedelta(days=29)).isoformat()
 return {'days':rows('SELECT day,sum(views) views FROM metrics WHERE day>=? GROUP BY day ORDER BY day',(cutoff,)),'pages':rows('SELECT path,sum(views) views FROM metrics WHERE day>=? GROUP BY path ORDER BY views DESC LIMIT 20',(cutoff,)),'referrers':rows('SELECT referrer,sum(views) views FROM metrics WHERE day>=? GROUP BY referrer ORDER BY views DESC LIMIT 15',(cutoff,)),'devices':rows('SELECT device,sum(views) views FROM metrics WHERE day>=? GROUP BY device',(cutoff,)),'campaigns':rows('SELECT status,count(*) count FROM campaigns GROUP BY status')}
class SettingsBody(BaseModel):
 auto_draft:bool=True;prospecting_enabled:bool;prospecting_hour:int=Field(ge=0,le=23);daily_target:int=Field(ge=1,le=50);queries:list[str]=Field(min_length=1,max_length=10);offer_scope:str=Field(min_length=20,max_length=3000);offer_price:str=Field(min_length=1,max_length=50);tax_note:str=Field(min_length=1,max_length=500);sender_name:str=Field(min_length=1,max_length=150);company_address:str=Field(max_length=500);daily_send_limit:int=Field(ge=1,le=50);analytics_enabled:bool;retention_days:int=Field(ge=7,le=365);mail_sync_enabled:bool
@app.get('/api/settings')
def settings(session=Depends(admin)):return {k:setting(k) for k in SettingsBody.model_fields}
@app.put('/api/settings')
def settings_save(body:SettingsBody,session=Depends(admin)):
 if any(len(q)>500 or not q.strip() for q in body.queries):raise HTTPException(400,'Use 1–10 search queries, each under 500 characters.')
 if body.prospecting_enabled and not os.getenv('BRAVE_SEARCH_API_KEY'):raise HTTPException(400,'Connect search before enabling the daily schedule.')
 if body.mail_sync_enabled and not os.getenv('IMAP_HOST'):raise HTTPException(400,'Connect IMAP before enabling mailbox sync.')
 for key,value in body.model_dump().items():put(key,value)
 audit('Settings updated');return {'ok':True}

@app.get('/healthz')
def health():return {'status':'ok'}
@app.get('/admin/',response_class=HTMLResponse)
def dashboard():return (ROOT/'app/admin/index.html').read_text()
@app.get('/admin/{asset}')
def admin_asset(asset:str):
 if asset not in ('admin.js','admin.css'):raise HTTPException(404)
 return FileResponse(ROOT/'app/admin'/asset)
@app.get('/search-index.json')
def search_index():return [{'path':r['path'],'title':r['title'],'description':r['description']} for r in rows("SELECT * FROM pages WHERE path!='/offline/'")]+[{'path':'/insights/'+r['slug']+'/','title':r['title'],'description':r['description']} for r in rows("SELECT * FROM posts WHERE status='published'")]
@app.get('/sitemap.xml')
def sitemap():
 paths=[r['path'] for r in rows("SELECT path FROM pages WHERE path!='/offline/'")]+['/insights/'+r['slug']+'/' for r in rows("SELECT slug FROM posts WHERE status='published'")]
 return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+escape(ORIGIN+p)+'</loc></url>' for p in paths)+'</urlset>',media_type='application/xml')
@app.get('/robots.txt')
def robots():return Response('User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\nDisallow: /unsubscribe/\nSitemap: '+ORIGIN+'/sitemap.xml\n',media_type='text/plain')
@app.get('/llms.txt')
def llms():return Response('# Helmies\n\n'+''.join(f'- [{p["title"]}]({ORIGIN}{p["path"]}): {p["description"]}\n' for p in search_index()),media_type='text/plain')

def record_view(request,path):
 if not setting('analytics_enabled') or request.cookies.get('helmies_admin') or request.headers.get('DNT')=='1' or request.headers.get('Sec-GPC')=='1':return
 ua=request.headers.get('user-agent','')
 if re.search('bot|crawler|spider|preview|Headless',ua,re.I):return
 # Only aggregates are retained: no IP, cookie, visitor ID, full referrer or query string.
 try:ref=(urlsplit(request.headers.get('referer','')).hostname or '')[:180]
 except ValueError:ref='' 
 if ref==urlsplit(ORIGIN).hostname:ref='Internal'
 device='Mobile' if re.search('Mobile|Android|iPhone',ua,re.I) else 'Desktop / other'
 day=datetime.now(ZoneInfo('Europe/Helsinki')).date().isoformat()
 with db() as c:c.execute('INSERT INTO metrics VALUES (?,?,?,?,1) ON CONFLICT(day,path,referrer,device) DO UPDATE SET views=views+1',(day,path,ref,device))

@app.get('/{path:path}')
def public(path:str,request:Request):
 route='/'+path
 if route.startswith('/insights/') and route!='/insights/':
  slug=route.strip('/').split('/')
  if len(slug)==2:
   post=one("SELECT * FROM posts WHERE slug=? AND status='published'",(slug[1],))
   if post:record_view(request,route);return HTMLResponse(render_post(post),headers={'Cache-Control':'no-cache'})
  # Never expose bundled article HTML after it has been unpublished in the CMS.
  return HTMLResponse((SITE/'404.html').read_text().replace(OLD_ORIGIN,ORIGIN),status_code=404)
 page=one('SELECT * FROM pages WHERE path=?',(route if route.endswith('/') else route+'/',))
 if page:record_view(request,page['path']);return HTMLResponse(render_page(page),headers={'Cache-Control':'no-cache'})
 file=(SITE/path).resolve()
 if not file.is_relative_to(SITE.resolve()) or not file.is_file() or file.suffix in ('.html','.py','.db'):return HTMLResponse((SITE/'404.html').read_text().replace(OLD_ORIGIN,ORIGIN),status_code=404)
 return FileResponse(file,headers={'Cache-Control':'no-cache'})
