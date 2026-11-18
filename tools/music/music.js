/* ===== EXG Music — раздел «как Яндекс Музыка» =====
   Основной источник — Яндекс Музыка (токен YANDEX_MUSIC_TOKEN на сервере, id треков вида «y123», звук идёт редиректом через /music/stream);
   запасной — Jamendo (JAMENDO_CLIENT_ID, независимые исполнители, CC; звук играет напрямую, поле u). Если Яндекс не настроен/недоступен — всё на Jamendo.
   Списки приходят через сервер форума (/forum/api/music/get, для Яндекса src=ym).
   Основной упор — русскоязычные треки (lang=ru); зарубежное вынесено в отдельную подборку.
   Любимое и история хранятся на устройстве (kf_mu_likes, kf_mu_hist). */
const MU=(()=>{
/* жанры = теги Jamendo */
const GENRES=[['','Всё'],['hiphop','Хип-хоп'],['pop','Поп'],['rock','Рок'],['electronic','Электроника'],['indie','Инди'],['rnb','R&B'],['lounge','Лаунж'],['jazz','Джаз'],['folk','Фолк'],['metal','Метал'],['ambient','Эмбиент']];
const MI={
 note:I('<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>'),
 play:'<svg class="i" viewBox="0 0 24 24"><path fill="currentColor" stroke="none" d="M8.2 5.3v13.4a1 1 0 0 0 1.5.86l10.6-6.7a1 1 0 0 0 0-1.72L9.7 4.44a1 1 0 0 0-1.5.86z"/></svg>',
 pause:'<svg class="i" viewBox="0 0 24 24"><rect x="6" y="5" width="4.2" height="14" rx="1.4" fill="currentColor" stroke="none"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.4" fill="currentColor" stroke="none"/></svg>',
 next:I('<path d="M6 5.5v13l9-6.5z" style="fill:currentColor"/><path d="M18.5 5v14"/>'),
 prev:I('<path d="M18 5.5v13l-9-6.5z" style="fill:currentColor"/><path d="M5.5 5v14"/>'),
 shuf:I('<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>'),
 rep:I('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'),
 rep1:I('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10l1-.7V14"/>'),
 wave:I('<path d="M3 12h2M7 8v8M11 4v16M15 8v8M19 10v4"/>')
};
IC.music=MI.note;
const A=new Audio();A.preload='auto';
let Q=[],qi=-1,shuf=0,rep=0,wave=0,tryFb=0,fails=0,sessionSet=0;
const st={tab:'home',genre:'',q:'',artist:null,ahist:[]};
let redraw=null;
const cache=new Map();
const jget=(k,d)=>{try{const v=ls.get(k);return v?JSON.parse(v):d}catch(e){return d}};
/* треки старой библиотеки (нецифровые id без файла) больше не играют — не тащим их из сохранённого */
const okT=x=>x&&(x.src||/^y?\d+$/.test(String(x.id)));
let likes=jget('mu_likes',[]).filter(okT),hist=jget('mu_hist',[]).filter(okT);
const isLiked=id=>likes.some(x=>x.id===id);
const cur=()=>Q[qi]||null;
const fmt=s=>{s=Math.max(0,Math.round(s||0));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
const hue=id=>{let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))%360;return h};

/* ---------- данные ---------- */
async function aj(p){
  const qs=new URLSearchParams(p).toString(),c=cache.get(qs);
  if(c&&Date.now()-c.t<300000)return c.d;
  const d=await api('/music/get?'+qs),arr=(d&&d.data)||[];if(!Array.isArray(arr))throw new Error('Пустой ответ');
  cache.set(qs,{t:Date.now(),d:arr});if(cache.size>80)cache.delete(cache.keys().next().value);return arr}
function norm(t){return{id:String(t.id),t:t.t||'Без названия',a:t.a||'Неизвестный исполнитель',img:t.img||'',d:t.d|0,u:t.u||'',ai:t.ai||''}}
const tracks=async p=>(await aj(p)).filter(t=>t&&t.id).map(norm);
/* русскоязычное (основное) и зарубежное (отдельная подборка); genre — тег Jamendo */
const RU='ru',WORLD='en';
const catalog=(lang,order,genre,limit,offset)=>tracks(Object.assign({lang,order,limit:limit||30,groupby:'artist_id'},genre?{tags:genre}:{},offset?{offset}:{}));
const trending=(genre,limit,lang)=>catalog(lang||RU,'popularity_week',genre,limit);
/* Яндекс Музыка — основной источник; при любой ошибке/пустом ответе на 5 минут отключаем и берём Jamendo */
let ymDown=0;
const GQ={hiphop:'русский рэп',pop:'русский поп',rock:'русский рок',electronic:'русская электроника',indie:'русский инди',rnb:'русский r&b',lounge:'русский лаунж',jazz:'русский джаз',folk:'русский фолк',metal:'русский метал',ambient:'русский эмбиент'};
async function ymOr(p,fb){
  if(Date.now()>ymDown){try{const l=await tracks(Object.assign({src:'ym',limit:30},p));if(l.length)return l;ymDown=Date.now()+300000}catch(e){ymDown=Date.now()+300000}}
  return fb()}
async function searchAll(q,n){
  const [y,j]=await Promise.all([Date.now()>ymDown?tracks({src:'ym',k:'search',q,limit:n}).catch(()=>[]):[],tracks({search:q,order:'relevance',limit:n}).catch(()=>null)]);
  if(!y.length&&j===null)throw new Error('search');return y.concat(j||[])}
const fbUrl=id=>BASE+'/forum/api/music/stream?id='+encodeURIComponent(id);
const shuffled=a=>{a=a.slice();for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a};

/* ---------- разметка ---------- */
function cover(t,cls){const h=hue(t.id);
  return `<span class="mu-cv ${cls||''}" style="background:linear-gradient(135deg,hsl(${h} 45% 34%),hsl(${(h+50)%360} 50% 16%))">${MI.note}${t.img?`<img src="${esc(t.img)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`:''}<span class="eq"><i></i><i></i><i></i></span></span>`}
const arName=t=>t.ai?`<span class="mu-ar" data-ar="${esc(t.ai)}">${esc(t.a)}</span>`:esc(t.a);
function row(t,i){return `<div class="mu-row${cur()&&cur().id===t.id?' cur':''}" data-i="${i}" data-id="${esc(t.id)}">${cover(t)}<span class="mu-ti"><b>${esc(t.t)}</b><small>${arName(t)}</small></span><span class="mu-dur">${t.d?fmt(t.d):''}</span><button class="mu-lk${isLiked(t.id)?' on':''}" data-lk="1" aria-label="Нравится">${IC.heart}</button></div>`}
const listHtml=a=>`<div class="mu-list">${a.map(row).join('')}</div>`;
function wire(box,arr){box.onclick=e=>{const ar=e.target.closest('[data-ar]');if(ar){e.stopPropagation();openArtist(ar.dataset.ar);return}const r=e.target.closest('.mu-row');if(!r)return;const t=arr[+r.dataset.i];if(!t)return;
  if(e.target.closest('.mu-lk')){e.stopPropagation();toggleLike(t);return}start(arr,+r.dataset.i)}}
const skel=n=>'<div class="mu-skel"></div>'.repeat(n||6);

/* ---------- плеер ---------- */
const uiOn=()=>{const a=$('#app');if(a)a.classList.add('mu-on')};
function start(arr,i){wave=0;Q=arr.slice();playAt(i)}
function playAt(i){
  const t=Q[i];if(!t)return;qi=i;tryFb=(t.src||!t.u)?1:0;uiOn();
  document.body.classList.add('mu-loading');
  A.src=t.src||t.u||fbUrl(t.id);
  const p=A.play();if(p&&p.catch)p.catch(e=>{if(e&&e.name==='NotAllowedError')paint()});
  hist=[t].concat(hist.filter(x=>x.id!==t.id)).slice(0,40);ls.set('mu_hist',JSON.stringify(hist));
  paint();session()}
function toggle(){if(qi<0)return;if(A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}else A.pause()}
function next(auto){
  if(!Q.length)return;
  if(auto&&rep===2){A.currentTime=0;const p=A.play();if(p&&p.catch)p.catch(()=>{});return}
  let n;
  if(shuf&&Q.length>1){do{n=Math.floor(Math.random()*Q.length)}while(n===qi)}else n=qi+1;
  if(n>=Q.length){
    if(wave){loadWave(true);return}
    if(rep===1||!auto)n=0;else{try{A.pause()}catch(e){}A.currentTime=0;paint();return}}
  playAt(n)}
function prev(){if(A.currentTime>3){A.currentTime=0;return}playAt(qi>0?qi-1:(Q.length?Q.length-1:0))}
async function loadWave(append){
  const pool=GENRES,g=pool[Math.floor(Math.random()*pool.length)][0];
  document.body.classList.add('mu-loading');
  try{
    let l=await ymOr({k:'search',q:GQ[g]||'русские хиты',limit:50},()=>catalog(RU,'popularity_month',g,40,Math.floor(Math.random()*3)*15));
    if(l.length<5)l=await catalog(RU,'popularity_total','',40);
    l=shuffled(l);if(!l.length)throw new Error('empty');
    if(append&&wave){Q=Q.concat(l);playAt(qi+1)}else{wave=1;Q=l;playAt(0)}}
  catch(e){document.body.classList.remove('mu-loading');toast('Не удалось загрузить «Мою волну»',1)}}
function toggleLike(t){const i=likes.findIndex(x=>x.id===t.id);if(i>=0)likes.splice(i,1);else likes.unshift(t);likes=likes.slice(0,500);ls.set('mu_likes',JSON.stringify(likes));
  $$('.mu-row').forEach(r=>{if(r.dataset.id===t.id){const b=$('.mu-lk',r);if(b)b.classList.toggle('on',isLiked(t.id))}});paint();
  toast(i>=0?'Убрано из любимого':'Добавлено в любимое')}
function session(){
  if(!('mediaSession' in navigator)||qi<0)return;const t=cur();if(!t)return;
  try{navigator.mediaSession.metadata=new MediaMetadata({title:t.t,artist:t.a,album:'EXG Music',artwork:t.img?[{src:t.img,sizes:'480x480'}]:[]})}catch(e){}
  if(sessionSet)return;sessionSet=1;
  const h=(n,f)=>{try{navigator.mediaSession.setActionHandler(n,f)}catch(e){}};
  h('play',toggle);h('pause',toggle);h('nexttrack',()=>next(false));h('previoustrack',prev);
  h('seekto',d=>{if(d&&isFinite(d.seekTime))A.currentTime=d.seekTime})}

A.addEventListener('playing',()=>{fails=0;document.body.classList.remove('mu-loading');document.body.classList.add('mu-playing');syncPP()});
A.addEventListener('pause',()=>{document.body.classList.remove('mu-playing');syncPP()});
A.addEventListener('waiting',()=>document.body.classList.add('mu-loading'));
A.addEventListener('canplay',()=>document.body.classList.remove('mu-loading'));
A.addEventListener('ended',()=>next(true));
A.addEventListener('timeupdate',progress);
A.addEventListener('error',()=>{
  const t=cur();if(!t||!A.src)return;
  if(!tryFb){tryFb=1;A.src=fbUrl(t.id);const p=A.play();if(p&&p.catch)p.catch(()=>{});return}
  document.body.classList.remove('mu-loading');
  if(++fails>=4){toast('Не удалось воспроизвести музыку. Проверьте интернет',1);try{A.pause()}catch(e){}return}
  toast('Трек недоступен — включаю следующий',1);setTimeout(()=>next(true),500)});

/* ---------- мини-плеер и полноэкранный ---------- */
const MINI=`<div id="muMini"><span class="mu-cv"></span><span class="mu-ti"><b></b><small></small></span><button class="mb pp" data-a="pp" aria-label="Пуск/пауза"></button><button class="mb" data-a="next" aria-label="Дальше">${MI.next}</button><div class="prog"><i></i></div></div>`;
const FULL=`<div id="muFull"><div class="bgc"></div>
<div class="mf-top"><button class="ib" data-a="close" aria-label="Свернуть">${IC.chevd}</button><small>EXG Music</small><span style="width:42px"></span></div>
<div class="mf-art"><span class="mu-cv"></span></div>
<div class="mf-info"><div class="mu-ti"><b></b><small></small></div><button class="mu-lk" data-a="topf" aria-label="В профиль">${IC.plus}</button><button class="mu-lk" data-a="like" aria-label="Нравится">${IC.heart}</button></div>
<div class="mf-seek"><input type="range" min="0" max="1000" value="0" aria-label="Перемотка"><div><span class="tc">0:00</span><span class="td">0:00</span></div></div>
<div class="mf-ctl"><button class="sm" data-a="shuf" aria-label="Вперемешку">${MI.shuf}</button><button data-a="prev" aria-label="Назад">${MI.prev}</button><button class="pp" data-a="pp" aria-label="Пуск/пауза"></button><button data-a="next" aria-label="Дальше">${MI.next}</button><button class="sm" data-a="rep" aria-label="Повтор">${MI.rep}</button></div>
<div class="mf-nx"></div></div>`;
function mount(noNav){
  const app=$('#app');if(!app)return;
  if(!$('#muMini',app)){app.insertAdjacentHTML('beforeend',MINI);app.insertAdjacentHTML('beforeend',FULL);bindUi(app)}
  app.classList.toggle('mu-on',qi>=0);app.classList.toggle('mu-nonav',!!noNav);
  const f=$('#muFull');if(f&&noNav)f.classList.remove('open');
  paint()}
function bindUi(app){
  const mini=$('#muMini',app),full=$('#muFull',app);
  const act=a=>{if(a==='ar'){const t=cur();if(t&&t.ai){full.classList.remove('open');openArtist(t.ai)}return}
    if(a==='pp')toggle();else if(a==='next')next(false);else if(a==='prev')prev();
    else if(a==='close')full.classList.remove('open');
    else if(a==='like'){const t=cur();if(t)toggleLike(t)}
    else if(a==='topf'){const t=cur();if(t)addToProfile(t)}
    else if(a==='shuf'){shuf=shuf?0:1;paint()}
    else if(a==='rep'){rep=(rep+1)%3;paint()}};
  mini.onclick=e=>{const b=e.target.closest('[data-a]');if(b){e.stopPropagation();act(b.dataset.a);return}full.classList.add('open')};
  full.onclick=e=>{if(e.target.closest('[data-ar]')){act('ar');return}const b=e.target.closest('[data-a]');if(b)act(b.dataset.a)};
  const rg=$('input[type=range]',full);
  rg.oninput=()=>{const d=isFinite(A.duration)&&A.duration>0?A.duration:(cur()?cur().d:0);if(d){A.currentTime=rg.value/1000*d}};
  window.addEventListener('hashchange',()=>full.classList.remove('open'))}
function syncPP(){
  pmSync();
  const html=A.paused?MI.play:MI.pause;
  $$('#muMini [data-a=pp],#muFull [data-a=pp]').forEach(b=>{if(b._h!==html){b._h=html;b.innerHTML=html}})}
function progress(){
  const t=cur();if(!t)return;
  const d=isFinite(A.duration)&&A.duration>0?A.duration:t.d||0,p=d?Math.min(1,A.currentTime/d):0;
  const bar=$('#muMini .prog i');if(bar)bar.style.width=(p*100).toFixed(1)+'%';
  $$('.pm-live.on .pm-prog i').forEach(i=>i.style.width=(p*100).toFixed(1)+'%');
  const f=$('#muFull');if(!f||!f.classList.contains('open'))return;
  const rg=$('input[type=range]',f);if(rg&&document.activeElement!==rg){rg.value=Math.round(p*1000);rg.style.setProperty('--p',(p*100).toFixed(1)+'%')}
  $('.tc',f).textContent=fmt(A.currentTime);$('.td',f).textContent=fmt(d)}
function paint(){
  const t=cur();
  document.body.classList.toggle('mu-playing',!!t&&!A.paused&&!A.ended);
  $$('.mu-row').forEach(r=>r.classList.toggle('cur',!!t&&r.dataset.id===t.id));
  const mini=$('#muMini'),full=$('#muFull');if(!mini||!full)return;
  syncPP();
  if(!t)return;
  if(mini.dataset.id!==t.id){mini.dataset.id=t.id;
    mini.querySelector('.mu-cv').outerHTML=cover(t);
    $('.mu-ti b',mini).textContent=t.t;$('.mu-ti small',mini).textContent=t.a;
    $('.mf-art',full).innerHTML=cover(t);
    $('.mu-ti b',full).textContent=t.t;$('.mu-ti small',full).innerHTML=arName(t);
    const bg=$('.bgc',full);bg.style.backgroundImage=t.img?`url("${t.img.replace(/"/g,'%22')}")`:'';
    const h=hue(t.id);if(!t.img)bg.style.backgroundImage=`linear-gradient(135deg,hsl(${h} 50% 30%),hsl(${(h+60)%360} 50% 12%))`;
    const n=Q[qi+1];$('.mf-nx',full).textContent=n?'Дальше: '+n.t+' — '+n.a:'';
    progress()}
  $('[data-a=like]',full).classList.toggle('on',isLiked(t.id));
  $('[data-a=topf]',full).style.display=t.src?'none':'';
  $('[data-a=shuf]',full).classList.toggle('on',!!shuf);
  const rb=$('[data-a=rep]',full);rb.classList.toggle('on',rep>0);rb.innerHTML=rep===2?MI.rep1:MI.rep}
function stop(){try{A.pause()}catch(e){}A.removeAttribute('src');try{A.load()}catch(e){}Q=[];qi=-1;wave=0;
  const a=$('#app');if(a)a.classList.remove('mu-on');document.body.classList.remove('mu-playing','mu-loading')}

/* ---------- экран «EXG Music» ---------- */
function view(el){
  if(!st.go){st.artist=null;st.ahist=[]}st.go=0;
  el.innerHTML=`<div class="mu">
  <div class="mu-top"><button class="ib round" data-href="#/boards" aria-label="Назад">${IC.back}</button><span class="mu-logo">${MI.note}</span><div><h2>EXG <b>Music</b></h2><small>Русская музыка без рекламы</small></div></div>
  <div class="mu-search">${IC.search}<input class="inp" id="muQ" type="search" placeholder="Трек, исполнитель, жанр" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" value="${esc(st.q)}"><button class="mu-x" aria-label="Очистить" ${st.q?'':'hidden'}>${IC.close}</button></div>
  <div class="mu-tabs" ${st.q?'hidden style="display:none"':''}>${[['home','Главное'],['world','Зарубежное'],['likes','Любимое'],['hist','История']].map(([k,n])=>`<button class="tab ${st.tab===k?'on':''}" data-t="${k}">${n}</button>`).join('')}</div>
  <div id="muBody"></div>
  <p class="mu-note">Каталог — Яндекс Музыка, запасной — Jamendo (независимые исполнители). Полные треки зависят от подписки аккаунта сервера. Любимое и история хранятся на этом устройстве.</p></div>`;
  const body=$('#muBody',el),inp=$('#muQ',el),x=$('.mu-x',el),tabs=$('.mu-tabs',el);
  let seq=0,timer=0;
  const fail=(msg,retry)=>{body.innerHTML=`<div class="empty">${msg}<br><br><button class="btn ghost" id="muRetry">Повторить</button></div>`;$('#muRetry',body).onclick=retry};
  const chips=(cur_)=>`<div class="mu-chips">${GENRES.map(([k,n])=>`<button class="mu-chip ${cur_===k?'on':''}" data-g="${esc(k)}">${esc(n)}</button>`).join('')}</div>`;
  const gname=g=>(GENRES.find(x=>x[0]===g)||[0,g])[1];
  const bad=(box,retry)=>{box.innerHTML=`<div class="empty" style="padding:24px">Не удалось загрузить музыку.<br>Проверьте интернет<br><br><button class="btn ghost" id="muRetry">Повторить</button></div>`;$('#muRetry',box).onclick=retry};
  /* дополнительная подборка: при пустом/неудачном ответе убираем заголовок вместе с блоком */
  async function fill(my,id,fn){
    const el=$('#'+id,body);if(!el)return;
    const drop=()=>{if(el.previousElementSibling&&el.previousElementSibling.classList.contains('mu-h'))el.previousElementSibling.remove();el.remove()};
    try{const l=await fn();if(my!==seq)return;if(l.length){el.innerHTML=listHtml(l);wire(el,l)}else drop()}catch(e){if(my===seq)drop()}}
  async function home(){
    const my=++seq,g=st.genre;
    body.innerHTML=`<div class="mu-wave" id="muWave"><div class="bars"><i></i><i></i><i></i><i></i><i></i></div><b>Моя волна</b><span>Бесконечный микс русских треков — популярное и новое</span><button class="go" aria-label="Включить">${MI.play}</button></div>
    ${chips(g)}
    <div class="mu-h"><h3>${g?'Русское в тренде: '+esc(gname(g)):'Русское — сейчас в тренде'}</h3></div><div id="muTr">${skel(6)}</div>
    ${g?'':`<div class="mu-h"><h3>Новинки на русском</h3></div><div id="muNew"></div>
    <div class="mu-h"><h3>Русское — лучшее за всё время</h3></div><div id="muTop"></div>
    <div class="mu-h"><h3>Зарубежная подборка</h3><button class="btn sm ghost" id="muWorld">Все</button></div><div id="muWd"></div>`}`;
    $('#muWave',body).onclick=()=>{loadWave(false)};
    $$('.mu-chip',body).forEach(b=>b.onclick=()=>{st.genre=b.dataset.g;home()});
    const w=$('#muWorld',body);if(w)w.onclick=()=>{st.tab='world';draw()};
    const tr=$('#muTr',body);
    try{let l=await ymOr(g?{k:'search',q:GQ[g]||g}:{k:'chart',c:'russia'},()=>trending(g,30));if(my!==seq)return;
      if(l.length<5){const m=await catalog(RU,'popularity_total',g,30);if(my!==seq)return;if(m.length>l.length)l=m}
      if(!l.length){tr.innerHTML='<div class="empty" style="padding:24px">Здесь пока пусто</div>'}else{tr.innerHTML=listHtml(l);wire(tr,l)}}
    catch(e){if(my===seq)bad(tr,home);return}
    if(g)return;
    fill(my,'muNew',()=>ymOr({k:'search',q:'новинки русской музыки',limit:15},()=>catalog(RU,'releasedate_desc','',15)));
    fill(my,'muTop',()=>ymOr({k:'search',q:'русские хиты',limit:15},()=>catalog(RU,'popularity_total','',15)));
    fill(my,'muWd',()=>ymOr({k:'chart',c:'world',limit:10},()=>trending('',10,WORLD)))}
  async function world(){
    const my=++seq,g=st.wgenre||'';
    body.innerHTML=`<div class="mu-h"><h3>Зарубежная подборка</h3></div>${chips(g)}<div id="muTr">${skel(6)}</div>`;
    $$('.mu-chip',body).forEach(b=>b.onclick=()=>{st.wgenre=b.dataset.g;world()});
    const tr=$('#muTr',body);
    try{let l=await (g?trending(g,30,WORLD):ymOr({k:'chart',c:'world'},()=>trending('',30,WORLD)));if(my!==seq)return;
      if(l.length<5){const m=await catalog(WORLD,'popularity_total',g,30);if(my!==seq)return;if(m.length>l.length)l=m}
      if(!l.length){tr.innerHTML='<div class="empty" style="padding:24px">Здесь пока пусто</div>'}else{tr.innerHTML=listHtml(l);wire(tr,l)}}
    catch(e){if(my===seq)bad(tr,world)}}
  function collection(arr,empty,withBtns){
    if(!arr.length){body.innerHTML=emptyBox('music',empty);return}
    body.innerHTML=`${withBtns?`<div class="mu-h"><h3>${arr.length} ${arr.length%10===1&&arr.length%100!==11?'трек':(arr.length%10>=2&&arr.length%10<=4&&(arr.length%100<10||arr.length%100>=20)?'трека':'треков')}</h3><button class="btn sm" id="muAll">${MI.play}Слушать</button><button class="btn sm ghost" id="muSh">${MI.shuf}</button></div>`:'<div style="height:8px"></div>'}<div id="muLs"></div>`;
    const ls_=$('#muLs',body);ls_.innerHTML=listHtml(arr);wire(ls_,arr);
    if(withBtns){$('#muAll',body).onclick=()=>start(arr,0);$('#muSh',body).onclick=()=>start(shuffled(arr),0)}}
  async function search(q){
    const my=++seq;body.innerHTML=skel(7);
    try{const l=await searchAll(q,30);if(my!==seq)return;
      if(!l.length){body.innerHTML=emptyBox('search','Ничего не нашлось по запросу «'+esc(q)+'»');return}
      body.innerHTML=`<div class="mu-h"><h3>Результаты</h3></div><div id="muLs"></div>`;const b=$('#muLs',body);b.innerHTML=listHtml(l);wire(b,l)}
    catch(e){if(my===seq)fail('Поиск не удался.<br>Проверьте интернет',()=>search(q))}}
  /* ---- карточка исполнителя ---- */
  const aCache=new Map();
  async function artistData(id){const c=aCache.get(id);if(c&&Date.now()-c.t<300000)return c.d;
    const d=await api('/music/artist?id='+encodeURIComponent(id));aCache.set(id,{t:Date.now(),d});if(aCache.size>20)aCache.delete(aCache.keys().next().value);return d}
  const uniq=a=>{const s=new Set();return a.filter(t=>!s.has(t.id)&&s.add(t.id))};
  async function artistPage(id){
    const my=++seq;
    body.innerHTML=`<div class="ar-hero"><button class="ib round ar-back" data-ab="1" aria-label="Назад">${IC.back}</button></div>${skel(7)}`;
    $('[data-ab]',body).onclick=artistBack;
    let d;
    try{d=await artistData(id);if(my!==seq)return}
    catch(e){if(my===seq){body.innerHTML=`<div class="ar-hero"><button class="ib round ar-back" data-ab="1" aria-label="Назад">${IC.back}</button></div><div class="empty">Не удалось загрузить исполнителя<br><br><button class="btn ghost" id="muRetry">Повторить</button></div>`;$('[data-ab]',body).onclick=artistBack;$('#muRetry',body).onclick=()=>artistPage(id)}return}
    const a=d.artist||{},all=(d.tracks||[]).map(norm),top=(d.top||[]).map(norm),sim=(d.similar||[]).map(norm),sa=d.sim_artists||[];
    const main=uniq(top.concat(all)),five=(top.length?top:all).slice(0,5),h=hue(a.id||'x');
    const meta=[a.sub,(a.genres||[]).join(', ')].filter(Boolean).map(esc).join(' · ');
    body.innerHTML=`<div class="ar-hero" style="--h:${h}"><div class="ar-bg"${a.img?` style="background-image:url('${esc(a.img).replace(/'/g,'%27')}')"`:''}></div>
      <button class="ib round ar-back" data-ab="1" aria-label="Назад">${IC.back}</button>
      <span class="ar-ph">${MI.note}${a.img?`<img src="${esc(a.img)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">`:''}</span>
      <h2 class="ar-name">${esc(a.name||'Исполнитель')}</h2>${meta?`<div class="ar-meta">${meta}</div>`:''}
      <div class="ar-act"><button class="btn" id="arPlay">${MI.play}Слушать</button><button class="btn ghost" id="arRadio">${MI.wave}Радио</button><button class="btn ghost ar-sh" id="arSh" aria-label="Вперемешку">${MI.shuf}</button></div></div>
    ${five.length?`<div class="mu-h"><h3>Популярное</h3></div><div id="arTop"></div>`:''}
    ${all.length>five.length?`<div class="mu-h"><h3>Все песни</h3><small class="ar-cnt">${all.length}</small></div><div id="arAll"></div>`:''}
    ${sa.length?`<div class="mu-h"><h3>Похожие исполнители</h3></div><div class="ar-sim">${sa.map(x=>`<button class="ar-card" data-ar="${esc(x.id)}"><span class="ar-av">${MI.note}${x.img?`<img src="${esc(x.img)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`:''}</span><b>${esc(x.name)}</b></button>`).join('')}</div>`:''}
    ${sim.length?`<div class="mu-h"><h3>Похожие песни</h3><button class="btn sm ghost" id="arSimPlay">${MI.play}Слушать</button></div><div id="arSim"></div>`:''}
    ${!all.length&&!sim.length?'<div class="empty" style="padding:24px">Песен исполнителя пока нет</div>':''}`;
    $('[data-ab]',body).onclick=artistBack;
    const put=(sel,arr)=>{const el=$(sel,body);if(el){el.innerHTML=listHtml(arr);wire(el,arr)}};
    put('#arTop',five);put('#arAll',all);put('#arSim',sim);
    $('#arPlay',body).onclick=()=>{if(main.length)start(main,0);else toast('Нет треков для воспроизведения',1)};
    $('#arSh',body).onclick=()=>{if(main.length)start(shuffled(main),0)};
    /* радио исполнителя: его песни вперемешку с песнями похожих исполнителей */
    $('#arRadio',body).onclick=()=>{const l=shuffled(uniq(main.slice(0,25).concat(sim)));if(l.length)start(l,0);else toast('Нет треков для воспроизведения',1)};
    const sp=$('#arSimPlay',body);if(sp)sp.onclick=()=>start(sim,0);
    const sl=$('.ar-sim',body);if(sl)sl.onclick=e=>{const c=e.target.closest('[data-ar]');if(c)openArtist(c.dataset.ar)};
    const vw=$('#view');if(vw)vw.scrollTop=0}
  function artistBack(){st.artist=st.ahist.pop()||null;draw()}
  function draw(){
    const q=st.q.trim();
    tabs.hidden=!!q||!!st.artist;tabs.style.display=(q||st.artist)?'none':'';x.hidden=!st.q;
    if(q.length>=2)return search(q);
    if(q){body.innerHTML='';return}
    if(st.artist)return artistPage(st.artist);
    $$('.tab',tabs).forEach(b=>b.classList.toggle('on',b.dataset.t===st.tab));
    if(st.tab==='likes')collection(likes,'Отмечайте треки сердечком — они появятся здесь',true);
    else if(st.tab==='hist')collection(hist,'Вы пока ничего не слушали',false);
    else if(st.tab==='world')world();
    else home()}
  $$('.tab',tabs).forEach(b=>b.onclick=()=>{st.tab=b.dataset.t;st.artist=null;st.ahist=[];draw()});
  inp.oninput=()=>{st.q=inp.value;x.hidden=!st.q;clearTimeout(timer);timer=setTimeout(draw,450)};
  inp.onkeydown=e=>{if(e.key==='Enter'){clearTimeout(timer);inp.blur();draw()}};
  x.onclick=()=>{st.q='';inp.value='';clearTimeout(timer);draw()};
  redraw=draw;draw()}

/* ---------- исполнитель: открыть карточку откуда угодно (список, полный плеер) ---------- */
function openArtist(id){
  if(!id)return;
  if(st.artist&&st.artist!==id)st.ahist.push(st.artist);
  if(st.artist===id&&$('#muBody')){return}
  st.artist=id;st.q='';
  const f=$('#muFull');if(f)f.classList.remove('open');
  const i=$('#muQ');if(i)i.value='';
  if($('#muBody')&&redraw)redraw();else{st.go=1;location.hash='#/music'}}

/* ---------- музыка в профиле ---------- */
/* Трек профиля — файл, загруженный пользователем (src), либо трек из EXG Music (id Jamendo). Хранится на сервере: /forum/api/pmusic* */
const pmT=x=>x.kind==='exg'?{id:x.ext,t:x.t,a:x.a,img:x.img||'',d:x.d|0,pid:x.id}:{id:'pf_'+x.id,t:x.t,a:x.a,img:x.img?BASE+x.img:'',d:x.d|0,src:BASE+x.src,pid:x.id};
const pmAdd=t=>post_('/pmusic/add',{ext:t.id,title:t.t,artist:t.a,duration:t.d,img:t.img});
async function addToProfile(t){
  if(t.src){toast('Это загруженный файл — добавить можно только свои треки или треки из EXG Music',1);return}
  try{await pmAdd(t);toast('Добавлено в музыку профиля')}catch(e){toast(e.message,1)}}
const totalTxt=s=>{s=Math.round(s||0);if(!s)return '';const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?h+' ч '+m+' мин':Math.max(1,m)+' мин'};

/* теги ID3 (название, исполнитель, обложка) — чтобы файл красиво заполнился сам */
function tdec(enc,d){
  if(!d.length)return '';
  try{
    if(enc===1||enc===2){let le=enc===1?true:false,o=0;
      if(d[0]===0xFF&&d[1]===0xFE){le=true;o=2}else if(d[0]===0xFE&&d[1]===0xFF){le=false;o=2}
      return new TextDecoder(le?'utf-16le':'utf-16be').decode(d.subarray(o)).replace(/\0+$/,'').trim()}
    if(enc===3)return new TextDecoder('utf-8').decode(d).replace(/\0+$/,'').trim();
    let ascii=true;for(let i=0;i<d.length;i++)if(d[i]>127){ascii=false;break}
    return new TextDecoder(ascii?'utf-8':'windows-1251').decode(d).replace(/\0+$/,'').trim()
  }catch(e){return ''}}
async function id3(file){
  const out={};
  try{
    const hb=new Uint8Array(await file.slice(0,10).arrayBuffer());
    if(hb[0]!==0x49||hb[1]!==0x44||hb[2]!==0x33)return out;
    const ver=hb[3],size=((hb[6]&127)<<21)|((hb[7]&127)<<14)|((hb[8]&127)<<7)|(hb[9]&127);
    if(ver<2||ver>4||size<=0)return out;
    const buf=new Uint8Array(await file.slice(10,10+Math.min(size,8*1048576)).arrayBuffer());
    const v2=ver===2,idl=v2?3:4,hl=v2?6:10;let p=0;
    if(hb[5]&0x40&&!v2)p=ver===4?(((buf[0]&127)<<21)|((buf[1]&127)<<14)|((buf[2]&127)<<7)|(buf[3]&127)):(((buf[0]<<24)|(buf[1]<<16)|(buf[2]<<8)|buf[3])>>>0)+4;
    let pic=null;
    while(p+hl<=buf.length){
      const id=String.fromCharCode(buf[p],buf[p+1],buf[p+2],v2?0:buf[p+3]).replace(/\0/g,'');
      if(!/^[A-Z0-9]+$/.test(id))break;
      let fs;
      if(v2)fs=(buf[p+3]<<16)|(buf[p+4]<<8)|buf[p+5];
      else if(ver===4)fs=((buf[p+4]&127)<<21)|((buf[p+5]&127)<<14)|((buf[p+6]&127)<<7)|(buf[p+7]&127);
      else fs=((buf[p+4]<<24)|(buf[p+5]<<16)|(buf[p+6]<<8)|buf[p+7])>>>0;
      if(!fs||p+hl+fs>buf.length)break;
      const d=buf.subarray(p+hl,p+hl+fs);
      if(id==='TIT2'||id==='TT2')out.title=tdec(d[0],d.subarray(1));
      else if(id==='TPE1'||id==='TP1')out.artist=tdec(d[0],d.subarray(1));
      else if((id==='APIC'||id==='PIC')&&!pic){
        const enc=d[0];let q=1;
        if(v2)q+=3;else{while(q<d.length&&d[q]!==0)q++;q++}
        q++; /* тип картинки */
        if(enc===1||enc===2){while(q+1<d.length&&!(d[q]===0&&d[q+1]===0))q+=2;q+=2}else{while(q<d.length&&d[q]!==0)q++;q++}
        const im=d.subarray(q),jpg=im[0]===0xFF&&im[1]===0xD8,png=im[0]===0x89&&im[1]===0x50;
        if((jpg||png)&&im.length<6*1048576)pic={bytes:im,mime:jpg?'image/jpeg':'image/png'}}
      p+=hl+fs}
    if(pic)out.cover=await coverBlob(pic.bytes,pic.mime)
  }catch(e){}
  return out}
function coverBlob(bytes,mime){return new Promise(res=>{
  const u=URL.createObjectURL(new Blob([bytes],{type:mime})),im=new Image();
  im.onload=()=>{const k=Math.min(1,600/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=Math.max(1,Math.round(im.width*k));c.height=Math.max(1,Math.round(im.height*k));
    c.getContext('2d').drawImage(im,0,0,c.width,c.height);URL.revokeObjectURL(u);c.toBlob(b=>res(b&&b.size<=700000?b:null),'image/jpeg',.85)};
  im.onerror=()=>{URL.revokeObjectURL(u);res(null)};im.src=u})}
const fileDur=f=>new Promise(res=>{
  const a=new Audio(),u=URL.createObjectURL(f);let done=0;
  const fin=v=>{if(done)return;done=1;clearTimeout(tm);a.onloadedmetadata=a.onerror=null;URL.revokeObjectURL(u);res(v)};
  const tm=setTimeout(()=>fin(0),5000);a.preload='metadata';
  a.onloadedmetadata=()=>fin(isFinite(a.duration)?a.duration:0);a.onerror=()=>fin(0);a.src=u});

function editDlg(t){return new Promise(res=>{
  const bg=document.createElement('div');bg.className='sheet-bg';
  bg.innerHTML=`<div class="sheet pm-dlg"><div class="sh-m">Данные трека</div><label class="lbl">Название</label><input class="inp" id="pmT" maxlength="120" value="${esc(t.t)}"><label class="lbl">Исполнитель</label><input class="inp" id="pmA" maxlength="120" value="${esc(t.a)}"><div class="pm-dlgb"><button class="btn ghost" data-x="0">Отмена</button><button class="btn" data-x="1">Сохранить</button></div></div>`;
  bg.onclick=e=>{const b=e.target.closest('[data-x]');if(!b&&e.target!==bg)return;const ok=b&&b.dataset.x==='1',r=ok?{title:$('#pmT',bg).value.trim(),artist:$('#pmA',bg).value.trim()}:null;bg.remove();res(r)};
  document.body.appendChild(bg)})}

/* выбор трека из EXG Music: поиск, любимое, тренды; тап по строке — предпрослушивание, «+» — в профиль */
function pickExg(have,onAdd){
  const bg=document.createElement('div');bg.className='sheet-bg pm-pk';
  bg.innerHTML=`<div class="sheet pm-sheet"><div class="sh-m">Добавить из EXG Music</div><div class="mu-search" style="margin:0 6px">${IC.search}<input class="inp" type="search" placeholder="Трек, исполнитель, жанр" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false"></div><div class="mu-tabs" style="padding:12px 6px 4px"><button class="tab on" data-t="likes">Любимое</button><button class="tab" data-t="trend">Русское</button><button class="tab" data-t="world">Зарубежное</button></div><div class="pm-pkl"></div></div>`;
  document.body.appendChild(bg);
  const box=$('.pm-pkl',bg),inp=$('input',bg),tabs=$('.mu-tabs',bg);let tab=likes.some(x=>!x.src)?'likes':'trend',seq=0,timer=0,arr=[];
  const rowA=(t,i)=>`<div class="mu-row${cur()&&cur().id===t.id?' cur':''}" data-i="${i}" data-id="${esc(t.id)}">${cover(t)}<span class="mu-ti"><b>${esc(t.t)}</b><small>${esc(t.a)}</small></span><span class="mu-dur">${t.d?fmt(t.d):''}</span><button class="mu-lk pm-plus${have.has(t.id)?' done':''}" data-add="1" aria-label="Добавить в профиль">${have.has(t.id)?IC.check:IC.plus}</button></div>`;
  const show=(l,empty)=>{arr=l;box.innerHTML=l.length?`<div class="mu-list">${l.map(rowA).join('')}</div>`:`<div class="empty" style="padding:28px 12px">${empty}</div>`};
  async function draw(){
    const my=++seq,q=inp.value.trim();tabs.style.display=q?'none':'';
    if(q.length===1)return;
    if(q){box.innerHTML=skel(6);try{const l=await searchAll(q,25);if(my===seq)show(l,'Ничего не нашлось по запросу «'+esc(q)+'»')}catch(e){if(my===seq)box.innerHTML='<div class="empty" style="padding:28px 12px">Поиск не удался. Проверьте интернет</div>'}return}
    $$('.tab',tabs).forEach(b=>b.classList.toggle('on',b.dataset.t===tab));
    if(tab==='likes'){show(likes.filter(x=>!x.src),'Отмечайте треки сердечком в EXG Music — они появятся здесь. Или найдите трек через поиск');return}
    box.innerHTML=skel(6);try{const l=await trending('',30,tab==='world'?WORLD:RU);if(my===seq)show(l,'Здесь пока пусто')}catch(e){if(my===seq)box.innerHTML='<div class="empty" style="padding:28px 12px">Не удалось загрузить музыку</div>'}}
  $$('.tab',tabs).forEach(b=>b.onclick=()=>{tab=b.dataset.t;draw()});
  inp.oninput=()=>{clearTimeout(timer);timer=setTimeout(draw,450)};
  inp.onkeydown=e=>{if(e.key==='Enter'){clearTimeout(timer);inp.blur();draw()}};
  bg.onclick=async e=>{
    if(e.target===bg){bg.remove();return}
    const r=e.target.closest('.mu-row');if(!r)return;const t=arr[+r.dataset.i];if(!t)return;
    if(e.target.closest('[data-add]')){const b=$('[data-add]',r);if(have.has(t.id)){toast('Этот трек уже в профиле');return}
      b.disabled=true;try{await onAdd(t);have.add(t.id);b.classList.add('done');b.innerHTML=IC.check;toast('Добавлено в профиль')}catch(er){toast(er.message,1)}b.disabled=false;return}
    start(arr,+r.dataset.i)};
  draw()}

/* карточка «Музыка» в профиле. list = ответ /pmusic; o: {own, edit} */
function profile(box,list,o){
  o=o||{};const own=!!o.own;
  let arr=(list.tracks||[]).map(pmT);const max=list.max||10,fileMb=list.file_mb||10;
  const apply=r=>{arr=(r.tracks||[]).map(pmT);draw()};
  const rowP=(t,i)=>`<div class="mu-row${cur()&&cur().id===t.id?' cur':''}" data-i="${i}" data-id="${esc(t.id)}">${cover(t)}<span class="mu-ti"><b>${esc(t.t)}</b><small>${esc(t.a)}</small></span><span class="mu-dur">${t.d?fmt(t.d):''}</span>${own?`<button class="mu-lk" data-mg="1" aria-label="Ещё">${IC.more}</button>`:`<button class="mu-lk${isLiked(t.id)?' on':''}" data-lk="1" aria-label="Нравится">${IC.heart}</button>`}</div>`;
  async function addMenu(){
    if(arr.length>=max){toast('В профиле может быть не больше '+max+' треков — удалите лишние',1);return}
    const c=await sheet([{ic:'file',t:'Из файлов',k:'f'},{ic:'music',t:'Из EXG Music',k:'m'}],'Добавить музыку');if(!c)return;
    if(c.k==='f')pickFiles('audio/*,.mp3,.m4a,.aac,.ogg,.oga,.opus,.wav,.flac,.weba',addFiles);
    else pickExg(new Set(arr.map(t=>t.id)),async t=>{const r=await pmAdd(t);apply(r)})}
  async function addFiles(fs){
    let ok=0;const n=fs.length;
    for(let i=0;i<n;i++){const f=fs[i];
      if(arr.length>=max){toast('Достигнут лимит: '+max+' треков',1);break}
      if(f.size>fileMb*1048576){toast('«'+f.name+'» больше '+fileMb+' МБ',1);continue}
      toast(n>1?'Загружаю '+(i+1)+' из '+n+'…':'Загружаю трек…');
      try{
        const meta=await id3(f),du=await fileDur(f),fd=new FormData();
        fd.append('file',f,f.name);fd.append('title',meta.title||'');fd.append('artist',meta.artist||'');fd.append('duration',Math.round(du||0));
        if(meta.cover)fd.append('cover',meta.cover,'c.jpg');
        apply(await api('/pmusic/add',{method:'POST',form:fd}));ok++}
      catch(e){toast(e.message,1)}}
    if(ok)toast(ok>1?'Добавлено треков: '+ok:'Трек добавлен')}
  async function manage(i){
    const t=arr[i];if(!t)return;
    const items=[];if(i>0)items.push({ic:'pin',t:'Поставить первым',k:'first'});
    items.push({ic:'pencil',t:'Изменить название',k:'edit'},{ic:'trash',t:'Удалить из профиля',bad:true,k:'del'});
    const c=await sheet(items,t.t);if(!c)return;
    try{
      if(c.k==='first')apply(await post_('/pmusic/move',{id:t.pid,first:true}));
      else if(c.k==='edit'){const r=await editDlg(t);if(r)apply(await post_('/pmusic/edit',{id:t.pid,title:r.title,artist:r.artist}))}
      else if(c.k==='del'){if(!await confirmBox('Убрать «'+t.t+'» из профиля?'))return;
        if(cur()&&cur().id===t.id)stop();
        apply(await post_('/pmusic/delete',{id:t.pid}));toast('Трек убран')}}
    catch(e){toast(e.message,1)}}
  function draw(){
    box.classList.toggle('pm-edit',!!o.edit);
    if(!arr.length){
      box._pmArr=[];
      if(!own){box.innerHTML='';return}
      box.innerHTML=`<div class="pm pm-empty glass"><span class="pm-ic">${MI.note}</span><div class="pm-ht"><b>Музыка в профиле</b><small>Добавьте любимые треки — из файлов или из EXG Music</small></div><button class="btn sm" data-pm="add">${IC.plus}Добавить</button></div>`;
      $('[data-pm=add]',box).onclick=addMenu;return}
    const tot=totalTxt(arr.reduce((s,t)=>s+(t.d||0),0));
    box.innerHTML=`<section class="pm pm-live glass"><div class="pm-bg"></div>
      <div class="pm-head"><span class="pm-ic">${MI.note}<i class="pm-eq"><u></u><u></u><u></u></i></span><div class="pm-ht"><b>${own?'Моя музыка':'Музыка'}</b><small>${arr.length} ${plural(arr.length,'трек','трека','треков')}${tot?' · '+tot:''}</small></div>${own?`<button class="pm-addb" data-pm="add" aria-label="Добавить музыку">${IC.plus}</button>`:''}</div>
      <div class="pm-hero"><button class="pm-disc" data-pm="hero" aria-label="Играть"><span class="mu-cv"></span><span class="pm-pp"></span></button><div class="pm-meta"><b></b><small></small><div class="pm-prog"><i></i></div></div></div>
      <div class="pm-act"><button class="btn sm" data-pm="all">${MI.play}Слушать</button><button class="btn ghost sm" data-pm="shuf">${MI.shuf}Вперемешку</button></div>
      <div class="mu-list pm-list">${arr.map(rowP).join('')}</div></section>`;
    const sec=$('.pm-live',box);sec._arr=arr;
    sec.onclick=e=>{
      const pm=e.target.closest('[data-pm]');
      if(pm){const k=pm.dataset.pm;
        if(k==='add')addMenu();
        else if(k==='all'||k==='hero'){const c=cur(),i=c?arr.findIndex(x=>x.id===c.id):-1;if(i>=0)toggle();else start(arr,0)}
        else if(k==='shuf')start(shuffled(arr),0);
        return}
      const r=e.target.closest('.mu-row');if(!r)return;const i=+r.dataset.i,t=arr[i];if(!t)return;
      if(e.target.closest('[data-mg]')){e.stopPropagation();manage(i);return}
      if(e.target.closest('.mu-lk')){e.stopPropagation();toggleLike(t);return}
      start(arr,i)};
    pmSync()}
  draw()}

/* обновляет карточки профиля при смене трека/паузе (вызывается из paint/syncPP) */
function pmSync(){
  $$('.pm-live').forEach(sec=>{
    const arr=sec._arr||[];if(!arr.length)return;
    const c=cur(),idx=c?arr.findIndex(x=>x.id===c.id):-1,t=idx>=0?arr[idx]:arr[0];
    const on=idx>=0,playing=on&&!A.paused&&!A.ended;
    sec.classList.toggle('on',on);sec.classList.toggle('playing',playing);
    if(sec.dataset.cur!==t.id){
      sec.dataset.cur=t.id;
      const cv=$('.pm-disc .mu-cv',sec);if(cv)cv.outerHTML=cover(t);
      $('.pm-meta b',sec).textContent=t.t;$('.pm-meta small',sec).textContent=t.a;
      const bg=$('.pm-bg',sec),h=hue(t.id);
      bg.style.backgroundImage=t.img?`url("${t.img.replace(/"/g,'%22')}")`:`linear-gradient(135deg,hsl(${h} 50% 30%),hsl(${(h+60)%360} 50% 12%))`;
      const pr=$('.pm-prog i',sec);if(pr)pr.style.width='0'}
    const pp=$('.pm-pp',sec),html=playing?MI.pause:MI.play;if(pp&&pp._h!==html){pp._h=html;pp.innerHTML=html}
    const al=$('[data-pm=all]',sec);if(al){const h=(playing?MI.pause+'Пауза':MI.play+(on?'Продолжить':'Слушать'));if(al._h!==h){al._h=h;al.innerHTML=h}}})}

return{view,mount,stop,paint,profile,openArtist}})();
function viewMusic(el){MU.view(el)}
