"use strict";

const state = {
  manifest: null,
  shardCache: new Map(),
  flow: null,
  selectedId: null,
  pendingRootId: null,
  navigationVersion: 0,
  searchVersion: 0,
  searchTimer: null,
  restoreScheduled: false,
};
const el = id => document.getElementById(id);

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function text(tag, value, className) { const node=document.createElement(tag); node.textContent=value ?? ""; if(className) node.className=className; return node; }
function button(label, id, className="link-button") { const node=text("button", label, className); node.type="button"; node.dataset.objectId=id; node.addEventListener("click",()=>void selectObject(id).catch(showError)); return node; }

async function loadJson(path) { const response=await fetch(path); if(!response.ok) throw new Error(`${response.status} ${path}`); return response.json(); }
function objectPath(id) { return `data/objects/${encodeURIComponent(id)}.json`; }
function flowPath(id) { return `data/flows/${encodeURIComponent(id)}.json`; }
function objectIdFromHash() { return new URLSearchParams(location.hash.slice(1)).get("object"); }
function isObjectId(id) { return /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(id || ""); }
function objectHash(id) { return `#object=${encodeURIComponent(id)}`; }

function renderResults(items) {
  const list=el("results"); clear(list);
  for(const item of items.slice(0,100)) { const li=document.createElement("li"); const pick=button(item.qualified_name,item.id); pick.append(text("span",`${item.object_type} · ${item.provider}`)); li.append(pick); list.append(li); }
  if(!items.length) list.append(text("li","No matching objects.","empty"));
}

function searchPrefix(term) {
  const prefixes=(term.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu)||[]).filter(token=>Array.from(token).length>=3).map(token=>Array.from(token).slice(0,3).join(""));
  return prefixes.reduce((smallest,prefix)=>!smallest || (state.manifest.shards[prefix]?.object_count??0)<(state.manifest.shards[smallest]?.object_count??0) ? prefix : smallest,"");
}

async function loadSearchShard(prefix) {
  if(state.shardCache.has(prefix)) return state.shardCache.get(prefix);
  const shard=state.manifest.shards[prefix];
  if(!shard) return [];
  const promise=loadJson(shard.path).then(payload => payload.objects);
  state.shardCache.set(prefix,promise);
  try { return await promise; }
  catch(error) { state.shardCache.delete(prefix); throw error; }
}

async function search() {
  const version=++state.searchVersion;
  const term=el("search").value.trim().toLocaleLowerCase();
  if(Array.from(term).length < state.manifest.minimum_query_length) {
    const list=el("results"); clear(list);
    list.append(text("li",`Enter at least ${state.manifest.minimum_query_length} characters.`,"empty"));
    return;
  }
  const items=await loadSearchShard(searchPrefix(term));
  if(version !== state.searchVersion) return;
  const matches=[];
  for(const item of items) {
    if([item.qualified_name,item.name,item.object_type,item.provider].some(value => String(value||"").toLocaleLowerCase().includes(term))) matches.push(item);
    if(matches.length===100) break;
  }
  renderResults(matches);
}

function scheduleSearch() {
  clearTimeout(state.searchTimer);
  state.searchTimer=setTimeout(()=>void search().catch(showError),200);
}

function nodeMap(flow) { return new Map(flow.nodes.map(node=>[node.id,node])); }
function renderNodeGroup(containerId, ids, nodes) {
  const container=el(containerId); clear(container);
  for(const id of ids) { const item=nodes.get(id); if(item) container.append(button(item.qualified_name,id,"node-button")); }
  if(!ids.length) container.append(text("p","None","empty"));
}

function renderFlow(flow) {
  state.flow=flow; const nodes=nodeMap(flow);
  renderNodeGroup("upstream",flow.upstream,nodes); renderNodeGroup("root",[flow.root.id],nodes); renderNodeGroup("downstream",flow.downstream,nodes);
  const edgeList=el("edges"); clear(edgeList);
  for(const edge of flow.edges) { const li=document.createElement("li"); const source=nodes.get(edge.source); const target=nodes.get(edge.target); li.append(button(source?.qualified_name||edge.source,edge.source)); li.append(text("span",` —[${edge.relation_type}]→ `,"relation")); li.append(button(target?.qualified_name||edge.target,edge.target)); edgeList.append(li); }
  if(!flow.edges.length) edgeList.append(text("li","No traversable relations in the configured depth.","empty"));
  const warnings=Object.entries(flow.warnings).filter(([,count])=>count); el("warnings").hidden=!warnings.length; el("warnings").textContent=warnings.map(([name,count])=>`${name}: ${count}`).join(" · ");
  markSelection();
}

