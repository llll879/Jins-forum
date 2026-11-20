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
 wave:I('<path d="M3 12h2M7 8v8M11 4v16M15 8v8M19 10v4"/>'),
 lyr:I('<path d="M4 6h16M4 12h10M4 18h14"/>'),
 moon:I('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
 eq:I('<path d="M5 14v4M9 9v9M13 4v14M17 8v10M21 11v4" stroke-width="2.6"/>'),
 mic:I('<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/><path d="M12 6h.01" stroke-width="3"/>'),
 globe:I('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.9 5.6 3.9 9S14.6 18.4 12 21c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3z"/>'),
 dl:I('<path d="M12 3.5v11m0 0-4-4m4 4 4-4M5 20h14"/>'),
 ok:I('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
 clock:I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>'),
 dice:I('<rect x="4" y="4" width="16" height="16" rx="4.5"/><path d="M8.5 8.5h.01M15.5 8.5h.01M12 12h.01M8.5 15.5h.01M15.5 15.5h.01" stroke-width="3"/>'),
 users:I('<circle cx="9" cy="8" r="3.2"/><path d="M3 19c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><circle cx="17" cy="9" r="2.4"/><path d="M17 14c2.4 0 4 1.6 4 4"/>')
};
IC.music=MI.note;IC.moon=MI.moon;
const A=new Audio();A.preload='auto';
let Q=[],qi=-1,shuf=0,rep=0,wave=0,waveSel=null,tryFb=0,fails=0,sessionSet=0;
const st={tab:'home',genre:'',q:'',artist:null,ahist:[],wg:'m'};
let redraw=null,subsFn=null,netFn=null;
const cache=new Map();
const jget=(k,d)=>{try{const v=ls.get(k);return v?JSON.parse(v):d}catch(e){return d}};
/* треки старой библиотеки (нецифровые id без файла) больше не играют — не тащим их из сохранённого */
const okT=x=>x&&(x.src||/^y?\d+$/.test(String(x.id)));
let likes=jget('mu_likes',[]).filter(okT),hist=jget('mu_hist',[]).filter(okT);
const isLiked=id=>likes.some(x=>x.id===id);
const cur=()=>Q[qi]||null;

/* ---------- скачанная музыка (офлайн) ----------
   Файлы, обложки и данные трека лежат в Cache Storage («exg-dl-v1») — не стираются при выходе из аккаунта.
   Скачанный трек играет с устройства (без трафика); без интернета доступна только «Моя волна» — она крутит скачанное вперемешку. */
const offline=()=>{try{return NET.off||navigator.onLine===false}catch(e){return navigator.onLine===false}};
const DLN='exg-dl-v1',dlMeta=new Map(),dlBusy=new Set();
let dlCur='';
const dlK=(k,id)=>location.origin+'/__dl/'+k+'/'+encodeURIComponent(id);
const dlC=()=>typeof caches!=='undefined'?caches.open(DLN):Promise.reject(new Error('no cache'));
const dlHas=id=>dlMeta.has(String(id));
const dlMB=()=>{let n=0;dlMeta.forEach(m=>n+=m.size||0);return Math.max(1,Math.round(n/1048576))};
const dlList=()=>[...dlMeta.values()].sort((a,b)=>(b.ts||0)-(a.ts||0)).map(m=>({id:m.id,t:m.t,a:m.a,img:m.imgL||m.img||'',d:m.d|0,u:'',ai:m.ai||''}));
async function dlLoad(){
  try{const c=await dlC(),ks=await c.keys();
    for(const k of ks){if(!new URL(k.url).pathname.startsWith('/__dl/meta/'))continue;
      try{const m=await (await c.match(k)).json();
        const cv=await c.match(dlK('cover',m.id));if(cv){try{m.imgL=URL.createObjectURL(await cv.blob())}catch(e){}}
        dlMeta.set(String(m.id),m)}catch(e){}}}
  catch(e){}
  if(subsFn)subsFn();paint()}
async function dlUrl(id){
  try{const c=await dlC(),r=await c.match(dlK('audio',id));if(!r)return '';
    const b=await r.blob();if(dlCur){URL.revokeObjectURL(dlCur)}dlCur=URL.createObjectURL(b);return dlCur}
  catch(e){return ''}}
async function dlAdd(t,quiet){
  if(t.src){if(!quiet)toast('Загруженные файлы уже хранятся в профиле',1);return false}
  if(dlHas(t.id)||dlBusy.has(t.id))return true;
  if(offline()){if(!quiet)toast('Нет интернета — скачать нельзя',1);return false}
  dlBusy.add(t.id);paint();if(!quiet)toast('Скачиваю…');
  try{
    try{navigator.storage&&navigator.storage.persist&&navigator.storage.persist()}catch(e){}
    const r=await fetch(t.u||fbUrl(t.id));if(!r.ok)throw new Error('http');
    const b=await r.blob();if(b.size<20000)throw new Error('small');
    const c=await dlC();
    await c.put(dlK('audio',t.id),new Response(b,{headers:{'Content-Type':b.type||'audio/mpeg'}}));
    let imgL='';
    if(t.img){try{const cr=await fetch(t.img,{referrerPolicy:'no-referrer'});if(cr.ok){const cb=await cr.blob();if(cb.size<600000){await c.put(dlK('cover',t.id),new Response(cb,{headers:{'Content-Type':cb.type||'image/jpeg'}}));imgL=URL.createObjectURL(cb)}}}catch(e){}}
    const m={id:String(t.id),t:t.t,a:t.a,img:t.img||'',d:t.d|0,ai:t.ai||'',size:b.size,ts:Date.now()};
    await c.put(dlK('meta',t.id),new Response(JSON.stringify(m),{headers:{'Content-Type':'application/json'}}));
    m.imgL=imgL;dlMeta.set(m.id,m);dlBusy.delete(t.id);paint();if(subsFn)subsFn();
    if(!quiet)toast('Скачано — доступно без интернета');return true}
  catch(e){dlBusy.delete(t.id);paint();
    try{const c=await dlC();await c.delete(dlK('audio',t.id));await c.delete(dlK('cover',t.id))}catch(x){}
    if(!quiet)toast(offline()?'Нет интернета':'Не удалось скачать трек',1);return false}}
async function dlRemove(id,quiet){
  id=String(id);const m=dlMeta.get(id);dlMeta.delete(id);
  try{const c=await dlC();for(const k of ['audio','cover','meta'])await c.delete(dlK(k,id))}catch(e){}
  if(m&&m.imgL){try{URL.revokeObjectURL(m.imgL)}catch(e){}}
  paint();if(subsFn)subsFn();if(!quiet)toast('Удалено из скачанного')}
async function dlClear(){for(const id of [...dlMeta.keys()])await dlRemove(id,true);toast('Скачанное очищено')}
async function dlToggle(t){if(dlHas(t.id))await dlRemove(t.id);else await dlAdd(t)}
async function dlMany(arr){
  const todo=arr.filter(t=>!t.src&&!dlHas(t.id));if(!todo.length){toast('Всё уже скачано');return}
  toast('Скачиваю треков: '+todo.length+'…');let ok=0;
  for(const t of todo){if(offline())break;if(await dlAdd(t,true))ok++}
  toast(ok?'Скачано: '+ok+' из '+todo.length:'Не удалось скачать',!ok)}
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
/* ---------- волны: бесконечные радио по настроению, занятию, жанру, эпохе ----------
   Строка: [id, название, группа, оттенок, поисковые запросы Яндекса (крутятся по очереди), тег Jamendo для запасного источника].
   Группа w — зарубежное (запасной источник берёт en-каталог). */
const WG=[['m','Настроение'],['a','Занятия'],['g','Жанры'],['e','Эпохи'],['w','Со всего мира']];
const WAVES=[
/* настроение */
['bodro','Бодрая','m',45,['бодрые русские песни','энергичные хиты на русском','песни чтобы взбодриться'],'energetic'],
['calm','Спокойная','m',200,['спокойная русская музыка','тихие нежные песни','расслабляющие песни на русском'],'relaxing'],
['sad','Грустная','m',225,['грустные русские песни','песни про расставание','печальные хиты'],'sad'],
['fun','Весёлая','m',330,['весёлые песни','песни для хорошего настроения','позитивные русские хиты'],'happy'],
['love','Романтика','m',348,['романтичные русские песни','песни о любви','любовные баллады'],'romantic'],
['motiv','Мотивация','m',18,['мотивирующие песни','песни про силу и цель','песни чтобы не сдаваться'],'energetic'],
['dream','Мечтательная','m',265,['мечтательные песни','атмосферная русская музыка','дрим-поп на русском'],'dream'],
['dark','Мрачная','m',282,['мрачные русские песни','тёмная атмосферная музыка','русский дарквейв и готик'],'dark'],
['nostal','Ностальгия','m',32,['ностальгия русские песни','песни из детства','любимые песни прошлых лет'],''],
['cozy','Уютная','m',26,['уютные песни','тёплая домашняя музыка','нежная акустика'],'acoustic'],
['epic','Эпичная','m',6,['эпичная музыка','мощные песни с пафосом','эпичные саундтреки'],'epic'],
['summer','Летняя','m',52,['летние песни','песни про лето','летние хиты на русском'],'summer'],
/* занятия */
['sport','Тренировка','a',10,['музыка для тренировки','песни для спортзала','музыка для бега'],'sport'],
['road','В дорогу','a',150,['песни в дорогу','музыка для поездки на машине','песни для путешествия'],''],
['work','Для работы','a',190,['музыка для работы','музыка для концентрации','фоновая музыка для офиса'],'ambient'],
['study','Учёба','a',175,['музыка для учёбы','спокойная музыка для чтения','lofi для учёбы'],'lofi'],
['cook','Готовка','a',36,['музыка для готовки','уютные песни на кухню','лёгкая музыка для дома'],'lounge'],
['clean','Уборка','a',58,['песни для уборки','бодрая музыка для дома','весёлые песни для дома'],'happy'],
['walk','Прогулка','a',122,['музыка для прогулки','песни для прогулки по городу','лёгкие песни на ходу'],'indie'],
['sleep','Для сна','a',252,['музыка для сна','спокойные мелодии для засыпания','колыбельные для взрослых'],'ambient'],
['party','Вечеринка','a',316,['песни для вечеринки','танцевальные хиты','клубные русские хиты'],'party'],
['morning','Утро','a',42,['утренние песни','музыка для бодрого утра','песни чтобы проснуться'],'happy'],
['evening','Вечер','a',292,['вечерняя музыка','расслабляющие песни на вечер','вечерний лаунж'],'chillout'],
['rain','Дождь','a',210,['музыка под дождь','песни про дождь','осенние песни'],'ambient'],
['gaming','Игры','a',140,['музыка для игр','электронная музыка для геймеров','синтвейв'],'electronic'],
['medit','Медитация','a',168,['музыка для медитации','медитативная музыка','музыка для релаксации'],'meditation'],
['kids','Детям','a',62,['детские песни','песни из мультфильмов','колыбельные песни'],'children'],
['ny','Зима и Новый год','a',195,['новогодние песни','зимние песни','песни про новый год'],'christmas'],
/* жанры */
['rap','Рэп','g',14,['русский рэп','русский хип-хоп новинки','русский рэп классика'],'hiphop'],
['trap','Трэп','g',2,['русский трэп','трэп хиты','мелодичный рэп'],'hiphop'],
['phonk','Фонк','g',350,['фонк','русский фонк','drift phonk'],''],
['pop','Поп','g',322,['русский поп','поп хиты россии','русская поп-музыка новинки'],'pop'],
['rock','Рок','g',8,['русский рок','русский рок классика','рок-группы России'],'rock'],
['punk','Панк','g',356,['русский панк-рок','панк рок классика','панк-группы'],'punk'],
['metal','Метал','g',0,['русский метал','тяжёлая музыка','метал группы россии'],'metal'],
['indie','Инди','g',166,['русский инди','инди-поп','инди группы россии'],'indie'],
['electro','Электроника','g',196,['русская электроника','электронная музыка','синтипоп'],'electronic'],
['house','Хаус','g',272,['house музыка','deep house','русский хаус'],'house'],
['techno','Техно','g',240,['техно','techno','минимал техно'],'techno'],
['disco','Диско','g',332,['диско хиты','итало диско','диско 80-х'],'disco'],
['rnb','R&B','g',286,['русский r&b','r&b хиты','нео-соул на русском'],'rnb'],
['jazz','Джаз','g',38,['русский джаз','джаз классика','вокальный джаз'],'jazz'],
['blues','Блюз','g',222,['блюз','русский блюз','блюз-рок'],'blues'],
['folk','Фолк','g',92,['русский фолк','народные песни современные','этно музыка'],'folk'],
['reggae','Регги','g',108,['регги','ска и регги','reggae'],'reggae'],
['lounge','Лаунж','g',182,['русский лаунж','чиллаут','лаунж для вечера'],'lounge'],
['lofi','Lo-fi','g',256,['lofi hip hop','lo-fi beats','lofi chill'],'lofi'],
['chanson','Шансон','g',28,['русский шансон','шансон хиты','душевный шансон'],''],
['bard','Авторская песня','g',72,['авторская песня','бардовские песни','песни под гитару классика'],'folk'],
['acoustic','Под гитару','g',34,['песни под гитару','акустические русские песни','дворовые песни под гитару'],'acoustic'],
['classic','Классика','g',48,['классическая музыка','Чайковский','Бах Моцарт Бетховен'],'classical'],
['ost','Саундтреки','g',302,['саундтреки к фильмам','музыка из кино','оригинальный саундтрек'],'soundtrack'],
/* эпохи */
['y70','70-е','e',46,['хиты 70-х','песни 70-х','ВИА 70-х'],''],
['y80','80-е','e',332,['хиты 80-х','русские песни 80-х','поп-музыка 80-х'],''],
['y90','90-е','e',300,['хиты 90-х','русские песни 90-х','поп-музыка 90-х'],''],
['y00','2000-е','e',204,['хиты 2000-х','русские песни 2000-х','хиты нулевых'],''],
['y10','2010-е','e',160,['хиты 2010-х','русские песни 2010-х','клубные хиты 2010-х'],''],
['y20','Сейчас','e',130,['новые хиты','хиты 2026','русские новинки'],''],
['sov','Советская эстрада','e',16,['советская эстрада','песни СССР','советские хиты'],''],
['rock80','Русский рок 80-х','e',4,['русский рок 80-х','Кино ДДТ Наутилус','ленинградский рок-клуб'],'rock'],
/* со всего мира */
['wpop','Зарубежный поп','w',320,['pop hits','top pop songs','best pop music'],'pop'],
['wrock','Зарубежный рок','w',8,['rock classics','best rock songs','alternative rock hits'],'rock'],
['whh','Хип-хоп мира','w',24,['hip hop hits','rap hits','best rap songs'],'hiphop'],
['wrnb','R&B и соул','w',286,['r&b hits','soul music','neo soul'],'rnb'],
['wel','Dance и EDM','w',256,['electronic dance hits','edm','dance music'],'electronic'],
['wjazz','Джаз мира','w',40,['jazz classics','smooth jazz','jazz standards'],'jazz'],
['kpop','K-pop','w',336,['k-pop hits','kpop','korean pop'],''],
['anime','Аниме','w',346,['anime openings','anime songs','j-pop'],''],
['latin','Латино','w',16,['latin hits','reggaeton','latin pop'],'latin'],
['french','Французская','w',216,['chanson française','french pop','musique française'],''],
['italian','Итальянская','w',130,['canzoni italiane','italian pop','musica italiana'],''],
['turk','Турецкая','w',4,['turkish pop','türkçe pop','turkish hits'],''],
['arab','Восточная','w',22,['arabic pop','arabic music','eastern music'],''],
['country','Кантри','w',34,['country hits','country music','folk country'],'country']
].map(([id,t,g,h,q,j])=>({id,t,g,h,q,j,w:g==='w'}));
const WQ=new Map();   /* очередь запросов волны: каждый запрос по разу, потом перемешиваем заново — чтобы треки не повторялись */
const wavePick=w=>{let a=WQ.get(w.id);if(!a||!a.length){a=shuffled(w.q.map((_,i)=>i));WQ.set(w.id,a)}return w.q[a.pop()]};
const markWave=()=>{const id=wave&&waveSel?waveSel.id:'';$$('.mu-wv').forEach(b=>b.classList.toggle('on',!!id&&b.dataset.w===id))};
async function ymOr(p,fb){
  if(Date.now()>ymDown){try{const l=await tracks(Object.assign({src:'ym',limit:30},p));if(l.length)return l;ymDown=Date.now()+300000}catch(e){ymDown=Date.now()+300000}}
  return fb()}
/* умный поиск: сервер сам чинит раскладку/транслит, берёт подсказки Яндекса; ai=1 — ещё и Gemini (при его сбое просто пусто) */
const searchApi=(q,ai)=>api('/music/search?q='+encodeURIComponent(q)+(ai?'&ai=1':'')).then(d=>({artists:d.artists||[],tracks:(d.tracks||[]).map(norm),fixed:d.fixed||''}));
const searchAll=async(q,n)=>(await searchApi(q)).tracks.slice(0,n);
/* карточка исполнителя: портрет с именем поверх; без фото — цветной градиент и первая буква */
const ini=n=>(String(n||'').trim().match(/[\p{L}\p{N}]/u)||['♪'])[0].toUpperCase();
const arImg=(u,cls)=>u?`<img${cls?` class="${cls}"`:''} src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer" onload="this.classList.add('ok')" onerror="this.remove()">`:'';
const cards=sa=>`<div class="ar-sim">${sa.map(x=>`<button class="ar-card" style="--h:${hue(x.id)}" data-ar="${esc(x.id)}"><em>${esc(ini(x.name))}</em>${arImg(x.img)}<span class="ar-ov"><b>${esc(x.name)}</b><small>Исполнитель</small></span></button>`).join('')}</div>`;
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
function start(arr,i){wave=0;waveSel=null;Q=arr.slice();playAt(i)}
function playAt(i){
  const t=Q[i];if(!t)return;qi=i;
  if(NM()&&!permAsked){permAsked=1;try{window.EXGPerm&&EXGPerm.ensure('notif').then(()=>nat(true))}catch(e){}}   /* Android 13+: без разрешения на уведомления шторки с плеером не будет */
 tryFb=(t.src||!t.u)?1:0;uiOn();
  document.body.classList.add('mu-loading');
  const go=u=>{if(Q[qi]!==t)return;A.src=u;const p=A.play();if(p&&p.catch)p.catch(e=>{if(e&&e.name==='NotAllowedError')paint()})};
  if(dlHas(t.id)){tryFb=1;dlUrl(t.id).then(u=>{if(u)go(u);else{tryFb=t.u?0:1;go(t.u||fbUrl(t.id))}})}   /* скачанное играет с устройства */
  else go(t.src||t.u||fbUrl(t.id));
  hist=[t].concat(hist.filter(x=>x.id!==t.id)).slice(0,40);ls.set('mu_hist',JSON.stringify(hist));if(subsFn)subsFn();
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
async function loadWave(append,w){
  if(w===undefined)w=append?waveSel:null;          /* без аргумента — продолжаем текущую волну */
  if(offline()){                                   /* без интернета «волна» крутит скачанное */
    const l=shuffled(dlList());if(!l.length){toast('Нет скачанных треков. Скачайте музыку, пока есть интернет',1);return}
    if(append&&wave){Q=Q.concat(l);playAt(qi+1)}else{wave=1;waveSel=null;Q=l;playAt(0)}return}
  document.body.classList.add('mu-loading');
  try{
    let l;
    if(w){                                         /* тематическая волна: запрос Яндекса, запасной — каталог Jamendo по тегу */
      const q=wavePick(w),lang=w.w?WORLD:RU,tag=w.j||'',off=Math.floor(Math.random()*3)*15;
      l=await ymOr({k:'search',q,limit:50},()=>catalog(lang,'popularity_month',tag,40,off));
      if(l.length<5)l=await catalog(lang,'popularity_total',tag,40,off)}
    else{
      const pool=GENRES,g=pool[Math.floor(Math.random()*pool.length)][0];
      l=await ymOr({k:'search',q:GQ[g]||'русские хиты',limit:50},()=>catalog(RU,'popularity_month',g,40,Math.floor(Math.random()*3)*15));
      if(l.length<5)l=await catalog(RU,'popularity_total','',40)}
    l=shuffled(l);if(!l.length)throw new Error('empty');
    if(append&&wave){
      const have=new Set(Q.map(x=>x.id)),f=l.filter(x=>!have.has(x.id));if(f.length>=3)l=f;
      if(qi>60){Q=Q.slice(qi-10);qi=10}
      Q=Q.concat(l);playAt(qi+1)}
    else{wave=1;waveSel=w||null;Q=l;playAt(0);if(w)toast('Волна «'+w.t+'»')}}
  catch(e){document.body.classList.remove('mu-loading');toast('Не удалось загрузить '+(w?'волну «'+w.t+'»':'«Мою волну»'),1)}}
function toggleLike(t){const i=likes.findIndex(x=>x.id===t.id);if(i>=0)likes.splice(i,1);else likes.unshift(t);likes=likes.slice(0,500);ls.set('mu_likes',JSON.stringify(likes));if(subsFn)subsFn();
  $$('.mu-row').forEach(r=>{if(r.dataset.id===t.id){const b=$('.mu-lk',r);if(b)b.classList.toggle('on',isLiked(t.id))}});paint();
  toast(i>=0?'Убрано из любимого':'Добавлено в любимое')}
/* ---------- фоновое воспроизведение и управление из шторки/экрана блокировки ----------
   Браузер: Media Session API (уведомление Chrome, экран блокировки, гарнитура, Bluetooth).
   Приложение Android (WebView): тот же API там ничего не показывает, поэтому шлём состояние в мост
   window.ExgNative.media — нативная служба рисует уведомление с обложкой, ◀◀ ▶/❚❚ ▶▶ и полосой перемотки. */
const MS='mediaSession' in navigator?navigator.mediaSession:null;
const NM=()=>{const n=window.ExgNative;return n&&typeof n.media==='function'?n:null};
let natSig='',natPos=0,permAsked=0;
function durOf(t){return isFinite(A.duration)&&A.duration>0?A.duration:(t&&t.d)||0}
function artwork(t){if(!t||!t.img)return [];return [96,192,256,384,512].map(n=>({src:t.img,sizes:n+'x'+n}))}
function posState(){
  if(!MS||!MS.setPositionState)return;const t=cur(),d=durOf(t);
  try{if(t&&d&&isFinite(A.currentTime))MS.setPositionState({duration:d,playbackRate:A.playbackRate||1,position:Math.min(A.currentTime,d)});else MS.setPositionState()}catch(e){}}
/* состояние → в уведомление Android (только когда что-то изменилось: трек, пауза/игра, перемотка) */
function nat(force){
  const n=NM();if(!n)return;const t=cur();
  if(!t){try{n.mediaStop()}catch(e){}natSig='';return}
  const pl=!A.paused&&!A.ended,d=Math.round(durOf(t)*1000),pos=Math.round((A.currentTime||0)*1000);
  const sig=t.id+'|'+pl+'|'+d;
  if(!force&&sig===natSig&&Math.abs(pos-natPos)<2500)return;
  natSig=sig;natPos=pos;
  try{n.media(JSON.stringify({id:String(t.id),title:t.t||'',artist:t.a||'',img:t.img||'',playing:pl,pos:pos,dur:d}))}catch(e){}}
/* кнопки из уведомления Android приходят сюда: play | pause | next | prev | seek:мс | stop */
window.__exgMedia=function(a){
  try{
    if(a==='play'){if(qi>=0&&A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}}
    else if(a==='pause'){if(!A.paused)A.pause()}
    else if(a==='next')next(false);
    else if(a==='prev')prev();
    else if(a==='stop')stop();
    else if(a&&a.indexOf('seek:')===0){const v=+a.slice(5);if(isFinite(v)){A.currentTime=v/1000;nat(true)}}
  }catch(e){}};
function session(){
  const t=cur();if(!t||qi<0)return;
  if(MS){
    try{MS.metadata=new MediaMetadata({title:t.t,artist:t.a,album:'EXG Music',artwork:artwork(t)})}catch(e){}
    if(!sessionSet){sessionSet=1;
      const h=(n,f)=>{try{MS.setActionHandler(n,f)}catch(e){}};
      h('play',()=>{if(qi>=0&&A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}});
      h('pause',()=>{if(!A.paused)A.pause()});
      h('stop',()=>stop());
      h('nexttrack',()=>next(false));h('previoustrack',prev);
      h('seekbackward',d=>{A.currentTime=Math.max(0,A.currentTime-((d&&d.seekOffset)||10))});
      h('seekforward',d=>{const m=durOf(cur())||1e9;A.currentTime=Math.min(m,A.currentTime+((d&&d.seekOffset)||10))});
      h('seekto',d=>{if(d&&isFinite(d.seekTime)){if(d.fastSeek&&A.fastSeek)A.fastSeek(d.seekTime);else A.currentTime=d.seekTime;posState()}})}
    syncState()}
  nat(true)}
function syncState(){
  if(MS)try{MS.playbackState=!cur()?'none':A.paused?'paused':'playing'}catch(e){}
  posState()}

A.addEventListener('playing',()=>{lyRun();fails=0;document.body.classList.remove('mu-loading');document.body.classList.add('mu-playing');syncPP();syncState();nat()});
A.addEventListener('pause',()=>{document.body.classList.remove('mu-playing');syncPP();syncState();nat()});
A.addEventListener('loadedmetadata',()=>{posState();nat()});
A.addEventListener('durationchange',()=>{posState();nat()});
A.addEventListener('ratechange',posState);
A.addEventListener('waiting',()=>document.body.classList.add('mu-loading'));
A.addEventListener('canplay',()=>document.body.classList.remove('mu-loading'));
A.addEventListener('ended',()=>{if(slp.eot){slpClear('Таймер сна: музыка остановлена');return}next(true)});
A.addEventListener('timeupdate',progress);
A.addEventListener('seeked',()=>{lyI=-2;lyTick();posState();nat(true)});
A.addEventListener('error',()=>{
  const t=cur();if(!t||!A.src)return;
  if(offline()&&!dlHas(t.id)&&dlMeta.size){wave=1;Q=shuffled(dlList());toast('Нет сети — играет скачанное');playAt(0);return}
  if(!tryFb){tryFb=1;A.src=fbUrl(t.id);const p=A.play();if(p&&p.catch)p.catch(()=>{});return}
  document.body.classList.remove('mu-loading');
  if(++fails>=4){toast('Не удалось воспроизвести музыку. Проверьте интернет',1);try{A.pause()}catch(e){}return}
  toast('Трек недоступен — включаю следующий',1);setTimeout(()=>next(true),500)});

/* ---------- тексты песен ---------- */
/* Сервер: /music/lyrics -> {sync:[[сек,строка]…], plain, src}. Показываем в двух местах одновременно:
   на обратной стороне перевёрнутой обложки и на второй «странице» полноэкранного плеера (листнуть вниз). Синхронный текст — как караоке:
   текущая строка подсвечивается и «заливается» по ходу пения, список сам едет за ней, тап по строке — перемотка. */
let LY={id:null,st:'',d:null},lyI=-2,lyUser=0,lyNeed=0,raf=0;
const lyCache=new Map();
const lySync=()=>LY.st==='ok'&&LY.d&&LY.d.sync&&LY.d.sync.length?LY.d.sync:null;
function lyBody(){
  if(LY.st==='load'||!LY.st)return '<div class="ly-in"><div class="ly-sk"><i></i><i></i><i></i><i></i><i></i></div></div>';
  if(LY.st==='none')return `<div class="ly-in"><div class="ly-msg">${MI.lyr}<b>Текста пока нет</b><small>Для этой песни мы его не нашли</small></div></div>`;
  if(LY.st==='err')return `<div class="ly-in"><div class="ly-msg">${MI.lyr}<b>Не удалось загрузить текст</b><button class="btn sm ghost" data-a="lyretry">Повторить</button></div></div>`;
  const s=lySync();
  if(s)return `<div class="ly-in">${s.map((l,i)=>l[1]?`<p class="ly-l" data-i="${i}" data-t="${l[0]}"><span data-tx="${esc(l[1])}">${esc(l[1])}</span></p>`:`<p class="ly-l ly-gap" data-i="${i}" data-t="${l[0]}"><span>• • •</span></p>`).join('')}</div>`;
  return `<div class="ly-in ly-pl">${String(LY.d.plain||'').split(/\n\s*\n/).map(b=>`<p>${esc(b.trim())}</p>`).join('')}<small class="ly-note">Текст без синхронизации — его можно листать вручную</small></div>`}
function lyRender(){
  const f=$('#muFull');if(!f)return;
  const h=lyBody(),src=LY.st==='ok'&&LY.d?(LY.d.src==='ym'?'Текст: Яндекс Музыка':'Текст: LRCLIB'):'';
  $$('.ly',f).forEach(b=>{b.innerHTML=h;b.classList.toggle('sync',!!lySync());b.scrollTop=0;b.style.setProperty('--pad',Math.round(b.clientHeight*.4)+'px')});
  const sr=$('.ly-src',f);if(sr)sr.textContent=src;
  lyI=-2;lyTick(true)}
function lyReset(){LY={id:null,st:'',d:null};lyI=-2;const f=$('#muFull');if(f){$$('.ly',f).forEach(b=>{b.innerHTML='';b.scrollTop=0});const s=$('.ly-src',f);if(s)s.textContent=''}}
async function ensureLy(){
  const t=cur();if(!t)return;
  if(LY.id===t.id&&LY.st&&LY.st!=='err')return;
  LY={id:t.id,st:'load',d:null};lyRender();
  const c=lyCache.get(t.id);
  if(c){LY.d=c;LY.st=(c.sync&&c.sync.length)||c.plain?'ok':'none';lyRender();lyRun();return}
  try{
    const d=await api('/music/lyrics?'+new URLSearchParams({id:t.id,t:t.t,a:t.a,d:t.d||0}));
    if(!cur()||cur().id!==t.id)return;
    const ok=d&&((d.sync&&d.sync.length)||d.plain);
    if(ok){lyCache.set(t.id,d);if(lyCache.size>40)lyCache.delete(lyCache.keys().next().value)}
    LY.d=ok?d:null;LY.st=ok?'ok':'none'}
  catch(e){if(!cur()||cur().id!==t.id)return;LY.st='err'}
  lyRender();lyRun()}
function flipTo(on){
  const f=$('#muFull');if(!f)return;const fl=$('.flip',f);
  fl.classList.toggle('on',!!on);fl.setAttribute('aria-label',on?'Вернуть обложку':'Показать текст песни');
  if(on){ensureLy();setTimeout(()=>{lyUser=0;lyI=-2;const b=$('.ly[data-ly="1"]',f);if(b)b.style.setProperty('--pad',Math.round(b.clientHeight*.4)+'px');lyTick(true)},520)}}
function lySeek(t){
  if(!isFinite(t))return;lyUser=0;A.currentTime=Math.max(0,t);
  if(A.paused){const p=A.play();if(p&&p.catch)p.catch(()=>{})}
  lyI=-2;lyTick(true)}
/* какая строка сейчас поётся — двоичный поиск по таймкодам */
function lyTick(force){
  const s=lySync(),f=$('#muFull');if(!s||!f)return;
  if(!force&&!f.classList.contains('open'))return;
  const T=A.currentTime+.18;
  let lo=0,hi=s.length-1,r=-1;while(lo<=hi){const m=(lo+hi)>>1;if(s[m][0]<=T){r=m;lo=m+1}else hi=m-1}
  if(r!==lyI){const first=lyI===-2;lyI=r;
    $$('.ly.sync',f).forEach(b=>{const ls=b.querySelectorAll('.ly-l');
      for(let j=0;j<ls.length;j++){ls[j].classList.toggle('lyon',j===r);ls[j].classList.toggle('lypast',j<r);if(j!==r)ls[j].style.removeProperty('--lp')}
      if(!lyCenter(b,r>=0?ls[r]:null,!first))lyNeed=1})}
  else if(lyNeed&&r>=0&&Date.now()-lyUser>=3500){lyNeed=0;$$('.ly.sync',f).forEach(b=>lyCenter(b,b.querySelectorAll('.ly-l')[r],true))}
  if(r>=0){
    const a=s[r][0],nx=s[r+1]?s[r+1][0]:a+6,len=s[r][1].length,span=Math.max(.8,Math.min(nx-a-.05,len*.085+1.1)),p=Math.max(0,Math.min(1,(T-a)/span));
    $$('.ly.sync .ly-l.lyon',f).forEach(l=>l.style.setProperty('--lp',(p*100).toFixed(1)+'%'))}}
function lyCenter(b,el,smooth){            /* false — пользователь сам листает, вернёмся к строке позже */
  if(!el)return true;
  if(Date.now()-lyUser<3500)return false;
  const f=$('#muFull'),beh=smooth?'smooth':'auto';
  if(b.dataset.ly==='1'){                       /* обратная сторона обложки: свой скролл */
    if(!$('.flip',f).classList.contains('on'))return true;
    b.scrollTo({top:el.offsetTop-b.clientHeight/2+el.offsetHeight/2,behavior:beh});return true}
  const sc=$('.mf-sc',f),p1=$('.mf-p1',f);       /* вторая страница: едет весь экран */
  if(sc.scrollTop<p1.clientHeight*.35)return true;
  const hh=$('.mf-p2h',f).offsetHeight,r=el.getBoundingClientRect(),sr=sc.getBoundingClientRect();
  sc.scrollTo({top:sc.scrollTop+(r.top+r.height/2)-(sr.top+hh+(sc.clientHeight-hh)/2),behavior:beh});return true}
function lyRun(){
  if(raf)return;
  const step=()=>{raf=0;const f=$('#muFull');if(!f||!f.classList.contains('open')||A.paused||!lySync())return;lyTick();raf=requestAnimationFrame(step)};
  raf=requestAnimationFrame(step)}

/* ---------- таймер сна ---------- */
/* Через N минут музыка плавно затихает (последние 10 с) и ставится на паузу; «До конца трека» — остановка после текущей песни. */
let slp={end:0,eot:0,iv:0};
const sheetTop=(items,title)=>{const p=sheet(items,title);const b=[...document.querySelectorAll('.sheet-bg')].pop();if(b)b.style.zIndex=95;return p};
function slpPaint(){
  const on=!!(slp.end||slp.eot),f=$('#muFull');if(!f)return;const b=$('.sleep',f);if(!b)return;
  b.classList.toggle('on',on);
  $('i',b).textContent=slp.eot?'до конца':slp.end?fmt(Math.max(0,(slp.end-Date.now())/1000)):''}
function slpClear(msg){
  clearInterval(slp.iv);slp={end:0,eot:0,iv:0};A.volume=1;slpPaint();if(msg){try{A.pause()}catch(e){}toast(msg)}}
function slpTick(){
  const left=slp.end-Date.now();
  if(left<=0){slpClear('Таймер сна: музыка остановлена');return}
  A.volume=left<10000?Math.max(.03,left/10000):1;slpPaint()}
function slpSet(min){
  slpClear();
  if(min==='eot')slp.eot=1;
  else{slp.end=Date.now()+min*60000;slp.iv=setInterval(slpTick,500)}
  slpPaint();toast(min==='eot'?'Музыка остановится после этого трека':'Музыка остановится через '+min+' мин')}
async function sleepMenu(){
  const on=!!(slp.end||slp.eot),items=[15,30,45,60,90].map(m=>({ic:'moon',t:m+' минут',k:m}));
  items.push({ic:'music',t:'До конца трека',k:'eot'});
  if(on)items.push({t:'Выключить таймер',bad:true,k:'off'});
  const c=await sheetTop(items,on?'Таймер сна · '+(slp.eot?'до конца трека':'осталось '+fmt((slp.end-Date.now())/1000)):'Таймер сна');
  if(!c)return;
  if(c.k==='off')slpClear();else slpSet(c.k)}

/* ---------- мини-плеер и полноэкранный ---------- */
const MINI=`<div id="muMini"><span class="mu-cv"></span><span class="mu-ti"><b></b><small></small></span><button class="mb pp" data-a="pp" aria-label="Пуск/пауза"></button><button class="mb" data-a="next" aria-label="Дальше">${MI.next}</button><div class="prog"><i></i></div></div>`;
const FULL=`<div id="muFull"><div class="bgc"></div><div class="mf-sc">
<section class="mf-p1">
<div class="mf-top"><button class="ib" data-a="close" aria-label="Свернуть">${IC.chevd}</button><small>EXG Music</small><button class="ib sleep" data-a="sleep" aria-label="Таймер сна">${MI.moon}<i></i></button></div>
<div class="mf-art"><div class="flip" data-a="flip" role="button" aria-label="Показать текст песни"><div class="face fr"><span class="cvh"></span><span class="fl-hint">${MI.lyr}Текст</span></div><div class="face bk"><div class="ly" data-ly="1"></div><button class="fl-back" data-a="flipb" aria-label="Вернуть обложку">${IC.close}</button></div></div></div>
<div class="mf-info"><div class="mu-ti"><b></b><small></small></div><button class="mu-lk" data-a="dl" aria-label="Скачать для офлайна">${MI.dl}</button><button class="mu-lk" data-a="topf" aria-label="В профиль">${IC.plus}</button><button class="mu-lk" data-a="like" aria-label="Нравится">${IC.heart}</button></div>
<div class="mf-seek"><input type="range" min="0" max="1000" value="0" aria-label="Перемотка"><div><span class="tc">0:00</span><span class="td">0:00</span></div></div>
<div class="mf-ctl"><button class="sm" data-a="shuf" aria-label="Вперемешку">${MI.shuf}</button><button data-a="prev" aria-label="Назад">${MI.prev}</button><button class="pp" data-a="pp" aria-label="Пуск/пауза"></button><button data-a="next" aria-label="Дальше">${MI.next}</button><button class="sm" data-a="rep" aria-label="Повтор">${MI.rep}</button></div>
<div class="mf-nx"></div>
<button class="mf-more" data-a="down">${MI.lyr}Текст песни<span>${IC.chevd}</span></button>
</section>
<section class="mf-p2"><div class="mf-p2h"><span class="cvs"></span><span class="mu-ti"><b></b><small></small></span><button class="mb pp" data-a="pp" aria-label="Пуск/пауза"></button><button class="mb up" data-a="up" aria-label="К плееру">${IC.chevd}</button></div><div class="ly" data-ly="2"></div><div class="ly-src"></div></section>
</div></div>`;
function mount(noNav){
  const app=$('#app');if(!app)return;
  if(!$('#muMini',app)){app.insertAdjacentHTML('beforeend',MINI);app.insertAdjacentHTML('beforeend',FULL);bindUi(app)}
  app.classList.toggle('mu-on',qi>=0);app.classList.toggle('mu-nonav',!!noNav);
  const f=$('#muFull');if(f&&noNav)f.classList.remove('open');
  paint()}
function bindUi(app){
  const mini=$('#muMini',app),full=$('#muFull',app);
  const sc=$('.mf-sc',full);
  const act=a=>{if(a==='ar'){const t=cur();if(t&&t.ai){full.classList.remove('open');openArtist(t.ai)}return}
    if(a==='pp')toggle();else if(a==='next')next(false);else if(a==='prev')prev();
    else if(a==='close')full.classList.remove('open');
    else if(a==='sleep')sleepMenu();
    else if(a==='flip'||a==='flipb')flipTo(a==='flip'?!$('.flip',full).classList.contains('on'):false);
    else if(a==='down'){ensureLy();sc.scrollTo({top:$('.mf-p2',full).offsetTop,behavior:'smooth'})}
    else if(a==='up')sc.scrollTo({top:0,behavior:'smooth'});
    else if(a==='lyretry'){LY.id=null;ensureLy()}
    else if(a==='like'){const t=cur();if(t)toggleLike(t)}
    else if(a==='dl'){const t=cur();if(t)dlToggle(t)}
    else if(a==='topf'){const t=cur();if(t)addToProfile(t)}
    else if(a==='shuf'){shuf=shuf?0:1;paint()}
    else if(a==='rep'){rep=(rep+1)%3;paint()}};
  mini.onclick=e=>{const b=e.target.closest('[data-a]');if(b){e.stopPropagation();act(b.dataset.a);return}full.classList.add('open');ensureLy();lyRun()};
  full.onclick=e=>{if(e.target.closest('[data-ar]')){act('ar');return}
    const ln=e.target.closest('.ly-l[data-t]');if(ln){lySeek(+ln.dataset.t);return}
    const b=e.target.closest('[data-a]');if(!b||(b.dataset.a==='flip'&&e.target.closest('.bk')))return;act(b.dataset.a)};
  /* пока пользователь сам листает текст — автопрокрутку не трогаем */
  ['wheel','touchstart','pointerdown'].forEach(ev=>sc.addEventListener(ev,()=>{lyUser=Date.now()},{passive:true}));
  $('.ly[data-ly="1"]',full).addEventListener('touchstart',()=>{lyUser=Date.now()},{passive:true});
  sc.addEventListener('scroll',()=>{if(sc.scrollTop>30)ensureLy()},{passive:true});
  const rg=$('input[type=range]',full);
  rg.oninput=()=>{const d=isFinite(A.duration)&&A.duration>0?A.duration:(cur()?cur().d:0);if(d){A.currentTime=rg.value/1000*d}};
  window.addEventListener('hashchange',()=>full.classList.remove('open'))}
function syncPP(){
  pmSync();
  const html=A.paused?MI.play:MI.pause;
  $$('#muMini [data-a=pp],#muFull [data-a=pp],.ar-rc [data-rpp]').forEach(b=>{if(b._h!==html){b._h=html;b.innerHTML=html}})}
function progress(){
  const t=cur();if(!t)return;
  if(!raf)lyTick();
  const d=isFinite(A.duration)&&A.duration>0?A.duration:t.d||0,p=d?Math.min(1,A.currentTime/d):0;
  const bar=$('#muMini .prog i');if(bar)bar.style.width=(p*100).toFixed(1)+'%';
  $$('.pm-live.on .pm-prog i').forEach(i=>i.style.width=(p*100).toFixed(1)+'%');
  const f=$('#muFull');if(!f||!f.classList.contains('open'))return;
  const rg=$('input[type=range]',f);if(rg&&document.activeElement!==rg){rg.value=Math.round(p*1000);rg.style.setProperty('--p',(p*100).toFixed(1)+'%')}
  $('.tc',f).textContent=fmt(A.currentTime);$('.td',f).textContent=fmt(d)}
function paint(){
  const t=cur();markWave();
  document.body.classList.toggle('mu-playing',!!t&&!A.paused&&!A.ended);
  $$('.mu-row').forEach(r=>r.classList.toggle('cur',!!t&&r.dataset.id===t.id));
  const mini=$('#muMini'),full=$('#muFull');if(!mini||!full)return;
  syncPP();
  if(!t)return;
  if(mini.dataset.id!==t.id){mini.dataset.id=t.id;
    mini.querySelector('.mu-cv').outerHTML=cover(t);
    $('.mu-ti b',mini).textContent=t.t;$('.mu-ti small',mini).textContent=t.a;
    $('.mf-art .cvh',full).innerHTML=cover(t);$('.mf-p2h .cvs',full).innerHTML=cover(t);
    $('.mf-info .mu-ti b',full).textContent=t.t;$('.mf-info .mu-ti small',full).innerHTML=arName(t);
    $('.mf-p2h .mu-ti b',full).textContent=t.t;$('.mf-p2h .mu-ti small',full).textContent=t.a;
    lyReset();if(full.classList.contains('open'))ensureLy();
    const bg=$('.bgc',full);bg.style.backgroundImage=t.img?`url("${t.img.replace(/"/g,'%22')}")`:'';
    const h=hue(t.id);if(!t.img)bg.style.backgroundImage=`linear-gradient(135deg,hsl(${h} 50% 30%),hsl(${(h+60)%360} 50% 12%))`;
    const n=Q[qi+1];$('.mf-nx',full).textContent=n?'Дальше: '+n.t+' — '+n.a:'';
    progress()}
  $('[data-a=like]',full).classList.toggle('on',isLiked(t.id));
  {const db=$('[data-a=dl]',full),has=dlHas(t.id),bz=dlBusy.has(t.id);db.classList.toggle('on',has);db.classList.toggle('busy',bz);db.style.display=t.src?'none':'';
   const h=bz?'<span class="mu-aid"></span>':has?MI.ok:MI.dl;if(db._h!==h){db._h=h;db.innerHTML=h}db.setAttribute('aria-label',has?'Убрать из скачанного':'Скачать для офлайна')}
  $('[data-a=topf]',full).style.display=t.src?'none':'';
  $('[data-a=shuf]',full).classList.toggle('on',!!shuf);
  const rb=$('[data-a=rep]',full);rb.classList.toggle('on',rep>0);rb.innerHTML=rep===2?MI.rep1:MI.rep}
function stop(){lyReset();slpClear();try{A.pause()}catch(e){}A.removeAttribute('src');try{A.load()}catch(e){}Q=[];qi=-1;wave=0;waveSel=null;
  const a=$('#app');if(a)a.classList.remove('mu-on');document.body.classList.remove('mu-playing','mu-loading');
  if(MS){try{MS.metadata=null;MS.playbackState='none'}catch(e){}}nat(true)}

/* карточки-«рулетка» вместо поиска и вкладок: тап по боковой — докрутить, по кнопке на центральной — включить */
const CARDS=[
 {h:300,k:'karaoke',tab:'karaoke',t:'Караоке 2007',ic:'mic',pl:1,q:'караоке хиты 2007 русские',fb:'popularity_total'},
 {h:250,k:'wave',tab:'home',t:'Моя волна',ic:'eq',pl:1,big:1},
 {h:28,k:'nostalg',tab:'nostalg',t:'Ностальгия 2010-х',ic:'eq',pl:1,q:'русские хиты 2010-х ностальгия',fb:'popularity_month'},
 {h:190,k:'world',tab:'world',t:'Зарубежное',ic:'globe',sub:'Хиты со всего мира'},
 {h:345,k:'likes',tab:'likes',t:'Любимое',ic:'heart'},
 {h:150,k:'dl',tab:'dl',t:'Скачанное',ic:'dl'},
 {h:42,k:'hist',tab:'hist',t:'История',ic:'clock'},
 {h:215,k:'search',tab:'search',t:'Поиск',ic:'search',sub:'Трек, исполнитель, текст'}];
const cardOf=tab=>Math.max(0,CARDS.findIndex(c=>c.tab===tab));
const plural=n=>n%10===1&&n%100!==11?'трек':(n%10>=2&&n%10<=4&&(n%100<10||n%100>=20)?'трека':'треков');
const subTxt=c=>c.k==='dl'?(dlMeta.size?dlMeta.size+' '+plural(dlMeta.size)+' · '+dlMB()+' МБ':'Для офлайна'):c.k==='likes'?(likes.length?likes.length+' '+plural(likes.length):'Отмечайте сердечком'):c.k==='hist'?(hist.length?hist.length+' '+plural(hist.length):'Пока пусто'):(c.sub||'');
const plMemo=new Map();

/* ---------- экран «EXG Music» ---------- */
function view(el){
  if(!st.go){st.artist=null;st.ahist=[]}st.go=0;
  const icHtml=c=>c.ic==='eq'?'<span class="cd-eqb"><i></i><i></i><i></i><i></i><i></i></span>':c.ic==='mic'?`<span class="cd-mic">${MI.mic}</span>`:(MI[c.ic]||IC[c.ic]);
  const cardHtml=(c,i)=>`<div class="mu-cd${c.big?' big':''}" style="--ch:${c.h}" data-i="${i}" data-k="${c.k}" role="button" tabindex="0" aria-label="${esc(c.t)}"><span class="cd-ic">${icHtml(c)}</span><b>${esc(c.t)}</b><span class="cd-bt">${c.pl?`<span class="cd-go" data-go="1" role="button" aria-label="Включить">${MI.play}</span>`:`<small data-sub="${c.k}">${esc(subTxt(c))}</small>`}</span></div>`;
  el.innerHTML=`<div class="mu">
  <canvas class="mu-fx" id="muFx"></canvas>
  <div class="mu-top"><button class="ib round" data-href="#/boards" aria-label="Назад">${IC.back}</button><span class="mu-logo">${MI.note}</span><div><h2>EXG <b>Music</b></h2><small>Русская музыка без рекламы</small></div></div>
  <div class="mu-search" ${st.q||st.tab==='search'?'':'hidden'}>${IC.search}<input class="inp" id="muQ" type="search" placeholder="Трек, исполнитель, текст песни" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" value="${esc(st.q)}"><button class="mu-x" aria-label="Очистить" ${st.q?'':'hidden'}>${IC.close}</button></div>
  <div class="mu-rl-w" id="muRlw"><div class="mu-pod"><i></i><i></i><i></i></div><span class="mu-mark"></span><div class="mu-rl" id="muRl">${CARDS.map(cardHtml).join('')}</div><button class="mu-spinb" id="muSpin" aria-label="Крутануть рулетку">${MI.dice}</button></div>
  <div class="mu-dots" id="muDots">${CARDS.map((c,i)=>`<button data-i="${i}" aria-label="${esc(c.t)}"></button>`).join('')}</div>
  <div id="muBody"></div>
  <p class="mu-note">Каталог — Яндекс Музыка, запасной — Jamendo (независимые исполнители). Полные треки зависят от подписки аккаунта сервера. Любимое и история хранятся на этом устройстве.</p></div>`;
  const body=$('#muBody',el),inp=$('#muQ',el),x=$('.mu-x',el),sb=$('.mu-search',el),rlw=$('#muRlw',el),rl=$('#muRl',el),dots=$('#muDots',el);
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
  /* блок «Волны»: вкладки-группы и сетка плиток; тап по плитке запускает бесконечную волну */
  const waveTile=w=>`<button class="mu-wv${wave&&waveSel&&waveSel.id===w.id?' on':''}" data-w="${w.id}" style="--h:${w.h};--h2:${(w.h+45)%360}"><span class="wv-eq"><i></i><i></i><i></i><i></i><i></i></span><b>${esc(w.t)}</b></button>`;
  function wvDraw(){
    const box=$('#muWv',body);if(!box)return;
    box.innerHTML=`<div class="mu-h wv-top"><h3>Волны</h3><small class="ar-cnt">${WAVES.length} · играют без конца</small></div>
      <div class="mu-wt-w">${WG.map(([k,n])=>`<button class="mu-wt${st.wg===k?' on':''}" data-wg="${k}">${esc(n)}</button>`).join('')}</div>
      <div class="mu-wvs">${WAVES.filter(w=>w.g===st.wg).map(waveTile).join('')}</div>`;
    $$('.mu-wt',box).forEach(b=>b.onclick=()=>{st.wg=b.dataset.wg;wvDraw()});
    $$('.mu-wv',box).forEach(b=>b.onclick=()=>{const w=WAVES.find(x=>x.id===b.dataset.w);if(w)loadWave(false,w)})}
  async function home(){
    const my=++seq,g=st.genre;
    body.innerHTML=`<div id="muWv"></div>${chips(g)}
    <div class="mu-h"><h3>${g?'Русское в тренде: '+esc(gname(g)):'Русское — сейчас в тренде'}</h3></div><div id="muTr">${skel(6)}</div>
    ${g?'':`<div class="mu-h"><h3>Новинки на русском</h3></div><div id="muNew"></div>
    <div class="mu-h"><h3>Русское — лучшее за всё время</h3></div><div id="muTop"></div>
    <div class="mu-h"><h3>Зарубежная подборка</h3><button class="btn sm ghost" id="muWorld">Все</button></div><div id="muWd"></div>`}`;
    wvDraw();
    $$('.mu-chip',body).forEach(b=>b.onclick=()=>{st.genre=b.dataset.g;home()});
    const w=$('#muWorld',body);if(w)w.onclick=()=>goCard(cardOf('world'));
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
  /* подборки-карточки «Караоке 2007», «Ностальгия 2010-х»: поиск по Яндексу, запасной — каталог Jamendo */
  const plData=c=>{let p=plMemo.get(c.k);if(p&&Date.now()-p.t<600000)return p.p;
    p={t:Date.now(),p:ymOr({k:'search',q:c.q,limit:40},()=>catalog(RU,c.fb,'',40))};plMemo.set(c.k,p);p.p.catch(()=>plMemo.delete(c.k));return p.p};
  async function plist(c){
    const my=++seq;
    body.innerHTML=`<div class="mu-h"><h3>${esc(c.t)}</h3><button class="btn sm" id="muAll" hidden>${MI.play}Слушать</button><button class="btn sm ghost" id="muSh" hidden>${MI.shuf}</button></div><div id="muLs">${skel(7)}</div>`;
    const ls_=$('#muLs',body);
    try{const l=await plData(c);if(my!==seq)return;
      if(!l.length){ls_.innerHTML='<div class="empty" style="padding:24px">Здесь пока пусто</div>';return}
      ls_.innerHTML=listHtml(l);wire(ls_,l);
      const a=$('#muAll',body),h=$('#muSh',body);a.hidden=h.hidden=false;a.onclick=()=>start(l,0);h.onclick=()=>start(shuffled(l),0)}
    catch(e){if(my===seq)bad(ls_,()=>plist(c))}}
  async function playCard(c){
    if(c.k==='wave'){loadWave(false);return}
    if(!c.q)return;
    document.body.classList.add('mu-loading');
    try{const l=await plData(c);document.body.classList.remove('mu-loading');
      if(l.length)start(shuffled(l),0);else toast('Подборка пока пустая',1)}
    catch(e){document.body.classList.remove('mu-loading');toast('Не удалось загрузить подборку',1)}}
  function collection(arr,empty,withBtns){
    if(!arr.length){body.innerHTML=emptyBox('music',empty);return}
    body.innerHTML=`${withBtns?`<div class="mu-h"><h3>${arr.length} ${arr.length%10===1&&arr.length%100!==11?'трек':(arr.length%10>=2&&arr.length%10<=4&&(arr.length%100<10||arr.length%100>=20)?'трека':'треков')}</h3><button class="btn sm" id="muAll">${MI.play}Слушать</button><button class="btn sm ghost" id="muSh">${MI.shuf}</button></div>`:'<div style="height:8px"></div>'}<div id="muLs"></div>`;
    const ls_=$('#muLs',body);ls_.innerHTML=listHtml(arr);wire(ls_,arr);
    if(withBtns){$('#muAll',body).onclick=()=>start(arr,0);$('#muSh',body).onclick=()=>start(shuffled(arr),0)}}
  async function search(q){
    const my=++seq;body.innerHTML=skel(7);
    let d;
    try{d=await searchApi(q);if(my!==seq)return}
    catch(e){if(my===seq)fail('Поиск не удался.<br>Проверьте интернет',()=>search(q));return}
    const none=!d.artists.length&&!d.tracks.length;
    body.innerHTML=`${d.fixed?`<div class="mu-fix">Показано по запросу «${esc(d.fixed)}»</div>`:''}
      ${d.artists.length?`<div class="mu-h"><h3>Исполнители</h3></div>${cards(d.artists)}`:''}
      ${d.tracks.length?`<div class="mu-h"><h3>Треки</h3></div><div id="muLs"></div>`:''}
      ${none?`<div id="muNone">${emptyBox('search','Ничего не нашлось по запросу «'+esc(q)+'»')}</div>`:''}
      <div id="muAi"><div class="mu-ai"><span class="mu-aid"></span>Умный поиск ищет ещё…</div></div>`;
    const sl=$('.ar-sim',body);if(sl)sl.onclick=e=>{const c=e.target.closest('[data-ar]');if(c)openArtist(c.dataset.ar)};
    const lb=$('#muLs',body);if(lb){lb.innerHTML=listHtml(d.tracks);wire(lb,d.tracks)}
    /* второй этап: ИИ (может быть недоступен/перегружен — тогда блок тихо исчезает) */
    const ai=$('#muAi',body);
    try{
      const r=await searchApi(q,true);if(my!==seq)return;
      const haveA=new Set(d.artists.map(x=>x.id)),haveT=new Set(d.tracks.map(x=>x.id));
      const ea=r.artists.filter(x=>!haveA.has(x.id)),et=r.tracks.filter(x=>!haveT.has(x.id));
      if(!ea.length&&!et.length){ai.remove();return}
      const nn=$('#muNone',body);if(nn)nn.remove();
      ai.innerHTML=`<div class="mu-h"><h3>Умный поиск</h3><small class="ar-cnt">возможно, вы искали</small></div>${ea.length?cards(ea):''}${et.length?'<div id="muAiL"></div>':''}`;
      const c2=$('.ar-sim',ai);if(c2)c2.onclick=e=>{const c=e.target.closest('[data-ar]');if(c)openArtist(c.dataset.ar)};
      const l2=$('#muAiL',ai);if(l2){l2.innerHTML=listHtml(et);wire(l2,et)}}
    catch(e){if(my===seq&&ai)ai.remove()}}
  /* ---- карточка исполнителя ---- */
  const aCache=new Map();
  async function artistData(id){const c=aCache.get(id);if(c&&Date.now()-c.t<300000)return c.d;
    const d=await api('/music/artist?id='+encodeURIComponent(id));aCache.set(id,{t:Date.now(),d});if(aCache.size>20)aCache.delete(aCache.keys().next().value);return d}
  const uniq=a=>{const s=new Set();return a.filter(t=>!s.has(t.id)&&s.add(t.id))};
  /* буквы имени выезжают по очереди */
  const nameHtml=n=>String(n||'Исполнитель').split(/(\s+)/).map(w=>/^\s+$/.test(w)?' ':`<span class="w">${[...w].map(ch=>`<span class="l" style="--i:${nameHtml.i++}">${esc(ch)}</span>`).join('')}</span>`).join('');
  const numUp=(box,txt)=>{               /* «12 345 слушателей» — число набегает с нуля */
    const m=/^(\d[\d   ]*\d|\d)\s+(.*)$/.exec(txt);if(!m||REDUCE){box.textContent=txt;return}
    const n=parseInt(m[1].replace(/\D/g,''),10);if(!n){box.textContent=txt;return}
    const t0=performance.now(),D=1100,f=v=>String(v).replace(/\B(?=(\d{3})+(?!\d))/g,' ');
    const st_=now=>{if(!box.isConnected)return;const p=Math.min(1,(now-t0)/D),e=1-Math.pow(1-p,3);box.textContent=f(Math.round(n*e))+' '+m[2];if(p<1)requestAnimationFrame(st_)};
    box.textContent='0 '+m[2];setTimeout(()=>requestAnimationFrame(st_),500)};
  const rowR=(t,i)=>`<div class="mu-row rv${cur()&&cur().id===t.id?' cur':''}" style="--r:${i}" data-i="${i}" data-id="${esc(t.id)}"><span class="ar-n">${i+1}</span>${cover(t)}<span class="mu-ti"><b>${esc(t.t)}</b><small>${arName(t)}</small></span><span class="mu-dur">${t.d?fmt(t.d):''}</span><button class="mu-lk${isLiked(t.id)?' on':''}" data-lk="1" aria-label="Нравится">${IC.heart}</button><span class="ar-rc"><button data-rpp="1" aria-label="Пуск/пауза">${A.paused?MI.play:MI.pause}</button><button data-rnx="1" aria-label="Дальше">${MI.next}</button></span></div>`;
  function wireR(box,arr){
    wire(box,arr);const h=box.onclick;
    box.onclick=e=>{
      if(e.target.closest('[data-rpp]')){e.stopPropagation();toggle();return}
      if(e.target.closest('[data-rnx]')){e.stopPropagation();next(false);return}
      h(e)}}
  /* появление блоков при прокрутке */
  function reveal(box){
    const els=$$('.rv',box);
    if(!('IntersectionObserver' in window)||REDUCE){els.forEach(x=>x.classList.add('in'));return}
    const io=new IntersectionObserver(es=>es.forEach(en=>{if(en.isIntersecting){en.target.classList.add('in');io.unobserve(en.target)}}),{root:$('#view'),rootMargin:'0px 0px -6% 0px'});
    els.forEach(x=>io.observe(x))}
  async function artistPage(id){
    const my=++seq,back=`<button class="ib round ar-back" data-ab="1" aria-label="Назад">${IC.back}</button>`;
    body.innerHTML=`<div class="ar-pg"><div class="ar-hero">${back}<div class="ar-skph"></div></div>${skel(7)}</div>`;
    $('[data-ab]',body).onclick=artistBack;
    let d;
    try{d=await artistData(id);if(my!==seq)return}
    catch(e){if(my===seq){body.innerHTML=`<div class="ar-pg"><div class="ar-hero">${back}</div><div class="empty">Не удалось загрузить исполнителя<br><br><button class="btn ghost" id="muRetry">Повторить</button></div></div>`;$('[data-ab]',body).onclick=artistBack;$('#muRetry',body).onclick=()=>artistPage(id)}return}
    const a=d.artist||{},all=(d.tracks||[]).map(norm),top=(d.top||[]).map(norm),sim=(d.similar||[]).map(norm),sa=d.sim_artists||[];
    const main=uniq(top.concat(all)),five=(top.length?top:all).slice(0,5),h=hue(a.id||'x');
    const chips=(a.sub?`<span class="ar-chip ar-lis">${MI.users}<span class="ar-num"></span></span>`:'')+(a.genres||[]).filter(Boolean).map(x=>`<span class="ar-chip g">${esc(x)}</span>`).join('');
    nameHtml.i=0;
    body.innerHTML=`<div class="ar-pg" style="--h:${h}"><div class="ar-hero">${back}
      <div class="ar-ph"><i class="ar-rg"></i><i class="ar-rg r2"></i><div class="ar-fl"><div class="ar-fr"><div class="ar-pi"><em>${esc(ini(a.name))}</em>${arImg(a.img)}</div></div></div></div>
      <div class="ar-kick"><span>Исполнитель</span></div>
      <h2 class="ar-name">${nameHtml(a.name)}</h2>${chips?`<div class="ar-chips">${chips}</div>`:''}
      <div class="ar-act"><button class="btn ar-play" id="arPlay">${MI.play}Слушать</button><button class="btn ghost ar-rd" id="arRadio">${MI.wave}Радио</button><button class="btn ghost ar-sh" id="arSh" aria-label="Вперемешку">${MI.shuf}</button></div></div>
    ${five.length?`<div class="mu-h rv"><h3>Популярное</h3>${all.length>five.length?'<button class="ar-more" id="arMore">Все треки ›</button>':''}</div><div id="arTop" class="ar-rank"></div>`:''}
    ${all.length>five.length?`<div class="mu-h rv" id="arAllH"><h3>Все песни</h3><small class="ar-cnt">${all.length}</small></div><div id="arAll"></div>`:''}
    ${sa.length?`<div class="mu-h rv"><h3>Похожие исполнители</h3></div><div class="rv">${cards(sa)}</div>`:''}
    ${sim.length?`<div class="mu-h rv"><h3>Похожие песни</h3><button class="btn sm ghost" id="arSimPlay">${MI.play}Слушать</button></div><div id="arSim"></div>`:''}
    ${!all.length&&!sim.length?'<div class="empty" style="padding:24px">Песен исполнителя пока нет</div>':''}</div>`;
    $('[data-ab]',body).onclick=artistBack;
    const ln=$('.ar-num',body);if(ln)numUp(ln,a.sub);
    const put=(sel,arr,rk)=>{const el=$(sel,body);if(el){el.innerHTML=rk?`<div class="mu-list">${arr.map(rowR).join('')}</div>`:listHtml(arr);(rk?wireR:wire)(el,arr);if(!rk)$$('.mu-row',el).forEach(r=>r.classList.add('rv'))}};
    put('#arTop',five,1);put('#arAll',all);put('#arSim',sim);
    reveal(body);
    $('#arPlay',body).onclick=()=>{if(main.length)start(main,0);else toast('Нет треков для воспроизведения',1)};
    $('#arSh',body).onclick=()=>{if(main.length)start(shuffled(main),0)};
    /* радио исполнителя: его песни вперемешку с песнями похожих исполнителей */
    $('#arRadio',body).onclick=()=>{const l=shuffled(uniq(main.slice(0,25).concat(sim)));if(l.length)start(l,0);else toast('Нет треков для воспроизведения',1)};
    const mo=$('#arMore',body);if(mo)mo.onclick=()=>{const t=$('#arAllH',body);if(t)t.scrollIntoView({behavior:'smooth',block:'start'})};
    const sp=$('#arSimPlay',body);if(sp)sp.onclick=()=>start(sim,0);
    const sl=$('.ar-sim',body);if(sl)sl.onclick=e=>{const c=e.target.closest('[data-ar]');if(c)openArtist(c.dataset.ar)};
    /* фото чуть наклоняется вслед за пальцем */
    const ph=$('.ar-ph',body);
    if(ph&&!REDUCE){
      const tilt=(x,y)=>{ph.style.setProperty('--ry',x.toFixed(1)+'deg');ph.style.setProperty('--rx',y.toFixed(1)+'deg')};
      ph.addEventListener('pointermove',e=>{const r=ph.getBoundingClientRect();tilt(((e.clientX-r.left)/r.width-.5)*18,-((e.clientY-r.top)/r.height-.5)*18)});
      ['pointerleave','pointerup','pointercancel'].forEach(ev=>ph.addEventListener(ev,()=>tilt(0,0)))}
    const vw=$('#view');if(vw)vw.scrollTop=0}
  function artistBack(){st.artist=st.ahist.pop()||null;draw()}
  function draw(){
    const q=st.q.trim(),off=offline(),art=!!st.artist&&!off,srch=(st.tab==='search'||!!st.q)&&!off;
    rlw.hidden=art;dots.hidden=art||off;sb.hidden=!srch||art;x.hidden=!st.q;
    $('.mu',el).classList.toggle('mu-art',art);fx.set(art,art?346:(CARDS[curI]||CARDS[0]).h);
    if(!art)requestAnimationFrame(()=>fit());
    if(off)return offBody();
    if(q.length>=2)return search(q);
    if(q){body.innerHTML='';return}
    if(art)return artistPage(st.artist);
    if(st.tab==='search'){seq++;body.innerHTML=`<div class="empty" style="padding:28px 24px">Введите название трека, исполнителя<br>или строчку из песни</div>`;return}
    const pc=CARDS.find(c=>c.tab===st.tab&&c.q);
    if(pc)plist(pc);
    else if(st.tab==='likes'){collection(likes,'Отмечайте треки сердечком — они появятся здесь',true);
      const h=$('.mu-h',body);if(h&&likes.length){h.insertAdjacentHTML('beforeend',`<button class="btn sm ghost" id="muDlAll">${MI.dl}Скачать</button>`);$('#muDlAll',body).onclick=()=>dlMany(likes)}}
    else if(st.tab==='dl'){const l=dlList();collection(l,'Здесь будут скачанные треки. Нажмите ↓ в плеере или «Скачать» в «Любимом» — и они заиграют без интернета',true);
      const h=$('.mu-h',body);if(h&&l.length){h.insertAdjacentHTML('beforeend',`<button class="btn sm ghost" id="muDlClr">Очистить</button>`);$('#muDlClr',body).onclick=async()=>{if(await confirmBox('Удалить все скачанные треки?')){await dlClear();draw()}}}}
    else if(st.tab==='hist')collection(hist,'Вы пока ничего не слушали',false);
    else if(st.tab==='world')world();
    else home()}
  /* ---- живой фон: шёлковые волны, свечение и искры (canvas). На экране артиста — бордовый «шёлк» ---- */
  const REDUCE=(()=>{try{return matchMedia('(prefers-reduced-motion:reduce)').matches}catch(e){return false}})();
  const fx=(()=>{
    const cv=$('#muFx',el),g=cv.getContext('2d');
    let W=0,H=0,dpr=1,hue=250,hueT=250,inten=0,modeK=0,art=0,last=performance.now(),ph=0,lastDraw=0;
    const sp=Array.from({length:34},()=>({x:Math.random(),y:Math.random(),r:.5+Math.random()*1.5,s:.01+Math.random()*.03,p:Math.random()*6.28}));
    const lerp=(a,b,k)=>a+(b-a)*k;
    function size(){
      const w=cv.clientWidth,h=cv.clientHeight;if(!w||!h)return false;
      if(w===W&&h===H)return true;
      dpr=Math.min(window.devicePixelRatio||1,1.5);W=w;H=h;cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);return true}
    function glow(x,y,r,col){const gr=g.createRadialGradient(x,y,0,x,y,r);gr.addColorStop(0,col);gr.addColorStop(1,'hsla(0,0%,0%,0)');g.fillStyle=gr;g.fillRect(x-r,y-r,r*2,r*2)}
    /* пучок лент: n линий, фаза каждой чуть сдвинута — получается шёлковая лента */
    function ribbon(b,area,k,A,sx){
      const n=7,top=[],bot=[],pts=Math.max(14,Math.round(W/12));
      for(let j=0;j<n;j++){
        const line=[];
        for(let i=0;i<=pts;i++){
          const xn=i/pts,x=xn*W;
          const base=area*(.16+.26*b)+Math.sin(xn*2.4+ph*.35+b*2.1)*area*.05;
          const y=base+j*(7+5*Math.sin(xn*3+ph*.5+b))
            +A*Math.sin(xn*(3.1+b*.7)+ph*sx+b*1.7+j*.24)
            +A*.45*Math.sin(xn*(7+b)-ph*sx*1.3+j*.17);
          line.push(x,y)}
        if(j===0)top.push(...line);if(j===n-1)bot.push(...line);
        g.beginPath();g.moveTo(line[0],line[1]);for(let i=2;i<line.length;i+=2)g.lineTo(line[i],line[i+1]);
        const mid=1-Math.abs(j-(n-1)/2)/((n-1)/2);
        g.strokeStyle=`hsla(${hue+j*3},${art?70:45}%,${art?72:82}%,${(.05+.15*mid)*k})`;g.lineWidth=j===0||j===n-1?1.4:.9;g.stroke()}
      /* прозрачная заливка между крайними линиями — стеклянная лента */
      g.beginPath();g.moveTo(top[0],top[1]);for(let i=2;i<top.length;i+=2)g.lineTo(top[i],top[i+1]);
      for(let i=bot.length-2;i>=0;i-=2)g.lineTo(bot[i],bot[i+1]);g.closePath();
      const gr=g.createLinearGradient(0,area*.1,W,area*.9);
      gr.addColorStop(0,`hsla(${hue},70%,60%,0)`);gr.addColorStop(.5,`hsla(${hue},${art?80:50}%,${art?58:70}%,${(art?.1:.045)*k})`);gr.addColorStop(1,`hsla(${hue+20},70%,50%,0)`);
      g.fillStyle=gr;g.fill()}
    function draw(now,vel,force){
      if(!size())return;
      if(!force&&!vel&&now-lastDraw<32)return;lastDraw=now;
      const dt=Math.min(.05,(now-last)/1000);last=now;
      const play=document.body.classList.contains('mu-playing')?1:0;
      inten=lerp(inten,play,Math.min(1,dt*2));modeK=lerp(modeK,art?1:0,Math.min(1,dt*3));
      let dh=((hueT-hue+540)%360)-180;hue=(hue+dh*Math.min(1,dt*3)+360)%360;
      ph+=REDUCE?0:dt*(.4+inten*.55+Math.min(3,Math.abs(vel||0)*.22)+modeK*.12);
      g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);
      const area=lerp(Math.min(H,640),H,modeK);
      g.globalCompositeOperation='lighter';
      glow(W*(.8+.08*Math.sin(ph*.7)),area*(.1+.04*Math.cos(ph*.5)),W*.85,`hsla(${hue},75%,52%,${.2+.1*inten+.12*modeK})`);
      glow(W*(.1+.06*Math.cos(ph*.6)),area*(.55+.05*Math.sin(ph*.4)),W*.8,`hsla(${hue+25},60%,45%,${.1+.06*inten+.08*modeK})`);
      if(modeK>.02)glow(W*(.5+.15*Math.sin(ph*.3)),area*.42,W*.7,`hsla(${hue},80%,40%,${.14*modeK})`);
      const A=lerp(14,24,modeK)*(1+inten*.5),nb=art?4:3;
      for(let b=0;b<nb;b++)ribbon(b,area,lerp(1,1.15,modeK),A,.9+b*.18);
      for(const p of sp){
        p.y-=p.s*dt*(1+inten*2);if(p.y<-.02){p.y=1.02;p.x=Math.random()}
        const a=(.12+.4*(.5+.5*Math.sin(ph*2+p.p)))*(art?1.1:.8);
        g.fillStyle=`hsla(${hue+10},80%,88%,${a})`;g.beginPath();g.arc(p.x*W,p.y*area,p.r,0,6.283);g.fill()}
      g.globalCompositeOperation='source-over'}
    return{draw,size,set(a,h){art=a?1:0;hueT=a?346:h},hue:h=>{if(!art)hueT=h}}})();

  /* ---- рулетка: барабан. Карточки стоят по кругу, крутится пальцем с инерцией, останавливается ровно на карточке ---- */
  let vis=[],visK=[],N=0,cw=0,R=250,stepA=45,pos=0,vel=0,pv=0,pPos=0,pLast=performance.now(),md='idle',drag=null,anim=null,lastK=-1,swallow=0,miss=0,vibT=0,curI=cardOf(st.tab),started=0;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const mod=(a,n)=>((a%n)+n)%n;
  const wrapD=d=>N?mod(d+N/2,N)-N/2:0;
  const cds=()=>$$('.mu-cd',rl);
  const eoc=p=>1-Math.pow(1-p,3),eoq=p=>1-Math.pow(1-p,4);
  const tick=n=>{const t=Date.now();if(t-vibT<45)return;vibT=t;try{navigator.vibrate&&navigator.vibrate(n||4)}catch(e){}};
  function measure(){
    const cs=cds();if(!cs.length||!rl.clientWidth)return false;
    vis=[];visK=cs.map(()=>-1);cs.forEach((c,i)=>{if(!c.classList.contains('offh')){visK[i]=vis.length;vis.push(i)}});
    if(!vis.length)return false;N=vis.length;
    cw=cs[vis[0]].offsetWidth;if(!cw)return false;
    stepA=360/Math.max(N,8);R=cw*.98/(2*Math.sin(stepA*Math.PI/360));return true}
  function paintCards(now){
    if(!N)return;
    const cs=cds(),tm=now/1000;let best=0,bd=1e9;
    cs.forEach((c,i)=>{
      const k=visK[i];if(k<0)return;
      const rel=wrapD(k-pos),ad=Math.abs(rel);if(ad<bd){bd=ad;best=k}
      const a=rel*stepA,aa=Math.abs(a),ar=a*Math.PI/180;
      const x=R*Math.sin(ar),z=R*Math.cos(ar)-R,on=ad<.5;
      const bob=on?Math.sin(tm*1.7)*3.5*(1-ad*2):0;
      const op=aa<=45?1-aa/45*.2:Math.max(0,.8*(1-(aa-45)/36));
      c.style.transform=`translate3d(${x.toFixed(1)}px,${bob.toFixed(1)}px,${z.toFixed(1)}px) rotateY(${a.toFixed(1)}deg)`;
      c.style.opacity=op.toFixed(2);c.style.zIndex=String(100-Math.round(aa/1.5));c.style.visibility=op<.01?'hidden':'visible';
      c.style.setProperty('--dk',(Math.min(aa,90)/90*.55).toFixed(2));
      if(on!==c.classList.contains('on'))c.classList.toggle('on',on)});
    if(best!==lastK){
      if(lastK>=0)tick(4);lastK=best;
      $$('button',dots).forEach((b,i)=>b.classList.toggle('on',i===vis[best]));
      fx.hue(CARDS[vis[best]].h)}}
  function landed(){
    pos=mod(pos,N);if(pos>N-1e-6)pos=0;
    const k=Math.round(pos)%N,c=cds()[vis[k]];
    if(c){c.classList.remove('land');void c.offsetWidth;c.classList.add('land')}
    settle()}
  function stepPhys(now){
    const dt=Math.min(.05,Math.max(.001,(now-pLast)/1000));pLast=now;
    if(md==='fling'){pos+=vel*dt;vel*=Math.exp(-dt*2.3);if(Math.abs(vel)<1.1)md='snap'}
    else if(md==='snap'){const tg=Math.round(pos);pos+=(tg-pos)*(1-Math.exp(-dt*11));if(Math.abs(tg-pos)<.003){pos=tg;md='idle';vel=0;landed()}}
    else if(md==='spin'){const p=clamp((now-anim.t0)/anim.d,0,1);pos=anim.a+(anim.b-anim.a)*anim.e(p);if(p>=1){pos=anim.b;md='idle';anim=null;landed()}}
    pv=pv*.8+((pos-pPos)/dt)*.2;pPos=pos;
    paintCards(now)}
  function loop(now){
    if(!rl.isConnected){if(++miss>180)return;requestAnimationFrame(loop);return}
    miss=0;
    if(!document.hidden){
      if(!rlw.hidden&&N)stepPhys(now);
      fx.draw(now,rlw.hidden?0:(md==='drag'?vel:pv),0)}
    requestAnimationFrame(loop)}
  function fit(){
    if(rlw.hidden||!measure())return;
    const k=vis.indexOf(curI);pos=pPos=k<0?0:k;md='idle';anim=null;paintCards(performance.now())}
  function startAnim(b,d,e){anim={a:pos,b,t0:performance.now(),d,e};md='spin'}
  function goCard(i){
    if(!N&&!measure())return;
    const k=vis.indexOf(i);if(k<0)return;
    const d=wrapD(k-pos);if(Math.abs(d)<.001)return;
    startAnim(pos+d,clamp(260+Math.abs(d)*120,300,700),eoc)}
  /* случайный бросок: несколько оборотов и остановка на случайной карточке */
  function spin(){
    if(N<2||md==='spin')return;
    const cur_=Math.round(pos),dir=Math.random()<.5?-1:1;let k;
    do{k=Math.floor(Math.random()*N)}while(k===mod(cur_,N));
    const loops=2+Math.floor(Math.random()*2),far=dir>0?mod(k-pos,N):mod(pos-k,N);
    startAnim(pos+dir*(far+loops*N),2800+loops*450,eoq);tick(12)}
  /* когда барабан остановился — открываем раздел центральной карточки */
  function settle(){
    if(rlw.hidden||!N)return;
    const ci=vis[Math.round(pos)%N];
    if(ci===curI)return;
    curI=ci;const c=CARDS[ci];
    if(st.q&&c.k!=='search'){st.q='';inp.value=''}
    st.tab=c.tab;st.artist=null;st.ahist=[];draw();
    if(c.k==='search')setTimeout(()=>{try{inp.focus({preventScroll:true})}catch(e){}},250)}
  const PX=()=>Math.max(120,cw*.78);
  rl.addEventListener('pointerdown',e=>{
    if(rlw.hidden||N<2||(e.pointerType==='mouse'&&e.button))return;
    if(md==='fling'||md==='snap'||md==='spin'){md='hold';swallow=1;anim=null}
    drag={x:e.clientX,y:e.clientY,p0:pos,s:[[e.clientX,e.timeStamp]],on:0}});
  rl.addEventListener('pointermove',e=>{
    if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(!drag.on){if(Math.abs(dx)>7&&Math.abs(dx)>Math.abs(dy)*1.2){drag.on=1;md='drag';try{rl.setPointerCapture(e.pointerId)}catch(x){}}else return}
    pos=drag.p0-dx/PX();vel=0;
    drag.s.push([e.clientX,e.timeStamp]);while(drag.s.length>2&&e.timeStamp-drag.s[0][1]>110)drag.s.shift();
    const a=drag.s[0],b=drag.s[drag.s.length-1],dtm=(b[1]-a[1])/1000;vel=dtm>0?-(b[0]-a[0])/dtm/PX():0});
  const endDrag=e=>{
    if(!drag)return;const d=drag;drag=null;
    if(d.on){swallow=1;setTimeout(()=>{swallow=0},80);
      const stale=e&&d.s.length&&e.timeStamp-d.s[d.s.length-1][1]>90;
      vel=stale?0:clamp(vel,-16,16);md=Math.abs(vel)>1.5?'fling':'snap'}
    else if(md==='hold'){md='snap';setTimeout(()=>{swallow=0},80)}};
  rl.addEventListener('pointerup',endDrag);rl.addEventListener('pointercancel',endDrag);
  rl.onclick=e=>{
    if(swallow){swallow=0;return}
    const c=e.target.closest('.mu-cd');if(!c)return;const i=+c.dataset.i,k=visK[i];if(k<0)return;
    if(Math.abs(wrapD(k-pos))>.5){goCard(i);return}
    if(e.target.closest('[data-go]'))playCard(CARDS[i])};
  rl.onkeydown=e=>{const c=e.target.closest('.mu-cd');if(!c)return;
    if(e.key==='Enter'||e.key===' '){e.preventDefault();c.click()}
    else if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const k=mod(Math.round(pos)+(e.key==='ArrowRight'?1:-1),N);goCard(vis[k])}};
  dots.onclick=e=>{const b=e.target.closest('button[data-i]');if(b)goCard(+b.dataset.i)};
  const sb_=$('#muSpin',el);if(sb_)sb_.onclick=spin;
  /* кнопка «назад» в шапке на экране артиста возвращает к предыдущему артисту/списку */
  const hb=$('.mu-top .ib',el);
  if(hb)hb.addEventListener('click',e=>{if(st.artist&&!offline()){e.stopImmediatePropagation();e.preventDefault();artistBack()}},true);
  /* экран может быть ещё не в документе (собирается заранее) — ждём, пока появится ширина */
  let tries=0;const init=()=>{if(measure()){fit();if('ResizeObserver' in window)new ResizeObserver(()=>{fx.size();if(measure())fit()}).observe(rl)}else if(++tries<90)requestAnimationFrame(init)};init();
  requestAnimationFrame(loop);
  /* счётчики на карточках «Любимое»/«История» */
  const subs=()=>CARDS.forEach(c=>{const n=$('[data-sub="'+c.k+'"]',rl);if(n)n.textContent=subTxt(c)});
  inp.oninput=()=>{st.q=inp.value;x.hidden=!st.q;clearTimeout(timer);timer=setTimeout(draw,450)};
  inp.onkeydown=e=>{if(e.key==='Enter'){clearTimeout(timer);inp.blur();draw()}};
  x.onclick=()=>{st.q='';inp.value='';clearTimeout(timer);draw()};
  /* без интернета: остаётся одна карточка «Моя волна» (она играет скачанное), остальное скрыто */
  const offBody=()=>{seq++;const n=dlMeta.size;
    body.innerHTML=`<div class="mu-offn">${MI.dl}<b>Нет интернета</b><span>${n?'«Моя волна» включит скачанные треки вперемешку — их '+n:'Скачанных треков пока нет. Пока есть интернет, нажимайте ↓ в плеере или «Скачать» в «Любимом»'}</span></div>`};
  let wasOff=null;
  function applyNet(init){
    if(!init&&!rl.isConnected)return;
    const off=offline();if(off===wasOff)return;const first=wasOff===null;wasOff=off;if(first&&!off)return;
    $('.mu',el).classList.toggle('mu-off',off);
    $$('.mu-cd',rl).forEach(c=>c.classList.toggle('offh',off&&c.dataset.k!=='wave'));
    if(off){curI=cardOf('home');st.tab='home';st.q='';inp.value='';st.artist=null;st.ahist=[]}
    measure();fit();draw()}
  netFn=applyNet;
  subsFn=subs;applyNet(true);
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

dlLoad();
return{view,mount,stop,paint,profile,openArtist,net:()=>{if(netFn)netFn()}}})();
function viewMusic(el){MU.view(el)}
