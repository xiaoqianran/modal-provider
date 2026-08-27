const state = { data: null, input: null, sort: 'speed', activeViewer: null };
const $ = (s) => document.querySelector(s);
const fmt = new Intl.NumberFormat('en-US');
const palette = ['#a6d189','#ca9ee6','#8caaee','#ef9f76','#99d1db'];
const preprocessLabel = input => input.preprocess_label || 'SAM 3.1';

function seconds(v){ return Number.isFinite(v) ? `${v.toFixed(v < 10 ? 2 : 1)}s` : '—'; }
function bytes(v){
  if (!Number.isFinite(v)) return '—';
  const units=['B','KB','MB','GB']; let n=v,i=0;
  while(n>=1024 && i<units.length-1){n/=1024;i++;}
  return `${n.toFixed(i<2?0:2)} ${units[i]}`;
}
function faces(v){ return Number.isFinite(v) ? (v >= 1e6 ? `${(v/1e6).toFixed(2)}M` : `${Math.round(v/1000)}k`) : '—'; }
function esc(s){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function renderRecommendations(){
  const picks = [
    ['speed','最快彩色','FastSAM3D++'],['alt','完整 PBR','Hunyuan2.1++'],
    ['texture','1536 PBR','Pixal3D'],['detail','高密 PBR','Hermite-TRELLIS2++']
  ];
  $('#recommendations').innerHTML = picks.map(([tone,label,name]) =>
    `<div class="rec-card" data-tone="${tone}"><small>${label}</small><strong>${name}</strong></div>`).join('');
}

function renderInputs(){
  $('#input-tabs').innerHTML = state.data.inputs.map((input,i)=>`
    <button class="input-card" role="tab" aria-selected="${input.id===state.input}" data-input="${input.id}">
      <img class="input-image" src="${input.image}" alt="${esc(input.label)}" loading="${i?'lazy':'eager'}" decoding="async">
      <span class="input-meta"><span class="input-copy"><strong>${esc(input.label)}</strong><span>${esc(preprocessLabel(input))} → ${esc(input.subject)}</span></span><span>${input.width}×${input.height}</span></span>
    </button>`).join('');
  document.querySelectorAll('.input-card').forEach(btn=>btn.addEventListener('click',()=>{
    state.input=btn.dataset.input; renderInputs(); renderResults();
  }));
}

function sortedResults(){
  const list=[...state.data.results[state.input]];
  const key = state.sort==='speed'?'inference_s':state.sort==='faces'?'faces':'glb_bytes';
  list.sort((a,b)=>state.sort==='faces' ? (b[key]??-1)-(a[key]??-1) : (a[key]??Infinity)-(b[key]??Infinity));
  return list;
}

function renderResults(){
  const input=state.data.inputs.find(x=>x.id===state.input);
  const results=sortedResults();
  const finite=results.filter(x=>Number.isFinite(x.inference_s));
  const fastest=finite.length?Math.min(...finite.map(x=>x.inference_s)):1;
  const slowest=finite.length?Math.max(...finite.map(x=>x.inference_s)):1;
  $('#result-summary').innerHTML=`<strong>${esc(input.label)}</strong><span class="summary-dot"></span><span>${esc(preprocessLabel(input))} → ${esc(input.subject)}</span><span class="summary-dot"></span><span>${results.length} models · seed 42 · L40S</span>`;
  $('#model-grid').innerHTML=results.map((r,idx)=>{
    const width=Number.isFinite(r.inference_s)?Math.max(10,100-((r.inference_s-fastest)/Math.max(.001,slowest-fastest))*76):10;
    const badges=[r.kind==='textured'?'Textured':'Geometry'];
    if(r.recommended) badges.push('Recommended');
    if(r.watertight===true) badges.push('Watertight');
    return `<article class="model-card ${r.recommended?'recommended':''}" style="--accent:${palette[idx%palette.length]}">
      <div class="model-head"><div><h3 class="model-title">${esc(r.name)}</h3><p class="model-subtitle">${esc(r.role||'')}</p></div><div class="rank">${idx+1}</div></div>
      <div class="badges">${badges.map((b,i)=>`<span class="badge ${b==='Recommended'?'best':''}">${b}</span>`).join('')}</div>
      <div class="metrics">
        <div class="metric"><span>Inference</span><strong>${seconds(r.inference_s)}</strong></div>
        <div class="metric"><span>Faces</span><strong>${faces(r.faces)}</strong></div>
        <div class="metric"><span>Full GLB</span><strong>${bytes(r.glb_bytes)}</strong></div>
      </div>
      <div class="speed-track" title="relative inference time"><div class="speed-bar" style="--width:${width}%"></div></div>
      <div class="card-actions">
        <button class="view-button" type="button" data-preview="${esc(r.preview)}" data-model="${esc(r.name)}" data-input-label="${esc(input.label)}" data-preview-bytes="${r.preview_bytes||0}">查看 3D</button>
        <a class="source-link" href="${esc(r.source)}" target="_blank" rel="noopener">代码 ↗</a>
      </div>
    </article>`;
  }).join('');
  document.querySelectorAll('.view-button').forEach(btn=>btn.addEventListener('click',()=>openViewer(btn)));
}

function openViewer(btn){
  const dialog=$('#viewer-dialog'); const stage=$('#viewer-stage');
  stage.replaceChildren();
  const mv=document.createElement('model-viewer');
  mv.src=btn.dataset.preview; mv.setAttribute('camera-controls',''); mv.setAttribute('shadow-intensity','0.8');
  mv.setAttribute('environment-image','neutral'); mv.setAttribute('interaction-prompt','auto');
  mv.alt=`${btn.dataset.model} 3D preview`;
  stage.append(mv); state.activeViewer=mv;
  $('#viewer-title').textContent=btn.dataset.model;
  $('#viewer-input').textContent=btn.dataset.inputLabel;
  $('#viewer-size').textContent=`Web preview · ${bytes(Number(btn.dataset.previewBytes))}`;
  dialog.showModal();
}
function closeViewer(){
  const dialog=$('#viewer-dialog');
  if(state.activeViewer){ state.activeViewer.src=''; state.activeViewer.remove(); state.activeViewer=null; }
  if(dialog.open) dialog.close();
}

async function init(){
  renderRecommendations();
  const res=await fetch('./data/results.json',{cache:'no-cache'});
  if(!res.ok) throw new Error(`results.json: ${res.status}`);
  state.data=await res.json(); state.input=state.data.inputs[0].id;
  renderInputs(); renderResults();
  document.querySelectorAll('.sort-button').forEach(btn=>btn.addEventListener('click',()=>{
    state.sort=btn.dataset.sort;
    document.querySelectorAll('.sort-button').forEach(x=>x.classList.toggle('active',x===btn));
    renderResults();
  }));
  $('#viewer-close').addEventListener('click',closeViewer);
  $('#viewer-dialog').addEventListener('click',e=>{ if(e.target===$('#viewer-dialog')) closeViewer(); });
  $('#viewer-dialog').addEventListener('cancel',e=>{e.preventDefault();closeViewer();});
}
init().catch(err=>{
  console.error(err);
  $('#model-grid').innerHTML=`<p class="section-note">Benchmark data failed to load. ${esc(err.message)}</p>`;
});
