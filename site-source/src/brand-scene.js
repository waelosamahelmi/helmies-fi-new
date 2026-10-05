import * as THREE from 'three';
const { clamp, damp, smoothstep } = THREE.MathUtils;
const TAU = Math.PI * 2;

// Preserve the exact brand silhouette; evolve its material and choreography.
export function buildIdentity() {
  const shape = new THREE.Shape();
  shape.moveTo(.38,.88);
  shape.bezierCurveTo(.38,1.19,.23,1.32,-.02,1.32);
  shape.bezierCurveTo(-.29,1.32,-.43,1.10,-.43,.87);
  shape.bezierCurveTo(-.43,.61,-.39,.45,-.23,.40);
  shape.bezierCurveTo(-.43,.33,-.46,.11,-.43,-.11);
  shape.bezierCurveTo(-.41,-.29,-.36,-.41,-.22,-.45);
  shape.bezierCurveTo(-.41,-.52,-.44,-.73,-.42,-.94);
  shape.bezierCurveTo(-.40,-1.23,-.21,-1.35,.01,-1.32);
  shape.bezierCurveTo(.23,-1.30,.38,-1.13,.38,-.87);
  shape.bezierCurveTo(.38,-.64,.54,-.43,.83,-.43);
  shape.bezierCurveTo(.54,-.43,.38,-.24,.38,.02);
  shape.lineTo(.38,.88); shape.closePath();
  const geometry = new THREE.ExtrudeGeometry(shape,{depth:.46,bevelEnabled:true,bevelSize:.09,bevelThickness:.13,bevelSegments:12,curveSegments:48,steps:1});
  geometry.translate(0,0,-.23);
  const material = new THREE.MeshPhysicalMaterial({color:'#b8d9f6',metalness:.98,roughness:.135,clearcoat:1,clearcoatRoughness:.07,iridescence:.35,iridescenceIOR:1.32,iridescenceThicknessRange:[160,380],envMapIntensity:1.3});
  const violet = material.clone(); violet.color.set('#c0b4eb'); violet.iridescence = .48;
  const left = new THREE.Mesh(geometry,material); left.position.x = -.83;
  const right = new THREE.Mesh(geometry,violet); right.scale.x = -1; right.position.x = .83;
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(.405,64,40),new THREE.MeshPhysicalMaterial({color:'#e4f0ff',metalness:1,roughness:.075,clearcoat:1,clearcoatRoughness:.04,envMapIntensity:1.55}));
  sphere.position.set(0,-.02,.08);
  const group = new THREE.Group(); group.add(left,right,sphere);
  return {group,left,right,sphere};
}

// Long photographic softboxes, separated by dark negative fill, shape the chrome.
function studioEnvironment(renderer) {
  const studio = new THREE.Scene(); studio.background = new THREE.Color('#060713');
  function panel(color,power,position,width,height,roll=0) {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width,height),new THREE.MeshBasicMaterial({color:new THREE.Color(color).multiplyScalar(power),side:THREE.DoubleSide}));
    mesh.position.set(...position); mesh.lookAt(0,0,0); mesh.rotateZ(roll); studio.add(mesh);
  }
  panel('#e7f3ff',7,[-3,3,4],2.2,6.5,-.32);
  panel('#6fbcff',5.5,[-4,-.5,1],.7,7,-.18);
  panel('#ab78ff',6.5,[4,1,2],1.1,6.5,.3);
  panel('#ede0ff',5,[.5,5,-1],5,1.5,.1);
  panel('#e68fdf',3.8,[2,-3,-2],3,.7,-.5);
  panel('#477feb',3,[-2,0,-4],1.2,4);
  panel('#c3d8ff',.65,[0,-.5,5],4,4);
  const generator = new THREE.PMREMGenerator(renderer);
  const target = generator.fromScene(studio,.035,.1,30);
  studio.traverse(object=>{if(object.isMesh){object.geometry.dispose();object.material.dispose()}});
  generator.dispose(); return target;
}

