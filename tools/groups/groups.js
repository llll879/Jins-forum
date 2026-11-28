/* ===== группы, каналы, упоминания, стикеры и эмодзи-паки (tools/groups/groups.js) ===== */
const gav=(g,cls='')=>{const l=esc((g.title||'?').trim().charAt(0).toUpperCase());return `<span class="av ${cls}" data-href="#/ginfo/${g.id}">${l}${g.av?`<img data-bsrc="/forum/api/groups/avatar/${g.id}?v=${S.gav||0}" onerror="this.remove()" alt="">`:''}</span>`};
const plN=(n,a,b,c)=>n+' '+plural(n,a,b,c);
const membersLbl=n=>plN(n,'участник','участника','участников');
const kindLbl=k=>k==='channel'?'Канал':'Группа';
/* ----- ссылки exg/имя и юзернеймы ----- */
const linkName=v=>String(v||'').trim().replace(/^https?:\/\/[^\/\s]+\//i,'').replace(/^(forum\/)?exg\//i,'').replace(/^@/,'').replace(/[?#].*$/,'').replace(/\/+$/,'');
const isLink=v=>/^(https?:\/\/[^\/\s]+\/)?(forum\/)?exg\/\S+$/i.test(String(v||'').trim());
const lnkFull=n=>(BASE||location.origin)+'/exg/'+n;
const copyLink=n=>copyText(lnkFull(n),'Ссылка скопирована');
const nameField=(val,ph)=>`<div class="nmf"><span>exg/</span><input class="nmi" maxlength="32" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="${esc(ph||'имя')}" value="${esc(val||'')}"></div><small class="nms"></small>`;
/* проверка имени на лету; возвращает функцию «текущее значение» */
function bindName(root,kind,ref,orig){
  const inp=$('.nmi',root),st=$('.nms',root);let tk=0,t;orig=(orig||'').toLowerCase();
  inp.oninput=()=>{inp.value=inp.value.replace(/[^A-Za-z0-9_]/g,'');clearTimeout(t);const v=inp.value.toLowerCase(),my=++tk;st.className='nms';
    if(!v||v===orig){st.textContent='';return}
    if(v.length<4){st.textContent='Минимум 4 символа';st.className='nms bad';return}
    st.textContent='Проверяю…';
    t=setTimeout(async()=>{try{const r=await api('/name/check?kind='+kind+'&id='+(ref||0)+'&name='+encodeURIComponent(v));if(my!==tk)return;st.className='nms '+(r.ok?'ok':'bad');st.textContent=r.ok?'Свободно':r.msg}catch(e){}},350)};
  return ()=>inp.value.trim().toLowerCase()}
/* окно «изменить ссылку» (для наборов) */
function nameSheet(kind,ref,cur,title){return new Promise(res=>{
  const bg=document.createElement('div');bg.className='sheet-bg';
  bg.innerHTML=`<div class="sheet"><div class="sh-t">${esc(title)}</div><div style="padding:0 6px">${nameField(cur)}<button class="btn" id="nsOk" type="button" style="width:100%;margin-top:14px">Сохранить</button></div></div>`;
  const get=bindName(bg,kind,ref,cur);let done=false;const fin=v=>{if(done)return;done=true;bg.remove();res(v)};
  bg.onclick=e=>{if(e.target===bg)fin(null)};$('#nsOk',bg).onclick=()=>{const v=get();fin(v&&v!==cur?v:null)};
  document.body.appendChild(bg);setTimeout(()=>{try{$('.nmi',bg).focus()}catch(e){}},60)})}
/* тап по стикеру в чате → страница его набора, где набор можно добавить себе */
async function openStickerPack(sid){
  try{const r=await api('/stickers/of?id='+sid);location.hash='#/pack/'+r.pack+(r.name?'/'+encodeURIComponent(r.name):'')}
  catch(e){toast(e.message,1)}}
/* открыть по ссылке: профиль / группа / канал / набор */
async function viewResolve(el,name){
  el.innerHTML='<div class="spin"></div>';
  try{const r=await api('/resolve?name='+encodeURIComponent(name));
    if(r.kind==='user')location.replace('#/u/'+r.id);
    else if(r.kind==='pack')location.replace('#/pack/'+r.id+'/'+encodeURIComponent(linkName(name)));
    else if(r.via==='invite'&&!r.member){const j=await post_('/groups/join',{code:r.invite});location.replace('#/g/'+j.id)}
    else location.replace('#/g/'+r.id)}
  catch(e){el.innerHTML=`${head('Ссылка')}${emptyBox('find',esc(e.message))}`}}
const hueOf=id=>`hsl(${(Math.abs(+id||0)*47)%360} 68% 70%)`;
const gSub=d=>{const t=d.typing||[];return d.recording==='video'?'записывает видеосообщение…':d.recording?'записывает голосовое…':t.length?(t.length>2?t.length+' человека печатают…':t.join(', ')+(t.length>1?' печатают…':' печатает…')):kindLbl(d.group.kind).toLowerCase()+' · '+membersLbl(d.group.members)};
const chatX=(peer,G)=>{const me=S.me?S.me.id:0;return G?
  {g:1,list:l=>'/groups/messages?id='+peer+'&limit='+l,ep:k=>'/groups/msg/'+k,body:o=>({gid:peer,...o}),send:'/groups/send',idf:'id',typing:o=>post_('/groups/typing',{id:peer,...o}),dk:'draft_'+me+'_g'+peer}:
  {g:0,list:l=>'/messages?peer='+peer+'&limit='+l,ep:k=>'/messages/'+k,body:o=>o,send:'/messages',idf:'peer',typing:o=>post_('/typing',{peer,...o}),dk:'draft_'+me+'_'+peer}};
function insertAtCaret(ta,t){
  if(ta.insertText){ta.insertText(t);return}
  const a=ta.selectionStart==null?ta.value.length:ta.selectionStart,b=ta.selectionEnd==null?a:ta.selectionEnd;ta.value=ta.value.slice(0,a)+t+ta.value.slice(b);const p=a+t.length;try{ta.setSelectionRange(p,p)}catch(e){}ta.dispatchEvent(new Event('input',{bubbles:true}));ta.focus()}

/* ----- поле ввода сообщения -----
   Ведёт себя как <textarea> (value, selectionStart/End, setSelectionRange, focus, события input/keydown),
   но эмодзи из паков, которые в тексте хранятся токеном :em123:, показываются картинками, а не буквами.
   Наружу текст всегда отдаётся в «токенной» форме — отправка, черновики, упоминания работают как раньше. */
function emField(div,max){
  const EMT=/:em(\d{1,9}):/g,tokLen=el=>(':em'+el.dataset.em+':').length;
  const emImg=id=>{const i=document.createElement('img'),path='/forum/api/stickers/img/'+id;
    i.className='cem';i.alt='🙂';i.draggable=false;i.contentEditable='false';i.dataset.em=id;i.dataset.bsrc=path;
    const u=typeof BLOBU!=='undefined'&&BLOBU.get(path);       // уже загруженная картинка — без мигания
    if(u&&(BTYPE.get(u)||'').indexOf('video/')!==0){i.src=u;i.dataset.bdone=path}
    return i};
  const nodesOf=str=>{const f=document.createDocumentFragment();let k=0,m;EMT.lastIndex=0;
    while((m=EMT.exec(str))){if(m.index>k)f.appendChild(document.createTextNode(str.slice(k,m.index)));f.appendChild(emImg(m[1]));k=m.index+m[0].length}
    if(k<str.length)f.appendChild(document.createTextNode(str.slice(k)));return f};
  /* DOM → текст с токенами */
  const ser=root=>{let o='';
    const w=n=>{
      if(n.nodeType===3){o+=n.nodeValue;return}
      if(n.nodeType!==1)return;
      if(n.dataset&&n.dataset.em){o+=':em'+n.dataset.em+':';return}
      if(n.tagName==='BR'){if(!(n.dataset&&n.dataset.s))o+='\n';return}
      const blk=(n.tagName==='DIV'||n.tagName==='P')&&n.parentNode===root;
      if(blk&&o&&o.slice(-1)!=='\n')o+='\n';
      n.childNodes.forEach(w)};
    root.childNodes.forEach(w);return o};
  const get=()=>ser(div);
  /* пустое поле должно быть по-настоящему пустым (иначе не покажется подсказка), а завершающий перевод строки — виден */
  const norm=()=>{
    div.querySelectorAll('br').forEach(b=>{if(b.dataset.s)b.remove()});
    if(!div.querySelector('[data-em]')&&!div.textContent){div.textContent='';return}
    if(get().slice(-1)==='\n'){const b=document.createElement('br');b.dataset.s='1';div.appendChild(b)}};
  let last={a:0,b:0};
  const posOf=(node,off)=>{const r=document.createRange();r.selectNodeContents(div);r.setEnd(node,off);return ser(r.cloneContents()).length};
  const inside=sel=>sel&&sel.rangeCount&&div.contains(sel.anchorNode)&&div.contains(sel.focusNode);
  const live=()=>{const sel=getSelection();if(!inside(sel))return null;const r=sel.getRangeAt(0);return{a:posOf(r.startContainer,r.startOffset),b:posOf(r.endContainer,r.endOffset)}};
  const remember=()=>{const l=live();if(l)last=l};
  const point=off=>{let n=0;
    const w=node=>{for(let i=0;i<node.childNodes.length;i++){const c=node.childNodes[i];
      if(c.nodeType===3){const l=c.nodeValue.length;if(off<=n+l)return[c,off-n];n+=l}
      else if(c.nodeType===1&&c.dataset&&c.dataset.em){const l=tokLen(c);if(off<=n)return[node,i];n+=l;if(off<=n)return[node,i+1]}   // внутри токена — ставим после картинки
      else if(c.nodeType===1&&c.tagName==='BR'){if(c.dataset&&c.dataset.s)continue;if(off<=n)return[node,i];n+=1}
      else if(c.nodeType===1){const r=w(c);if(r)return r}}
      return null};
    return w(div)||[div,div.childNodes.length]};
  const setSel=(a,b)=>{const len=get().length;a=Math.max(0,Math.min(a,len));b=b==null?a:Math.max(0,Math.min(b,len));
    last={a,b};const sel=getSelection();if(!sel)return;
    try{const r=document.createRange(),p=point(a),q=a===b?p:point(b);r.setStart(p[0],p[1]);r.setEnd(q[0],q[1]);sel.removeAllRanges();sel.addRange(r)}catch(e){}};
  const range=()=>{const l=live()||last,len=get().length;return[Math.min(l.a,len),Math.min(l.b,len)]};
  /* вставка текста (с токенами) на место выделения */
  const ins=(str,del)=>{str=String(str||'').replace(/\r\n?/g,'\n');if(!str&&!del)return;
    const cur=get(),[a,b]=range(),room=max?max-(cur.length-(b-a)):1e9;if(room<=0)return;
    if(str.length>room)str=str.slice(0,room);
    div.focus({preventScroll:true});
    setSel(a,b);const sel=getSelection();let r=sel.rangeCount?sel.getRangeAt(0):null;
    if(!r||!div.contains(r.startContainer)){r=document.createRange();r.selectNodeContents(div);r.collapse(false)}
    r.deleteContents();r.insertNode(nodesOf(str));div.normalize();norm();
    setSel(a+str.length);
    div.dispatchEvent(new Event('input',{bubbles:true}));
    const sc=div.scrollHeight>div.clientHeight;if(sc)div.scrollTop=div.scrollHeight};
  div.addEventListener('beforeinput',e=>{const t=e.inputType||'';
    if(t==='insertParagraph'||t==='insertLineBreak'){e.preventDefault();ins('\n');return}
    if(t==='insertFromPaste'||t==='insertFromDrop'||t==='insertFromYank'){const dt=e.dataTransfer,x=dt?dt.getData('text/plain'):'';e.preventDefault();if(x)ins(x);return}
    if(t==='insertText'&&max){const[a,b]=range();if(get().length-(b-a)+(e.data||'').length>max)e.preventDefault()}});
  div.addEventListener('input',e=>{if(e.isComposing)return;norm();if(max&&get().length>max){const v=get().slice(0,max);div.value=v;setSel(v.length)}});
  div.addEventListener('copy',e=>{const sel=getSelection();if(!inside(sel)||sel.isCollapsed)return;e.clipboardData.setData('text/plain',ser(sel.getRangeAt(0).cloneContents()));e.preventDefault()});
  div.addEventListener('cut',e=>{const sel=getSelection();if(!inside(sel)||sel.isCollapsed)return;e.clipboardData.setData('text/plain',ser(sel.getRangeAt(0).cloneContents()));e.preventDefault();ins('',true)});
  div.addEventListener('blur',remember);
  const onSel=()=>{if(!div.isConnected){document.removeEventListener('selectionchange',onSel);return}remember()};
  document.addEventListener('selectionchange',onSel);
  Object.defineProperty(div,'value',{configurable:true,
    get:get,
    set(v){v=String(v==null?'':v);if(v===get())return;div.textContent='';div.appendChild(nodesOf(v));norm();last={a:v.length,b:v.length};
      if(document.activeElement===div)setSel(v.length)}});
  Object.defineProperty(div,'selectionStart',{configurable:true,get:()=>range()[0]});
  Object.defineProperty(div,'selectionEnd',{configurable:true,get:()=>range()[1]});
  Object.defineProperty(div,'maxLength',{configurable:true,get:()=>max||-1});
  div.setSelectionRange=(a,b)=>setSel(a,b);
  div.insertText=ins;
  const nativeFocus=div.focus.bind(div);
  div.focus=o=>{const l=last;nativeFocus(o);setSel(l.a,l.b)};      // как у textarea: курсор остаётся там, где был
  return div}

/* ----- подсказка при вводе @ ----- */
function mentionBox(ta,form,getList){
  let box=null,items=[],idx=0,tok=0,range=null;
  const close=()=>{tok++;if(box){box.remove();box=null}items=[];range=null};
  const pick=u=>{if(!u||!range)return close();const v=ta.value,ins='@'+u.username+' ';ta.value=v.slice(0,range[0])+ins+v.slice(range[1]);const p=range[0]+ins.length;close();try{ta.setSelectionRange(p,p)}catch(e){}ta.dispatchEvent(new Event('input',{bubbles:true}));ta.focus()};
  const draw=()=>{if(!items.length){if(box){box.remove();box=null}return}
    if(!box){box=document.createElement('div');box.className='mnp';form.appendChild(box);const h=e=>{const r=e.target.closest('[data-i]');if(r){e.preventDefault();pick(items[+r.dataset.i])}};box.addEventListener('mousedown',h);box.addEventListener('touchstart',h,{passive:false})}
    box.innerHTML=items.map((u,i)=>`<div class="mni${i===idx?' on':''}" data-i="${i}">${av(u,'s')}<span><b>${esc(u.name)}</b><small>@${esc(u.username)}</small></span></div>`).join('')};
  const sync=async()=>{const pos=ta.selectionStart==null?ta.value.length:ta.selectionStart;const m=/(^|[\s(])@([A-Za-z0-9_]{0,32})$/.exec(ta.value.slice(0,pos));
    if(!m){close();return}
    const q=m[2];range=[pos-q.length-1,pos];const my=++tok;await sleep_(110);if(my!==tok)return;
    let list=[];try{list=await getList(q)}catch(e){}
    if(my!==tok||!range)return;items=list.slice(0,8);idx=0;draw()};
  const key=e=>{if(!box||!items.length)return false;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){idx=(idx+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;draw();e.preventDefault();return true}
    if(e.key==='Enter'||e.key==='Tab'){pick(items[idx]);e.preventDefault();return true}
    if(e.key==='Escape'){close();return true}return false};
  return {sync,key,close}}

/* ----- картинки для стикеров: ужимаем в WebP (или PNG), прозрачность сохраняется ----- */
const WEBP_OK=(()=>{try{return document.createElement('canvas').toDataURL('image/webp').indexOf('data:image/webp')===0}catch(e){return false}})();
/* анимацию (GIF, анимированный WebP, APNG, WebM) не перекодируем — canvas оставил бы один кадр */
function isAnimBytes(b){
  const s=(o,n)=>String.fromCharCode.apply(null,b.subarray(o,o+n));
  if(s(0,4)==='GIF8')return true;
  if(b[0]===0x1a&&b[1]===0x45&&b[2]===0xdf&&b[3]===0xa3)return true;
  if(s(0,4)==='RIFF'&&s(8,4)==='WEBP')return s(12,4)==='VP8X'&&!!(b[20]&2);
  if(b[0]===0x89&&s(1,3)==='PNG'){let p=8;while(p+8<=b.length){const n=((b[p]<<24)|(b[p+1]<<16)|(b[p+2]<<8)|b[p+3])>>>0,t=s(p+4,4);if(t==='acTL')return true;if(t==='IDAT'||t==='IEND')return false;p+=12+n}}
  return false}
async function fitImg(file,max,lim){
  try{if(file.type==='video/webm'||isAnimBytes(new Uint8Array(await file.slice(0,65536).arrayBuffer())))return file}catch(e){}
  return fitStatic(file,max,lim)}
function fitStatic(file,max,lim){return new Promise(res=>{
  const im=new Image(),u=URL.createObjectURL(file);
  im.onload=()=>{URL.revokeObjectURL(u);if(file.size<=lim&&Math.max(im.width,im.height)<=max&&/^image\/(png|webp)$/.test(file.type)){res(file);return}const k=Math.min(1,max/Math.max(im.width,im.height)),w=Math.max(1,Math.round(im.width*k)),h=Math.max(1,Math.round(im.height*k));
    const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(im,0,0,w,h);
    const enc=q=>new Promise(r=>c.toBlob(b=>r(b),WEBP_OK?'image/webp':'image/png',q));
    (async()=>{let b=await enc(.92);if(b&&b.size>lim&&WEBP_OK)b=await enc(.7);if(b&&b.size>lim&&WEBP_OK)b=await enc(.45);
      res(b?new File([b],'s.'+(WEBP_OK?'webp':'png'),{type:b.type}):file)})()};
  im.onerror=()=>{URL.revokeObjectURL(u);res(file)};im.src=u})}

/* ----- панель «эмодзи / стикеры» ----- */
const EMO=('😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😋 😛 😜 🤪 😝 🤑 🤗 🤭 🤔 🤨 😐 😑 😶 😏 😒 🙄 😬 😌 😔 😪 😴 😷 🤒 🤕 🤢 🤮 🥵 🥶 🥴 😵 🤯 🤠 🥳 😎 🤓 🧐 😕 😟 🙁 😮 😲 😳 🥺 😦 😨 😰 😥 😢 😭 😱 😖 😞 😓 😩 😫 🥱 😤 😡 😠 🤬 😈 💀 💩 🤡 👻 👽 🤖 😺 😹 😻 🙈 🙉 🙊 💋 💌 💘 💖 💗 💓 💞 💕 💔 ❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💯 💥 💫 💦 💨 💬 👋 ✋ 👌 🤌 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 👍 👎 ✊ 👊 👏 🙌 🤝 🙏 💪 🔥 ✨ ⭐ 🎉 🎊 🎁 🏆 🥇 👀 🧠 🫶 🚀 💎 💰 📌 ✅ ❌ ⚠️ ❓ ❗').split(' ');
const stkRecent=()=>{try{return JSON.parse(ls.get('stk_recent')||'[]')}catch(e){return[]}};
const stkPush=id=>{const a=[id,...stkRecent().filter(x=>x!==id)].slice(0,24);ls.set('stk_recent',JSON.stringify(a))};
/* ----- GIF: «Мои GIF» + поиск (GIPHY через сервер) ----- */
const gif={mine:[],web:false,items:[],next:'',q:'',ready:false,tk:0,more:false};
const gifBtn=(it,mine)=>`<button type="button" class="gi" data-gif="${esc(it.id)}" data-m="${mine?1:0}" style="aspect-ratio:${it.w&&it.h?Math.min(2.2,Math.max(.7,it.w/it.h)).toFixed(2):'1.33'}"><img data-bsrc="${esc(it.p)}" alt=""></button>`;
async function stkPanel(o){
  const ST=ls.get('stk_tab');let tab=ST==='e'?'e':ST==='g'&&o.gif?'g':'s',packs=[];gif.ready=false;gif.q='';gif.items=[];
  const bg=document.createElement('div');bg.className='sheet-bg';
  bg.innerHTML=`<div class="sheet stkp"><div class="stkh"><button class="tab" data-t="e" type="button">Эмодзи</button><button class="tab" data-t="s" type="button">Стикеры</button>${o.gif?'<button class="tab" data-t="g" type="button">GIF</button>':''}<span class="sp"></span><button class="ib" data-up="1" type="button" aria-label="Загрузить GIF" hidden>${IC.plus}</button><button class="ib" data-mg="1" type="button" aria-label="Мои наборы">${IC.gear}</button></div><div class="gsb" hidden><div class="search-box glass">${IC.search}<input id="gq" placeholder="Поиск GIF" autocomplete="off" enterkeyhint="search"></div></div><div class="sps"></div><div class="sgr"><div class="spin"></div></div></div>`;
  const sgr=$('.sgr',bg),sps=$('.sps',bg),close=()=>bg.remove();
  const cover=p=>p.items&&p.items[0]?`<img data-bsrc="/forum/api/stickers/img/${p.items[0].id}" alt="">`:'?';
  const drawGif=()=>{
    let h='';
    if(!gif.q&&gif.mine.length)h+=`<h4>Мои GIF</h4><div class="gg">${gif.mine.map(i=>gifBtn(i,1)).join('')}</div>`;
    if(gif.items.length)h+=(gif.q?'':'<h4>Популярные</h4>')+`<div class="gg">${gif.items.map(i=>gifBtn(i,0)).join('')}</div>`;
    else if(gif.ready&&gif.q)h+='<div class="none">Ничего не найдено</div>';
    if(!h)h=gif.ready?`<div class="none">${gif.web?'GIF не нашлось.':'Здесь будут ваши GIF.<br>Нажмите «+», чтобы загрузить свой, или сохраните GIF из чата: долгое нажатие на GIF → «Сохранить в мои GIF».'}</div>`:'<div class="spin"></div>';
    if(gif.web&&gif.items.length)h+='<div class="gpw">Powered by GIPHY</div>';
    sgr.innerHTML=h};
  const gifLoad=async()=>{const my=++gif.tk;gif.more=false;
    try{if(!gif.ready){const m=await api('/gifs/mine');if(my!==gif.tk)return;gif.mine=m.items;gif.web=!!m.web}
      if(gif.web){const d=await api('/gifs/search?q='+encodeURIComponent(gif.q));if(my!==gif.tk)return;gif.items=d.items;gif.next=d.next||'';if(d.off)gif.web=false}
      else{gif.items=[];gif.next=''}}
    catch(e){if(my!==gif.tk)return;toast(e.message,1)}
    gif.ready=true;if(tab==='g'&&bg.isConnected)drawGif()};
  const gifMore=async()=>{if(gif.more||!gif.next||gif.q!==$('#gq',bg).value.trim())return;gif.more=true;const my=gif.tk;
    try{const d=await api('/gifs/search?q='+encodeURIComponent(gif.q)+'&pos='+gif.next);if(my!==gif.tk)return;
      const have=new Set(gif.items.map(i=>i.id));gif.items=gif.items.concat(d.items.filter(i=>!have.has(i.id)));gif.next=d.next||'';if(tab==='g'&&bg.isConnected)drawGif()}
    catch(e){}finally{gif.more=false}};
  const draw=()=>{$$('.stkh .tab',bg).forEach(b=>b.classList.toggle('on',b.dataset.t===tab));
    $('.gsb',bg).hidden=$('[data-up]',bg).hidden=tab!=='g';sps.hidden=tab==='g';
    if(tab==='g'){if(gif.ready)drawGif();else{sgr.innerHTML='<div class="spin"></div>';gifLoad()}return}
    const kp=packs.filter(p=>p.kind===(tab==='e'?'emoji':'sticker')&&p.items.length);
    sps.innerHTML=(tab==='s'?'<button type="button" data-j="rec">🕘</button>':'<button type="button" data-j="std">😀</button>')+kp.map(p=>`<button type="button" data-j="${p.id}" title="${esc(p.title)}">${cover(p)}</button>`).join('');
    if(tab==='s'){const rec=stkRecent(),known=new Set();packs.forEach(p=>p.items.forEach(i=>known.add(i.id)));const rl=rec.filter(x=>known.has(x));
      sgr.innerHTML=(rl.length?`<h4 data-s="rec">Недавние</h4><div class="g">${rl.map(id=>`<button type="button" data-s="${id}"><img data-bsrc="/forum/api/stickers/img/${id}" alt=""></button>`).join('')}</div>`:'')+
        kp.map(p=>`<h4 data-s="${p.id}">${esc(p.title)}</h4><div class="g">${p.items.map(i=>`<button type="button" data-s="${i.id}"><img data-bsrc="/forum/api/stickers/img/${i.id}" alt=""></button>`).join('')}</div>`).join('')||
        (rl.length?'':'<div class="none">Наборов стикеров пока нет.<br>Нажмите ⚙ — там можно найти чужие наборы или создать свой.</div>')}
    else sgr.innerHTML=`<h4 data-s="std">Смайлики</h4><div class="g e">${EMO.map(e=>`<button type="button" data-e="${e}">${e}</button>`).join('')}</div>`+
        kp.map(p=>`<h4 data-s="${p.id}">${esc(p.title)}</h4><div class="g e">${p.items.map(i=>`<button type="button" data-e=":em${i.id}:"><img data-bsrc="/forum/api/stickers/img/${i.id}" alt=""></button>`).join('')}</div>`).join('')};
  bg.onclick=e=>{
    if(e.target===bg){close();return}
    const t=e.target.closest('[data-t]');if(t){tab=t.dataset.t;ls.set('stk_tab',tab);draw();return}
    if(e.target.closest('[data-up]')){pickFiles('image/gif',async fs=>{let ok=0;toast('Загрузка…');
      for(const f of fs){try{const fd=new FormData();fd.append('file',f,f.name||'a.gif');await api('/gifs/save',{method:'POST',form:fd});ok++}catch(er){toast(er.message,1);break}}
      if(ok){toast(ok>1?'GIF сохранены: '+ok:'GIF сохранён');gif.ready=false;if(bg.isConnected&&tab==='g')draw()}});return}
    const gi=e.target.closest('.gi[data-gif]');if(gi){if(gifLp){gifLp=false;return}close();o.gif(gi.dataset.gif);return}
    if(e.target.closest('[data-mg]')){close();location.hash='#/stickers';return}
    const j=e.target.closest('[data-j]');if(j){const h=$(`h4[data-s="${j.dataset.j}"]`,sgr);if(h)sgr.scrollTo({top:h.offsetTop-sgr.offsetTop-4,behavior:'smooth'});else sgr.scrollTo({top:0,behavior:'smooth'});return}
    const s=e.target.closest('button[data-s]');if(s){const id=+s.dataset.s;stkPush(id);close();o.sticker(id);return}
    const em=e.target.closest('[data-e]');if(em){o.emoji(em.dataset.e);try{navigator.vibrate&&navigator.vibrate(6)}catch(x){}}};
  /* GIF: долгое нажатие / правый клик — «Сохранить в мои GIF» или «Удалить»; поиск с задержкой; подгрузка при прокрутке */
  let gifLp=false,lpT=null;
  const gifMenu=async b=>{gifLp=true;try{navigator.vibrate&&navigator.vibrate(12)}catch(x){}
    const mine=b.dataset.m==='1',c=await sheet([mine?{ic:'trash',t:'Удалить из моих GIF',k:'d',bad:true}:{ic:'plus',t:'Сохранить в мои GIF',k:'s'}],'');setTimeout(()=>{gifLp=false},400);if(!c)return;
    try{if(c.k==='d')await post_('/gifs/delete',{id:b.dataset.gif});else await post_('/gifs/save',{ref:b.dataset.gif});toast(c.k==='d'?'Удалено':'GIF сохранён');gif.ready=false;draw()}catch(er){toast(er.message,1)}};
  sgr.addEventListener('pointerdown',e=>{const b=e.target.closest('.gi');clearTimeout(lpT);if(b){gifLp=false;lpT=setTimeout(()=>gifMenu(b),480)}});
  ['pointerup','pointercancel','scroll'].forEach(n=>sgr.addEventListener(n,()=>clearTimeout(lpT),{passive:true}));
  sgr.addEventListener('contextmenu',e=>{const b=e.target.closest('.gi');if(b){e.preventDefault();if(!gifLp)gifMenu(b)}});
  sgr.addEventListener('scroll',()=>{if(tab==='g'&&sgr.scrollTop+sgr.clientHeight>sgr.scrollHeight-260)gifMore()},{passive:true});
  let gqT;$('#gq',bg).oninput=e=>{clearTimeout(gqT);gqT=setTimeout(()=>{const v=e.target.value.trim();if(v===gif.q)return;gif.q=v;gif.next='';gif.items=[];sgr.innerHTML='<div class="spin"></div>';gifLoad()},350)};
  document.body.appendChild(bg);
  if(tab==='g')draw();
  try{packs=(await api('/stickers/mine')).packs}catch(e){if(tab!=='g')toast(e.message,1)}
  if(bg.isConnected&&tab!=='g')draw()}

/* ----- каталог групп и каналов ----- */
const gItemRow=g=>`<div class="crow" data-href="#/g/${g.id}">${gav(g,'l')}<span class="t"><b>${esc(g.title)}</b><small>${kindLbl(g.kind)} · ${membersLbl(g.members)}${g.username?' · exg/'+esc(g.username):''}${g.descr?' · '+esc(g.descr):''}</small></span>${g.member?'':'<span class="r"><span class="cnt">Открыть</span></span>'}</div>`;
async function viewGroupFind(el){
  el.innerHTML=`${head('Чаты и каналы')}<div class="search-box glass" style="margin-top:2px">${IC.search}<input id="gq" placeholder="Название или описание" autocomplete="off"></div>
  <div class="search-box glass" style="margin-top:8px">${IC.link}<input id="gc" placeholder="Ссылка exg/… или @имя" autocomplete="off" autocapitalize="none" spellcheck="false"><button class="btn sm" id="gcB" type="button" style="height:34px;padding:0 14px">Открыть</button></div><div id="gres"></div>`;
  let tk=0;const run=async()=>{const my=++tk,v=$('#gq',el).value.trim(),r=$('#gres',el);
    try{const d=await api('/groups/find?q='+encodeURIComponent(v));if(my!==tk)return;r.innerHTML=(d.items.length?`<div class="sec">${v?'Найдено':'Популярные'}</div>`+d.items.map(gItemRow).join(''):emptyBox('find','Публичных чатов и каналов не найдено'))}catch(e){toast(e.message,1)}};
  let t;$('#gq',el).oninput=()=>{clearTimeout(t);t=setTimeout(run,300)};run();
  const go=()=>{const c=linkName($('#gc',el).value);if(c)location.hash='#/n/'+encodeURIComponent(c)};
  $('#gcB',el).onclick=go;$('#gc',el).onkeydown=e=>{if(e.key==='Enter')go()}}

/* ----- создание ----- */
function viewGroupNew(el,kind,board){
  kind=kind==='channel'?'channel':'group';board=+board||0;const b=board?S.boards.find(x=>x.id==board):null;
  el.innerHTML=`${head(kind==='channel'?'Новый канал':'Новая группа')}<div style="padding:0 16px">
  <label class="lbl">Название</label><input class="inp" id="gt" maxlength="60" placeholder="${kind==='channel'?'Название канала':'Название группы'}" value="${b?esc(b.name):''}">
  <label class="lbl">Описание</label><textarea class="inp" id="gd" maxlength="300" style="min-height:90px"></textarea>
  ${b?`<p style="color:var(--dim)">${kind==='channel'?'Канал':'Чат'} раздела «${esc(b.name)}» — публичный, его модерируют админы.</p>`:
   `<div class="grow glass" id="gp" style="margin:18px 0 0"><span class="t"><b>Публичный</b><small>Виден в каталоге, вступить может любой. Иначе — только по ссылке-приглашению или по добавлению</small></span><i class="sw"></i></div>`}
  <div id="gnm" ${b?'':'hidden'}><label class="lbl">Ссылка (необязательно)</label>${nameField('',kind==='channel'?'имя_канала':'имя_группы')}</div>
  <p style="color:var(--dim);font-size:0.8125rem;margin:12px 2px 0">${kind==='channel'?'В канале пишут только владелец и админы, остальные читают и ставят реакции.':'Участников можно добавить после создания.'}</p>
  <button class="btn" id="gGo" style="width:100%;margin-top:18px">Создать</button></div>`;
  const gp=$('#gp',el),getNm=bindName($('#gnm',el),'group',0,'');
  if(gp)gp.onclick=()=>{$('.sw',gp).classList.toggle('on');$('#gnm',el).hidden=!$('.sw',gp).classList.contains('on')};
  $('#gGo',el).onclick=async()=>{const bt=$('#gGo',el);bt.disabled=true;
    try{const pub=gp?$('.sw',gp).classList.contains('on'):true;const r=await post_('/groups/create',{kind,title:$('#gt',el).value,descr:$('#gd',el).value,public:pub,username:pub?getNm():'',board_id:board||undefined});location.replace('#/g/'+r.id)}
    catch(e){toast(e.message,1);bt.disabled=false}}}

/* ----- карточка группы / канала ----- */
async function addMembersSheet(gid,done){
  const bg=document.createElement('div');bg.className='sheet-bg';
  bg.innerHTML=`<div class="sheet" style="min-height:50%"><div class="sh-t">Добавить участников</div><div class="search-box glass" style="margin:0 6px 8px">${IC.search}<input id="amq" placeholder="Имя или @ник" autocomplete="off"></div><div id="amr"></div></div>`;
  const close=()=>{bg.remove();if(done)done()};bg.onclick=e=>{if(e.target===bg)close()};
  let tk=0,t;const run=async()=>{const my=++tk,v=$('#amq',bg).value.trim(),r=$('#amr',bg);if(v.length<2){r.innerHTML='<div class="cl-empty" style="text-align:center;color:var(--dim);padding:20px">Введите минимум 2 символа</div>';return}
    try{const d=await api('/search?q='+encodeURIComponent(v));if(my!==tk)return;r.innerHTML=d.users.map(u=>`<div class="crow" data-u="${u.id}">${av(u,'m')}<span class="t"><b>${esc(u.name)}</b><small>${u.username?'@'+esc(u.username):''}</small></span><span class="r"><button class="btn sm" type="button">Добавить</button></span></div>`).join('')||'<div style="text-align:center;color:var(--dim);padding:20px">Никого не найдено</div>'}catch(e){toast(e.message,1)}};
  $('#amq',bg).oninput=()=>{clearTimeout(t);t=setTimeout(run,300)};run();
  $('#amr',bg).onclick=async e=>{const r=e.target.closest('[data-u]');if(!r)return;e.stopPropagation();const b=$('button',r);if(b.disabled)return;b.disabled=true;
    try{const x=await post_('/groups/add',{id:gid,user_ids:[+r.dataset.u]});b.textContent=x.added?'Добавлен':'Уже в чате'}catch(er){toast(er.message,1);b.disabled=false}};
  document.body.appendChild(bg)}
async function viewGroupInfo(el,id){
  let i=await api('/groups/info?id='+id),mm=await api('/groups/members?id='+id),members=mm.members,edit=false;
  const mrow=x=>`<div class="crow" data-mem="${x.user.id}" data-role="${x.role}">${av(x.user,'m')}<span class="t"><b>${esc(x.user.name)}${tags(x.user.sb)}</b><small>${x.user.username?'@'+esc(x.user.username):''}</small></span><span class="r">${x.role==='owner'?'Владелец':x.role==='admin'?'Админ':''}</span></div>`;
  const reload=async()=>{i=await api('/groups/info?id='+id);mm=await api('/groups/members?id='+id);members=mm.members;paint()};
  const gLink=()=>i.username||(i.invite?'+'+i.invite:'');
  function paint(){
    const g={id,title:i.title,kind:i.kind,av:i.av};
    el.innerHTML=`${head(kindLbl(i.kind),i.admin?`<button class="ib round" id="gEd" type="button" aria-label="Изменить">${IC.pencil}</button>`:'',"location.hash='#/g/"+id+"'")}
    <div class="ginfo-h">${gav(g,'xl')}<h2>${esc(i.title)}</h2><small>${kindLbl(i.kind)}${i.public?' · публичный':' · закрытый'} · ${membersLbl(i.members)}${i.board_name?' · раздел «'+esc(i.board_name)+'»':''}</small>${i.descr?`<p>${esc(i.descr)}</p>`:''}</div>
    ${edit?`<div style="padding:0 16px"><label class="lbl">Название</label><input class="inp" id="eT" maxlength="60" value="${esc(i.title)}"><label class="lbl">Описание</label><textarea class="inp" id="eD" maxlength="300" style="min-height:90px">${esc(i.descr)}</textarea>
      ${i.board?'':`<div class="grow glass" id="eP" style="margin:16px 0 0"><span class="t"><b>Публичный</b><small>Виден в каталоге</small></span><i class="sw ${i.public?'on':''}"></i></div>`}
      <div id="eNm" ${i.public?'':'hidden'}><label class="lbl">Ссылка</label>${nameField(i.username,i.kind==='channel'?'имя_канала':'имя_группы')}</div>
      <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap"><button class="btn" id="eS" type="button" style="flex:1">Сохранить</button><button class="btn ghost" id="eA" type="button">${sm('img',19)}Фото</button>${i.av?`<button class="btn bad" id="eAx" type="button">Убрать фото</button>`:''}</div></div>`:''}
    <div class="ginfo-a">${!i.member&&i.public?'<button class="btn" id="gJ" type="button">Вступить</button>':''}${i.member||i.admin?`<button class="btn" data-href="#/g/${id}">${sm('chat',19)}Открыть</button>`:''}${i.admin&&i.kind==='group'||i.admin&&i.kind==='channel'?'<button class="btn ghost" id="gAdd" type="button">'+sm('plus',19)+'Участники</button>':''}</div>
    ${i.member?`<div class="grow glass" id="gMu"><span class="t"><b>Уведомления</b><small>${i.muted?'Выключены':'Включены'}</small></span><i class="sw ${i.muted?'':'on'}"></i></div>`:''}
    ${gLink()?`<div class="grow glass" id="gInv"><span class="t"><b>Ссылка</b><small class="codebox">exg/${esc(gLink())}</small></span><span style="color:var(--acc);font-weight:600">Копировать</span></div>${i.admin&&!i.username&&i.invite?'<div style="text-align:center"><button class="btn ghost sm" id="gInvR" type="button">Сменить ссылку-приглашение</button></div>':''}`:''}
    <div class="sec">Участники · ${i.members}</div>
    <div id="gml">${members.map(mrow).join('')}</div>${mm.more?'<div class="grow glass" id="gMore" style="justify-content:center;min-height:48px">Показать ещё</div>':''}
    <div style="padding:18px 16px 30px;display:flex;flex-direction:column;gap:10px">${i.member&&!i.owner?'<button class="btn bad" id="gLv" type="button">Покинуть</button>':''}${i.owner?'<button class="btn bad" id="gDel" type="button">Удалить '+(i.kind==='channel'?'канал':'группу')+'</button>':''}</div>`;
    bind()}
  function bind(){
    const q=s=>$(s,el);
    if(q('#gEd'))q('#gEd').onclick=()=>{edit=!edit;paint()};
    if(q('#gJ'))q('#gJ').onclick=async()=>{try{await post_('/groups/join',{id});await reload()}catch(e){toast(e.message,1)}};
    if(q('#gAdd'))q('#gAdd').onclick=()=>addMembersSheet(id,reload);
    if(q('#gMu'))q('#gMu').onclick=async()=>{try{await post_('/groups/pref',{id,muted:!i.muted});await reload()}catch(e){toast(e.message,1)}};
    if(q('#gInv'))q('#gInv').onclick=()=>copyLink(gLink());
    if(q('#gInvR'))q('#gInvR').onclick=async()=>{if(!await confirmBox('Сменить ссылку? Старая перестанет работать.'))return;try{await post_('/groups/update',{id,reset_invite:true});await reload()}catch(e){toast(e.message,1)}};
    const getNm=q('#eNm')?bindName(q('#eNm'),'group',id,i.username):null;
    if(q('#eP'))q('#eP').onclick=()=>{$('.sw',q('#eP')).classList.toggle('on');q('#eNm').hidden=!$('.sw',q('#eP')).classList.contains('on')};
    if(q('#eS'))q('#eS').onclick=async()=>{try{const b={id,title:q('#eT').value,descr:q('#eD').value};if(q('#eP'))b.public=$('.sw',q('#eP')).classList.contains('on');if(getNm&&!q('#eNm').hidden)b.username=getNm();await post_('/groups/update',b);edit=false;await reload();toast('Сохранено')}catch(e){toast(e.message,1)}};
    if(q('#eA'))q('#eA').onclick=()=>pickFiles('image/*',async fs=>{try{const f=await fitImg(fs[0],512,400000),fd=new FormData();fd.append('id',id);fd.append('file',f,f.name||'a.png');await api('/groups/avatar',{method:'POST',form:fd});S.gav=(S.gav||0)+1;await reload();toast('Фото обновлено')}catch(e){toast(e.message,1)}});
    if(q('#eAx'))q('#eAx').onclick=async()=>{const fd=new FormData();fd.append('id',id);fd.append('remove','1');try{await api('/groups/avatar',{method:'POST',form:fd});S.gav=(S.gav||0)+1;await reload()}catch(e){toast(e.message,1)}};
    if(q('#gMore'))q('#gMore').onclick=async()=>{try{const r=await api('/groups/members?id='+id+'&off='+members.length);members=members.concat(r.members);mm.more=r.more;paint()}catch(e){toast(e.message,1)}};
    if(q('#gLv'))q('#gLv').onclick=async()=>{if(!await confirmBox('Покинуть '+(i.kind==='channel'?'канал':'группу')+'?'))return;try{await post_('/groups/leave',{id});location.hash='#/chats'}catch(e){toast(e.message,1)}};
    if(q('#gDel'))q('#gDel').onclick=async()=>{if(!await confirmBox('Удалить навсегда вместе со всеми сообщениями?'))return;try{await post_('/groups/delete',{id});location.hash='#/chats'}catch(e){toast(e.message,1)}};
    $$('#gml [data-mem]',el).forEach(r=>r.onclick=async ev=>{if(ev.target.closest('.av'))return;const uid=+r.dataset.mem,role=r.dataset.role;
      const rows=[{ic:'user',t:'Профиль',k:'p'}];
      if(i.admin&&uid!==S.me.id&&role!=='owner'){if(i.owner)rows.push({ic:'crown',t:role==='admin'?'Снять с админов':'Сделать админом',k:'r'});if(role!=='admin'||i.owner||!i.member)rows.push({ic:'trash',t:'Удалить из чата',k:'k',bad:true})}
      const c=await sheet(rows,'');if(!c)return;
      try{if(c.k==='p')location.hash='#/u/'+uid;else if(c.k==='r'){await post_('/groups/role',{id,user_id:uid,role:role==='admin'?'member':'admin'});await reload()}
        else if(c.k==='k'&&await confirmBox('Удалить участника?')){await post_('/groups/kick',{id,user_id:uid});await reload()}}catch(e){toast(e.message,1)}})}
  paint()}

/* ----- чат и канал раздела (кнопки на странице раздела) ----- */
async function boardChats(box,b){
  let items=[];try{items=(await api('/groups/board?id='+b.id)).items}catch(e){return}
  const have=k=>items.find(x=>x.kind===k);
  let h=items.map(gItemRow).join('');
  if(S.me.main)for(const k of ['group','channel'])if(!have(k))h+=`<div class="grow glass" data-href="#/gnew/${k}/${b.id}" style="min-height:52px;color:#d6d1ee;gap:10px">${sm('plus',20)}${k==='channel'?'Создать канал раздела':'Создать чат раздела'}</div>`;
  box.innerHTML=h?`<div class="sec" style="margin-top:0">Чаты раздела</div>${h}`:''}

/* ----- стикеры и эмодзи-паки ----- */
const packCover=p=>`<span class="av m sq">${p.cover?`<img data-bsrc="/forum/api/stickers/img/${p.cover}" alt="">`:'?'}</span>`;
const packRow=p=>`<div class="crow" data-href="#/pack/${p.id}">${packCover(p)}<span class="t"><b>${esc(p.title)}</b><small>${p.kind==='emoji'?'Эмодзи':'Стикеры'} · ${p.n} шт. · ${esc(p.owner)}${p.username?' · exg/'+esc(p.username):''}</small></span>${p.added?'':`<span class="r"><button class="btn sm" data-addp="${p.id}" type="button">Добавить</button></span>`}</div>`;
async function viewStickers(el){
  let mine=(await api('/stickers/mine')).packs;
  el.innerHTML=`${head('Стикеры и эмодзи',`<button class="ib round" id="pNew" type="button" aria-label="Создать набор">${IC.plus}</button>`,"location.hash='#/chats'")}
  <div id="pm"></div><div class="sec">Найти наборы</div>
  <div class="search-box glass" style="margin-top:2px">${IC.search}<input id="pq" placeholder="Название набора" autocomplete="off"></div>
  <div class="search-box glass" style="margin-top:8px">${IC.link}<input id="pc" placeholder="Ссылка на набор exg/…" autocomplete="off" autocapitalize="none" spellcheck="false"><button class="btn sm" id="pcB" type="button" style="height:34px;padding:0 14px">Добавить</button></div><div id="pr"></div>`;
  const drawMine=()=>{$('#pm',el).innerHTML=mine.length?`<div class="sec" style="margin-top:0">Мои наборы</div>`+mine.map(p=>packRow({...p,cover:p.items[0]&&p.items[0].id,added:true})).join(''):'<div class="cl-empty" style="text-align:center;color:var(--dim);padding:22px">У вас пока нет наборов.<br>Нажмите + чтобы создать свой, или найдите чужие ниже.</div>'};
  drawMine();
  let tk=0;const run=async()=>{const my=++tk,v=$('#pq',el).value.trim();try{const d=await api('/stickers/find?q='+encodeURIComponent(v));if(my!==tk)return;$('#pr',el).innerHTML=d.packs.length?d.packs.map(packRow).join(''):emptyBox('find','Наборов не найдено')}catch(e){toast(e.message,1)}};
  let t;$('#pq',el).oninput=()=>{clearTimeout(t);t=setTimeout(run,300)};run();
  el.addEventListener('click',async e=>{const b=e.target.closest('[data-addp]');if(!b)return;e.stopPropagation();e.preventDefault();b.disabled=true;
    try{await post_('/stickers/add',{id:+b.dataset.addp});b.remove();mine=(await api('/stickers/mine')).packs;drawMine();toast('Набор добавлен')}catch(er){toast(er.message,1);b.disabled=false}},true);
  const addByLink=async()=>{const c=linkName($('#pc',el).value);if(!c)return;try{const r=await post_('/stickers/add',{name:c});location.hash='#/pack/'+r.id}catch(e){toast(e.message,1)}};
  $('#pcB',el).onclick=addByLink;$('#pc',el).onkeydown=e=>{if(e.key==='Enter')addByLink()};
  /* плюс → тип набора → набор уже создан (название и ссылка выдаются сами) и открыт: остаётся нажать «+» и выбрать картинку */
  $('#pNew',el).onclick=async()=>{const k=await sheet([{ic:'sticker',t:'Набор стикеров',k:'sticker'},{ic:'smile',t:'Набор эмодзи (вставляются в текст)',k:'emoji'}],'Что создать?');if(!k)return;
    try{const r=await post_('/stickers/pack',{kind:k.k});location.hash='#/pack/'+r.id}catch(e){toast(e.message,1)}}}
async function viewPack(el,id,via){
  const qs=()=>'/stickers/pack?id='+id+(via?'&name='+encodeURIComponent(via):'');
  let p=(await api(qs())).pack;
  const emo=()=>p.kind==='emoji',lim=()=>emo()?163840:524288,mx=()=>emo()?128:512;
  const reload=async()=>{p=(await api(qs())).pack;paint()};
  function paint(){
    const plus=p.mine?`<div class="it add" id="pPlus" role="button" aria-label="Добавить картинку"><svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></div>`:'';
    el.innerHTML=`${head(esc(p.title),'',"history.back()")}
    <div class="ginfo-h"><small>${emo()?'Набор эмодзи':'Набор стикеров'} · ${p.n} шт. · автор ${esc(p.owner)}${p.public?'':' · закрытый'}</small></div>
    <div class="ginfo-a">${p.added?'<button class="btn ghost" id="pRm" type="button">Убрать из моих</button>':'<button class="btn" id="pAd" type="button">Добавить набор</button>'}</div>
    <div class="pk-grid ${emo()?'e':''}">${plus}${p.items.map(it=>`<div class="it" data-it="${it.id}"><img data-bsrc="/forum/api/stickers/img/${it.id}" alt="">${it.e?`<i>${esc(it.e)}</i>`:''}</div>`).join('')}</div>
    ${p.mine&&!p.items.length?`<p style="color:var(--dim);font-size:0.875rem;margin:16px 22px 0;text-align:center;line-height:1.45">Нажмите «+» и выберите ${emo()?'картинки — каждая станет эмодзи':'фото — оно сразу станет стикером'}. Можно выбрать несколько. Анимация тоже подходит: WebP, GIF, APNG или WebM (до ${emo()?256:1024} КБ).</p>`:''}
    ${emo()?'<p style="color:var(--dim);font-size:0.8125rem;margin:14px 18px 0">Эмодзи из набора вставляются в текст сообщения кнопкой 🙂 рядом с полем ввода.</p>':''}
    ${p.username?`<div class="grow glass" id="pCode" style="margin-top:16px"><span class="t"><b>Ссылка на набор</b><small class="codebox">exg/${esc(p.username)}</small></span><span style="color:var(--acc);font-weight:600">Копировать</span></div>`:''}
    ${p.mine?`<div class="sec">Управление</div><div class="grow glass" id="pPub"><span class="t"><b>Публичный</b><small>Виден в каталоге и поиске. Закрытый открывается только по ссылке</small></span><i class="sw ${p.public?'on':''}"></i></div>
      <div style="padding:10px 16px 30px;display:flex;flex-direction:column;gap:10px"><button class="btn ghost" id="pRen" type="button">${sm('pencil',19)}Переименовать</button><button class="btn ghost" id="pLn" type="button">${sm('link',19)}Изменить ссылку</button><button class="btn bad" id="pDel" type="button">Удалить набор</button></div>`:''}`;
    const q=s=>$(s,el);
    if(q('#pAd'))q('#pAd').onclick=async()=>{try{await post_('/stickers/add',{id,name:via||undefined});await reload();toast('Набор добавлен')}catch(e){toast(e.message,1)}};
    if(q('#pRm'))q('#pRm').onclick=async()=>{try{await post_('/stickers/remove',{id});await reload()}catch(e){toast(e.message,1)}};
    if(q('#pPub'))q('#pPub').onclick=async()=>{try{await post_('/stickers/pack/update',{id,public:!p.public});await reload()}catch(e){toast(e.message,1)}};
    if(q('#pCode'))q('#pCode').onclick=()=>copyLink(p.username);
    if(q('#pRen'))q('#pRen').onclick=async()=>{const t=prompt('Название набора',p.title);if(!t||!t.trim())return;try{await post_('/stickers/pack/update',{id,title:t});await reload()}catch(e){toast(e.message,1)}};
    if(q('#pLn'))q('#pLn').onclick=async()=>{const v=await nameSheet('pack',id,p.username||'','Ссылка на набор');if(!v)return;try{await post_('/stickers/pack/update',{id,username:v});await reload();toast('Ссылка изменена')}catch(e){toast(e.message,1)}};
    if(q('#pDel'))q('#pDel').onclick=async()=>{if(!await confirmBox('Удалить набор? У всех, кто его добавил, он пропадёт. Отправленные стикеры останутся в чатах.'))return;try{await post_('/stickers/pack/delete',{id});location.hash='#/stickers'}catch(e){toast(e.message,1)}};
    /* «+» → выбор фото → стикер добавлен. Без вопросов: смайлик к стикеру можно привязать позже (нажать на стикер) */
    if(q('#pPlus'))q('#pPlus').onclick=()=>pickImg(async fs=>{
      let ok=0;toast('Загрузка…');
      for(const f of fs){try{const x=await fitImg(f,mx(),lim()),fd=new FormData();fd.append('pack_id',id);fd.append('file',x,x.name||'s.png');await api('/stickers/item',{method:'POST',form:fd});ok++}catch(er){toast(er.message,1);break}}
      if(ok)toast(emo()?(ok>1?'Эмодзи добавлены: '+ok:'Эмодзи добавлено'):(ok>1?'Стикеры добавлены: '+ok:'Стикер добавлен'));await reload()},'image/*,video/webm');
    $$('.it[data-it]',el).forEach(n=>n.onclick=async()=>{if(!p.mine)return;
      const c=await sheet([...(emo()?[]:[{ic:'smile',t:'Смайлик для стикера',k:'e'}]),{ic:'trash',t:'Удалить из набора',k:'d',bad:true}],'');if(!c)return;
      try{if(c.k==='e'){const cur=(p.items.find(x=>x.id===+n.dataset.it)||{}).e||'';const e=prompt('Смайлик, с которым связан стикер',cur);if(e===null)return;await post_('/stickers/item/update',{id:+n.dataset.it,emoji:e})}
        else await post_('/stickers/item/delete',{id:+n.dataset.it});await reload()}catch(e){toast(e.message,1)}})}
  paint()}
