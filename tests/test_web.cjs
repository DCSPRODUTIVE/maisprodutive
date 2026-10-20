const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor() { this.children = []; this.handlers = {}; this.disabled = true; this.hidden = false; this._text = ""; }
  set textContent(text) { this._text = text; this.children = []; }
  get textContent() { return this._text; }
  replaceChildren() { this.children = []; this._text = ""; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.handlers[name] = callback; }
}

async function setup(networkResponse) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const calls = [];
  const status = { csrf: "test-csrf", configured: false, authenticated: false, devices: [], video_available: false };
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (url === "/api/status") return { ok: true, json: async () => status };
    if (url === "/api/connectivity") return networkResponse;
    throw new Error("Unexpected request: " + url);
  };
  const code = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8");
  vm.runInNewContext(code, { fetch, document: { getElementById: get, createElement: () => new Element() } });
  await new Promise(setImmediate);
  return { get, calls };
}

test("missing integration disables credentials but leaves network diagnostic usable", async () => {
  const { get } = await setup();
  assert.equal(get("credentials").disabled, true);
  assert.equal(get("connect").disabled, true);
  assert.equal(get("network").disabled, false);
  assert.match(get("configuration").textContent, /Login indisponível/);
});

test("successful network test sends no credentials and does not enable login", async () => {
  const { get, calls } = await setup({ ok: true, json: async () => ({
    observations: [{ host: "api3.cloud-links.net", protocol_response: true, reachable: true }],
    message: "1 de 1 servidores responderam como API. Este teste não faz login nem acessa vídeos.",
  }) });
  await get("network").handlers.click();
  const request = calls.find((call) => call.url === "/api/connectivity");
  assert.equal(request.options.body, "{}");
  assert.equal(request.options.headers["X-CSRF-Token"], "test-csrf");
  assert.equal(calls.some((call) => call.url === "/api/login"), false);
  assert.match(get("network-results").children[0].textContent, /API respondeu/);
  assert.match(get("network-results").children[1].textContent, /não faz login/);
  assert.equal(get("connect").disabled, true);
  assert.equal(get("network").disabled, false);
});

test("failed network test clears stale successes and restores the test button", async () => {
  const { get } = await setup({ ok: false, json: async () => ({ message: "Aguarde 30 segundos entre testes de rede." }) });
  get("network-results").append(new Element());
  await get("network").handlers.click();
  assert.equal(get("network-results").children.length, 0);
  assert.match(get("network-results").textContent, /Aguarde 30 segundos/);
  assert.equal(get("network").disabled, false);
});