function glow(color,opacity,scale) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1,1),new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    uniforms:{tint:{value:new THREE.Color(color)},strength:{value:opacity}},
    vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:'varying vec2 vUv;uniform vec3 tint;uniform float strength;void main(){float r=length((vUv-.5)*2.);float a=pow(max(0.,1.-r),3.5);gl_FragColor=vec4(tint,a*strength);}'
  }));
  mesh.scale.set(...scale); return mesh;
}
function orbitPoint(angle,radius){return new THREE.Vector3(Math.cos(angle)*radius,Math.sin(angle)*radius*.67,Math.sin(angle*2)*.13)}
function buildOrbit(radius,offset,color,opacity) {
  const points = Array.from({length:145},(_,i)=>orbitPoint(offset+i/144*TAU*.79,radius));
  const curve = new THREE.CatmullRomCurve3(points);
  const material = new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    uniforms:{opacity:{value:opacity},color:{value:new THREE.Color(color)}},
    vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:'varying vec2 vUv;uniform vec3 color;uniform float opacity;void main(){float tail=smoothstep(0.,.22,vUv.x)*(1.-smoothstep(.88,1.,vUv.x));gl_FragColor=vec4(color,tail*opacity);}'
  });
  const group = new THREE.Group();
  const trail = new THREE.Mesh(new THREE.TubeGeometry(curve,160,.007,5,false),material);
  const pearl = new THREE.Mesh(new THREE.SphereGeometry(.018,12,8),new THREE.MeshBasicMaterial({color}));
  const halo = glow(color,.55,[.32,.32,1]); pearl.add(halo); pearl.position.copy(points[125]);
  group.add(trail,pearl); return {group,pearl,halo,material};
}

