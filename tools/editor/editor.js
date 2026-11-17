const KE=(()=>{
'use strict';
/* Редактор вложений: фото — рисование, обрезка, поворот; видео — рисование, обрезка кадра, обрезка длины.
   KE.edit(file,{limit}) -> Promise<{file,changed}|null>. Всё делается на устройстве, на сервер уходит готовый файл. */
const COLORS=['#ff3b30','#ffcc00','#34c759','#0a84ff','#ffffff','#000000'];
const RATIOS=[['free','Свободно',0],['1:1','1:1',1],['4:3','4:3',4/3],['3:4','3:4',3/4],['16:9','16:9',16/9],['9:16','9:16',9/16]];
const MAXIMG=2048,MAXVID=1280;
const E=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic=(b,w)=>`<svg viewBox="0 0 24 24" width="${w||22}" height="${w||22}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${b}</svg>`;
const I={
 x:ic('<path d="M6 6l12 12M18 6 6 18"/>'),ok:ic('<path d="m5 12.5 4.5 4.5L19 7.5"/>',24),undo:ic('<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>'),
 rot:ic('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
 pen:ic('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
 mark:ic('<path d="m9 11-5 5v4h4l5-5"/><path d="m9 11 6-6 4 4-6 6z"/>'),
 arrow:ic('<path d="M5 19 19 5M9 5h10v10"/>'),rect:ic('<rect x="4" y="5" width="16" height="14" rx="2"/>'),
 text:ic('<path d="M5 6V4h14v2M12 4v16M9 20h6"/>'),
 draw:ic('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',20),
 crop:ic('<path d="M6 2v14a2 2 0 0 0 2 2h14M2 6h14a2 2 0 0 1 2 2v14"/>',20),
 trim:ic('<path d="M7 4v16M17 4v16M7 12h10"/>',20),
 play:'<svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M8.2 5.3v13.4a1 1 0 0 0 1.5.86l10.6-6.7a1 1 0 0 0 0-1.72L9.7 4.44a1 1 0 0 0-1.5.86z"/></svg>',
 pause:'<svg viewBox="0 0 24 24" width="22" height="22"><rect x="6" y="5" width="4.2" height="14" rx="1.4" fill="currentColor"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.4" fill="currentColor"/></svg>'};
const fmtT=s=>{s=Math.max(0,s);const m=Math.floor(s/60),r=s-m*60;return m+':'+(r<10?'0':'')+r.toFixed(1)};
const once=(el,ev)=>new Promise((res,rej)=>{const ok=()=>{el.removeEventListener('error',er);res()},er=()=>{el.removeEventListener(ev,ok);rej(new Error('media'))};el.addEventListener(ev,ok,{once:true});el.addEventListener('error',er,{once:true})});
const toast=m=>{try{(KE.toast||(()=>{}))(m,1)}catch(e){}};

/* ---------- рисование (как в мини-аппе) ---------- */
function drawItem(cx,it){
  cx.save();cx.lineCap='round';cx.lineJoin='round';cx.strokeStyle=cx.fillStyle=it.c;cx.lineWidth=it.w;const p=it.pts;
  if(it.t==='pen'||it.t==='marker'){if(it.t==='marker')cx.globalAlpha=.4;cx.beginPath();cx.moveTo(p[0].x,p[0].y);if(p.length===1)cx.lineTo(p[0].x+.01,p[0].y);else for(let i=1;i<p.length;i++)cx.lineTo(p[i].x,p[i].y);cx.stroke()}
  else if(it.t==='rect'&&p.length>1)cx.strokeRect(p[0].x,p[0].y,p[1].x-p[0].x,p[1].y-p[0].y);
  else if(it.t==='arrow'&&p.length>1){const a=Math.atan2(p[1].y-p[0].y,p[1].x-p[0].x),hl=it.w*4.5;
    cx.beginPath();cx.moveTo(p[0].x,p[0].y);cx.lineTo(p[1].x-Math.cos(a)*hl*.6,p[1].y-Math.sin(a)*hl*.6);cx.stroke();
    cx.beginPath();cx.moveTo(p[1].x,p[1].y);cx.lineTo(p[1].x-hl*Math.cos(a-.45),p[1].y-hl*Math.sin(a-.45));cx.lineTo(p[1].x-hl*Math.cos(a+.45),p[1].y-hl*Math.sin(a+.45));cx.closePath();cx.fill()}
  else if(it.t==='text'){const fs=it.w*5;cx.font=`700 ${fs}px -apple-system,Segoe UI,Roboto,sans-serif`;cx.textAlign='center';cx.textBaseline='middle';
    cx.lineWidth=fs/6;cx.strokeStyle=it.c==='#000000'?'#fff':'#000';cx.globalAlpha=.85;
    const ls=it.s.split('\n');ls.forEach((l,i)=>cx.strokeText(l,p[0].x,p[0].y+(i-(ls.length-1)/2)*fs*1.15));cx.globalAlpha=1;
    ls.forEach((l,i)=>cx.fillText(l,p[0].x,p[0].y+(i-(ls.length-1)/2)*fs*1.15))}
  cx.restore()}

/* ---------- общая оболочка ---------- */
function edit(file,opt){
  opt=opt||{};
  const isVid=/^video\//.test(file.type)||(!file.type&&/\.(mp4|m4v|webm|mov)$/i.test(file.name||''));
  const ALPHA=/^image\/(png|webp|gif)$/i.test(file.type);      // у этих форматов бывает прозрачность — не заливаем её белым
  return new Promise(async resolve=>{
    const root=document.createElement('div');root.className='ke';
    root.innerHTML=`<div class="ke-top"><button class="ke-b" data-a="x" type="button" aria-label="Закрыть">${I.x}</button><span class="ke-sp"></span><button class="ke-b" data-a="undo" type="button" aria-label="Отменить">${I.undo}</button>${isVid?'':`<button class="ke-b" data-a="rot" type="button" aria-label="Повернуть">${I.rot}</button>`}<button class="ke-b ok" data-a="ok" type="button" aria-label="Готово">${I.ok}</button></div>
    <div class="ke-st"><div class="ke-box"><div class="ke-ld"><i class="ke-spin"></i></div></div></div>
    <div class="ke-pn" id="kePn"></div>
    <div class="ke-tabs"><button data-m="draw" class="on" type="button">${I.draw}<span>Рисовать</span></button><button data-m="crop" type="button">${I.crop}<span>Обрезать</span></button>${isVid?`<button data-m="trim" type="button">${I.trim}<span>Длина</span></button>`:''}</div>`;
    document.body.appendChild(root);
    const $=s=>root.querySelector(s),st=$('.ke-st'),box=$('.ke-box'),pn=$('#kePn');
    let W=0,H=0,media=null,vid=null,url='',closed=false;
    let mode='draw',tool='pen',color=COLORS[0],size=6,items=[],cur=null;
    let crop=null,ratio=0,rotated=false,dirty=false;
    let t0=0,t1=0,dur=0,playing=false;
    const cv=document.createElement('canvas');cv.className='ke-cv';let cx=cv.getContext('2d');
    const done=v=>{if(closed)return;closed=true;document.removeEventListener('keydown',onKey);window.removeEventListener('resize',layout);try{vid&&(vid.pause(),vid.removeAttribute('src'),vid.load())}catch(e){}if(url)URL.revokeObjectURL(url);root.remove();resolve(v)};
    const onKey=e=>{if(e.key==='Escape'&&!root.querySelector('.ke-txt')&&!root.querySelector('.ke-prog'))done(null)};
    document.addEventListener('keydown',onKey);

    /* --- загрузка --- */
    try{
      if(!isVid){
        let bmp;
        try{bmp=await createImageBitmap(file,{imageOrientation:'from-image'})}
        catch(e){bmp=await new Promise((res,rej)=>{const u=URL.createObjectURL(file),im=new Image();im.onload=()=>{URL.revokeObjectURL(u);res(im)};im.onerror=()=>{URL.revokeObjectURL(u);rej(new Error('bad'))};im.src=u})}
        const bw=bmp.width||bmp.naturalWidth,bh=bmp.height||bmp.naturalHeight,k=Math.min(1,MAXIMG/Math.max(bw,bh));
        W=Math.round(bw*k);H=Math.round(bh*k);
        media=document.createElement('canvas');media.width=W;media.height=H;const c=media.getContext('2d');if(!ALPHA){c.fillStyle='#fff';c.fillRect(0,0,W,H)}c.drawImage(bmp,0,0,W,H);
        try{bmp.close&&bmp.close()}catch(e){}
      }else{
        url=URL.createObjectURL(file);vid=document.createElement('video');vid.className='ke-vid';vid.playsInline=true;vid.setAttribute('playsinline','');vid.preload='auto';vid.src=url;
        await once(vid,'loadedmetadata');
        if(!isFinite(vid.duration)||!vid.videoWidth)throw new Error('bad');
        W=vid.videoWidth;H=vid.videoHeight;dur=vid.duration;t0=0;t1=dur;media=vid;
        vid.currentTime=0.01;
      }
    }catch(e){toast(isVid?'Не удалось открыть видео в редакторе':'Не удалось открыть фото');done(null);return}
    crop={x:0,y:0,w:W,h:H};
    $('.ke-ld').remove();if(isVid){vid.style.cssText='position:absolute;max-width:none;max-height:none';box.appendChild(vid)}box.appendChild(cv);

    /* --- раскладка: видимая область = рамка обрезки (или весь кадр в режиме обрезки) --- */
    const region=()=>mode==='crop'?{x:0,y:0,w:W,h:H}:crop;
    let sc=1;
    function layout(){
      const r=region(),aw=st.clientWidth-16,ah=st.clientHeight-8;if(aw<=0||ah<=0)return;
      sc=Math.min(aw/r.w,ah/r.h);box.style.width=Math.round(r.w*sc)+'px';box.style.height=Math.round(r.h*sc)+'px';
      if(!isVid){cv.width=r.w;cv.height=r.h;cv.style.cssText='position:absolute;inset:0;width:100%;height:100%';}
      else{vid.style.width=Math.round(W*sc)+'px';vid.style.height=Math.round(H*sc)+'px';vid.style.left=Math.round(-r.x*sc)+'px';vid.style.top=Math.round(-r.y*sc)+'px';
        const k=Math.min(1,1600/Math.max(r.w,r.h));cv.width=Math.round(r.w*k);cv.height=Math.round(r.h*k);cv.style.cssText='position:absolute;inset:0;width:100%;height:100%';}
      render();if(mode==='crop')cropUI()}
    function render(){
      const r=region();cx.setTransform(1,0,0,1,0,0);cx.clearRect(0,0,cv.width,cv.height);
      const k=cv.width/r.w;cx.setTransform(k,0,0,k,-r.x*k,-r.y*k);
      if(!isVid)cx.drawImage(media,0,0);
      items.forEach(it=>drawItem(cx,it));if(cur)drawItem(cx,cur);cx.setTransform(1,0,0,1,0,0)}
    window.addEventListener('resize',layout);

    /* --- рисование --- */
    const M=Math.max(W,H),lw=()=>size*M/900*(tool==='marker'?3.5:1);
    const pt=e=>{const r=cv.getBoundingClientRect(),g=region();return{x:g.x+(e.clientX-r.left)*g.w/r.width,y:g.y+(e.clientY-r.top)*g.h/r.height}};
    function askText(p){
      const b=document.createElement('div');b.className='ke-txt';b.innerHTML='<input maxlength="80" placeholder="Текст"><button type="button">OK</button>';st.appendChild(b);const inp=b.querySelector('input');inp.focus();
      const fin=ok=>{const v=inp.value.trim();b.remove();if(ok&&v){items.push({t:'text',c:color,w:size*M/900,pts:[p],s:v});dirty=true;render()}};
      b.querySelector('button').onclick=()=>fin(true);inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();fin(true)}else if(e.key==='Escape'){e.stopPropagation();fin(false)}}}
    cv.addEventListener('pointerdown',e=>{if(mode!=='draw'||e.button>0)return;e.preventDefault();const p=pt(e);
      if(tool==='text'){if(!root.querySelector('.ke-txt'))askText(p);return}
      try{cv.setPointerCapture(e.pointerId)}catch(x){}cur={t:tool,c:color,w:lw(),pts:[p]};render()});
    cv.addEventListener('pointermove',e=>{if(!cur)return;const p=pt(e);if(cur.t==='pen'||cur.t==='marker')cur.pts.push(p);else cur.pts[1]=p;render()});
    const up=()=>{if(!cur)return;const p=cur.pts;if(!((cur.t==='rect'||cur.t==='arrow')&&(p.length<2||Math.hypot(p[1].x-p[0].x,p[1].y-p[0].y)<6))){items.push(cur);dirty=true}cur=null;render()};
    cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);

    /* --- обрезка кадра --- */
    let cropEl=null;
    function cropUI(){
      if(!cropEl){cropEl=document.createElement('div');cropEl.className='ke-crop';
        cropEl.innerHTML='<div class="ke-cf"><i data-h="nw"></i><i data-h="n"></i><i data-h="ne"></i><i data-h="w"></i><i data-h="e"></i><i data-h="sw"></i><i data-h="s"></i><i data-h="se"></i><b></b><b></b></div>';box.appendChild(cropEl);
        let drag=null;
        cropEl.addEventListener('pointerdown',e=>{const h=e.target.dataset&&e.target.dataset.h||(e.target.closest('.ke-cf')?'m':null);if(!h)return;e.preventDefault();
          try{cropEl.setPointerCapture(e.pointerId)}catch(x){}drag={h,x:e.clientX,y:e.clientY,r:{...crop}}});
        cropEl.addEventListener('pointermove',e=>{if(!drag)return;const dx=(e.clientX-drag.x)/sc,dy=(e.clientY-drag.y)/sc;crop=resize(drag.r,drag.h,dx,dy);dirty=true;place()});
        const end=()=>{drag=null};cropEl.addEventListener('pointerup',end);cropEl.addEventListener('pointercancel',end)}
      place()}
    function place(){const f=cropEl&&cropEl.firstChild;if(!f)return;f.style.left=crop.x/W*100+'%';f.style.top=crop.y/H*100+'%';f.style.width=crop.w/W*100+'%';f.style.height=crop.h/H*100+'%'}
    const MINC=48;
    function resize(r,h,dx,dy){
      let x0=r.x,y0=r.y,x1=r.x+r.w,y1=r.y+r.h;
      if(h==='m'){let nx=r.x+dx,ny=r.y+dy;nx=Math.max(0,Math.min(W-r.w,nx));ny=Math.max(0,Math.min(H-r.h,ny));return{x:nx,y:ny,w:r.w,h:r.h}}
      if(h.includes('w'))x0=Math.min(x1-MINC,Math.max(0,r.x+dx));
      if(h.includes('e'))x1=Math.max(x0+MINC,Math.min(W,x1+dx));
      if(h.includes('n'))y0=Math.min(y1-MINC,Math.max(0,r.y+dy));
      if(h.includes('s'))y1=Math.max(y0+MINC,Math.min(H,y1+dy));
      if(ratio){
        let w=x1-x0,hh=y1-y0;
        const horiz=h==='e'||h==='w',vert=h==='n'||h==='s';
        if(vert)w=hh*ratio;else hh=w/ratio;
        const maxW=h.includes('w')?r.x+r.w:h.includes('e')?W-r.x:Math.min(r.x+r.w/2,W-r.x-r.w/2)*2;
        const maxH=h.includes('n')?r.y+r.h:h.includes('s')?H-r.y:Math.min(r.y+r.h/2,H-r.y-r.h/2)*2;
        const k=Math.min(1,maxW/w,maxH/hh);w*=k;hh*=k;
        if(w<MINC){hh=MINC/ratio;w=MINC}if(hh<MINC){w=MINC*ratio;hh=MINC}
        const cxm=r.x+r.w/2,cym=r.y+r.h/2;
        if(h.includes('w'))x0=x1-w;else if(h.includes('e'))x1=x0+w;else{x0=cxm-w/2;x1=cxm+w/2}
        if(h.includes('n'))y0=y1-hh;else if(h.includes('s'))y1=y0+hh;else{y0=cym-hh/2;y1=cym+hh/2}
        if(horiz||vert){/* уже центрировано по второй оси */}
        x0=Math.max(0,x0);y0=Math.max(0,y0);x1=Math.min(W,x1);y1=Math.min(H,y1)}
      return{x:Math.round(x0),y:Math.round(y0),w:Math.round(x1-x0),h:Math.round(y1-y0)}}
    function setRatio(r){ratio=r;if(!r){return}
      let w=crop.w,h=crop.h;if(w/h>r)w=h*r;else h=w/r;
      crop={x:Math.round(crop.x+(crop.w-w)/2),y:Math.round(crop.y+(crop.h-h)/2),w:Math.round(w),h:Math.round(h)};dirty=true;place()}

    /* --- поворот (фото) --- */
    function rotate(){
      const n=document.createElement('canvas');n.width=H;n.height=W;const c=n.getContext('2d');c.translate(H,0);c.rotate(Math.PI/2);c.drawImage(media,0,0);
      items.forEach(it=>it.pts=it.pts.map(p=>({x:H-p.y,y:p.x})));
      media=n;const w=W;W=H;H=w;crop={x:0,y:0,w:W,h:H};rotated=true;dirty=true;layout()}

    /* --- видео: длина --- */
    let tl=null;
    function vidTick(){if(!playing)return;if(vid.currentTime>=t1-0.03){vid.currentTime=t0;if(vid.paused)vid.play().catch(()=>{})}updPh();requestAnimationFrame(vidTick)}
    function play(on){if(!isVid)return;playing=on;const b=pn.querySelector('.ke-pl');if(b)b.innerHTML=on?I.pause:I.play;
      if(on){if(vid.currentTime<t0||vid.currentTime>=t1-0.05)vid.currentTime=t0;vid.play().catch(()=>{playing=false;if(b)b.innerHTML=I.play});requestAnimationFrame(vidTick)}else vid.pause()}
    function updPh(){if(!tl)return;const ph=tl.querySelector('.ke-ph');if(ph)ph.style.left=Math.max(0,Math.min(100,vid.currentTime/dur*100))+'%'}
    function updTl(){if(!tl)return;tl.querySelector('.ke-sel').style.cssText=`left:${t0/dur*100}%;width:${(t1-t0)/dur*100}%`;
      pn.querySelector('.ke-tt').textContent=fmtT(t0)+' — '+fmtT(t1)+' · '+(t1-t0).toFixed(1)+' с';updPh()}
    async function strip(el){
      try{const v=document.createElement('video');v.muted=true;v.preload='auto';v.playsInline=true;v.src=url;await once(v,'loadeddata');
        const n=Math.min(10,Math.max(5,Math.round(el.clientWidth/46)||8));el.innerHTML='';
        for(let i=0;i<n&&!closed;i++){const c=document.createElement('canvas');c.width=64;c.height=64;el.appendChild(c);
          v.currentTime=Math.min(dur-0.05,dur*(i+.5)/n);await once(v,'seeked');const q=Math.min(v.videoWidth,v.videoHeight);
          c.getContext('2d').drawImage(v,(v.videoWidth-q)/2,(v.videoHeight-q)/2,q,q,0,0,64,64)}
        v.removeAttribute('src');v.load()}catch(e){}}
    function trimUI(){
      pn.innerHTML=`<div class="ke-tlw"><div class="ke-tl"><div class="ke-ts"></div><div class="ke-sel"><i class="ke-hl" data-d="a"></i><i class="ke-hl r" data-d="b"></i></div><i class="ke-ph"></i></div></div>
      <div class="ke-trow"><button class="ke-pl" type="button" aria-label="Воспроизвести">${I.play}</button><span class="ke-tt"></span><span class="ke-sp"></span><button class="ke-rs" type="button">Сбросить</button></div>`;
      tl=pn.querySelector('.ke-tl');strip(tl.querySelector('.ke-ts'));updTl();
      const track=tl.getBoundingClientRect.bind(tl);let drag=null;
      tl.addEventListener('pointerdown',e=>{const d=e.target.dataset&&e.target.dataset.d;
        const r=track(),t=(e.clientX-r.left)/r.width*dur;
        if(d){drag=d;try{tl.setPointerCapture(e.pointerId)}catch(x){}play(false);e.preventDefault()}
        else{vid.currentTime=Math.max(t0,Math.min(t1,t));updPh()}});
      tl.addEventListener('pointermove',e=>{if(!drag)return;const r=track(),t=Math.max(0,Math.min(dur,(e.clientX-r.left)/r.width*dur)),gap=Math.min(0.5,dur/2);
        if(drag==='a'){t0=Math.min(t,t1-gap);vid.currentTime=t0}else{t1=Math.max(t,t0+gap);vid.currentTime=Math.max(0,t1-0.05)}dirty=true;updTl()});
      const end=()=>{if(drag){drag=null;vid.currentTime=t0;updTl()}};tl.addEventListener('pointerup',end);tl.addEventListener('pointercancel',end);
      pn.querySelector('.ke-pl').onclick=()=>play(!playing);
      pn.querySelector('.ke-rs').onclick=()=>{t0=0;t1=dur;vid.currentTime=0.01;updTl()}}

    /* --- панели --- */
    function panel(){
      play(false);tl=null;
      if(mode==='draw'){
        pn.innerHTML=`<div class="ke-row">${[['pen',I.pen],['marker',I.mark],['arrow',I.arrow],['rect',I.rect],['text',I.text]].map(([k,s])=>`<button class="ke-t${k===tool?' on':''}" data-t="${k}" type="button">${s}</button>`).join('')}<span class="ke-sp2"></span>${COLORS.map(c=>`<button class="ke-c${c===color?' on':''}" data-c="${c}" style="background:${c}" type="button" aria-label="Цвет"></button>`).join('')}</div><div class="ke-row"><input type="range" class="ke-rg" min="2" max="24" value="${size}" aria-label="Толщина"></div>`;
        pn.querySelector('.ke-rg').oninput=e=>{size=+e.target.value}}
      else if(mode==='crop'){
        pn.innerHTML=`<div class="ke-row ke-rt">${RATIOS.map(([k,n,v])=>`<button class="ke-r${(v||0)===(ratio||0)?' on':''}" data-r="${v}" type="button">${n}</button>`).join('')}</div><div class="ke-row"><button class="ke-rs" data-a="creset" type="button">Сбросить рамку</button></div>`}
      else trimUI();
      root.querySelectorAll('.ke-tabs button').forEach(b=>b.classList.toggle('on',b.dataset.m===mode))}
    function setMode(m){if(m===mode)return;
      if(mode==='crop'&&cropEl){cropEl.remove();cropEl=null}
      mode=m;panel();layout();if(m==='trim')play(false)}
    pn.addEventListener('click',e=>{
      const t=e.target.closest('[data-t]'),c=e.target.closest('[data-c]'),r=e.target.closest('[data-r]');
      if(t){tool=t.dataset.t;pn.querySelectorAll('.ke-t').forEach(b=>b.classList.toggle('on',b===t))}
      if(c){color=c.dataset.c;pn.querySelectorAll('.ke-c').forEach(b=>b.classList.toggle('on',b===c))}
      if(r){const v=+r.dataset.r;pn.querySelectorAll('.ke-r').forEach(b=>b.classList.toggle('on',b===r));setRatio(v)}
      if(e.target.closest('[data-a=creset]')){crop={x:0,y:0,w:W,h:H};ratio=0;panel();place()}});
    root.querySelector('.ke-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-m]');if(b)setMode(b.dataset.m)});
    root.querySelector('.ke-top').addEventListener('click',async e=>{const b=e.target.closest('[data-a]');if(!b)return;const a=b.dataset.a;
      if(a==='x')done(null);
      else if(a==='undo'){if(items.length){items.pop();render()}}
      else if(a==='rot')rotate();
      else if(a==='ok'){b.disabled=true;try{await finish()}catch(er){toast((er&&er.message)||'Не удалось обработать');b.disabled=false}}});

    /* --- экспорт --- */
    const cropped=()=>crop.x||crop.y||crop.w!==W||crop.h!==H;
    async function finish(){
      if(!isVid){
        if(!dirty&&!rotated&&!items.length&&!cropped()&&file.size<=(opt.limit||1e12))return done({file,changed:false});
        const r=crop,k=Math.min(1,MAXIMG/Math.max(r.w,r.h)),o=document.createElement('canvas');o.width=Math.round(r.w*k);o.height=Math.round(r.h*k);
        const c=o.getContext('2d');if(!ALPHA){c.fillStyle='#fff';c.fillRect(0,0,o.width,o.height)}c.setTransform(k,0,0,k,-r.x*k,-r.y*k);c.drawImage(media,0,0);items.forEach(it=>drawItem(c,it));
        const b=await new Promise(res=>o.toBlob(res,ALPHA?'image/webp':'image/jpeg',ALPHA?.92:.9));if(!b)throw new Error('Не удалось сохранить фото');
        return done({file:new File([b],'photo.'+(b.type==='image/png'?'png':b.type==='image/webp'?'webp':'jpg'),{type:b.type||'image/jpeg'}),changed:true})}
      /* видео */
      const trimmed=t0>0.05||t1<dur-0.05,need=trimmed||cropped()||items.length||file.size>(opt.limit||1e12);
      if(!need)return done({file,changed:false});
      play(false);
      const out=await encode();if(!out)return;done({file:out,changed:true})}
    function pickMime(){if(typeof MediaRecorder==='undefined')return '';
      for(const m of ['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/mp4','video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm']){try{if(MediaRecorder.isTypeSupported(m))return m}catch(e){}}return ''}
    async function encode(){
      const mime=pickMime(),r=crop;
      if(!mime||!HTMLCanvasElement.prototype.captureStream){throw new Error('Этот браузер не умеет обрабатывать видео. Отправьте без правок')}
      const k=Math.min(1,MAXVID/Math.max(r.w,r.h)),ow=Math.max(2,Math.round(r.w*k/2)*2),oh=Math.max(2,Math.round(r.h*k/2)*2);
      const o=document.createElement('canvas');o.width=ow;o.height=oh;const c=o.getContext('2d');
      const ov=document.createElement('canvas');ov.width=W;ov.height=H;const oc=ov.getContext('2d');items.forEach(it=>drawItem(oc,it));
      const hasOv=items.length>0;
      const len=t1-t0,limit=opt.limit||20*1048576,vbps=Math.max(250000,Math.min(3000000,Math.floor(limit*0.85*8/len)-96000));
      const prog=document.createElement('div');prog.className='ke-prog';prog.innerHTML='<div class="ke-pc"><i class="ke-spin"></i><b>Обработка видео…</b><span id="kePp">0%</span><small>Не сворачивайте приложение</small><button type="button" class="ke-pcx">Отмена</button></div>';root.appendChild(prog);
      let rec,ac,cancelled=false,chunks=[];
      const stream=o.captureStream(30);
      try{
        const AC=window.AudioContext||window.webkitAudioContext;
        if(AC){ac=new AC();const src=ac.createMediaElementSource(vid),dst=ac.createMediaStreamDestination();src.connect(dst);dst.stream.getAudioTracks().forEach(t=>stream.addTrack(t));if(ac.state==='suspended')await ac.resume()}
      }catch(e){}
      rec=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:vbps,audioBitsPerSecond:96000});
      rec.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
      const stopped=new Promise(res=>rec.onstop=res);
      prog.querySelector('.ke-pcx').onclick=()=>{cancelled=true};
      vid.muted=false;vid.currentTime=t0;await Promise.race([once(vid,'seeked').catch(()=>{}),new Promise(r=>setTimeout(r,1500))]);
      const frame=()=>{c.drawImage(vid,r.x,r.y,r.w,r.h,0,0,ow,oh);if(hasOv)c.drawImage(ov,r.x,r.y,r.w,r.h,0,0,ow,oh)};
      frame();rec.start(500);
      let ok=true;try{await vid.play()}catch(e){vid.muted=true;try{await vid.play()}catch(x){ok=false}}
      if(ok){
        await new Promise(res=>{
          const step=()=>{if(cancelled||closed)return res();frame();const p=Math.max(0,Math.min(1,(vid.currentTime-t0)/len));
            const pp=prog.querySelector('#kePp');if(pp)pp.textContent=Math.round(p*100)+'%';
            if(vid.currentTime>=t1-0.04||vid.ended)return res();
            if(vid.requestVideoFrameCallback)vid.requestVideoFrameCallback(step);else requestAnimationFrame(step)};
          step()})}
      try{vid.pause()}catch(e){}
      await new Promise(r=>setTimeout(r,120));
      try{rec.state!=='inactive'&&rec.stop()}catch(e){}await stopped;
      try{stream.getTracks().forEach(t=>t.stop());ac&&ac.close()}catch(e){}
      prog.remove();
      if(cancelled||closed)return null;
      if(!ok)throw new Error('Не удалось обработать видео');
      const blob=new Blob(chunks,{type:mime.split(';')[0]});
      if(!blob.size)throw new Error('Не удалось обработать видео');
      if(blob.size>limit)throw new Error('Видео всё ещё больше '+Math.round(limit/1048576)+' МБ — обрежьте длину');
      return new File([blob],'video.'+(/mp4/.test(mime)?'mp4':'webm'),{type:blob.type})}

    panel();layout();
    if(isVid){vid.addEventListener('ended',()=>{play(false)})}
    requestAnimationFrame(layout);
  });
}
return{edit,toast:null}
})();
