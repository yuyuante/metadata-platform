"use strict";

const state = { index: [], byId: new Map(), flow: null, selectedId: null };
const el = id => document.getElementById(id);

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function text(tag, value, className) { const node=document.createElement(tag); node.textContent=value ?? ""; if(className) node.className=className; return node; }
function button(label, id, className="link-button") { const node=text("button", label, className); node.type="button"; node.addEventListener("click",()=>selectObject(id)); return node; }

async function loadJson(path) { const response=await fetch(path); if(!response.ok) throw new Error(`${response.status} ${path}`); return response.json(); }

function renderResults(items) {
  const list=el("results"); clear(list);
  for(const item of items.slice(0,100)) { const li=document.createElement("li"); const pick=button(item.qualified_name,item.id); pick.append(text("span",`${item.object_type} · ${item.provider}`)); li.append(pick); list.append(li); }
  if(!items.length) list.append(text("li","No matching objects.","empty"));
}

function search() {
  const term=el("search").value.trim().toLocaleLowerCase();
  const matches=!term ? state.index.slice(0,50) : state.index.filter(item => [item.qualified_name,item.name,item.object_type,item.provider,item.system].some(value => String(value||"").toLocaleLowerCase().includes(term)));
  renderResults(matches);
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

function markSelection() { document.querySelectorAll(".node-button").forEach(node=>node.classList.toggle("selected",node.textContent===state.byId.get(state.selectedId)?.qualified_name)); }

async function selectObject(id) {
  const item=state.byId.get(id); if(!item) return; state.selectedId=id; el("explore").disabled=state.flow?.root.id===id; markSelection(); renderDetail(await loadJson(item.detail));
}

async function explore(id) { const item=state.byId.get(id); if(!item) return; history.replaceState(null,"",`#object=${encodeURIComponent(id)}`); renderFlow(await loadJson(item.flow)); await selectObject(id); }

async function start() {
  try { const payload=await loadJson("data/index.json"); state.index=payload.objects; state.byId=new Map(state.index.map(item=>[item.id,item])); el("status").textContent=`${payload.generated.object_count.toLocaleString()} repository objects`; el("search").addEventListener("input",search); el("explore").addEventListener("click",()=>explore(state.selectedId)); search(); const requested=new URLSearchParams(location.hash.slice(1)).get("object"); const initial=state.byId.has(requested) ? requested : state.index[0]?.id; if(initial) await explore(initial); }
  catch(error) { el("status").textContent="Unable to load export"; el("detail").append(text("p",String(error),"warnings")); }
}

start();
