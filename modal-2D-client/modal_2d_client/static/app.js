"use strict";
const $=s=>document.querySelector(s);
const state={session:sessionStorage.getItem("modal2d.session")||"",connected:false,models:[],jobs:[],job:null,artifactIndex:0,blobUrl:null,poll:null,busy:false};
const terminal=new Set(["succeeded","failed","cancelled","expired"]);
const STATUS_LABEL={queued:"排队中",submitting:"提交中",running:"生成中",succeeded:"已完成",failed:"失败",cancelled:"已取消",expired:"已过期"};
const META_KEY="modal2d.jobmeta",META_MAX=200;
function toast(message,kind=""){const el=document.createElement("div");el.className=`toast ${kind}`;el.textContent=message;$("#toasts").append(el);setTimeout(()=>el.remove(),3500)}
function debug(method,path,status,data){$("#debug-log").textContent=`${method} ${path}\nHTTP ${status}\n\n${typeof data==="string"?data:JSON.stringify(data,null,2)}`}
async function request(path,options={}){
  const headers={...(options.headers||{})};if(state.session)headers["X-Modal-2D-Session"]=state.session;
  let body=options.body;if(body&&!(body instanceof FormData)){headers["Content-Type"]="application/json";body=JSON.stringify(body)}
  let res;try{res=await fetch(path,{...options,headers,body})}catch{setAgent("bad","Agent 不可达");throw new Error("无法连接本地 Agent")}
  const type=res.headers.get("content-type")||"";const data=type.includes("application/json")?await res.json():type.includes("image/")?await res.blob():await res.text();
  debug(options.method||"GET",path,res.status,data instanceof Blob?`Blob ${data.size} bytes`:data);
  if(!res.ok){const err=new Error(data&&data.detail?data.detail:`HTTP ${res.status}`);err.status=res.status;throw err}return{data,res};
}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function truncate(v,n){const s=String(v??"");return s.length>n?`${s.slice(0,n)}…`:s}
function statusLabel(status){return STATUS_LABEL[status]||String(status||"未知")}
function fmt(v){if(!v)return"";const d=new Date(v);return Number.isNaN(d.getTime())?"":d.toLocaleString("zh-CN",{hour12:false})}
function relTime(v){if(!v)return"";const d=new Date(v),t=d.getTime();if(Number.isNaN(t))return"";const diff=Date.now()-t,min=60000,hour=3600000,day=86400000;if(diff<0)return fmt(v);if(diff<min)return"刚刚";if(diff<hour)return`${Math.floor(diff/min)} 分钟前`;if(diff<day)return`${Math.floor(diff/hour)} 小时前`;if(diff<day*7)return`${Math.floor(diff/day)} 天前`;return d.toLocaleDateString("zh-CN",{month:"numeric",day:"numeric"})}
function modelLabel(id){if(!id)return"生成任务";for(const opt of $("#model").options)if(opt.value===id)return opt.textContent;return id}
function readMeta(){try{return JSON.parse(localStorage.getItem(META_KEY))||{}}catch{return{}}}
function rememberJob(id,meta){
  if(!id)return;const all=readMeta();all[id]=meta;
  const keys=Object.keys(all);if(keys.length>META_MAX)keys.slice(0,keys.length-META_MAX).forEach(k=>delete all[k]);
  try{localStorage.setItem(META_KEY,JSON.stringify(all))}catch{}
}
function setAgent(mode,text){const el=$("#agent-status");el.dataset.state=mode;el.lastElementChild.textContent=text}
function setBusy(btn,busy,label,text){btn.classList.toggle("is-busy",busy);btn.disabled=busy;if(label&&text)label.textContent=text}
function setConnected(value){
  state.connected=value;
  setAgent(value?"ok":"warn",value?"Modal 已连接":"Modal 未连接");
  $("#form-message").textContent=value?"准备就绪，任务会直接提交到 Modal。":"请先在设置中输入 Modal Token。";
  $("#drawer-status").textContent=value?"已连接 Modal":"尚未连接";
}
function updateJobState(job){const el=$("#job-state");el.textContent=`${statusLabel(job.status)} · ${truncate(job.id,12)}`;el.title=job.id}
let lastFocus=null;
function openSettings(){
  if($("#settings").classList.contains("open"))return;
  lastFocus=document.activeElement;
  const drawer=$("#settings");
  drawer.classList.add("open");drawer.setAttribute("aria-hidden","false");drawer.removeAttribute("inert");
  $("#scrim").hidden=false;document.body.style.overflow="hidden";
  setTimeout(()=>$("#token-command").focus(),80);
}
function closeSettings(){
  const drawer=$("#settings");
  if(!drawer.classList.contains("open"))return;
  drawer.classList.remove("open");drawer.setAttribute("aria-hidden","true");drawer.setAttribute("inert","");
  $("#scrim").hidden=true;
  if($("#lightbox").hidden)document.body.style.overflow="";
  if(lastFocus&&typeof lastFocus.focus==="function")lastFocus.focus();
}
function openLightbox(){
  if(!state.blobUrl)return;
  $("#lightbox-image").src=state.blobUrl;$("#lightbox").hidden=false;document.body.style.overflow="hidden";
  $("#lightbox-close").focus();
}
function closeLightbox(){
  if($("#lightbox").hidden)return;
  $("#lightbox").hidden=true;$("#lightbox-image").removeAttribute("src");
  if(!$("#settings").classList.contains("open"))document.body.style.overflow="";
}
function parseTokenCommand(value){const id=value.match(/(?:^|\s)--token-id(?:=|\s+)(?:["']([^"']+)["']|(\S+))/i),secret=value.match(/(?:^|\s)--token-secret(?:=|\s+)(?:["']([^"']+)["']|(\S+))/i),hint=$("#parse-hint");if(!value.trim()){hint.className="parse-hint";hint.textContent="粘贴后自动提取 ID 和 Secret。";return false}if(!id||!secret){hint.className="parse-hint error";hint.textContent="未识别到完整的 --token-id 和 --token-secret。";return false}$("#token-id").value=id[1]||id[2];$("#token-secret").value=secret[1]||secret[2];hint.className="parse-hint ok";hint.textContent="已提取 Token ID 和 Secret，可以直接连接。";return true}
async function health(){try{const{data}=await request("/health");setConnected(Boolean(data.modal_connected))}catch{setAgent("bad","Agent 不可达")}}
async function connect(){
  const token_id=$("#token-id").value.trim(),token_secret=$("#token-secret").value.trim();
  state.session=$("#session-token").value.trim();sessionStorage.setItem("modal2d.session",state.session);
  if(!token_id||!token_secret){toast("请填写 Token ID 和 Secret","error");return}
  const btn=$("#connect");setBusy(btn,true);
  try{
    await request("/modal/connect",{method:"POST",body:{token_id,token_secret}});
    setConnected(true);
    $("#token-secret").value="";$("#token-command").value="";parseTokenCommand("");
    await loadModels();closeSettings();toast("Modal 连接成功");$("#prompt").focus();
  }catch(e){$("#drawer-status").textContent=`连接失败：${e.message}`;toast(`连接失败：${e.message}`,"error")}
  finally{setBusy(btn,false)}
}
async function disconnect(){try{await request("/modal/connect",{method:"DELETE"});setConnected(false);toast("已断开 Modal")}catch(e){toast(e.message,"error")}}
function updateModelNote(){const model=state.models.find(m=>m.id===$("#model").value);const profile=model?.profiles?.[0];$("#model-note").textContent=model?`${model.width} × ${model.height}${profile?.steps?` · ${profile.steps} steps`:""}`:"1024 × 1024"}
async function loadModels(){try{const{data}=await request("/v1/models");const models=Array.isArray(data.models)?data.models:[];state.models=models;if(models.length)$("#model").innerHTML=models.map(m=>`<option value="${esc(m.id)}">${esc(m.name||m.id)}</option>`).join("");updateModelNote();renderJobs()}catch(e){if(e.status!==409)toast(`模型加载失败：${e.message}`,"error")}}
function parseSeeds(){const values=$("#seeds").value.split(/[\s,]+/).filter(Boolean).map(Number);if(!values.length||values.length>8||values.some(v=>!Number.isInteger(v)||v<0||v>4294967295)||new Set(values).size!==values.length)throw new Error("Seeds 需要 1–8 个不重复整数");return values}
function payload(){const prompt=$("#prompt").value.trim();if(!prompt)throw new Error("请先描述你想生成的画面");const body={prompt,model:$("#model").value};if($("#batch-toggle").checked)body.seeds=parseSeeds();else{const seed=Number($("#seed").value);if(!Number.isInteger(seed)||seed<0||seed>4294967295)throw new Error("Seed 不合法");body.seed=seed}const guidance=$("#guidance").value.trim();if(guidance){const n=Number(guidance);if(!Number.isFinite(n)||n<0||n>20)throw new Error("Guidance 需在 0–20 之间");body.guidance=n}return body}
async function generate(){
  if(state.busy)return;
  if(!state.connected){openSettings();toast("请先连接 Modal","error");return}
  let body;try{body=payload()}catch(e){toast(e.message,"error");return}
  const btn=$("#generate"),label=$("#generate-label");
  state.busy=true;setBusy(btn,true,label,"提交中");showProgress("正在提交任务");
  try{
    const{data}=await request("/v1/jobs",{method:"POST",body});
    state.job=data;state.artifactIndex=0;
    rememberJob(data.id,{prompt:body.prompt,model:body.model,seed:body.seed,guidance:body.guidance,seeds:body.seeds});
    updateJobState(data);await loadJobs();startPolling();toast("任务已提交");
  }catch(e){showEmpty();toast(`提交失败：${e.message}`,"error")}
  finally{state.busy=false;setBusy(btn,false,label,"生成图片")}
}
function showProgress(copy,title){$("#result-empty").hidden=true;$("#result-image").hidden=true;$("#result-meta").hidden=true;$("#result-progress").hidden=false;$("#progress-title").textContent=title||"正在生成";$("#progress-copy").textContent=copy}
function showEmpty(){$("#result-empty").hidden=false;$("#result-progress").hidden=true;$("#result-image").hidden=true;$("#result-meta").hidden=true;$("#download").disabled=true;$("#verify-state").textContent="尚无产物"}
async function poll(){if(!state.job)return;try{const{data}=await request(`/v1/jobs/${encodeURIComponent(state.job.id)}`);state.job=data;updateJobState(data);if(data.status==="succeeded"){stopPolling();await loadArtifact(0);await loadJobs()}else if(terminal.has(data.status)){stopPolling();showEmpty();renderJobs();toast(`任务结束：${statusLabel(data.status)}`,"error")}else showProgress(data.status==="submitting"?"正在提交到 Modal，请稍候":"GPU 正在生成，请稍候",statusLabel(data.status))}catch(e){stopPolling();toast(`轮询失败：${e.message}`,"error")}}
function startPolling(){stopPolling();poll();state.poll=setInterval(poll,1800)}function stopPolling(){if(state.poll)clearInterval(state.poll);state.poll=null}
function descriptors(){if(!state.job?.result)return[];if(Array.isArray(state.job.result.artifacts))return state.job.result.artifacts;return state.job.result.artifact?[state.job.result.artifact]:[]}
async function loadArtifact(index){
  const items=descriptors();if(!items.length)return;
  state.artifactIndex=index;
  const path=items.length>1?`/v1/jobs/${encodeURIComponent(state.job.id)}/artifacts/${index}`:`/v1/jobs/${encodeURIComponent(state.job.id)}/artifact`;
  showProgress("正在下载并校验图片","校验中");
  try{
    const{data,res}=await request(path);
    if(!(data instanceof Blob))throw new Error("产物不是图片");
    if(state.blobUrl)URL.revokeObjectURL(state.blobUrl);
    state.blobUrl=URL.createObjectURL(data);
    const img=$("#result-image");
    img.onload=()=>{$("#result-progress").hidden=true;$("#result-empty").hidden=true;img.hidden=false;$("#download").disabled=false;renderMeta()};
    img.onerror=()=>{showEmpty();toast("图片加载失败","error")};
    img.src=state.blobUrl;
    const expected=items[index].sha256,actual=res.headers.get("x-artifact-sha256");
    $("#verify-state").textContent=expected&&actual&&expected.toLowerCase()===actual.toLowerCase()?`SHA-256 已验证 · ${actual.slice(0,10)}…`:"图片已加载";
    renderCandidates();renderJobs();
  }catch(e){showEmpty();toast(`产物读取失败：${e.message}`,"error")}
}
function renderCandidates(){const items=descriptors();$("#candidate-tabs").innerHTML=items.length>1?items.map((_,i)=>`<button class="${i===state.artifactIndex?"active":""}" data-index="${i}" aria-label="查看候选 ${i+1}" aria-pressed="${i===state.artifactIndex}">${i+1}</button>`).join(""):""}
function renderMeta(){
  const job=state.job,box=$("#result-meta");
  const meta=job?readMeta()[job.id]:null;
  if(!job||!meta||!meta.prompt){box.hidden=true;return}
  box.hidden=false;$("#meta-prompt").textContent=meta.prompt;
  const chips=[`模型 ${modelLabel(job.model||meta.model)}`];
  if(Array.isArray(meta.seeds)&&meta.seeds.length)chips.push(`Seeds ${meta.seeds.join(", ")}`);
  else if(meta.seed!==undefined&&meta.seed!==null)chips.push(`Seed ${meta.seed}`);
  if(meta.guidance!==undefined&&meta.guidance!==null)chips.push(`Guidance ${meta.guidance}`);
  const items=descriptors();if(items.length>1)chips.push(`${items.length} 个候选`);
  $("#meta-chips").innerHTML=chips.map(c=>`<span>${esc(c)}</span>`).join("");
}
async function loadJobs(){try{const{data}=await request("/v1/jobs?limit=12");state.jobs=Array.isArray(data.jobs)?data.jobs:[];renderJobs()}catch(e){toast(`任务加载失败：${e.message}`,"error")}}
function renderJobs(){
  const root=$("#job-list");
  if(!state.jobs.length){root.innerHTML='<div class="list-empty">还没有生成任务</div>';return}
  const meta=readMeta(),activeId=state.job?state.job.id:null;
  root.innerHTML=state.jobs.map(j=>{
    const m=meta[j.id]||{},prompt=m.prompt||"";
    return `<article class="job-card${j.id===activeId?" active":""}" data-id="${esc(j.id)}" tabindex="0" role="button" aria-label="查看任务 ${esc(truncate(j.id,16))}" title="${esc(fmt(j.created_at))}">
      <div class="job-top"><span class="job-status" data-state="${esc(j.status)}">${esc(statusLabel(j.status))}</span><time class="job-time" datetime="${esc(j.created_at||"")}">${esc(relTime(j.created_at))}</time></div>
      <p class="job-prompt${prompt?"":" is-empty"}">${esc(prompt||"本地无该任务的提示词记录")}</p>
      <div class="job-foot"><span class="job-model">${esc(modelLabel(j.model))}</span><span class="job-id">${esc(truncate(j.id,14))}</span></div>
    </article>`;
  }).join("");
}
async function selectJob(id){
  const row=state.jobs.find(j=>j.id===id);if(!row)return;
  state.job=row;updateJobState(row);renderJobs();
  if(row.status==="succeeded")await loadArtifact(0);
  else if(!terminal.has(row.status)){showProgress("GPU 正在生成，请稍候",statusLabel(row.status));startPolling()}
  else{showEmpty();renderMeta();toast(`任务状态：${statusLabel(row.status)}`)}
}
function download(){if(!state.blobUrl)return;const descriptor=descriptors()[state.artifactIndex];const a=document.createElement("a");a.href=state.blobUrl;a.download=`${descriptor?.id||state.job?.id||"modal-2d"}.png`;a.click()}
function syncShortcutHint(){$("#kbd-hint").textContent=/Mac|iPhone|iPad|iPod/.test(navigator.platform||navigator.userAgent)?"⌘ ↵":"Ctrl ↵"}
$("#open-settings").onclick=openSettings;$("#close-settings").onclick=closeSettings;$("#scrim").onclick=closeSettings;$("#connect").onclick=connect;$("#disconnect").onclick=disconnect;$("#generate").onclick=generate;$("#refresh-jobs").onclick=loadJobs;$("#download").onclick=download;
$("#prompt").oninput=e=>$("#prompt-count").textContent=`${e.target.value.length} / 4000`;
$("#model").onchange=updateModelNote;
$("#token-command").addEventListener("input",e=>parseTokenCommand(e.target.value));
$("#token-command").addEventListener("paste",e=>setTimeout(()=>parseTokenCommand(e.target.value),0));
$("#batch-toggle").onchange=e=>{$("#batch-seeds-wrap").hidden=!e.target.checked;$("#seed-wrap").hidden=e.target.checked};
$("#candidate-tabs").onclick=e=>{const b=e.target.closest("button[data-index]");if(b)loadArtifact(Number(b.dataset.index))};
$("#job-list").onclick=e=>{const card=e.target.closest("[data-id]");if(card)selectJob(card.dataset.id)};
$("#job-list").onkeydown=e=>{if(e.key!=="Enter"&&e.key!==" ")return;const card=e.target.closest("[data-id]");if(card){e.preventDefault();selectJob(card.dataset.id)}};
$("#result-image").onclick=openLightbox;
$("#result-image").onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openLightbox()}};
$("#lightbox-close").onclick=closeLightbox;
$("#lightbox").onclick=e=>{if(e.target===$("#lightbox"))closeLightbox()};
$("#settings").addEventListener("keydown",e=>{
  if(e.key!=="Tab")return;
  const nodes=Array.from($("#settings").querySelectorAll("input,button,select,textarea,summary,[tabindex]:not([tabindex='-1'])")).filter(n=>!n.disabled&&n.offsetParent!==null);
  if(!nodes.length)return;
  const first=nodes[0],last=nodes[nodes.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
});
document.addEventListener("keydown",e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==="Enter"){e.preventDefault();if(!$("#generate").disabled)generate()}
  if(e.key==="Escape"){closeLightbox();closeSettings()}
});
$("#session-token").value=state.session;syncShortcutHint();
health().then(()=>{loadJobs();if(state.connected){loadModels();$("#prompt").focus()}else openSettings()});
