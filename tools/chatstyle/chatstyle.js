/* ===== Оформление чатов (обои, пузыри, текст) =====
   Настройки хранятся на устройстве: localStorage (параметры) + IndexedDB (своё фото-обои).
   Приоритет: настройки этого чата → настройки «для всех чатов» → стандартный вид.
   API: CS.attach(chatNode,key) → ctx;  CS.open(ctx);  CS.open({}) — настройки для всех чатов. */
const CS=(()=>{
  const uid=()=>S.me?S.me.id:0;
  const kAll=()=>'cs_'+uid()+'_all',kChat=k=>'cs_'+uid()+'_'+k;
  const DEF={wp:{t:'none',v:'',blur:0,dim:0,pat:'none',pop:20},out:{c:'',st:'grad'},inc:{c:''},rad:20,tail:1,fs:15,gap:7};
  const clone=o=>JSON.parse(JSON.stringify(o));
  const HEX=/^#[0-9a-f]{6}$/i,ST=['grad','solid','glass','outline'];
  const num=(v,a,b,d)=>typeof v==='number'&&isFinite(v)?Math.min(b,Math.max(a,Math.round(v))):d;
  /* любые данные из хранилища приводим к безопасному виду */
  function merge(o){
    const c=clone(DEF);if(!o||typeof o!=='object')return c;
    const w=o.wp||{},u=o.out||{},n=o.inc||{};
    if(['none','p','img','color'].includes(w.t))c.wp.t=w.t;
    c.wp.v=typeof w.v==='string'?w.v.slice(0,80):'';
    c.wp.blur=num(w.blur,0,20,0);c.wp.dim=num(w.dim,0,80,0);c.wp.pop=num(w.pop,5,50,20);
    c.wp.pat=['none','dots','grid','stars','waves','rhomb'].includes(w.pat)?w.pat:'none';
    if(c.wp.t==='color'&&!HEX.test(c.wp.v))c.wp.t='none';
    c.out.c=HEX.test(u.c||'')?u.c:'';c.out.st=ST.includes(u.st)?u.st:'grad';
    c.inc.c=HEX.test(n.c||'')?n.c:'';
    c.rad=num(o.rad,4,28,20);c.tail=o.tail===0?0:1;c.fs=num(o.fs,13,20,15);c.gap=num(o.gap,2,16,7);
    return c}
  const isDef=c=>JSON.stringify(c)===JSON.stringify(DEF);
  const load=k=>{try{const s=ls.get(k);return s?merge(JSON.parse(s)):null}catch(e){return null}};
  const eff=key=>(key&&load(kChat(key)))||load(kAll())||clone(DEF);

  /* ----- обои-пресеты и узоры ----- */
  const WPS=[
    {id:'night',n:'Ночь',bg:'linear-gradient(160deg,#0f0c29,#302b63 55%,#24243e)'},
    {id:'aurora',n:'Аврора',bg:'radial-gradient(120% 70% at 0% 0%,rgba(31,190,170,.75),transparent 60%),radial-gradient(100% 70% at 100% 100%,rgba(123,47,247,.8),transparent 62%)',c:'#0a0e1c'},
    {id:'sunset',n:'Закат',bg:'linear-gradient(170deg,#2a1b4d,#7a3f78 55%,#e9737f)'},
    {id:'ocean',n:'Океан',bg:'linear-gradient(170deg,#021b3a,#0b3d6e 55%,#1d78a8)'},
    {id:'forest',n:'Лес',bg:'linear-gradient(165deg,#07161a,#14463a 60%,#2a8a62)'},
    {id:'rose',n:'Роза',bg:'linear-gradient(160deg,#2a0f1d,#6b1f3f 60%,#c2456e)'},
    {id:'graphite',n:'Графит',bg:'linear-gradient(180deg,#141418,#2a2a33)'},
    {id:'cream',n:'Сливки',light:1,bg:'linear-gradient(160deg,#f8f0e3,#e6d8c1)'},
    {id:'mint',n:'Мята',light:1,bg:'linear-gradient(160deg,#e4f6ee,#c3e6d8)'},
    {id:'marble',n:'Мрамор',img:1},{id:'clouds',n:'Облака',img:1},{id:'city',n:'Город',img:1},{id:'temple',n:'Храм',img:1},{id:'colon',n:'Колоннада',img:1}
  ];
  const PRE={};WPS.forEach(p=>PRE[p.id]=p);
  const PATS={
    dots:{n:'Точки',s:"<svg xmlns='http://www.w3.org/2000/svg' width='26' height='26'><circle cx='3' cy='3' r='1.5' fill='white'/><circle cx='16' cy='16' r='1.5' fill='white'/></svg>"},
    grid:{n:'Сетка',s:"<svg xmlns='http://www.w3.org/2000/svg' width='34' height='34'><path d='M34 0H0v34' fill='none' stroke='white' stroke-width='1'/></svg>"},
    stars:{n:'Звёзды',s:"<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'><path d='M12 5l1.7 4.6L18 11.5l-4.3 1.9L12 18l-1.7-4.6L6 11.5l4.3-1.9z' fill='white'/><path d='M56 46l1 2.8 2.8 1.2-2.8 1.2-1 2.8-1-2.8-2.8-1.2 2.8-1.2z' fill='white'/><circle cx='64' cy='14' r='1.3' fill='white'/><circle cx='30' cy='62' r='1.3' fill='white'/></svg>"},
    waves:{n:'Волны',s:"<svg xmlns='http://www.w3.org/2000/svg' width='44' height='22'><path d='M0 11q11-11 22 0t22 0' fill='none' stroke='white' stroke-width='1.2'/></svg>"},
    rhomb:{n:'Ромбы',s:"<svg xmlns='http://www.w3.org/2000/svg' width='36' height='36'><path d='M18 4l14 14-14 14L4 18z' fill='none' stroke='white' stroke-width='1.1'/></svg>"}
  };
  const patUrl=id=>'url("data:image/svg+xml,'+encodeURIComponent(PATS[id].s)+'")';
  const OUTC=['#4a90ff','#2fb5a2','#3fbf6a','#e8638b','#ef8a3c','#e0525f','#7a8296','#101014','#f2f0ea'];
  const INC=['#4a90ff','#2fb5a2','#3fbf6a','#e8638b','#ef8a3c','#9d92e6','#7a8296'];

  const lum=h=>{const n=parseInt(h.slice(1),16),f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};return .2126*f(n>>16)+.7152*f((n>>8)&255)+.0722*f(n&255)};

  /* ----- своё фото: IndexedDB (в памяти, если IndexedDB недоступна) ----- */
  const mem={},urls={};
  const idb=()=>new Promise((res,rej)=>{try{const r=indexedDB.open('kf_cs',1);r.onupgradeneeded=()=>r.result.createObjectStore('wp');r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error)}catch(e){rej(e)}});
  const idbDo=(mode,fn)=>idb().then(db=>new Promise((res,rej)=>{const q=fn(db.transaction('wp',mode).objectStore('wp'));q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)}));
  const putImg=async(k,b)=>{try{await idbDo('readwrite',s=>s.put(b,k));delete mem[k];return true}catch(e){mem[k]=b;return false}};
  const delImg=k=>{delete mem[k];if(urls[k]){try{URL.revokeObjectURL(urls[k].u)}catch(e){}delete urls[k]}return idbDo('readwrite',s=>s.delete(k)).catch(()=>{})};
  async function imgUrl(k,rev){
    const c=urls[k];if(c&&c.rev===rev)return c.u;
    let b=mem[k];if(!b)try{b=await idbDo('readonly',s=>s.get(k))}catch(e){}
    if(!b)return'';if(c)try{URL.revokeObjectURL(c.u)}catch(e){}
    const u=URL.createObjectURL(b);urls[k]={rev,u};return u}
  /* сжимаем до 1440px по длинной стороне — хватает для телефона и не раздувает хранилище */
  const fit=(file,max=1440)=>new Promise((res,rej)=>{const u=URL.createObjectURL(file),im=new Image();
    im.onload=()=>{try{const k=Math.min(1,max/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=Math.max(1,Math.round(im.width*k));c.height=Math.max(1,Math.round(im.height*k));
      c.getContext('2d').drawImage(im,0,0,c.width,c.height);c.toBlob(b=>{URL.revokeObjectURL(u);b?res(b):rej(new Error('Не удалось обработать фото'))},'image/jpeg',.84)}catch(e){URL.revokeObjectURL(u);rej(e)}};
    im.onerror=()=>{URL.revokeObjectURL(u);rej(new Error('Не удалось открыть изображение'))};im.src=u});

  /* ----- применить настройки к узлу (чат или превью) ----- */
  const VARS=['--cs-r','--cs-rt','--cs-fs','--cs-gap','--cs-me-c','--cs-me-ink','--cs-me-tint','--cs-in-c'];
  function apply(node,c){
    const st=node.style;VARS.forEach(v=>st.removeProperty(v));
    let wp=node.querySelector(':scope>.cs-wp');
    ['data-cs','data-cs-wp','data-cs-out','data-cs-in'].forEach(a=>node.removeAttribute(a));
    if(isDef(c)){if(wp)wp.remove();return}
    node.setAttribute('data-cs','1');
    st.setProperty('--cs-r',c.rad+'px');st.setProperty('--cs-rt',(c.tail?Math.min(6,c.rad):c.rad)+'px');
    st.setProperty('--cs-fs',c.fs+'px');st.setProperty('--cs-gap',c.gap+'px');
    if(c.out.c||c.out.st!=='grad'){
      const base=c.out.c||'#f2f2f2',light=lum(base)>.5,own=c.out.st==='glass'||c.out.st==='outline';
      node.setAttribute('data-cs-out',c.out.st);st.setProperty('--cs-me-c',base);
      st.setProperty('--cs-me-ink',own?'var(--txt)':light?'#15131c':'#fff');
      st.setProperty('--cs-me-tint',own?'rgba(127,127,127,.18)':light?'rgba(0,0,0,.1)':'rgba(255,255,255,.2)')}
    if(c.inc.c){node.setAttribute('data-cs-in','1');st.setProperty('--cs-in-c',c.inc.c)}
    const w=c.wp;
    if(w.t==='none'||(w.t==='p'&&!PRE[w.v])){if(wp)wp.remove();return}
    node.setAttribute('data-cs-wp','1');
    if(!wp){wp=document.createElement('div');wp.className='cs-wp';wp.innerHTML='<div class="cs-wp-b"></div><div class="cs-wp-p"></div>';node.insertBefore(wp,node.firstChild)}
    const b=wp.firstChild,p=wp.lastChild;
    wp.style.setProperty('--cs-blur',w.blur);wp.style.setProperty('--cs-sc',w.blur>0?1+Math.min(.25,w.blur*.012):1);
    wp.style.setProperty('--cs-dim',w.dim/100);wp.style.setProperty('--cs-pop',w.pop/100);
    b.removeAttribute('data-p');delete b.dataset.k;b.style.backgroundImage='';b.style.backgroundColor='';
    if(w.t==='color')b.style.backgroundColor=w.v;
    else if(w.t==='p'){const pr=PRE[w.v];if(pr.img)b.dataset.p=w.v;else{b.style.backgroundImage=pr.bg;if(pr.c)b.style.backgroundColor=pr.c}}
    else if(w.t==='img'){const [k,rev]=String(w.v).split(':');b.dataset.k=w.v;imgUrl(k,rev).then(u=>{if(b.dataset.k===w.v&&u)b.style.backgroundImage='url("'+u+'")'})}
    p.style.backgroundImage=w.pat!=='none'&&PATS[w.pat]?patUrl(w.pat):''}

  const ICON='<svg class="i" viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1 .8-1.7 1.8-1.7H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/></svg>';
  const PLUS='<svg class="i" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>';

  /* ----- панель настроек ----- */
  function open(ctx){
    ctx=ctx||{};if(document.querySelector('.cs-bg'))return;
    let scope=ctx.key?'chat':'all',cfg,prev;
    const keyOf=()=>scope==='chat'?kChat(ctx.key):kAll();
    const start=()=>clone(scope==='chat'?(load(kChat(ctx.key))||load(kAll())||DEF):(load(kAll())||DEF));
    cfg=start();
    const sw=(path,val,cls,style)=>`<button type="button" class="cs-sw ${cls||''}" data-k="${path}" data-v="${val}" ${style?`style="background:${style}"`:''} aria-label="${val||'По умолчанию'}"></button>`;
    const sl=(path,label,a,b,unit)=>`<div class="cs-sl" data-sl="${path}"><span>${label}</span><input type="range" min="${a}" max="${b}" step="1" data-r="${path}"><b></b></div>`;
    const bg=document.createElement('div');bg.className='cs-bg';
    bg.innerHTML=`<div class="cs-panel" role="dialog" aria-label="Оформление чата"><div class="cs-grip"></div>
      <div class="cs-top"><h3>Оформление</h3><button class="btn sm" type="button" id="csOk">Готово</button></div>
      ${ctx.key?`<div class="cs-scope"><button class="tab" type="button" data-scope="chat">Этот чат</button><button class="tab" type="button" data-scope="all">Все чаты</button></div>`:''}
      <p class="cs-hint" id="csHint"></p>
      <div class="cs-prev" id="csPrev"><div class="cday">Сегодня</div><div class="msg">Привет! Как тебе новый вид?<small>12:30</small></div><div class="msg me">Выглядит круто ✨<small>12:31 ✓✓</small></div></div>

      <span class="cs-sec">Обои</span>
      <div class="cs-row">
        <button type="button" class="cs-tile" data-wp="none">Нет</button>
        ${WPS.map(p=>p.img?`<button type="button" class="cs-tile" data-p="${p.id}" data-wp="p:${p.id}">${p.n}</button>`:`<button type="button" class="cs-tile" data-wp="p:${p.id}" style="background-image:${p.bg};${p.c?'background-color:'+p.c+';':''}${p.light?'color:#2a2530;text-shadow:none':''}">${p.n}</button>`).join('')}
        <label class="cs-tile col" data-wp="color">${PLUS}<input type="color" id="csWc" value="#3a3560" aria-label="Свой цвет"></label>
        <label class="cs-tile" data-wp="img">${PLUS}<span style="position:absolute;bottom:8px">Фото</span><input type="file" id="csFile" accept="image/*" style="display:none"></label>
      </div>
      <div id="csWpOpts">
        ${sl('wp.blur','Размытие',0,20)}${sl('wp.dim','Затемнение',0,80)}
        <span class="cs-sec" style="margin-top:16px">Узор поверх обоев</span>
        <div class="cs-chips"><button class="tab" type="button" data-k="wp.pat" data-v="none">Нет</button>${Object.keys(PATS).map(k=>`<button class="tab" type="button" data-k="wp.pat" data-v="${k}">${PATS[k].n}</button>`).join('')}</div>
        ${sl('wp.pop','Яркость узора',5,50)}
      </div>

      <span class="cs-sec">Мои сообщения</span>
      <div class="cs-chips">${[['grad','Градиент'],['solid','Сплошной'],['glass','Стекло'],['outline','Контур']].map(([k,n])=>`<button class="tab" type="button" data-k="out.st" data-v="${k}">${n}</button>`).join('')}</div>
      <div class="cs-wrap">${sw('out.c','','auto')}${OUTC.map(c=>sw('out.c',c,'',c)).join('')}<label class="cs-sw col" data-list="out.c"><input type="color" data-ck="out.c" value="#6d64b6" aria-label="Свой цвет"></label></div>

      <span class="cs-sec">Входящие</span>
      <div class="cs-wrap">${sw('inc.c','','auto inc')}${INC.map(c=>sw('inc.c',c,'',c)).join('')}<label class="cs-sw col" data-list="inc.c"><input type="color" data-ck="inc.c" value="#6d64b6" aria-label="Свой цвет"></label></div>

      <span class="cs-sec">Форма и текст</span>
      ${sl('rad','Скругление',4,28)}${sl('fs','Размер текста',13,20)}${sl('gap','Интервал',2,16)}
      <div class="cs-chips" style="margin:14px 0 0"><button class="tab" type="button" data-k="tail" data-v="1">С хвостиком</button><button class="tab" type="button" data-k="tail" data-v="0">Без хвостика</button></div>

      <div class="cs-foot"><button class="btn ghost" type="button" id="csReset">Сбросить</button></div>
    </div>`;
    document.body.appendChild(bg);
    const panel=bg.firstChild;prev=$('#csPrev',panel);
    const get=path=>path.split('.').reduce((o,k)=>o[k],cfg);
    const UNIT={'wp.dim':'%','wp.pop':'%',rad:'px',fs:'px',gap:'px'};

    function paint(){
      $$('[data-k]',panel).forEach(b=>{if(b.tagName==='INPUT')return;b.classList.toggle('on',String(get(b.dataset.k))===b.dataset.v)});
      $$('[data-list]',panel).forEach(b=>{const v=get(b.dataset.list),list=b.dataset.list==='out.c'?OUTC:INC;b.classList.toggle('on',!!v&&!list.includes(v));if(v)$('input',b).value=v});
      $$('[data-wp]',panel).forEach(b=>{const w=cfg.wp,a=b.dataset.wp;
        b.classList.toggle('on',a==='none'?w.t==='none':a==='color'?w.t==='color':a==='img'?w.t==='img':(w.t==='p'&&a==='p:'+w.v))});
      if(cfg.wp.t==='color')$('#csWc',panel).value=cfg.wp.v;
      $$('[data-r]',panel).forEach(r=>{const v=get(r.dataset.r);if(document.activeElement!==r)r.value=v;r.nextElementSibling.textContent=v+(UNIT[r.dataset.r]||'')});
      $('[data-sl="wp.pop"]',panel).hidden=cfg.wp.pat==='none';
      $('[data-sl="wp.blur"]',panel).hidden=$('[data-sl="wp.dim"]',panel).hidden=cfg.wp.t==='none';
      $$('[data-scope]',panel).forEach(b=>b.classList.toggle('on',b.dataset.scope===scope));
      $('#csHint',panel).textContent=ctx.key?(scope==='chat'?'Только для этого диалога.':'Для всех чатов, где не задано своё оформление.'):'Для всех чатов. Отдельный чат можно оформить по кнопке с палитрой в его шапке.';
      apply(prev,cfg);
      if(ctx.node)apply(ctx.node,eff(ctx.key))}
    function persist(){
      const k=keyOf();
      if(scope==='all'&&isDef(cfg))ls.del(k);else ls.set(k,JSON.stringify(cfg));
      paint()}
    const set=(path,val)=>{const a=path.split('.');let o=cfg;while(a.length>1)o=o[a.shift()];o[a[0]]=val;persist()};

    panel.addEventListener('click',e=>{
      const sc=e.target.closest('[data-scope]');if(sc){scope=sc.dataset.scope;cfg=start();paint();return}
      const k=e.target.closest('[data-k]');
      if(k&&k.tagName!=='INPUT'){const v=k.dataset.v;set(k.dataset.k,k.dataset.k==='tail'?+v:v);return}
      const w=e.target.closest('[data-wp]');
      if(w&&!e.target.closest('input')){const a=w.dataset.wp;
        if(a==='none'){cfg.wp.t='none';cfg.wp.v='';persist()}
        else if(a.startsWith('p:')){const id=a.slice(2);cfg.wp.t='p';cfg.wp.v=id;
          if(PRE[id].img){cfg.wp.dim=30;cfg.wp.blur=3}else{cfg.wp.dim=0;cfg.wp.blur=0}persist()}}});
    panel.addEventListener('input',e=>{
      const r=e.target.closest('[data-r]');if(r){set(r.dataset.r,+r.value);return}
      const c=e.target.closest('[data-ck]');if(c){set(c.dataset.ck,c.value);return}
      if(e.target.id==='csWc'){cfg.wp.t='color';cfg.wp.v=e.target.value;persist()}});
    $('#csFile',panel).onchange=async e=>{
      const f=e.target.files&&e.target.files[0];e.target.value='';if(!f)return;
      try{
        const b=await fit(f),k=keyOf(),ok=await putImg(k,b);
        cfg.wp.t='img';cfg.wp.v=k+':'+Date.now();if(!cfg.wp.dim)cfg.wp.dim=25;persist();
        if(!ok)toast('Фото применено, но после перезагрузки пропадёт: хранилище браузера недоступно',1)}
      catch(er){toast(er.message||'Не удалось загрузить фото',1)}};
    $('#csReset',panel).onclick=()=>{
      const k=keyOf();ls.del(k);delImg(k);cfg=start();if(scope==='all')cfg=clone(DEF);paint();toast('Оформление сброшено')};

    const close=()=>{window.removeEventListener('hashchange',close);bg.remove()};
    $('#csOk',panel).onclick=close;bg.onclick=e=>{if(e.target===bg)close()};
    window.addEventListener('hashchange',close);
    paint();
    const on=$('.cs-row .cs-tile.on',panel);if(on){const row=on.parentNode;row.scrollLeft=Math.max(0,on.offsetLeft-row.clientWidth/2+on.offsetWidth/2)}}

  /* привязать оформление к открытому чату; key: 'd<peer>' или 'g<id>' */
  function attach(node,key){const ctx={node,key};apply(node,eff(key));return ctx}

  return{attach,open,icon:ICON}
})();
