import * as THREE from './vendor/three.module.js';
const $ = id => document.getElementById(id);
let selected=null,busy=false,absorbing=false,paused=matchMedia('(prefers-reduced-motion: reduce)').matches;
let sceneReady=false,renderer,scene,camera,material,burstMaterial;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let tossStart=-100;
const clock=new THREE.Clock();
const params=new URLSearchParams(location.search);
const fixedTime=params.has('time')?Number(params.get('time')):null;
let demoPhase=null;
window.wormhole={ready:false,renderer:'not started',frameCount:0};
const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]').value;
async function request(url,method='GET',body,headers={}){
 const response=await fetch(url,{method,headers:{'X-CSRFToken':csrf(),...headers},body,credentials:'same-origin',redirect:'error'});
 const data=await response.json();
 if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);
 return data;
}
async function loadBuckets(){
 try{const data=await request('/api/buckets');$('bucket').replaceChildren(...data.buckets.map(b=>{const o=document.createElement('option');o.value=b.id;o.textContent=b.name;return o;}));$('status').textContent=data.buckets.length?'':'No upload destinations assigned. Contact your administrator.';}
 catch(e){$('status').textContent=e.message;}
}
function setFile(file){
 if(busy||!file)return;
 selected=file;$('file-name').textContent=file.name;$('file-size').textContent=`${file.size.toLocaleString()} bytes`;
 $('cargo-name').textContent=file.name;$('cargo').hidden=false;$('cargo').classList.remove('flying');
 $('toss').disabled=!$('bucket').value;$('status').textContent='';$('mode').textContent='CARGO READY';
}
$('file').onchange=e=>setFile(e.target.files[0]);
$('bucket').onchange=()=>{$('toss').disabled=!selected||!$('bucket').value;};
$('chamber').ondragover=e=>{e.preventDefault();$('dropzone').classList.add('dragging');};
$('chamber').ondragleave=e=>{if(!$('chamber').contains(e.relatedTarget))$('dropzone').classList.remove('dragging');};
$('chamber').ondrop=e=>{e.preventDefault();$('dropzone').classList.remove('dragging');setFile(e.dataTransfer.files[0]);};
$('motion').onclick=()=>{paused=!paused;updateMotionLabel();};
function updateMotionLabel(){$('motion').textContent=paused?'Resume motion ▷':'Pause motion ‖';}
reduced.addEventListener('change',e=>{paused=e.matches;updateMotionLabel();});updateMotionLabel();
$('toss').onclick=async()=>{
 if(!selected||busy||!$('bucket').value)return;
 busy=true;$('toss').disabled=true;$('file').disabled=true;$('bucket').disabled=true;
 let uid;
 try{
  $('mode').textContent='TRANSFERRING';
  const upload=await request('/api/uploads','POST',JSON.stringify({name:selected.name,size:selected.size,bucket_id:Number($('bucket').value)}),{'Content-Type':'application/json'});uid=upload.id;
  let offset=0;
  while(offset<selected.size){
   const bytes=await selected.slice(offset,offset+upload.chunk_bytes).arrayBuffer();
   const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
   const progress=await request(`/api/uploads/${uid}/chunk?offset=${offset}`,'PUT',bytes,{'Content-Type':'application/octet-stream','X-Chunk-SHA256':digest});
   offset=progress.offset;$('status').textContent=`${offset.toLocaleString()} / ${selected.size.toLocaleString()} bytes received`;
  }
  $('status').textContent='Verifying and committing…';
  const receipt=await request(`/api/uploads/${uid}/finish`,'POST');
  $('mode').textContent='RECEIVED';absorbing=true;tossStart=clock.getElapsedTime();$('cargo').classList.add('flying');
  await new Promise(resolve=>setTimeout(resolve,reduced.matches?30:2900));
  absorbing=false;$('cargo').hidden=true;$('cargo').classList.remove('flying');
  $('mode').textContent='ARCHIVED';$('status').textContent=`Archived ${receipt.name} · ${receipt.size.toLocaleString()} bytes · SHA256 ${receipt.sha256}`;
  selected=null;$('file').value='';$('file-name').textContent='Choose a file ↗';$('file-size').textContent='or drop a file anywhere';
 }catch(e){
  absorbing=false;$('mode').textContent='NOT CONFIRMED';$('status').textContent=`Not confirmed: ${e.message}. Your original file is unchanged.`;
  if(uid){try{await request(`/api/uploads/${uid}`,'DELETE');}catch{/* A lost final response can mean the server committed; never delete a completed archive. */}}
 }finally{busy=false;$('file').disabled=false;$('bucket').disabled=false;$('toss').disabled=!selected||!$('bucket').value;}
};
function resize(){
 if(!renderer||$('portal').hidden)return;
 const {width,height}=$('scene').getBoundingClientRect();
 renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();
 material.uniforms.uPixelRatio.value=renderer.getPixelRatio();
}
function initScene(){
 sceneReady=true;
 try {
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});
 }catch(e){
  $('scene').innerHTML='<pre class="webgl-fallback">(( ( ( @ ) ) ))<br><br>WebGL unavailable<br>File selection remains usable.</pre>';
  window.wormhole.ready=true;window.wormhole.renderer='fallback';return;
 }
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x090f0b,1);
 $('scene').appendChild(renderer.domElement);renderer.domElement.setAttribute('aria-hidden','true');
 scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(43,1,.1,80);camera.position.set(0,0,9.7);camera.lookAt(0,-.2,-1.5);
 // Glyph atlas is drawn locally, with no external font or image requests.
 const atlas=document.createElement('canvas');atlas.width=512;atlas.height=32;
 const ctx=atlas.getContext('2d');ctx.fillStyle='white';ctx.font='bold 25px monospace';ctx.textAlign='center';ctx.textBaseline='middle';
 const glyphs=' .:+*=#%@/01<>-~';
 for(let i=0;i<16;i++)ctx.fillText(glyphs[i]||'+',i*32+16,17);
 const texture=new THREE.CanvasTexture(atlas);texture.minFilter=THREE.LinearFilter;texture.magFilter=THREE.LinearFilter;
 const rings=86,segments=192,count=rings*segments;
 const positions=new Float32Array(count*3),uvs=new Float32Array(count*2),seeds=new Float32Array(count);
 let seed=421;
 const rng=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};
 for(let i=0;i<count;i++){
  const ring=Math.floor(i/segments),seg=i%segments;
  uvs[i*2]=(ring+rng()*.3)/rings;uvs[i*2+1]=(seg+rng()*.22)/segments;seeds[i]=rng();
 }
 const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));
 geometry.setAttribute('flowUV',new THREE.BufferAttribute(uvs,2));geometry.setAttribute('seed',new THREE.BufferAttribute(seeds,1));
 material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,depthTest:false,blending:THREE.AdditiveBlending,
 uniforms:{uTime:{value:0},uToss:{value:0},uAtlas:{value:texture},uPixelRatio:{value:1},uDebug:{value:params.get('debug')==='flow'?1:0}},
 vertexShader:`attribute vec2 flowUV;attribute float seed;uniform float uTime;uniform float uToss;uniform float uPixelRatio;uniform float uDebug;varying float vGlyph;varying vec3 vColor;varying float vAlpha;
 void main(){
 float u=flowUV.x;float v=flowUV.y;float t=uTime;float theta=v*6.2831853+u*4.8+t*.17+uToss*.45;
 float ripple=sin(theta*5.-u*15.+t*.48)*.075+sin(theta*9.+u*20.-t*.27)*.035;
 float radius=.29+3.46*pow(1.-u,1.4);radius+=ripple*(1.-u);
 vec3 p=vec3(cos(theta)*radius,sin(theta)*radius*.71,-u*7.2);
 p.x+=sin(u*4.+t*.17)*.13*u;p.y+=u*.6+.47;
 p.z+=sin(theta*3.+u*9.-t*.4)*.20*(1.-u);
 vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;
 float arm=pow(.5+.5*sin(theta*7.+u*19.-t*.65),5.);
 float band=.5+.5*sin(u*56.+theta*2.-t*.45);
 float brightness=.13+arm*.75+band*.16;
 vec3 deep=vec3(.29,.57,.22),bright=vec3(.72,.96,.38);
 vColor=mix(deep,bright,arm*.8+band*.2);if(uDebug>.5)vColor=vec3(u,1.-u,.4);
 vAlpha=brightness*(.52+.48*seed)*smoothstep(0.,.075,u)*smoothstep(1.,.92,u);
 vGlyph=floor(2.+seed*13.);
 gl_PointSize=clamp((6.5+seed*2.4)*uPixelRatio*9.7/(-mv.z),3.,12.);
 }`,
 fragmentShader:`uniform sampler2D uAtlas;varying float vGlyph;varying vec3 vColor;varying float vAlpha;
 void main(){vec2 uv=vec2((vGlyph+gl_PointCoord.x)/16.,1.-gl_PointCoord.y);float a=texture2D(uAtlas,uv).a;if(a<.08)discard;gl_FragColor=vec4(vColor,a*vAlpha);}`});
 const tunnel=new THREE.Points(geometry,material);scene.add(tunnel);
 // Preallocated glyph cargo: fragments release from the file plane, then spiral down the same throat.
 const fragments=640, fragmentPosition=new Float32Array(fragments*3),fragmentSeed=new Float32Array(fragments);
 for(let i=0;i<fragments;i++){fragmentPosition[i*3]=(rng()-.5)*1.25;fragmentPosition[i*3+1]=(rng()-.5)*.85;fragmentSeed[i]=rng();}
 const fragmentGeometry=new THREE.BufferGeometry();fragmentGeometry.setAttribute('position',new THREE.BufferAttribute(fragmentPosition,3));fragmentGeometry.setAttribute('seed',new THREE.BufferAttribute(fragmentSeed,1));
 burstMaterial=new THREE.ShaderMaterial({transparent:true,depthWrite:false,depthTest:false,blending:THREE.AdditiveBlending,
 uniforms:{uProgress:{value:0},uAtlas:{value:texture}},
 vertexShader:`attribute float seed;uniform float uProgress;varying float vGlyph;varying float vAlpha;varying vec3 vColor;
 void main(){
 float release=.12+seed*.28;float p=clamp((uProgress-release)/(1.-release),0.,1.);
 vec3 start=vec3(-2.15+position.x,-.7+position.y,0.);
 float a=p*8.+seed*1.8;float r=length(start.xy)*pow(1.-p,1.7);
 float base=atan(start.y,start.x);vec3 loc=vec3(cos(base+a)*r,sin(base+a)*r*.7,-p*6.6);
 loc.y+=p*.8;vec4 mv=modelViewMatrix*vec4(loc,1.);gl_Position=projectionMatrix*mv;
 gl_PointSize=(7.+seed*5.)*(1.-p*.5);vGlyph=floor(2.+seed*13.);
 vColor=mix(vec3(.85,.91,.65),vec3(.59,.98,.28),p);
 vAlpha=smoothstep(release,release+.08,uProgress)*smoothstep(1.,.75,p)*.85;
 }`,fragmentShader:material.fragmentShader});
 const fragmentsMesh=new THREE.Points(fragmentGeometry,burstMaterial);scene.add(fragmentsMesh);
 // Fixed-seed sparse stars share the glyph visual vocabulary, not a photographic skybox.
 const starCount=160,sp=new Float32Array(starCount*3);
 for(let i=0;i<starCount;i++){sp[i*3]=(rng()-.5)*24;sp[i*3+1]=(rng()-.5)*16;sp[i*3+2]=-4-rng()*10;}
 const stars=new THREE.BufferGeometry();stars.setAttribute('position',new THREE.BufferAttribute(sp,3));
 scene.add(new THREE.Points(stars,new THREE.PointsMaterial({color:0x73855a,size:.018,transparent:true,opacity:.5,depthWrite:false})));
 let motionTime=0,last=0;
 function animate(){
  requestAnimationFrame(animate);const now=clock.getElapsedTime(),dt=Math.min(now-last,.05);last=now;
  if(!paused)motionTime+=dt;
  const time=fixedTime??motionTime;material.uniforms.uTime.value=time;
  const progress=demoPhase??Math.max(0,Math.min(1,(now-tossStart)/2.8));
  material.uniforms.uToss.value=absorbing||demoPhase!==null?Math.sin(progress*Math.PI):0;
  burstMaterial.uniforms.uProgress.value=(absorbing||demoPhase!==null)&&!reduced.matches?progress:0;
  if(!$('portal').hidden){renderer.render(scene,camera);window.wormhole.frameCount++;}
  window.wormhole.ready=true;window.wormhole.renderer='threejs-webgl';
 }
 new ResizeObserver(resize).observe($('scene'));resize();animate();
}
initScene();
loadBuckets();