function facts(object) {
  const dl=document.createElement("dl"); dl.className="fact-grid";
  for(const [label,value] of [["Stable ID",object.id],["Qualified name",object.qualified_name],["Name",object.name],["Type",object.object_type],["Provider",object.provider],["Owner",object.owner],["Status",object.status]]) { dl.append(text("dt",label)); dl.append(text("dd",value||"—")); }
  return dl;
}

function relationList(title, items) {
  const section=document.createElement("section"); section.append(text("h3",title)); const list=document.createElement("ul"); list.className="link-list";
  for(const item of items) { const li=document.createElement("li"); li.append(button(item.qualified_name,item.id)); li.append(text("span",` [${item.relation_type}]`,"meta")); list.append(li); }
  if(!items.length) list.append(text("li","None","empty")); section.append(list); return section;
}

function renderDetail(detail) {
  const host=el("detail"); clear(host); const object=detail.object; host.append(text("h2",object.qualified_name)); host.append(facts(object));
  if(object.description) host.append(text("p",object.description));
  host.append(relationList("Dependencies",detail.dependencies)); host.append(relationList("Used by",detail.used_by));
  const locations=detail.source.locations; host.append(text("h3","Source context"));
  for(const location of locations) { const card=document.createElement("article"); card.className="source-card"; card.append(text("div",`${location.source_type} · ${location.source_file}`,"source-meta")); const line=location.start_line ? `Lines ${location.start_line}–${location.end_line||location.start_line}` : "Line range unavailable"; card.append(text("div",`${line}${location.context_identifier ? ` · ${location.context_identifier}` : ""}`,"source-meta")); if(location.warning) card.append(text("p",location.warning,"warnings")); if(location.excerpt) card.append(text("pre",location.excerpt)); host.append(card); }
  if(!locations.length) host.append(text("p","No persisted source locations.","empty"));
}

function markSelection() { document.querySelectorAll(".node-button").forEach(node=>node.classList.toggle("selected",node.dataset.objectId===state.selectedId)); }

async function selectObject(id) {
  if(!isObjectId(id)) return;
  const detail=await loadJson(objectPath(id));
  state.selectedId=id; el("explore").disabled=state.flow?.root.id===id; markSelection(); renderDetail(detail);
}

async function navigateRoot(id, historyMode="push") {
  if(!isObjectId(id) || state.pendingRootId===id || (state.flow?.root.id===id && historyMode==="none")) return;
  const version=++state.navigationVersion;
  state.pendingRootId=id;
  try {
    const [flow,detail]=await Promise.all([loadJson(flowPath(id)),loadJson(objectPath(id))]);
    if(version !== state.navigationVersion) return;
    if(historyMode==="push" && location.hash!==objectHash(id)) history.pushState(null,"",objectHash(id));
    if(historyMode==="replace" && location.hash!==objectHash(id)) history.replaceState(null,"",objectHash(id));
    renderFlow(flow); state.selectedId=id; renderDetail(detail); el("explore").disabled=true; markSelection();
  } finally {
    if(version===state.navigationVersion) state.pendingRootId=null;
  }
}

function scheduleHistoryRestore() {
  if(state.restoreScheduled) return;
  state.restoreScheduled=true;
  queueMicrotask(()=>{
    state.restoreScheduled=false;
    const requested=objectIdFromHash();
    if(isObjectId(requested)) void navigateRoot(requested,"none").catch(showError);
  });
}

function showError(error) {
  el("status").textContent="Unable to load export";
  const host=el("detail"); clear(host); host.append(text("p",String(error),"warnings"));
}

async function start() {
  try {
    state.manifest=await loadJson("data/index.json");
    el("status").textContent=`${state.manifest.generated.object_count.toLocaleString()} repository objects`;
    el("search").addEventListener("input",scheduleSearch);
    el("explore").addEventListener("click",()=>void navigateRoot(state.selectedId).catch(showError));
    window.addEventListener("popstate",scheduleHistoryRestore);
    window.addEventListener("hashchange",scheduleHistoryRestore);
    await search();
    const requested=objectIdFromHash();
    if(isObjectId(requested)) await navigateRoot(requested,"none");
    else if(isObjectId(state.manifest.default_object_id)) await navigateRoot(state.manifest.default_object_id,"replace");
  } catch(error) { showError(error); }
}

void start();
