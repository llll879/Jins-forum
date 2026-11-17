const KV=(()=>{
'use strict';
const CH='0123456789abcdefghijklmnopqrstuv',N=48,MIN_MS=700,MAX_MS=600000,SPEEDS=[1,1.5,2];
let cfg={heard(){},toast(){}};
const A=new Audio();A.preload='none';
let cur=null,raf=0,speed=1;
try{speed=parseFloat(localStorage.getItem('kv_speed'))||1}catch(e){}
if(SPEEDS.indexOf(speed)<0)speed=1;
const svg=(b,w)=>`<svg viewBox="0 0 24 24" width="${w||22}" height="${w||22}" aria-hidden="true">${b}</svg>`;
const st='fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"';
const IC_PLAY=svg('<path fill="currentColor" d="M8.2 5.3v13.4a1 1 0 0 0 1.5.86l10.6-6.7a1 1 0 0 0 0-1.72L9.7 4.44a1 1 0 0 0-1.5.86z"/>');
const IC_PAUSE=svg('<rect x="6" y="5" width="4.2" height="14" rx="1.4" fill="currentColor"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.4" fill="currentColor"/>');
const IC_MIC=svg(`<g ${st}><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/></g>`);
const IC_SEND=svg(`<g ${st} stroke-width="2.3"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></g>`);
const IC_TRASH=svg(`<g ${st}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 1.8h6a2 2 0 0 0 2-1.8l1-12M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/></g>`,20);
const IC_CAM=svg(`<g ${st}><rect x="3" y="6.5" width="13" height="11" rx="3"/><path d="m16 11 5-3v8l-5-3z"/></g>`);
const IC_LOCK=svg(`<g ${st}><rect x="5" y="11" width="14" height="9.5" rx="2.4"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></g>`,17);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtT=ms=>{const s=Math.max(0,Math.round(ms/1000));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
const spd=x=>(x===1?'1':String(x))+'×';
const vib=n=>{try{navigator.vibrate&&navigator.vibrate(n)}catch(e){}};

/* ---------- волна ---------- */
const maskCache=new Map();
function decode(w){const a=[];for(const c of String(w||'')){const v=CH.indexOf(c);a.push(v<0?4:v)}return a.length>=4?a:new Array(N).fill(5)}
function maskUrl(w){let m=maskCache.get(w);if(m)return m;const a=decode(w),n=a.length;let r='';
  a.forEach((v,i)=>{const h=Math.max(3,Math.round(3+v/31*27));r+=`<rect x="${i*3}" y="${(32-h)/2}" width="2" height="${h}" rx="1"/>`});
  m='url("data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n*3-1} 32" preserveAspectRatio="none">${r}</svg>`)+'")';
  if(maskCache.size>300)maskCache.clear();maskCache.set(w,m);return m}
function waveStr(levels){ // levels: 0..1, любое число значений -> строка из N символов
  const n=levels.length;if(!n)return CH[3].repeat(N);const out=[];
  for(let i=0;i<N;i++){const a=i*n/N,b=Math.max(a+1,(i+1)*n/N);let s=0,c=0,mx=0;
    for(let j=Math.floor(a);j<Math.min(n,Math.ceil(b));j++){s+=levels[j];c++;mx=Math.max(mx,levels[j])}
    out.push(c?(s/c)*.55+mx*.45:levels[Math.min(n-1,Math.floor(a))])}
  const pk=Math.max.apply(null,out.concat([.06]));
  return out.map(v=>CH[Math.max(1,Math.min(31,Math.round(Math.pow(v/pk,.7)*31)))]).join('')}

/* ---------- разметка сообщения ---------- */
function inner(v){return `<button class="vp" type="button" aria-label="Воспроизвести">${IC_PLAY}</button><div class="vc"><div class="vw" data-w="${esc(v.wave||'')}"><i class="vwv"></i></div><div class="vi"><span class="vt">${fmtT(v.dur)}</span><i class="vdot"></i><button class="vs" type="button" hidden>${spd(speed)}</button>${v.meta?`<small>${v.meta}</small>`:''}</div></div>`}
function bubble(cls,v){return `<div class="${esc(cls)} vm" data-id="${esc(v.id)}" data-url="${esc(v.url||'')}" data-dur="${v.dur|0}" data-heard="${v.heard?1:0}" data-mine="${v.mine?1:0}"${v.pending?' data-pending="1"':''}>${inner(v)}</div>`}
const setP=(el,p)=>{const w=el.querySelector('.vw');if(w)w.style.setProperty('--p',p)};
const durOf=el=>Math.max(1,parseInt(el.dataset.dur,10)||1);

function paint(el,playing){
  if(!el)return;const b=el.querySelector('.vp');
  if(el._pl!==playing){el._pl=playing;b.innerHTML=playing?IC_PAUSE:IC_PLAY;b.setAttribute('aria-label',playing?'Пауза':'Воспроизвести')}
  el.classList.toggle('playing',playing);
  const s=el.querySelector('.vs');if(s){s.hidden=!(cur&&cur.el===el);s.textContent=spd(speed)}}
function bind(root){
  root.querySelectorAll('.vm').forEach(el=>{
    const w=el.querySelector('.vw');if(w&&!w.dataset.m){w.dataset.m=1;w.style.setProperty('--m',maskUrl(w.dataset.w))}
    if(cur&&cur.id===el.dataset.id){cur.el=el;el._pl=null;paint(el,!A.paused);const t=A.currentTime*1000;setP(el,Math.min(1,t/cur.dur));el.querySelector('.vt').textContent=fmtT(t)}});
  root.querySelectorAll('.kn').forEach(el=>{
    if(curN&&curN.id===el.dataset.id){const nv=el.querySelector('.kn-v');if(nv&&nv!==curN.v)nv.replaceWith(curN.v); // играющее видео переезжает в новый пузырь (в том же такте — не прерывается)
      curN.el=el;el.classList.toggle('playing',!curN.v.paused);const t=curN.v.currentTime*1000;nP(el,Math.min(1,t/curN.dur));el.querySelector('.kn-t').textContent=fmtT(t)}});
  listen(root)}

/* ---------- плеер ---------- */
function tick(){raf=0;if(!cur||A.paused)return;const t=A.currentTime*1000;setP(cur.el,Math.min(1,t/cur.dur));cur.el.querySelector('.vt').textContent=fmtT(t);raf=requestAnimationFrame(tick)}
function reset(el){if(!el)return;paint(el,false);setP(el,0);const t=el.querySelector('.vt');if(t)t.textContent=fmtT(durOf(el));const s=el.querySelector('.vs');if(s)s.hidden=true}
function stop(){if(!cur)return;const c=cur;cur=null;try{A.pause()}catch(e){}reset(c.el)}
function nextUnheard(el){const all=Array.prototype.slice.call(document.querySelectorAll('.vm')),i=all.indexOf(el);for(let k=i+1;k<all.length;k++){const n=all[k];if(n.dataset.mine!=='1'&&n.dataset.heard==='0'&&n.dataset.url)return n}return null}
function begin(el,r){
  nStop();
  if(cur&&cur.el!==el)reset(cur.el);
  cur={id:el.dataset.id,el,dur:durOf(el)};
  const seek=(r||0)*cur.dur/1000;
  const fail=()=>{cfg.toast('Не удалось воспроизвести запись',1);if(cur&&cur.el===el){paint(el,false);cur=null}};
  const go=u=>{if(!cur||cur.el!==el)return;A.src=u;A.defaultPlaybackRate=speed;
    if(seek>0.05)A.addEventListener('loadedmetadata',()=>{try{A.currentTime=seek}catch(e){}},{once:true});
    const p=A.play();if(p&&p.catch)p.catch(fail)};
  if(cfg.res)cfg.res(el.dataset.url).then(go).catch(fail);else go(el.dataset.url); // cfg.res: форум отдаёт blob, адрес сервера не светится
  markHeard(el)}
function markHeard(el){if(el.dataset.mine!=='1'&&el.dataset.heard==='0'){el.dataset.heard='1';try{cfg.heard(el.dataset.id)}catch(e){}}}
function toggle(el){
  if(!el||el.dataset.pending||!el.dataset.url)return;
  if(cur&&cur.id===el.dataset.id){if(A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}else A.pause();return}
  begin(el,0)}
A.addEventListener('play',()=>{A.playbackRate=speed;if(cur){paint(cur.el,true);cancelAnimationFrame(raf);raf=requestAnimationFrame(tick)}});
A.addEventListener('pause',()=>{if(cur&&!A.ended)paint(cur.el,false)});
A.addEventListener('ended',()=>{const c=cur;if(!c)return;cur=null;reset(c.el);const nx=nextUnheard(c.el);if(nx)begin(nx,0)});
A.addEventListener('error',()=>{if(cur&&A.src){cfg.toast('Не удалось воспроизвести запись',1);paint(cur.el,false)}});

function listen(root){
  if(root._kv)return;root._kv=1;
  root.addEventListener('click',e=>{
    const sp=e.target.closest('.vs');
    if(sp){e.stopPropagation();speed=SPEEDS[(SPEEDS.indexOf(speed)+1)%SPEEDS.length];try{localStorage.setItem('kv_speed',speed)}catch(x){}
      A.playbackRate=speed;A.defaultPlaybackRate=speed;sp.textContent=spd(speed);return}
    const kc=e.target.closest('.kn-c');if(kc){e.stopPropagation();nToggle(kc.closest('.kn'));return}
    const b=e.target.closest('.vp');if(b){e.stopPropagation();toggle(b.closest('.vm'))}});
  root.addEventListener('pointerdown',e=>{
    const w=e.target.closest('.vw');if(!w)return;const el=w.closest('.vm');if(!el||el.dataset.pending||!el.dataset.url)return;
    const rc=w.getBoundingClientRect(),pid=e.pointerId,rt=ev=>Math.min(1,Math.max(0,(ev.clientX-rc.left)/Math.max(1,rc.width)));
    try{w.setPointerCapture(pid)}catch(x){}
    const isCur=cur&&cur.id===el.dataset.id;let r=rt(e);setP(el,r);
    const tx=el.querySelector('.vt');tx.textContent=fmtT(r*durOf(el));
    const mv=ev=>{if(ev.pointerId!==pid)return;r=rt(ev);setP(el,r);tx.textContent=fmtT(r*durOf(el))};
    const done=(ev,ok)=>{w.removeEventListener('pointermove',mv);w.removeEventListener('pointerup',up);w.removeEventListener('pointercancel',cn);
      if(!ok){if(isCur){const t=A.currentTime*1000;setP(el,Math.min(1,t/cur.dur));tx.textContent=fmtT(t)}else reset(el);return}
      if(isCur){try{A.currentTime=r*cur.dur/1000}catch(x){}if(A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}}else begin(el,r)};
    const up=ev=>done(ev,true),cn=ev=>done(ev,false);
    w.addEventListener('pointermove',mv);w.addEventListener('pointerup',up);w.addEventListener('pointercancel',cn)})}

/* ---------- кружки: разметка и плеер ---------- */
function knInner(v){return `<div class="kn-c"><video class="kn-v" playsinline webkit-playsinline muted preload="metadata" disablepictureinpicture${v.url?(cfg.res?` data-bsrc="${esc(v.url)}"`:` src="${esc(v.url)}#t=0.1"`):''}${v.poster?` poster="${esc(v.poster)}"`:''}></video><svg class="kn-r" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46"/></svg><span class="kn-t">${fmtT(v.dur)}</span><span class="kn-pl">${IC_PLAY}</span>${v.meta?`<span class="kn-tm">${v.meta}</span>`:''}</div>`}
function knBubble(cls,v){return `<div class="${esc(cls)} kn" data-id="${esc(v.id)}" data-url="${esc(v.url||'')}" data-dur="${v.dur|0}" data-heard="${v.heard?1:0}" data-mine="${v.mine?1:0}"${v.pending?' data-pending="1"':''}>${knInner(v)}</div>`}
let curN=null,rafN=0;
const nP=(el,p)=>{const c=el.querySelector('.kn-c');if(c)c.style.setProperty('--p',p)};
function nTick(){rafN=0;if(!curN||curN.v.paused)return;const t=curN.v.currentTime*1000;nP(curN.el,Math.min(1,t/curN.dur));curN.el.querySelector('.kn-t').textContent=fmtT(t);rafN=requestAnimationFrame(nTick)}
function nReset(el){if(!el)return;el.classList.remove('playing');nP(el,0);const t=el.querySelector('.kn-t');if(t)t.textContent=fmtT(durOf(el))}
function nStop(){if(!curN)return;const c=curN;curN=null;try{c.v.pause();c.v.muted=true;c.v.currentTime=0.1}catch(e){}nReset(c.el)}
function stopAll(){stop();nStop()}
function nToggle(el){
  if(!el||el.dataset.pending||!el.dataset.url)return;
  const v=el.querySelector('.kn-v');if(!v)return;
  if(cfg.res&&!v.getAttribute('src')){cfg.res(el.dataset.url).then(u=>{v.src=u;nToggle(el)}).catch(()=>cfg.toast('Не удалось воспроизвести видео',1));return}
  if(curN&&curN.el===el){if(v.paused){const p=v.play();if(p&&p.catch)p.catch(()=>{})}else v.pause();return}
  stop();nStop();
  curN={id:el.dataset.id,el,v,dur:durOf(el)};
  if(!v._kn){v._kn=1;
    v.addEventListener('play',()=>{if(curN&&curN.v===v){curN.el.classList.add('playing');cancelAnimationFrame(rafN);rafN=requestAnimationFrame(nTick)}});
    v.addEventListener('pause',()=>{if(curN&&curN.v===v&&!v.ended)curN.el.classList.remove('playing')});
    v.addEventListener('ended',()=>{if(curN&&curN.v===v){const c=curN;curN=null;v.muted=true;try{v.currentTime=0.1}catch(e){}nReset(c.el)}});
    v.addEventListener('error',()=>{if(curN&&curN.v===v){cfg.toast('Не удалось воспроизвести видео',1);nStop()}})}
  v.muted=false;try{if(v.ended||(v.duration&&v.currentTime>v.duration-0.2))v.currentTime=0}catch(e){}
  const p=v.play();if(p&&p.catch)p.catch(()=>{cfg.toast('Не удалось воспроизвести видео',1);nStop()});
  markHeard(el)}

/* ---------- запись ---------- */
function pickMime(){
  if(typeof MediaRecorder==='undefined'||!MediaRecorder.isTypeSupported)return '';
  const l=['audio/mp4;codecs=mp4a.40.2','audio/mp4','audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'];
  for(const m of l){try{if(MediaRecorder.isTypeSupported(m))return m}catch(e){}}return ''}
function pickVMime(){
  if(typeof MediaRecorder==='undefined'||!MediaRecorder.isTypeSupported)return '';
  const l=['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/mp4','video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm'];
  for(const m of l){try{if(MediaRecorder.isTypeSupported(m))return m}catch(e){}}return ''}
const extOfV=m=>/mp4/.test(m)?'mp4':'webm';
const MAX_V=60000,HOLD_MS=220;
const extOf=m=>/mp4|m4a|aac/.test(m)?'m4a':/ogg/.test(m)?'ogg':'webm';

function attach(o){
  const form=o.form,ta=o.ta,sb=o.sendBtn,log=o.log;
  if(!form||!ta||!sb||form._kvOn)return;
  form._kvOn=1;form.classList.add('kv-on');sb.classList.add('kv-sb');
  if(getComputedStyle(form).position==='static')form.style.position='relative';
  const mic=sb.cloneNode(false);['id','disabled','data-busy','title'].forEach(a=>mic.removeAttribute(a));
  let mode='voice',recMode='voice';try{if(localStorage.getItem('kv_mode')==='video')mode='video'}catch(e){}
  const modeIcon=()=>mode==='video'?IC_CAM:IC_MIC,modeLbl=()=>mode==='video'?'Записать видеосообщение (кружок)':'Записать голосовое сообщение';
  mic.type='button';mic.classList.add('kv-mic');mic.classList.remove('kv-sb');mic.innerHTML=modeIcon();mic.dataset.mode=mode;mic.setAttribute('aria-label',modeLbl());mic.title=mode==='video'?'Удерживайте — кружок, нажмите — голосовое':'Удерживайте — голосовое, нажмите — кружок';
  sb.after(mic);
  // первые разы показываем подсказку сами, потом — по тапу
  try{const n=+localStorage.getItem('kv_tip')||0;if(n<3){localStorage.setItem('kv_tip',String(n+1));setTimeout(()=>{if(form.isConnected)showTip(5200)},900)}}catch(e){}
  const ov=document.createElement('div');ov.className='kv-rec';ov.hidden=true;
  ov.innerHTML=`<button class="kv-x" type="button" aria-label="Удалить запись">${IC_TRASH}</button><i class="kv-dot"></i><b class="kv-t">0:00,0</b><canvas class="kv-cv"></canvas><span class="kv-hint">‹ Влево — отмена</span>`;
  const lock=document.createElement('div');lock.className='kv-lock';lock.hidden=true;lock.innerHTML=IC_LOCK;
  const circ=document.createElement('div');circ.className='kv-circ';circ.hidden=true;
  circ.innerHTML='<video muted playsinline></video><svg viewBox="0 0 100 100"><circle class="bg" cx="50" cy="50" r="48"/><circle class="fg" cx="50" cy="50" r="48"/></svg>';
  const tip=document.createElement('div');tip.className='kv-tip';tip.hidden=true;tip.setAttribute('role','status');
  form.appendChild(ov);form.appendChild(lock);form.appendChild(circ);form.appendChild(tip);
  let tipT=0;
  /* подсказка у кнопки, как в Telegram: что делает тап и что — удержание */
  function tipText(){return mode==='video'
    ?'<b>Удерживайте — запись кружка</b><span>Нажмите — переключить на голосовое</span>'
    :'<b>Удерживайте — голосовое</b><span>Нажмите — переключить на кружок</span>'}
  function showTip(ms){
    if(state!=='idle'||form.classList.contains('kv-txt'))return;
    const f=form.getBoundingClientRect(),m=mic.getBoundingClientRect();if(!m.width)return;
    tip.innerHTML=tipText();tip.hidden=false;tip.classList.remove('in');
    const w=Math.min(tip.offsetWidth||230,f.width-16);
    tip.style.right=(f.right-m.right)+'px';
    // стрелка — ровно над центром кнопки
    tip.style.setProperty('--ax',Math.max(14,Math.min(w-14,m.width/2))+'px');
    void tip.offsetWidth;tip.classList.add('in');clearTimeout(tipT);tipT=setTimeout(hideTip,ms||3800)}
  function hideTip(){clearTimeout(tipT);tip.classList.remove('in');tip.hidden=true}
  const cvid=circ.querySelector('video'),ringFg=circ.querySelector('.fg');
  const $x=ov.querySelector('.kv-x'),$t=ov.querySelector('.kv-t'),cv=ov.querySelector('.kv-cv'),hint=ov.querySelector('.kv-hint');

  const refresh=()=>{form.classList.toggle('kv-txt',!!ta.value.trim()&&state==='idle')};
  let state='idle',holding=false,gesture=false,holdT=0,pid=0,downAt=0,sx=0,sy=0,ignoreUntil=0,t0=0;
  let stream=null,rec=null,chunks=[],ac=null,an=null,buf=null,levels=[],live=[],timer=0,tping=0,mime='',gen=0;
  ta.addEventListener('input',refresh);refresh();
  const poll=setInterval(()=>{if(!form.isConnected){clearInterval(poll);if(state!=='idle')abort();return}refresh()},250);

  const accent=()=>(getComputedStyle(form).getPropertyValue('--acc').trim()||'#9d92e6');
  function place(){
    const f=form.getBoundingClientRect(),t=ta.getBoundingClientRect(),m=mic.getBoundingClientRect();let l=t.left;
    for(const c of form.children){if(c===ov||c===lock||c===mic||c===circ)continue;const r=c.getBoundingClientRect();if(r.width&&r.right<=t.left+1&&getComputedStyle(c).display!=='none')l=Math.min(l,r.left)}
    ov.style.left=(l-f.left)+'px';ov.style.top=(t.top-f.top)+'px';ov.style.width=Math.max(120,t.right-l)+'px';ov.style.height=t.height+'px';
    lock.style.right=(f.right-m.right+m.width/2-19)+'px'}
  function sizeCv(){const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;cv.width=Math.max(1,Math.round(r.width*d));cv.height=Math.max(1,Math.round(r.height*d))}
  function draw(){
    const c=cv.getContext('2d'),W=cv.width,H=cv.height,d=window.devicePixelRatio||1,bw=3*d,gap=2.4*d,step=bw+gap,n=Math.floor(W/step);
    c.clearRect(0,0,W,H);c.fillStyle=accent();
    for(let i=0;i<n;i++){const v=live[live.length-1-i];if(v==null)break;const h=Math.max(3*d,v*H*.92),x=W-(i+1)*step+gap,y=(H-h)/2;
      c.globalAlpha=Math.max(.25,1-i/n*.75);c.beginPath();if(c.roundRect)c.roundRect(x,y,bw,h,bw/2);else c.rect(x,y,bw,h);c.fill()}
    c.globalAlpha=1}
  function tickRec(){
    if(!an)return;an.getByteTimeDomainData(buf);let s=0;for(let i=0;i<buf.length;i++){const v=(buf[i]-128)/128;s+=v*v}
    const rms=Math.sqrt(s/buf.length);levels.push(rms);live.push(Math.min(1,Math.pow(rms*5,.72)));
    const ms=performance.now()-t0;$t.textContent=Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0')+','+Math.floor(ms%1000/100);
    draw();
    if(recMode==='video'){ringFg.style.strokeDashoffset=String(301.6*(1-Math.min(1,ms/MAX_V)));if(ms>=MAX_V){cfg.toast('Достигнут лимит — 1 минута');finish(true)}}
    else if(ms>=MAX_MS){cfg.toast('Достигнут лимит записи — 10 минут');finish(true)}}
  function cleanup(){
    clearInterval(timer);clearInterval(tping);timer=tping=0;
    try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}
    try{ac&&ac.close()}catch(e){}stream=ac=an=null;try{cvid.srcObject=null}catch(e){}}
  async function start(){
    const my=++gen;
    recMode=mode;const vid=recMode==='video',aud={echoCancellation:true,noiseSuppression:true,autoGainControl:true};
    stream=await navigator.mediaDevices.getUserMedia(vid?{audio:aud,video:{facingMode:'user',width:{ideal:480},height:{ideal:480},aspectRatio:{ideal:1},frameRate:{ideal:30}}}:{audio:aud});
    if(my!==gen){cleanup();return false}
    mime=vid?pickVMime():pickMime();
    rec=mime?new MediaRecorder(stream,vid?{mimeType:mime,videoBitsPerSecond:700000,audioBitsPerSecond:48000}:{mimeType:mime,audioBitsPerSecond:32000}):new MediaRecorder(stream);
    if(vid){cvid.srcObject=stream;const pp=cvid.play();if(pp&&pp.catch)pp.catch(()=>{})}
    chunks=[];levels=[];live=[];rec.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
    const tr=stream.getAudioTracks()[0];if(tr)tr.onended=()=>{if(state!=='idle'){cfg.toast('Запись прервана',1);abort()}};
    const AC=window.AudioContext||window.webkitAudioContext;
    if(AC){ac=new AC();if(ac.state==='suspended')ac.resume().catch(()=>{});const src=ac.createMediaStreamSource(stream);an=ac.createAnalyser();an.fftSize=512;src.connect(an);buf=new Uint8Array(an.fftSize)}
    rec.start(250);t0=performance.now();timer=setInterval(tickRec,60);
    if(o.typing){o.typing(recMode);tping=setInterval(()=>{try{o.typing(recMode)}catch(e){}},2500)}
    return true}
  function stopRec(){return new Promise(res=>{
    if(!rec||rec.state==='inactive'){res(null);return}
    const dur=performance.now()-t0,m=rec.mimeType||mime||(recMode==='video'?'video/webm':'audio/webm'),kind=recMode;
    rec.onstop=()=>res({kind,blob:new Blob(chunks,{type:m}),dur:Math.round(dur),mime:m,wave:kind==='video'?'':waveStr(levels),ext:kind==='video'?extOfV(m):extOf(m)});
    try{rec.stop()}catch(e){res(null)}})}
  function ui(on){
    if(on){place();ov.hidden=false;lock.hidden=false;if(recMode==='video'){ringFg.style.strokeDashoffset='301.6';circ.hidden=false}sizeCv();form.classList.add('kv-recording');requestAnimationFrame(()=>ov.classList.add('in'))}
    else{circ.hidden=true;ov.classList.remove('in','locked');ov.hidden=true;lock.hidden=true;lock.style.transform='';ov.style.transform='';form.classList.remove('kv-recording','kv-locked');mic.classList.remove('hold');mic.innerHTML=modeIcon();mic.style.transform='';refresh()}}
  function setLocked(){
    state='locked';holding=false;vib(14);lock.hidden=true;ov.classList.add('locked');form.classList.add('kv-locked');
    mic.classList.remove('hold');mic.innerHTML=IC_SEND;mic.style.transform='';mic.setAttribute('aria-label','Отправить');ov.style.transform=''}
  function abort(){clearTimeout(holdT);gen++;state='idle';holding=false;try{rec&&rec.state!=='inactive'&&(rec.onstop=null,rec.stop())}catch(e){}rec=null;cleanup();ui(false)}
  function snap(){try{const w=cvid.videoWidth,h=cvid.videoHeight;if(!w)return '';const q=Math.min(w,h),c=document.createElement('canvas');c.width=c.height=240;c.getContext('2d').drawImage(cvid,(w-q)/2,(h-q)/2,q,q,0,0,240,240);return c.toDataURL('image/jpeg',.7)}catch(e){return ''}}
  async function finish(send){
    if(state==='idle')return;state='idle';holding=false;
    const poster=recMode==='video'?snap():'';ui(false);
    const r=await stopRec();rec=null;cleanup();gen++;
    if(!send||!r)return;
    const vidK=r.kind==='video';
    if(r.dur<(vidK?1000:MIN_MS)||!r.blob.size){cfg.toast('Слишком короткая запись');return}
    if(r.blob.size>7.6*1024*1024){cfg.toast('Видео получилось слишком большим — запишите короче',1);return}
    let tmp=null;
    if(log){const d=document.createElement('div'),meta=o.nowMeta?o.nowMeta():'';
      d.innerHTML=vidK?knBubble(o.clsN||'me',{id:'tmp'+Date.now(),url:'',dur:r.dur,poster,mine:true,heard:true,pending:true,meta})
        :bubble(o.cls||'msg me',{id:'tmp'+Date.now(),url:'',dur:r.dur,wave:r.wave,mine:true,heard:true,pending:true,meta});
      tmp=d.firstChild;log.appendChild(tmp);bind(log);log.scrollTop=log.scrollHeight}
    try{await o.send(r)}
    catch(e){if(tmp)tmp.remove();cfg.toast((e&&e.message)||'Не удалось отправить запись',1)}}

  mic.addEventListener('contextmenu',e=>e.preventDefault());
  function toggleMode(){
    mode=mode==='video'?'voice':'video';try{localStorage.setItem('kv_mode',mode)}catch(e){}
    mic.dataset.mode=mode;mic.innerHTML=modeIcon();mic.setAttribute('aria-label',modeLbl());mic.classList.remove('kv-swap');void mic.offsetWidth;mic.classList.add('kv-swap');vib(8);
    mic.title=mode==='video'?'Удерживайте — кружок, нажмите — голосовое':'Удерживайте — голосовое, нажмите — кружок';showTip(3800)}
  mic.addEventListener('pointerdown',e=>{
    if(state!=='idle')return;
    e.preventDefault();state='pending';holding=true;gesture=true;pid=e.pointerId;downAt=performance.now();sx=e.clientX;sy=e.clientY;
    try{mic.setPointerCapture(pid)}catch(x){}
    holdT=setTimeout(()=>{if(state==='pending')begin()},HOLD_MS)});
  async function begin(){
    if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||typeof MediaRecorder==='undefined'){state='idle';holding=false;cfg.toast('Запись здесь недоступна. Откройте в браузере или в Telegram',1);return}
    state='starting';hideTip();stopAll();
    {
    try{
      const ok=await start();if(!ok)return;
      if(state!=='starting'){return}
      try{if(holding&&!mic.hasPointerCapture(pid))holding=false}catch(x){}
      ui(true);vib(10);
      if(holding){state='rec';mic.classList.add('hold');mic.style.transform='scale(1.35)'}else setLocked();
    }catch(err){
      state='idle';holding=false;cleanup();ui(false);
      const n=err&&err.name;
      const vd=mode==='video';
      cfg.toast(n==='NotAllowedError'||n==='SecurityError'?(vd?'Нет доступа к камере или микрофону. Разрешите их в настройках':'Нет доступа к микрофону. Разрешите его в настройках'):n==='NotFoundError'||n==='OverconstrainedError'?(vd?'Камера или микрофон не найдены':'Микрофон не найден'):(vd?'Не удалось включить камеру':'Не удалось включить микрофон'),1)}
    }}
  mic.addEventListener('pointermove',e=>{
    if(state!=='rec'||e.pointerId!==pid)return;
    const dx=e.clientX-sx,dy=e.clientY-sy;
    if(dy<-72){setLocked();return}
    if(dx<-110){vib(18);abort();return}
    const l=Math.max(0,Math.min(1,-dx/110));ov.style.transform=`translateX(${Math.min(0,dx)*.35}px)`;hint.style.opacity=String(1-l*.85);hint.classList.toggle('bad',l>.45);
    lock.style.transform=`translateY(${Math.max(dy,-80)*.7}px) scale(${1+Math.min(1,-dy/72)*.25})`});
  const release=cancelled=>{
    if(!holding)return; // отпускание не от жеста записи (например, тап по «отправить» в закреплённом режиме)
    holding=false;
    if(state==='starting'){ // отпустили сразу после старта — это не запись; а если ждали разрешения — закрепляем (см. start)
      if(performance.now()-downAt<650){gen++;state='idle';cleanup();ui(false)}
      return}
    if(state!=='rec')return;
    if(cancelled){abort();return}
    finish(true)};
  // click, который браузер шлёт после жеста записи, игнорируем (иначе закреплённая запись сразу отправится)
  mic.addEventListener('pointerup',e=>{if(e.pointerId===pid&&gesture){gesture=false;ignoreUntil=performance.now()+450;
    if(state==='pending'){clearTimeout(holdT);holding=false;state='idle';toggleMode();return} // короткий тап — микрофон ⇄ камера
    release(false)}});
  mic.addEventListener('pointercancel',e=>{if(e.pointerId===pid&&gesture){gesture=false;ignoreUntil=performance.now()+450;
    if(state==='pending'){clearTimeout(holdT);holding=false;state='idle';return}
    release(true)}});
  mic.addEventListener('click',e=>{
    if(performance.now()<ignoreUntil){e.preventDefault();return}
    if(state==='locked'){e.preventDefault();finish(true)}});
  $x.addEventListener('click',()=>{if(state==='locked'||state==='rec'){vib(10);abort()}});
  window.addEventListener('resize',()=>{if(state!=='idle'){place();sizeCv()}});
}
function init(c){cfg=Object.assign(cfg,c||{})}
return{init,attach,bind,bubble,inner,knBubble,knInner,stop:stopAll,waveStr}
})();
