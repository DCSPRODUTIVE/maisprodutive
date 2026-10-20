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

async function setup(networkResponse, statusOverride = {}, loginResponse = null, snapshotResponse = null) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const calls = [];
  const status = { csrf: "test-csrf", configured: true, auth_mode: "account-experimental",
    authenticated: false, devices: [], video_available: false, ...statusOverride };
  get("login").elements = { username: { value: "" }, password: { value: "" }, country_code: { value: "55" } };
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (url === "/api/status") return { ok: true, json: async () => status };
    if (url === "/api/connectivity") return networkResponse;
    if (url === "/api/login" && loginResponse) return loginResponse;
    if (url === "/api/video/snapshot" && snapshotResponse) return snapshotResponse;
    throw new Error("Unexpected request: " + url);
  };
  const code = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8");
  vm.runInNewContext(code, { fetch, document: { getElementById: get, createElement: () => new Element() } });
  await new Promise(setImmediate);
  return { get, calls };
}

test("account-only experiment enables login with an explicit compatibility notice", async () => {
  const { get } = await setup();
  assert.equal(get("credentials").disabled, false);
  assert.equal(get("connect").disabled, false);
  assert.equal(get("network").disabled, false);
  assert.match(get("configuration").textContent, /Modo antigo experimental/);
  assert.match(get("configuration").textContent, /importe primeiro/);
});

test("invalid SDK configuration disables login and explains the configuration error", async () => {
  const { get } = await setup(null, { configured: false, configuration_message: "Configuração SDK incompleta" });
  assert.equal(get("credentials").disabled, true);
  assert.equal(get("connect").disabled, true);
  assert.match(get("configuration").textContent, /Configuração SDK incompleta/);
  assert.equal(get("network").disabled, false);
});

test("imported Windows profile selects the new login label without claiming authentication", async () => {
  const { get } = await setup(null, { auth_mode: "windows-experimental" });
  assert.equal(get("connect").textContent, "Testar login Windows");
  assert.match(get("configuration").textContent, /Perfil Windows preparado/);
  assert.match(get("configuration").textContent, /ainda precisam ser confirmados/);
  assert.equal(get("refresh").disabled, true);
});

test("successful network test sends no credentials and does not authenticate", async () => {
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
  assert.equal(get("refresh").disabled, true);
  assert.equal(get("network").disabled, false);
});

test("login submits once, clears password, and displays the provider rejection", async () => {
  const { get, calls } = await setup(null, {}, { ok: false,
    json: async () => ({ message: "Yoosee não aceitou a operação (código 10901020)." }) });
  const form = get("login");
  form.elements.username.value = "test@example.invalid";
  form.elements.password.value = "test-password";
  const attempt = form.handlers.submit({ preventDefault() {}, currentTarget: form });
  assert.equal(form.elements.password.value, "");
  await attempt;
  const submissions = calls.filter((call) => call.url === "/api/login");
  assert.equal(submissions.length, 1);
  assert.deepEqual(JSON.parse(submissions[0].options.body), { username: "test@example.invalid", password: "test-password", country_code: "55" });
  assert.match(get("message").textContent, /10901020/);
  assert.equal(get("refresh").disabled, true);
  assert.equal(get("connect").disabled, false);
});

test("failed network test clears stale successes and restores the test button", async () => {
  const { get } = await setup({ ok: false, json: async () => ({ message: "Aguarde 30 segundos entre testes de rede." }) });
  get("network-results").append(new Element());
  await get("network").handlers.click();
  assert.equal(get("network-results").children.length, 0);
  assert.match(get("network-results").textContent, /Aguarde 30 segundos/);
  assert.equal(get("network").disabled, false);
});

test("capture renders a received image as a still and sends only the selected device", async () => {
  const image = "data:image/jpeg;base64,/9j/test/9k=";
  const { get, calls } = await setup(null, { auth_mode: "windows-experimental", authenticated: true,
    snapshot_ready: true, devices: [{ id: "owned", name: "Minha câmera" }] }, null,
    { ok: true, json: async () => ({ image, message: "Imagem recebida. Captura pontual." }) });
  const card = get("cameras").children[0];
  const button = card.children[3];
  assert.equal(button.textContent, "Testar imagem");
  assert.equal(button.disabled, false);
  await button.handlers.click();
  const submitted = calls.filter((call) => call.url === "/api/video/snapshot");
  assert.equal(submitted.length, 1);
  assert.deepEqual(JSON.parse(submitted[0].options.body), { device_id: "owned" });
  const updated = get("cameras").children[0];
  assert.equal(updated.children[4].src, image);
  assert.match(updated.children[5].textContent, /Não é transmissão ao vivo/);
});

test("unprepared capture stays disabled and explains the local requirement", async () => {
  const { get } = await setup(null, { auth_mode: "windows-experimental", authenticated: true,
    snapshot_ready: false, snapshot_message: "Prepare o adaptador local.", devices: [{ id: "owned", name: "Minha câmera" }] });
  assert.equal(get("cameras").children[0].children[3].disabled, true);
  assert.match(get("snapshot-status").textContent, /Prepare o adaptador/);
});
