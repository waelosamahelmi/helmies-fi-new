import re, json, html, math
from datetime import datetime,timezone
from bs4 import BeautifulSoup
import markdown,bleach
from .core import *

OLD_ORIGIN='https://helmies-creative-studio.waelhelmi.chatgpt.site'
TAGS=['p','h2','h3','h4','ul','ol','li','strong','em','a','blockquote','code','pre','hr','br','img','table','thead','tbody','tr','th','td']
def safe_markdown(text):return bleach.clean(markdown.markdown(text,extensions=['fenced_code','tables']),tags=TAGS,attributes={'a':['href','title'],'img':['src','alt','title']},protocols=['https','http','mailto'],strip=True)
def seed():
 if one('SELECT path FROM pages LIMIT 1'):return
 for f in SITE.rglob('index.html'):
  path='/'+str(f.relative_to(SITE).parent).replace('.','').strip('/')+'/'
  if path=='//':path='/'
  soup=BeautifulSoup(f.read_text(),'html.parser');main=soup.find('main')
  if not main:continue
  title=soup.title.get_text().removesuffix(' | Helmies');desc=soup.find('meta',attrs={'name':'description'});description=desc.get('content','') if desc else ''
  if path.startswith('/insights/') and path!='/insights/':
   article=soup.select_one('.article-body');parts=[]
   for section in article.select('section'):
    h=section.find('h2');parts.append('## '+h.get_text()+'\n\n'+'\n\n'.join(p.get_text() for p in section.find_all('p')))
   eyebrow=soup.select_one('.editorial .eyebrow');category=eyebrow.get_text().split('/')[0].strip().title() if eyebrow else 'Design'
   with db() as c:c.execute('INSERT OR IGNORE INTO posts(slug,title,description,category,body,status,created,updated) VALUES (?,?,?,?,?,?,?,?)',(path.strip('/').split('/')[-1],title,description,category,'\n\n'.join(parts),'published',now(),now()))
  else:
   with db() as c:c.execute('INSERT OR IGNORE INTO pages VALUES (?,?,?,?,?)',(path,title,description,str(main),now()))

def cards(posts):
 return '<div class="article-grid">'+''.join(f'<a class="article-card" data-category="{html.escape(p["category"])}" href="/insights/{p["slug"]}/"><div class="article-meta"><span>{html.escape(p["category"])}</span><span>{max(2,math.ceil(len(p["body"].split())/220))} MIN READ</span></div><h3>{html.escape(p["title"])}</h3><p>{html.escape(p["description"])}</p><span class="card-bottom">READ THE STORY</span></a>' for p in posts)+'</div>'

def shell(main,title,desc,path,article=None):
 source=(SITE/'index.html').read_text() if path=='/' else (SITE/'studio/index.html').read_text()
 soup=BeautifulSoup(source.replace(OLD_ORIGIN,ORIGIN),'html.parser');soup.find('main').replace_with(BeautifulSoup(main,'html.parser'))
 soup.title.string=title+' | Helmies'
 for name,value in [('description',desc),('og:title',title+' | Helmies'),('og:description',desc),('og:url',ORIGIN+path)]:
  el=soup.find('meta',attrs={'name':name}) or soup.find('meta',attrs={'property':name})
  if el:el['content']=value
 soup.find('link',rel='canonical')['href']=ORIGIN+path;soup.body['data-page']=path
 for tag in soup.find_all('script',type='application/ld+json'):tag.decompose()
 schema={'@context':'https://schema.org','@type':'Article' if article else 'WebPage','name':title,'url':ORIGIN+path,'description':desc}
 if article:schema.update(headline=title,dateModified=datetime.fromtimestamp(article['updated'],timezone.utc).isoformat(),author={'@type':'Organization','name':'Helmies'})
 el=soup.new_tag('script',type='application/ld+json');el.string=json.dumps(schema).replace('</','<\\/');soup.head.append(el)
 # Analytics is server-side aggregate counting; no visitor script or cookie.
 return str(soup)

def render_page(page):
 main=BeautifulSoup(page['html'],'html.parser')
 if page['path'] in ('/','/insights/'):
  posts=rows("SELECT * FROM posts WHERE status='published' ORDER BY updated DESC,id DESC")
  if page['path']=='/insights/':
   section=main.select_one('.insights-directory')
   if section:
    featured=section.select_one('.journal-feature')
    if featured:featured.decompose()
    for grid in section.select('.article-grid'):grid.decompose()
    section.append(BeautifulSoup(cards(posts),'html.parser'))
    count=section.select_one('#journal-count')
    if count:count.string=f'{len(posts)} articles'
    topics=section.select_one('.journal-topic')
    if topics:
     topics.clear()
     for category in ['All']+sorted({p['category'] for p in posts}):
      b=main.new_tag('button',attrs={'data-article-filter':category,'aria-pressed':str(category=='All').lower()});b.string=category;topics.append(b)
  else:
   grid=main.select_one('.article-grid')
   if grid:grid.replace_with(BeautifulSoup(cards(posts[:3]),'html.parser'))
 return shell(str(main),page['title'],page['description'],page['path'])

def render_post(post):
 body=safe_markdown(post['body']);soup=BeautifulSoup(body,'html.parser');toc=[]
 for i,h in enumerate(soup.find_all(['h2','h3'])):h['id']=f'part-{i}';toc.append(f'<a href="#part-{i}">{html.escape(h.get_text())}</a>')
 main=f'<main id="main"><nav class="breadcrumb"><a href="/">Home</a><span>/</span><a href="/insights/">Journal</a></nav><article class="editorial"><header><p class="eyebrow">{html.escape(post["category"])}</p><h1>{html.escape(post["title"])}</h1><p class="article-deck">{html.escape(post["description"])}</p><div class="byline">HELMIES JOURNAL</div></header><div class="article-layout"><aside><span class="eyebrow">IN THIS STORY</span><nav>{"".join(toc)}</nav></aside><div class="article-body">{soup}</div></div></article><section class="section"><h2>Keep exploring.</h2>{cards(rows("SELECT * FROM posts WHERE status=\'published\' AND id!=? ORDER BY updated DESC LIMIT 3",(post["id"],)))}</section></main>'
 return shell(main,post['title'],post['description'],'/insights/'+post['slug']+'/',post)

def editable_blocks(page):
 soup=BeautifulSoup(page['html'],'html.parser');blocks=[]
 for i,tag in enumerate(soup.find_all(['h1','h2','h3','p','li'])):
  if tag.find(['h1','h2','h3','p','li','input','button','video','canvas']):continue
  if len(tag.get_text(strip=True))<2:continue
  blocks.append({'id':i,'tag':tag.name,'text':tag.get_text(' ',strip=True)})
 return blocks

def edit_blocks(page,changes):
 soup=BeautifulSoup(page['html'],'html.parser');tags=soup.find_all(['h1','h2','h3','p','li']);allowed={b['id'] for b in editable_blocks(page)}
 for change in changes:
  i=change['id']
  if i not in allowed:raise ValueError('Unknown content block')
  tags[i].clear();tags[i].append(change['text'])
 return str(soup)
