"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const appPath = process.argv[2];
const app = fs.readFileSync(appPath, "utf8").replace(
  "void start();",
  "globalThis.testApi={navigateRoot,selectObject,scheduleHistoryRestore,state:()=>state};",
);
vm.runInThisContext(app, { filename: appPath });

class FakeNode {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.classList = { toggle: () => {} };
    this.disabled = false;
    this.hidden = false;
    this.textContent = "";
  }
  get firstChild() { return this.children[0] || null; }
  append(...nodes) { this.children.push(...nodes); }
  removeChild(node) { this.children.splice(this.children.indexOf(node), 1); }
  addEventListener() {}
}

const elements = new Map();
globalThis.document = {
  createElement: () => new FakeNode(),
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new FakeNode());
    return elements.get(id);
  },
  querySelectorAll: () => [],
};
const listeners = new Map();
globalThis.window = {
  addEventListener: (name, callback) => {
    if (!listeners.has(name)) listeners.set(name, []);
    listeners.get(name).push(callback);
  },
};
globalThis.location = { hash: "" };
const entries = [""];
let cursor = 0;
function emit(name) {
  for (const callback of listeners.get(name) || []) callback();
}
globalThis.history = {
  pushState: (_state, _title, url) => {
    entries.splice(cursor + 1);
    entries.push(url);
    cursor++;
    location.hash = url;
  },
  replaceState: (_state, _title, url) => {
    entries[cursor] = url;
    location.hash = url;
  },
  back: () => {
    cursor--;
    location.hash = entries[cursor];
    emit("popstate");
    emit("hashchange");
  },
  forward: () => {
    cursor++;
    location.hash = entries[cursor];
    emit("popstate");
    emit("hashchange");
  },
};

const first = "00000000-0000-4000-8000-000000000031";
const second = "00000000-0000-4000-8000-000000000032";
const fetches = new Map();
function detail(id) {
  return {
    object: {
      id,
      qualified_name: `dbo.${id.slice(-2)}`,
      name: id.slice(-2),
      object_type: "TABLE",
      provider: "TEST",
      owner: null,
      status: null,
      description: null,
    },
    dependencies: [],
    used_by: [],
    source: { locations: [] },
  };
}
function flow(id) {
  const root = { id, qualified_name: `dbo.${id.slice(-2)}` };
  return { root, nodes: [root], upstream: [], downstream: [], edges: [], warnings: {} };
}
globalThis.fetch = async path => {
  fetches.set(path, (fetches.get(path) || 0) + 1);
  const id = path.match(/([0-9a-f-]{36})\.json$/)[1];
  return {
    ok: true,
    json: async () => path.includes("/flows/") ? flow(id) : detail(id),
  };
};
window.addEventListener("popstate", testApi.scheduleHistoryRestore);
window.addEventListener("hashchange", testApi.scheduleHistoryRestore);

async function settle() {
  await new Promise(resolve => setTimeout(resolve, 0));
  await new Promise(resolve => setTimeout(resolve, 0));
}

(async () => {
  await testApi.navigateRoot(first, "replace");
  await testApi.selectObject(second);
  await testApi.navigateRoot(second, "push");
  assert.equal(entries.length, 2);
  assert.equal(location.hash, `#object=${second}`);
  assert.equal(testApi.state().flow.root.id, second);
  assert.equal(elements.get("detail").children[0].textContent, "dbo.32");

  history.back();
  await settle();
  assert.equal(entries.length, 2);
  assert.equal(location.hash, `#object=${first}`);
  assert.equal(testApi.state().flow.root.id, first);
  assert.equal(testApi.state().selectedId, first);
  assert.equal(elements.get("detail").children[0].textContent, "dbo.31");

  history.forward();
  await settle();
  assert.equal(entries.length, 2);
  assert.equal(location.hash, `#object=${second}`);
  assert.equal(testApi.state().flow.root.id, second);
  assert.equal(testApi.state().selectedId, second);
  assert.equal(elements.get("detail").children[0].textContent, "dbo.32");
  assert.equal(fetches.get(`data/flows/${first}.json`), 2);
  assert.equal(fetches.get(`data/flows/${second}.json`), 2);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