const root = typeof document !== 'undefined' ? document.querySelector('#experience') : null;
const canvas = root?.querySelector('#brand-scene');
if(root && canvas) {
  const stage=root.querySelector('.c-stage'),beats=[...root.querySelectorAll('[data-beat]')],chapters=[...root.querySelectorAll('[data-chapter]')];
  const motionQuery=matchMedia('(prefers-reduced-motion: reduce)'),compact=matchMedia('(max-width:600px) and (max-height:740px)'),mobile=matchMedia('(max-width:700px)');
  let renderer,scene,camera,identity,environment,aura,innerGlow,dust,orbitA,orbitB;
  let frame=0,active=true,failed=false,progress=0,smoothed=0,previousTime=0,lastFrame=0,elapsed=0,selected=-1;
  let pointerX=0,pointerY=0,targetX=0,targetY=0,pointerRead=0;
  const noMotion=()=>motionQuery.matches||document.body.classList.contains('motion-off');
  const select=next=>{
    if(selected===next)return;selected=next;
    beats.forEach((beat,i)=>{beat.classList.toggle('is-active',i===next);beat.inert=i!==next;beat.setAttribute('aria-hidden',String(i!==next))});
    chapters.forEach((button,i)=>{if(i===next)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current')});
  };
  const fail=()=>{failed=true;root.classList.remove('scene-ready');root.classList.add('scene-unavailable');select(0);cancelAnimationFrame(frame);frame=0};
  const measure=()=>{
    const header=document.querySelector('.site-header').getBoundingClientRect().height;
    stage.style.setProperty('--nav-height',`${header}px`);
    progress=clamp((header-root.getBoundingClientRect().top)/Math.max(1,root.offsetHeight-stage.offsetHeight),0,1);
    if(noMotion()||compact.matches||failed)progress=0;
    select(Math.min(2,Math.floor(progress*2.999)));root.style.setProperty('--scroll',progress);
  };
  const resize=()=>{
    if(!renderer||failed)return;
    const width=Math.max(1,canvas.clientWidth),height=Math.max(1,canvas.clientHeight),ratio=Math.min(devicePixelRatio||1,mobile.matches?1.35:1.8);
    renderer.setPixelRatio(ratio);renderer.setSize(width,height,false);
    dust.material.uniforms.pixelRatio.value=ratio;
    camera.aspect=width/height;camera.updateProjectionMatrix();measure();
  };
  const render=time=>{
    frame=0;if(failed||!active||document.hidden)return;
    // Full-rate desktop motion. Mobile uses a lower pixel budget and 30fps cap.
    if(mobile.matches&&time-lastFrame<31){frame=requestAnimationFrame(render);return}
    const dt=Math.min((time-(previousTime||time-16))/1000,.05);previousTime=time;lastFrame=time;
    const still=noMotion();if(!still)elapsed+=dt;
    const t=still?0:elapsed;smoothed=still?0:damp(smoothed,progress,6.5,dt);const p=smoothed;
    if(time-pointerRead>65){const css=getComputedStyle(document.documentElement);targetX=clamp(parseFloat(css.getPropertyValue('--px'))||0,-1,1);targetY=clamp(parseFloat(css.getPropertyValue('--py'))||0,-1,1);pointerRead=time}
    pointerX=still?0:damp(pointerX,targetX,3.8,dt);pointerY=still?0:damp(pointerY,targetY,3.8,dt);
    const opening=smoothstep(p,.10,.47),closing=smoothstep(p,.58,.94),separation=opening*(1-closing),turn=smoothstep(p,.13,.9),arrival=still?1:smoothstep(elapsed,0,1.8);
    identity.left.position.set(-.83-separation*.64,separation*.29,-separation*.18);
    identity.right.position.set(.83+separation*.64,-separation*.26,separation*.25);
    identity.left.rotation.set(separation*.18,-separation*.52,-separation*.15);
    identity.right.rotation.set(-separation*.17,separation*.55,separation*.12);
    identity.sphere.position.set(Math.sin(p*TAU)*separation*.12,-.02,.08+separation*.95);identity.sphere.scale.setScalar(1+separation*.12);
    identity.group.rotation.set(.16+Math.sin(p*Math.PI)*.13+pointerY*.09+Math.sin(t*.37)*.025,-.42+turn*TAU+pointerX*.18+Math.sin(t*.29)*.10+(1-arrival)*.26,-.13+Math.sin(p*TAU)*.16+Math.sin(t*.32)*.025);
    identity.group.position.set(pointerX*.035,Math.sin(t*.72)*.045-(1-arrival)*.13,0);identity.group.scale.setScalar(1.08-separation*.065);
    orbitA.group.rotation.set(.9+Math.sin(t*.17)*.07,-.25+p*.32,-.28+t*.055);
    orbitB.group.rotation.set(-.55,.45-p*.24,.7-t*.04);
    orbitA.group.scale.setScalar(1+separation*.07);orbitB.group.scale.setScalar(1+separation*.05);
    orbitA.material.uniforms.opacity.value=.30+separation*.2;orbitB.material.uniforms.opacity.value=.16+separation*.12;
    aura.material.uniforms.strength.value=.28+separation*.18;innerGlow.material.uniforms.strength.value=.20+separation*.25;
    innerGlow.position.x=Math.sin(t*.28)*.35;dust.rotation.y=t*.022+p*.15;dust.material.uniforms.time.value=t;
    const fit=Math.max(1,1.02/camera.aspect);
    camera.position.set(pointerX*.07,pointerY*-.045,(5.95+separation*.85+(1-arrival)*.3)*fit);camera.lookAt(0,0,0);
    // Billboard the small glints in each orbit's local coordinates.
    orbitA.group.getWorldQuaternion(orbitA.halo.quaternion).invert().multiply(camera.quaternion);
    orbitB.group.getWorldQuaternion(orbitB.halo.quaternion).invert().multiply(camera.quaternion);
    try{renderer.render(scene,camera);if(failed)return;if(!root.classList.contains('scene-ready')){root.classList.add('scene-ready');measure()}}catch{fail();return}
    if(!still)frame=requestAnimationFrame(render);
  };
  const start=()=>{if(!frame&&!failed&&active&&!document.hidden){previousTime=0;frame=requestAnimationFrame(render)}};
  try{
    renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:'default'});
    renderer.setClearColor(0x000000,0);renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.debug.onShaderError=fail;
    scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(39,1,.1,40);camera.position.z=5.95;
    environment=studioEnvironment(renderer);scene.environment=environment.texture;
    const key=new THREE.DirectionalLight('#d9eaff',2.2);key.position.set(-3,4,5);
    const rim=new THREE.DirectionalLight('#ac80ff',2.8);rim.position.set(4,-1,-2);
    const edge=new THREE.PointLight('#619fff',6,9,2);edge.position.set(-2,-.5,2);scene.add(key,rim,edge);
    identity=buildIdentity();scene.add(identity.group);
    aura=glow('#7752d8',.28,[7,6,1]);aura.position.set(.35,0,-2);
    innerGlow=glow('#598fff',.2,[3.2,3.2,1]);innerGlow.position.z=-.7;scene.add(aura,innerGlow);
    orbitA=buildOrbit(2.15,-.6,'#9bcfff',.30);orbitB=buildOrbit(2.34,1.4,'#bb92ff',.16);scene.add(orbitA.group,orbitB.group);
    const count=mobile.matches?48:90,positions=new Float32Array(count*3),phases=new Float32Array(count);let seed=137;
    const random=()=>{seed=seed*16807%2147483647;return(seed-1)/2147483646};
    for(let i=0;i<count;i++){const angle=random()*TAU,radius=2+random()*2.3;positions.set([Math.cos(angle)*radius,Math.sin(angle)*radius*.72,-1-random()*3],i*3);phases[i]=random()}
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('phase',new THREE.BufferAttribute(phases,1));
    dust=new THREE.Points(geometry,new THREE.ShaderMaterial({transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,uniforms:{time:{value:0},pixelRatio:{value:1}},
      vertexShader:'attribute float phase;uniform float time;uniform float pixelRatio;varying float light;void main(){vec3 p=position;p.y+=sin(time*.25+phase*6.28)*.07;vec4 mv=modelViewMatrix*vec4(p,1.);light=.2+.6*pow(.5+.5*sin(time*.6+phase*9.),2.);gl_PointSize=(1.4+phase*2.1)*pixelRatio;gl_Position=projectionMatrix*mv;}',
      fragmentShader:'varying float light;void main(){float r=length(gl_PointCoord-.5);gl_FragColor=vec4(.58,.68,1.,(1.-smoothstep(.05,.5,r))*light*.65);}'
    }));scene.add(dust);resize();select(0);start();
  }catch{fail()}
  let queued=false;
  addEventListener('scroll',()=>{if(queued||failed)return;queued=true;requestAnimationFrame(()=>{queued=false;measure();if(!noMotion())start()})},{passive:true});
  addEventListener('resize',()=>{resize();start()},{passive:true});
  chapters.forEach(button=>button.addEventListener('click',()=>{if(failed||noMotion()||compact.matches)return;const header=document.querySelector('.site-header').getBoundingClientRect().height;scrollTo({top:root.getBoundingClientRect().top+scrollY-header+(Number(button.dataset.chapter)/2)*(root.offsetHeight-stage.offsetHeight),behavior:'smooth'})}));
  new MutationObserver(()=>{resize();start()}).observe(document.body,{attributes:true,attributeFilter:['class']});
  motionQuery.addEventListener?.('change',()=>{resize();start()});
  if('IntersectionObserver' in window)new IntersectionObserver(entries=>{active=entries[0].isIntersecting;if(active)start();else{cancelAnimationFrame(frame);frame=0}},{rootMargin:'100px'}).observe(root);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0}else start()});
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();fail()});
  addEventListener('pagehide',()=>{cancelAnimationFrame(frame);frame=0});addEventListener('pageshow',start);
}
