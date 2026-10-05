(()=>{
 const root=document.querySelector('#founder');if(!root)return;
 const stage=root.querySelector('.founder-stage'),video=root.querySelector('video'),beats=[...root.querySelectorAll('.founder-beat')],rails=[...root.querySelectorAll('.founder-rail')];
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),short=matchMedia('(max-height:680px) and (orientation:landscape)');
 let target=0,p=0,frame=0,active=false,loaded=false,duration=0,last=0,desired=0,index=-1,staticMode=false;
 const clamp=v=>Math.max(0,Math.min(1,v));
 const select=n=>{if(n===index)return;index=n;beats.forEach((el,i)=>{el.classList.toggle('is-active',i===n);el.inert=!staticMode&&i!==n;el.setAttribute('aria-hidden',String(!staticMode&&i!==n))})};
 const seek=()=>{if(staticMode||!duration||video.seeking||video.readyState<1)return;const time=Math.min(duration-.045,Math.max(0,desired));if(Math.abs(video.currentTime-time)>.035){try{video.currentTime=time}catch{}}};
 video.addEventListener('loadedmetadata',()=>{duration=video.duration;desired=p*duration;seek()});
 video.addEventListener('seeked',()=>{if(active)seek()});
 video.addEventListener('error',()=>{root.classList.add('video-unavailable')});
 const load=()=>{if(loaded||staticMode)return;loaded=true;video.src=video.dataset.src;video.load()};
 const measure=()=>{
  const nav=document.querySelector('.site-header')?.getBoundingClientRect().height||0;
  stage.style.setProperty('--founder-nav',nav+'px');
  target=clamp((nav-root.getBoundingClientRect().top)/Math.max(1,root.offsetHeight-stage.offsetHeight));
 };
 const paint=time=>{
  frame=0;if(staticMode||!active||document.hidden)return;
  const dt=Math.min((time-(last||time-16))/1000,.06);last=time;p+=(target-p)*(1-Math.exp(-10*dt));
  if(Math.abs(p-target)<.0005)p=target;
  root.style.setProperty('--founder-p',p);
  select(Math.min(2,Math.floor(p*2.999)));desired=p*duration;seek();
  rails.forEach((rail,i)=>{const track=rail.firstElementChild;const travel=Math.max(0,track.scrollHeight-rail.clientHeight);track.style.transform=`translate3d(0,${-travel*(i?p:1-p)}px,0)`});
  if(Math.abs(target-p)>.0001)frame=requestAnimationFrame(paint);
 };
 const start=()=>{if(!frame&&!staticMode&&active&&!document.hidden){last=0;frame=requestAnimationFrame(paint)}};
 const preferences=()=>{
  staticMode=reduced.matches||document.body.classList.contains('motion-off')||short.matches;
  root.classList.toggle('is-static',staticMode);root.classList.toggle('is-enhanced',!staticMode);
  if(staticMode){cancelAnimationFrame(frame);frame=0;video.pause();index=-1;select(0)}else{index=-1;measure();select(Math.min(2,Math.floor(target*2.999)));if(active){load();start()}}
 };
 addEventListener('scroll',()=>{if(!staticMode){measure();start()}},{passive:true});
 addEventListener('resize',()=>{preferences();measure();start()},{passive:true});
 reduced.addEventListener('change',preferences);short.addEventListener('change',preferences);
 new MutationObserver(preferences).observe(document.body,{attributes:true,attributeFilter:['class']});
 document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0}else{measure();start()}});
 root.querySelectorAll('img').forEach(img=>img.addEventListener('load',start,{once:true}));
 preferences();
 if('IntersectionObserver'in window){
  new IntersectionObserver(entries=>{if(entries[0].isIntersecting)load()},{rootMargin:'900px'}).observe(root);
  new IntersectionObserver(entries=>{active=entries[0].isIntersecting;if(active){measure();load();start()}else{cancelAnimationFrame(frame);frame=0}},{rootMargin:'100px'}).observe(root);
 }else{active=true;load();measure();start()}
 addEventListener('pageshow',()=>{measure();start()});
})();
