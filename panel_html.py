PANEL_HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TTS</title>
<style>
/* те же цвета, что у окна программы (tts_app.py → C) */
:root{--bg:#18181b;--card:#202024;--field:#141417;--btn:#2c2c33;--line:#33333b;--fg:#efeff1;--mut:#a0a0ab;
  --acc:#9147ff;--acc-hi:#a970ff;--ok:#2ecc71;--warn:#f1c40f;--bad:#ff6b6f;--bad-bg:#c4383e}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,"Segoe UI",sans-serif}
h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:0 0 8px;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:0 8px 8px}
.row{display:flex;gap:8px;align-items:center}
.row>*{min-width:0}
.grow{flex:1}
button{background:var(--btn);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
button:hover{border-color:var(--acc)}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
button.pri:hover{background:var(--acc-hi);border-color:var(--acc-hi)}
button.bad{background:var(--bad-bg);border-color:var(--bad-bg);color:#fff}
input[type=text],input[type=number],select,textarea{width:100%;background:var(--field);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
textarea{resize:vertical;font:12px/1.4 ui-monospace,Consolas,monospace}
input[type=range]{width:100%;accent-color:var(--acc)}
.mut{color:var(--mut)}
.hint{color:var(--mut);margin-top:8px;font-size:12px}

/* пульт закреплён сверху: в узком доке до «Пропустить» не надо листать */
#top{position:sticky;top:0;z-index:2;background:var(--bg);padding:8px 0 0;border-bottom:1px solid var(--line);margin-bottom:8px}
#top .card{margin-bottom:8px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--mut);flex:none}
#st{font-size:15px;font-weight:600}
#now{margin-top:4px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#now b{color:var(--fg);font-weight:500}

/* вкладки — сегменты в одну строку */
#tabs{display:flex;margin:0 8px 8px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:2px}
#tabs button{flex:1;border:0;background:none;color:var(--mut);padding:6px 4px;border-radius:6px}
#tabs button[aria-selected=true]{background:var(--btn);color:var(--fg);box-shadow:inset 0 -2px 0 var(--acc)}
.pane{display:none}
.pane.on{display:block}

.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.chip{background:var(--btn);border-radius:999px;padding:2px 4px 2px 10px;display:flex;gap:4px;align-items:center}
.chip button{border:0;background:none;padding:0 6px;color:var(--mut);font-size:15px;line-height:1}
.chip button:hover{color:var(--bad)}
details summary{cursor:pointer;color:var(--mut);margin-top:8px}
#log{font:11px/1.5 ui-monospace,Consolas,monospace;color:var(--mut);max-height:60vh;overflow:auto;white-space:pre-wrap}
.chk{display:flex;gap:6px;align-items:center;cursor:pointer}
input[type=checkbox]{accent-color:var(--acc);width:16px;height:16px;margin:0}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.sgrid label,.slab{display:flex;flex-direction:column;gap:4px;color:var(--mut);font-size:12px}
.slab{margin-top:8px}
.chip .play{color:var(--fg);font-size:11px}
.chip .play:hover{color:var(--acc-hi)}
#gh{display:block;text-align:center;color:var(--mut);font-size:11px;margin:4px 0 8px;text-decoration:none}
#gh:hover{color:var(--acc-hi)}
#msg{position:fixed;left:8px;right:8px;bottom:8px;background:var(--acc);color:#fff;padding:8px 12px;border-radius:6px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:3}
</style></head><body>

<div id="top">
  <div class="card">
    <div class="row"><span class="dot" id="dot"></span><span id="st">…</span><span class="mut grow" id="ch" style="text-align:right"></span></div>
    <div id="now">Очередь: 0</div>
    <div class="row" style="margin-top:12px">
      <button class="pri grow" id="bSkip">Пропустить</button>
      <button class="grow" id="bClear">Очистить</button>
      <button class="grow" id="bToggle">Выкл.</button>
    </div>
  </div>
  <div id="tabs" role="tablist">
    <button role="tab" data-t="main">Пульт</button>
    <button role="tab" data-t="access">Доступ</button>
    <button role="tab" data-t="dict">Словарь</button>
    <button role="tab" data-t="log">Журнал</button>
  </div>
</div>

<section class="pane" id="p-main">
  <div class="card">
    <h2>Громкость <span id="volv" class="mut"></span></h2>
    <input type="range" id="vol" min="0" max="200" step="5">
  </div>
  <div class="card">
    <h2>Голос по умолчанию</h2>
    <select id="voice"></select>
    <div class="row" style="margin-top:8px">
      <input type="text" id="testtxt" placeholder="Текст для проверки" class="grow">
      <button id="bTest" title="Озвучить">Озвучить</button>
    </div>
  </div>
</section>

<section class="pane" id="p-access">
  <div class="card">
    <h2>Кому разрешено (!!!)</h2>
    <div class="row"><input type="text" id="allowIn" placeholder="ники через пробел: vasya petya @kolya" class="grow"><button id="bAllow">Добавить</button></div>
    <div class="chips" id="allowList"></div>
    <details><summary>Править списком</summary>
      <textarea id="allowArea" rows="5" style="margin-top:8px" placeholder="ники через пробел, запятую или с новой строки"></textarea>
      <div class="row" style="margin-top:8px"><button id="bAllowSet" class="grow">Заменить список</button></div>
    </details>
    <div class="hint">Модераторы, владелец и VIP — всегда. Список лежит в data/allowed_users.txt.</div>
  </div>
  <div class="card">
    <h2>Запрещено (ники)</h2>
    <div class="row"><input type="text" id="blockIn" placeholder="ники через пробел" class="grow"><button id="bBlock">Добавить</button></div>
    <div class="chips" id="blockList"></div>
    <div class="hint">Ни через !!!, ни за баллы — даже VIP и модерам. Лежит в data/blocked_users.txt. В чате: !!!tts block|unblock &lt;ник&gt;</div>
  </div>
  <div class="card">
    <h2>Мут на время</h2>
    <div class="row">
      <input type="text" id="muteIn" placeholder="ник" class="grow">
      <input type="number" id="muteMin" min="1" placeholder="мин" style="width:72px">
      <button id="bMute">Мут</button>
    </div>
    <div class="chips" id="muteList"></div>
    <div class="hint">В чате (модеры и владелец): !tts mute &lt;ник&gt; [минуты, по умолчанию 10], !tts unmute &lt;ник&gt;</div>
  </div>
  <div class="card">
    <h2>Чёрный список слов</h2>
    <div class="row"><input type="text" id="banIn" placeholder="слово или фраза" class="grow"><button id="bBan">Добавить</button></div>
    <div class="chips" id="banList"></div>
  </div>
  <div class="card">
    <h2>Награда за баллы</h2>
    <div class="row">
      <input type="number" id="price" min="1" placeholder="Цена" class="grow">
      <button id="bPrice">Применить</button>
    </div>
    <div class="row" style="margin-top:8px"><button id="bReward" class="grow">Создать награду «TTS»</button></div>
    <div class="hint" id="rinfo"></div>
  </div>
</section>

<section class="pane" id="p-dict">
  <div class="card">
    <h2>Словарь замен</h2>
    <div class="row"><input type="text" id="replTry" placeholder="проверить: gg, играем в minecraft 😂" class="grow"><button id="bReplTry">Проверить</button></div>
    <details id="replBox"><summary>Мой словарь</summary>
      <textarea id="replArea" rows="12" spellcheck="false" style="margin-top:8px"></textarea>
      <div class="row" style="margin-top:8px"><button id="bReplSave" class="pri grow">Сохранить</button></div>
    </details>
    <div class="hint">Строка: <b>что = на что</b>. Готовый словарь — data/replacements_twitch.txt, твои строки важнее.</div>
  </div>
  <div class="card">
    <h2>Звуки вместо слов</h2>
    <label class="chk"><input type="checkbox" id="sOn"> Включены</label>
    <div class="sgrid">
      <label title="Сколько звуков может прозвучать в одном сообщении, лишние пропускаются">Звуков на сообщение<input type="number" id="sMax" min="0" max="20"></label>
      <label title="Звук длиннее обрезается с затуханием">Макс. длина, сек<input type="number" id="sSec" min="0.5" max="30" step="0.5"></label>
    </div>
    <label class="slab"><span>Громкость звуков <span id="sVolv"></span></span><input type="range" id="sVol" min="0" max="200" step="5"></label>
    <div class="chips" id="sndList"></div>
    <div class="row" style="margin-top:8px">
      <input type="text" id="sName" placeholder="имя звука, например: смех" class="grow">
      <input type="file" id="sFile" accept="audio/*,.mp3,.ogg,.wav" hidden>
      <button id="bSnd" class="pri">Добавить…</button>
    </div>
    <div class="hint">В словаре выше: <b>kekw = [смех]</b> — вместо «kekw» прозвучит звук «смех». Подойдут mp3, ogg, wav (сохранится до 15 сек, громкость выровняется сама). Звук срабатывает только через словарь: написать [смех] в чате нельзя.</div>
  </div>
</section>

<section class="pane" id="p-log">
  <div class="card"><div id="log"></div></div>
</section>
<a id="gh" href="https://github.com/Koty9n/RU-Local-TTS-for-Twitch-" target="_blank" rel="noopener">RU-Local-TTS for Twitch · GitHub ↗</a>
<div id="msg"></div>

<script>
const K = new URLSearchParams(location.search).get('k') || '';
const $ = id => document.getElementById(id);
let toastT, last = {}, ver = '', busy = false, timer = 0, lastState = null;

function toast(t){ if(!t) return; const m=$('msg'); m.textContent=t; m.style.opacity=1; clearTimeout(toastT); toastT=setTimeout(()=>m.style.opacity=0,2500); }

async function post(body){
  const r = await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Key':K},body:JSON.stringify(body)});
  return r.json();
}
async function call(body){
  try{ const j = await post(body); toast(j.msg || (j.ok ? '' : 'Ошибка')); refresh(); return j; }
  catch(e){ toast('Нет связи с приложением'); }
}

// ---- ссылка на GitHub: док OBS сам ссылки не открывает — просим программу открыть обычный браузер
$('gh').onclick = e => { e.preventDefault(); call({action:'github'}); };

// ---- вкладки (выбранная запоминается в этом браузере)
function tab(t){
  document.querySelectorAll('#tabs button').forEach(b=>b.setAttribute('aria-selected', b.dataset.t===t));
  document.querySelectorAll('.pane').forEach(p=>p.classList.toggle('on', p.id==='p-'+t));
  try{ localStorage.setItem('tts-tab', t); }catch(e){}
  if(t==='log' && lastState) renderLog(lastState);
}
document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>tab(b.dataset.t));
let saved = 'main'; try{ saved = localStorage.getItem('tts-tab') || 'main'; }catch(e){}
tab(saved);

function chips(id, arr, action){
  const key = JSON.stringify(arr);
  if(last[id] === key) return; last[id] = key;
  const box = $(id); box.textContent = '';
  arr.forEach(it=>{   // элемент — строка или {v: значение, t: подпись}
    const v = typeof it === 'string' ? it : it.v;
    const c=document.createElement('span'); c.className='chip';
    const t=document.createElement('span'); t.textContent = typeof it === 'string' ? it : it.t;
    const b=document.createElement('button'); b.textContent='×'; b.title='Убрать'; b.setAttribute('aria-label','Убрать '+v);
    b.onclick=()=>call({action,value:v});
    c.append(t,b); box.append(c);
  });
}

function renderLog(s){
  const lg=$('log'); const atEnd = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 5;
  lg.textContent = s.log.join('\n'); if(atEnd) lg.scrollTop = lg.scrollHeight;
}

function render(s){
  lastState = s;
  const col = {connected:'var(--ok)',connecting:'var(--warn)',error:'var(--bad)',stopped:'var(--mut)'}[s.status]||'var(--mut)';
  const txt = {connected:'Подключён',connecting:'Подключение…',error:'Ошибка',stopped:'Не подключён'}[s.status]||s.status;
  $('dot').style.background = col; $('st').textContent = txt; $('ch').textContent = s.channel ? '#'+s.channel : '';
  const now=$('now'); now.textContent='';
  if(s.speaking){ now.append('▶ '); const b=document.createElement('b'); b.textContent=s.speaking; now.append(b, ' · '); }
  now.append('Очередь: ' + s.queue + (s.enabled ? '' : ' · TTS выключен'));
  const bt=$('bToggle'); bt.textContent = s.enabled ? 'Выкл.' : 'Вкл.'; bt.className = 'grow' + (s.enabled ? '' : ' bad');
  if(document.activeElement !== $('vol')){ $('vol').value = s.volume; }
  $('volv').textContent = $('vol').value + '%';
  const vk = JSON.stringify(s.voices);
  if(last.voices !== vk){
    last.voices = vk; const sel=$('voice'); sel.textContent='';
    s.voices.forEach(v=>{ const o=document.createElement('option'); o.value=v; o.textContent=v; sel.append(o); });
  }
  if(document.activeElement !== $('voice')) $('voice').value = s.default_voice;
  if(document.activeElement !== $('price') && s.price) $('price').value = s.price;
  $('rinfo').textContent = s.has_reward ? 'Награда привязана' : 'Награда не привязана';
  chips('allowList', s.allowed, 'allow_del');
  if(document.activeElement !== $('allowArea')) $('allowArea').value = s.allowed.join(' ');
  chips('banList', s.blacklist, 'ban_del');
  chips('blockList', s.blocked || [], 'block_del');
  chips('muteList', s.muted || [], 'mute_del');
  renderSounds(s);
  if($('p-log').classList.contains('on')) renderLog(s);   // журнал рисуем, только когда его видно
}

// ---- опрос: только когда док виден; сервер отвечает 204, если ничего не поменялось;
//      когда звучит или есть очередь — раз в секунду, в тишине — раз в 3 с
async function refresh(){
  if(busy) return; busy = true;
  try{
    const r = await fetch('/api/state?v='+ver,{headers:{'X-Key':K}});
    if(r.status === 200){ ver = r.headers.get('X-V') || ''; render(await r.json()); }
    else if(r.status !== 204) throw 0;
  }catch(e){ $('st').textContent='Нет связи'; $('dot').style.background='var(--bad)'; ver=''; }
  finally{ busy = false; }
}
function loop(){
  clearTimeout(timer);
  const active = lastState && (lastState.speaking || lastState.queue > 0 || lastState.status === 'connecting');
  if(!document.hidden) refresh();
  timer = setTimeout(loop, active ? 1000 : 3000);
}
document.addEventListener('visibilitychange', ()=>{ if(!document.hidden) loop(); });

$('bSkip').onclick = ()=>call({action:'skip'});
$('bClear').onclick = ()=>call({action:'clear'});
$('bToggle').onclick = ()=>call({action:'toggle'});
$('vol').oninput = ()=>{ $('volv').textContent = $('vol').value+'%'; };
$('vol').onchange = ()=>call({action:'volume',value:$('vol').value});
$('voice').onchange = ()=>call({action:'default_voice',value:$('voice').value});
$('bTest').onclick = ()=>call({action:'test',value:$('testtxt').value,voice:$('voice').value});
$('bPrice').onclick = ()=>call({action:'price',value:$('price').value});
$('bReward').onclick = ()=>call({action:'reward_create',value:$('price').value||'500'});
$('bAllow').onclick = async ()=>{ const v=$('allowIn').value.trim(); if(v){ await call({action:'allow_add',value:v}); $('allowIn').value=''; } };
$('bAllowSet').onclick = ()=>call({action:'allow_set',value:$('allowArea').value});
$('bBlock').onclick = async ()=>{ const v=$('blockIn').value.trim(); if(v){ await call({action:'block_add',value:v}); $('blockIn').value=''; } };
$('bMute').onclick = async ()=>{ const v=$('muteIn').value.trim(); if(v){ await call({action:'mute_add',value:(v+' '+$('muteMin').value).trim()}); $('muteIn').value=''; } };
$('blockIn').onkeydown = e=>{ if(e.key==='Enter') $('bBlock').click(); };
$('muteIn').onkeydown = e=>{ if(e.key==='Enter') $('bMute').click(); };
$('bBan').onclick = async ()=>{ const v=$('banIn').value.trim(); if(v){ await call({action:'ban_add',value:v}); $('banIn').value=''; } };
// словарь грузится только при открытии — общий опрос его не тащит
$('replBox').ontoggle = async ()=>{
  if(!$('replBox').open) return;
  try{ const j = await post({action:'repl_get'}); if(j.ok) $('replArea').value = j.msg; }
  catch(e){ toast('Нет связи с приложением'); }
};
$('bReplSave').onclick = ()=>call({action:'repl_set',value:$('replArea').value});
$('bReplTry').onclick = ()=>{ const v=$('replTry').value.trim(); if(v) call({action:'repl_try',value:v}); };
$('replTry').onkeydown = e=>{ if(e.key==='Enter') $('bReplTry').click(); };
// ---- звуки вместо слов
function renderSounds(s){
  const c = s.snd || {};
  if(document.activeElement !== $('sOn')) $('sOn').checked = !!c.sounds_on;
  if(document.activeElement !== $('sMax')) $('sMax').value = c.sound_max_per_msg;
  if(document.activeElement !== $('sSec')) $('sSec').value = c.sound_max_sec;
  if(document.activeElement !== $('sVol')) $('sVol').value = c.sound_volume;
  $('sVolv').textContent = $('sVol').value + '%';
  const key = JSON.stringify(s.sounds || []);
  if(last.sounds === key) return; last.sounds = key;
  const box = $('sndList'); box.textContent = '';
  if(!(s.sounds || []).length){ const m=document.createElement('span'); m.className='mut'; m.textContent='Звуков пока нет'; box.append(m); }
  (s.sounds || []).forEach(n=>{
    const c=document.createElement('span'); c.className='chip';
    const p=document.createElement('button'); p.className='play'; p.textContent='▶'; p.title='Прослушать'; p.setAttribute('aria-label','Прослушать '+n);
    p.onclick=()=>call({action:'snd_play',value:n});
    const t=document.createElement('span'); t.textContent=n;
    const b=document.createElement('button'); b.textContent='×'; b.title='Удалить'; b.setAttribute('aria-label','Удалить '+n);
    b.onclick=()=>{ if(confirm('Удалить звук «'+n+'»?')) call({action:'snd_del',value:n}); };
    c.append(p,t,b); box.append(c);
  });
}
function sndCfg(){
  call({action:'snd_cfg', sounds_on:$('sOn').checked, sound_max_per_msg:$('sMax').value,
        sound_max_sec:$('sSec').value, sound_volume:$('sVol').value});
}
['sOn','sMax','sSec','sVol'].forEach(id=>$(id).onchange = sndCfg);
$('sVol').oninput = ()=>{ $('sVolv').textContent = $('sVol').value+'%'; };

// любой mp3/ogg/wav -> WAV моно 16 бит 22050 Гц, до 15 с (декодирует сам браузер, программе не нужны библиотеки)
async function toWav(file){
  const RATE = 22050, MAXS = 15;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  let buf;
  try{ buf = await ctx.decodeAudioData(await file.arrayBuffer()); } finally { ctx.close(); }
  const len = Math.min(Math.ceil(buf.duration * RATE), MAXS * RATE);
  const off = new OfflineAudioContext(1, len, RATE);
  const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const dv = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (o, s)=>{ for(let i=0;i<s.length;i++) dv.setUint8(o+i, s.charCodeAt(i)); };
  str(0,'RIFF'); dv.setUint32(4, 36 + pcm.length*2, true); str(8,'WAVE'); str(12,'fmt ');
  dv.setUint32(16,16,true); dv.setUint16(20,1,true); dv.setUint16(22,1,true); dv.setUint32(24,RATE,true);
  dv.setUint32(28,RATE*2,true); dv.setUint16(32,2,true); dv.setUint16(34,16,true); str(36,'data'); dv.setUint32(40,pcm.length*2,true);
  for(let i=0;i<pcm.length;i++) dv.setInt16(44+i*2, Math.max(-1, Math.min(1, pcm[i])) * 32767, true);
  const bytes = new Uint8Array(dv.buffer); let bin = '';
  for(let i=0;i<bytes.length;i+=0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i+0x8000));
  return btoa(bin);
}
$('bSnd').onclick = ()=>$('sFile').click();
$('sFile').onchange = async ()=>{
  const f = $('sFile').files[0]; $('sFile').value = '';
  if(!f) return;
  const name = $('sName').value.trim() || f.name.replace(/\.[^.]+$/, '');
  toast('Загружаю «'+name+'»…');
  let data;
  try{ data = await toWav(f); }catch(e){ toast('Не получилось прочитать файл как звук'); return; }
  const j = await call({action:'snd_add', name, data});
  if(j && j.ok) $('sName').value = '';
};
$('sName').onkeydown = e=>{ if(e.key==='Enter') $('bSnd').click(); };

$('allowIn').onkeydown = e=>{ if(e.key==='Enter') $('bAllow').click(); };
$('banIn').onkeydown = e=>{ if(e.key==='Enter') $('bBan').click(); };

loop();
</script></body></html>
"""
