let csrf = "";
let busy = false;
let bulk = false;
let batchToken = 0;
let currentStatus = null;
let focused = false;
const economy = new Map();
const desired = new Map();
const qualities = new Map();
const snapshots = new Map();
const feeds = new Map();
const errors = new Map();
let views = new Map();
let cameraControls = [];
const $ = (id) => document.getElementById(id);

function frameAge(feed) {
  return feed.updatedAt ? (feed.age || 0) + (Date.now() - feed.updatedAt) / 1000 : Infinity;
}
function updateMetrics() {
  $("camera-count").textContent = String(currentStatus?.devices.length || 0);
  $("live-count").textContent = String([...feeds.values()].filter((f) => f.image && frameAge(f) <= 3).length);
  $("capture-count").textContent = String(snapshots.size);
}
function buttons() {
  const auth = !!currentStatus?.authenticated;
  const ready = auth && !!currentStatus?.snapshot_ready;
  $("network").disabled = busy || !csrf;
  $("credentials").disabled = busy || bulk || !currentStatus?.configured;
  $("connect").disabled = busy || bulk || !currentStatus?.configured;
  $("refresh").disabled = busy || bulk || !auth;
  $("logout").disabled = busy || !auth;
  $("watch-all").disabled = busy || bulk || !ready || !currentStatus?.devices.length;
  $("stop-all").disabled = busy || (!feeds.size && !desired.size && !economy.size && !bulk);
  for (const { id, capture, watch, stop, quality, saver } of cameraControls) {
    quality.disabled = busy || bulk || !ready;
    saver.disabled = busy || bulk || !ready;
    capture.disabled = busy || bulk || !ready || !!economy.get(id)?.paused || (feeds.has(id) && !feeds.get(id).image);
    watch.disabled = busy || bulk || !ready || feeds.has(id);
    stop.disabled = busy || (!feeds.has(id) && !desired.has(id) && !economy.has(id));
  }
  updateMetrics();
}
function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function stopEconomy(id) {
  const schedule = economy.get(id);
  if (schedule) { clearTimeout(schedule.pauseTimer); clearTimeout(schedule.nextTimer); }
  economy.delete(id);
}
async function economyCycle(id) {
  const schedule = economy.get(id);
  if (!schedule) return;
  clearTimeout(schedule.pauseTimer); clearTimeout(schedule.nextTimer);
  schedule.paused = false;
  schedule.nextAt = Date.now() + 30 * 60 * 1000;
  schedule.pauseTimer = setTimeout(async () => {
    if (economy.get(id) !== schedule) return;
    const feed = feeds.get(id);
    if (feed?.image) snapshots.set(id, feed.image);
    schedule.paused = true;
    await stopOne(id, true);
    paint(id); buttons();
  }, 5 * 60 * 1000);
  schedule.nextTimer = setTimeout(() => {
    if (economy.get(id) === schedule) return economyCycle(id);
  }, 30 * 60 * 1000);
  await startOne(id, true);
  render();
}
async function toggleEconomy(id) {
  if (economy.has(id)) {
    stopEconomy(id);
    await startOne(id);
  } else {
    economy.set(id, { paused: false });
    await economyCycle(id);
  }
  render();
}
function paint(id) {
  const view = views.get(id);
  if (!view) return;
  const feed = feeds.get(id);
  const saving = economy.get(id);
  const snapshot = snapshots.get(id);
  const image = feed ? feed.image : snapshot;
  const fresh = feed && feed.image && frameAge(feed) <= 3;
  view.card.className = "camera-card" + (fresh ? " is-live" : errors.has(id) ? " is-error" : "");
  view.badge.textContent = feed ? fresh ? "● AO VIVO" : feed.image ? "AGUARDANDO" : feed.state === "queued" ? "NA FILA" : "CONECTANDO" : errors.has(id) ? "ATENÇÃO" : snapshot ? "CAPTURA" : "EM ESPERA";
  view.img.hidden = !image;
  view.placeholder.hidden = !!image;
  if (image && view.img.src !== image) view.img.src = image;
  view.img.onload = () => {
    if (feed && view.img.naturalWidth) view.caption.textContent = `${feed.caption} Imagem: ${view.img.naturalWidth} × ${view.img.naturalHeight}.`;
  };
  view.caption.textContent = feed ? feed.caption + (view.img.naturalWidth ? ` Imagem: ${view.img.naturalWidth} × ${view.img.naturalHeight}.` : "") : errors.get(id) || (snapshot ? "Captura pontual desta sessão. A imagem não está sendo atualizada." : "Selecione Assistir para iniciar a transmissão.");
  if (saving?.paused) {
    view.badge.textContent = "ECONOMIA · PAUSADA";
    view.caption.textContent = `Último quadro · câmera desconectada. Próxima abertura: ${new Date(saving.nextAt).toLocaleTimeString("pt-BR", {hour:"2-digit", minute:"2-digit"})}.`;
  }
  view.overlay.textContent = saving?.paused ? "IMAGEM PAUSADA · ECONOMIA DE DADOS" : feed ? fresh ? "TRANSMISSÃO CONTÍNUA · SEM ÁUDIO" : "AGUARDANDO NOVOS QUADROS" : snapshot ? "CAPTURA PONTUAL" : "DCS · MONITORAMENTO";
}
function render() {
  $("cameras").replaceChildren();
  views = new Map();
  cameraControls = [];
  const devices = currentStatus?.devices || [];
  const search = ($("camera-search").value || "").trim().toLocaleLowerCase("pt-BR");
  const selected = devices.filter((camera) => camera.name.toLocaleLowerCase("pt-BR").includes(search));
  $("empty").hidden = devices.length > 0;
  for (const camera of selected) {
    const card = element("article", "camera-card");
    const header = element("div", "camera-head");
    const identity = element("div", "camera-title");
    const titles = element("div");
    titles.append(element("h3", "", camera.name), element("small", "", `CÂMERA ${String(devices.indexOf(camera)+1).padStart(2,"0")} · ${camera.id}`));
    identity.append(element("span", "camera-glyph", "▣"), titles);
    const badge = element("span", "camera-badge", "EM ESPERA");
    header.append(identity, badge);
    const media = element("div", "camera-media");
    const placeholder = element("div", "camera-placeholder");
    placeholder.append(element("strong", "", "▣"), element("p", "", "Aguardando visualização"));
    const img = element("img");
    img.alt = `Câmera ${camera.name}`;
    img.hidden = true;
    const overlay = element("span", "camera-overlay");
    const expand = element("button", "camera-expand", "⛶");
    expand.title = "Ampliar câmera";
    expand.addEventListener("click", () => {
      if (media.requestFullscreen) media.requestFullscreen().catch(() => { $("message").textContent = "Não foi possível abrir a tela cheia."; });
    });
    media.append(placeholder, img, overlay, expand);
    const caption = element("p", "camera-caption");
    const controls = element("div", "camera-controls");
    const quality = element("select", "camera-quality");
    quality.setAttribute?.("aria-label", `Qualidade de ${camera.name}`);
    for (const [value, label] of [["balanced", "Equilibrada"], ["original", "SD original"], ["hd", "HD · sem redução"], ["fhd", "FHD · sem redução"]]) {
      const option = element("option", "", label); option.value = value; quality.append(option);
    }
    quality.value = qualities.get(camera.id) || "balanced";
    quality.addEventListener("change", async () => {
      qualities.set(camera.id, quality.value);
      if (feeds.has(camera.id)) { await stopOne(camera.id, true); await startOne(camera.id); }
    });
    const group = element("div", "control-group");
    const capture = element("button", "secondary", "Capturar");
    capture.addEventListener("click", () => action("/api/video/snapshot", { device_id: camera.id }));
    const watch = element("button", "play", "Assistir");
    watch.addEventListener("click", () => economy.has(camera.id) ? economyCycle(camera.id) : startOne(camera.id));
    const stop = element("button", "quiet stop", "Parar");
    stop.addEventListener("click", () => stopOne(camera.id));
    group.append(watch, stop, capture);
    const saver = element("button", "data-saver" + (economy.has(camera.id) ? " selected" : ""), "Economia de dados");
    saver.setAttribute?.("aria-pressed", String(economy.has(camera.id)));
    saver.title = "5 minutos ao vivo a cada 30 minutos; conexão fechada durante a pausa";
    saver.addEventListener("click", () => toggleEconomy(camera.id));
    controls.append(group, saver);
    media.append(quality);
    card.append(header, media, caption, controls);
    views.set(camera.id, { card, img, placeholder, badge, caption, overlay });
    cameraControls.push({ id: camera.id, capture, watch, stop, quality, saver });
    paint(camera.id);
    $("cameras").append(card);
  }
  if (devices.length && !selected.length) $("cameras").append(element("p", "hint", "Nenhuma câmera encontrada para esta busca."));
  buttons();
}
async function status() {
  const response = await fetch("/api/status", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Não foi possível consultar o servidor.");
  csrf = data.csrf;
  const wasAuthenticated = currentStatus?.authenticated;
  currentStatus = data;
  if (!data.authenticated) { cancelAll(); snapshots.clear(); $("account-panel").open = true; }
  if (data.authenticated && !wasAuthenticated) $("account-panel").open = false;
  $("session-label").textContent = data.authenticated ? "Conta conectada" : "Conta desconectada";
  $("session-dot").className = data.authenticated ? "status-dot connected" : "status-dot";
  $("connect").textContent = "Entrar";
  $("login").hidden = !!data.authenticated;
  $("configuration").textContent = data.configured ? data.authenticated
    ? "Conta conectada. Consulte as câmeras e escolha quais deseja acompanhar."
    : data.auth_mode === "windows-experimental" ? "Entre com sua conta Yoosee para acessar as câmeras."
    : data.auth_mode === "account-experimental" ? "Modo antigo experimental. Para testar a API identificada no Windows, importe primeiro o instalador conforme as instruções do projeto."
    : "Pronto para testar a autenticação com a configuração SDK. Compatibilidade ainda não validada." : data.configuration_message;
  $("snapshot-status").textContent = data.auth_mode === "windows-experimental" ? data.snapshot_ready ? "Até 8 câmeras simultâneas. Selecione Assistir ou abra o mosaico." : data.snapshot_message || "" : "";
  if (data.detection_message) $("snapshot-status").textContent += " " + data.detection_message;
  render();
}
async function post(path, body, keepalive = false) {
  try {
    const response = await fetch(path, { method: "POST", cache: "no-store", keepalive,
      signal: keepalive ? undefined : AbortSignal.timeout(12000),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.message || "Falha na consulta."); error.status = response.status; error.kind = data.error; throw error; }
    return data;
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") throw new Error("O painel não respondeu a tempo. Tente novamente.");
    throw error;
  }
}
function cancelOne(id) {
  const feed = feeds.get(id);
  if (feed?.timer !== null && feed?.timer !== undefined) clearTimeout(feed.timer);
  feeds.delete(id);
  return feed;
}
function forget(id) {
  const intent = desired.get(id);
  if (intent?.timer !== undefined) clearTimeout(intent.timer);
  desired.delete(id);
}
function reconnect(id, error) {
  const intent = desired.get(id);
  const retryable = !error.status || error.status >= 500 || error.status === 429 ||
    ["video_timeout", "video_stale", "video_native", "video_decode", "video_resources", "video_stopped", "video_busy", "video_idle"].includes(error.kind);
  if (!intent || !retryable || !currentStatus?.authenticated) return;
  const delay = Math.min(60000, 5000 * 2 ** Math.min(intent.attempts++, 4));
  errors.set(id, `${error.message} Nova tentativa em ${delay / 1000}s.`);
  intent.timer = setTimeout(() => {
    if (desired.get(id) === intent) return startOne(id, intent.mosaic, true);
  }, delay);
}
function cancelAll() {
  for (const id of [...economy.keys()]) stopEconomy(id);
  for (const id of [...desired.keys()]) forget(id);
  batchToken++;
  bulk = false;
  for (const id of [...feeds.keys()]) cancelOne(id);
}
async function stopOne(id, preserveEconomy = false) {
  if (!preserveEconomy) stopEconomy(id);
  forget(id);
  const feed = cancelOne(id);
  paint(id); buttons();
  if (feed) {
    try { await post("/api/video/stop", { device_id: id, ...(feed.handle ? { stream_id: feed.handle } : {}) }); }
    catch (error) { $("message").textContent = error.message; }
  }
  paint(id); buttons();
}
async function stopAll() {
  cancelAll();
  render();
  try { await post("/api/video/stop", {}); $("message").textContent = "Todas as transmissões foram encerradas."; }
  catch (error) { $("message").textContent = error.message; }
}
async function startOne(id, mosaic = false, retry = false) {
  if (busy || feeds.has(id)) {
    if (retry) reconnect(id, new Error("Aguardando o painel ficar disponível."));
    return;
  }
  if (!retry) { forget(id); desired.set(id, { mosaic, attempts: 0 }); }
  const feed = { id, handle: null, sequence: 0, image: null, age: null, updatedAt: null, timer: null, caption: "Conectando. Aguardando o primeiro quadro…" };
  feeds.set(id, feed); errors.delete(id); render();
  try {
    const data = await post("/api/video/start", { device_id: id, mosaic, quality: qualities.get(id) || "balanced" });
    feed.handle = data.stream_id;
    if (feeds.get(id) !== feed) {
      await post("/api/video/stop", { device_id: id, stream_id: feed.handle });
      return;
    }
    feed.timer = setTimeout(() => pollFeed(feed), 0);
  } catch (error) {
    if (feeds.get(id) === feed) {
      cancelOne(id); errors.set(id, error.message); reconnect(id, error);
      $("message").textContent = error.message;
      render();
    }
  }
}
async function startAll() {
  if (busy || bulk) return;
  const token = ++batchToken;
  bulk = true;
  setFocus(true);
  buttons();
  $("message").textContent = "Abrindo o mosaico. As câmeras conectam de forma independente…";
  for (const camera of (currentStatus?.devices || []).slice(0, 8)) {
    if (token !== batchToken) break;
    if (economy.has(camera.id)) continue;
    await startOne(camera.id, true);
  }
  if (token === batchToken) { bulk = false; $("message").textContent = "Mosaico iniciado. Cada câmera recebe imagens de forma independente."; buttons(); }
}
async function pollFeed(feed) {
  if (feeds.get(feed.id) !== feed) return;
  try {
    const data = await post("/api/video/frame", { device_id: feed.id, stream_id: feed.handle, after: feed.sequence });
    if (feeds.get(feed.id) !== feed) return;
    if (data.device_id !== feed.id) throw new Error("A câmera da transmissão mudou. Inicie novamente.");
    if (typeof data.image === "string" && data.image.startsWith("data:image/jpeg;base64,")) {
      feed.image = data.image; feed.sequence = data.sequence;
      if (desired.has(feed.id)) desired.get(feed.id).attempts = 0;
    }
    feed.state = data.state;
    feed.age = data.age_seconds;
    feed.updatedAt = Date.now();
    feed.caption = data.age_seconds > 3 ? `Sem novos quadros há ${Math.floor(data.age_seconds)} segundos…`
      : feed.image ? "Recebendo imagens contínuas · até 5 imagens/s · sem áudio." : data.state === "queued" ? "Na fila de conexão. As câmeras abrem em etapas para manter a estabilidade." : "Conectando. Aguardando o primeiro quadro…";
    paint(feed.id); buttons();
    feed.timer = setTimeout(() => pollFeed(feed), 200);
  } catch (error) {
    if (feeds.get(feed.id) !== feed) return;
    cancelOne(feed.id); errors.set(feed.id, error.message);
    if (error.status === 403) {
      cancelAll(); snapshots.clear();
      try { await status(); } catch { render(); }
      $("message").textContent = "A sessão expirou. Entre novamente para continuar.";
      return;
    }
    try { await post("/api/video/stop", { device_id: feed.id, stream_id: feed.handle }); } catch { /* Idle lease is the final fallback. */ }
    reconnect(feed.id, error);
    $("message").textContent = error.message;
    paint(feed.id); buttons();
  }
}
async function action(path, body) {
  let openCameras = false;
  if (busy) return;
  busy = true; buttons();
  $("message").textContent = path === "/api/video/snapshot" ? "Capturando imagem…" : "Consultando…";
  if (path === "/api/connectivity") $("network-results").textContent = "Testando a comunicação com os servidores…";
  try {
    if (["/api/login", "/api/logout", "/api/devices"].includes(path)) {
      const hadFeeds = feeds.size > 0 || desired.size > 0 || bulk;
      cancelAll(); snapshots.clear(); errors.clear();
      if (hadFeeds) try { await post("/api/video/stop", {}); } catch { /* Session operation also closes streams. */ }
    }
    // Snapshot can take up to one minute; no new login or automatic retries.
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Falha na consulta.");
    if (path === "/api/video/snapshot" && typeof data.image === "string" && data.image.startsWith("data:image/jpeg;base64,")) {
      snapshots.set(body.device_id, data.image); errors.delete(body.device_id);
    }
    if (path === "/api/connectivity") {
      $("network-results").replaceChildren();
      for (const observation of data.observations) {
        const result = observation.protocol_response ? "API respondeu" : observation.reachable ? "servidor acessível; API não confirmada" : "sem comunicação";
        $("network-results").append(element("p", "", `${observation.host}: ${result}.`));
      }
      $("network-results").append(element("p", "", data.message));
    }
    $("message").textContent = data.message || "Consulta concluída.";
    if (path === "/api/login") {
      $("message").textContent = "Conta conectada. Buscando suas câmeras…";
      await post("/api/devices", {});
      openCameras = true;
    }
  } catch (error) {
    $("message").textContent = error.message;
    if (path === "/api/video/snapshot") errors.set(body.device_id, error.message);
    if (path === "/api/connectivity") $("network-results").textContent = error.message;
  } finally {
    try { await status(); } catch (error) { $("message").textContent = error.message; }
    busy = false; buttons();
    if (openCameras && currentStatus?.authenticated && currentStatus?.snapshot_ready) await startAll();
  }
}
// Refresh the HttpOnly cookie and local idle lease, even when cameras are stopped.
if (typeof setInterval !== "undefined") setInterval(() => {
  fetch("/api/status", { cache: "no-store", signal: AbortSignal.timeout(12000) })
    .then(response => response.ok ? response.json() : null)
    .then(data => {
      if (data && currentStatus?.authenticated && !data.authenticated) {
        cancelAll(); snapshots.clear();
        status().catch(() => {});
        $("message").textContent = "A sessão terminou. Entre novamente para continuar.";
      }
    }).catch(() => {});
}, 5 * 60 * 1000);
if (typeof setInterval !== "undefined") setInterval(() => {
  for (const feed of feeds.values()) {
    if (feed.image && frameAge(feed) > 3) feed.caption = `Sem novos quadros há ${Math.floor(frameAge(feed))} segundos…`;
    paint(feed.id);
  }
  updateMetrics();
}, 1000);
$("login").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const username = form.elements.username.value;
  const password = form.elements.password.value;
  const country_code = form.elements.country_code.value;
  form.elements.password.value = "";
  return action("/api/login", { username, password, country_code });
});
$("refresh").addEventListener("click", () => action("/api/devices", {}));
$("network").addEventListener("click", () => action("/api/connectivity", {}));
$("logout").addEventListener("click", () => { $("login").reset(); action("/api/logout", {}); });
function setFocus(value) {
  focused = value;
  $("dashboard").className = focused ? "focus-mode" : "";
  $("focus-mode").textContent = focused ? "⛶ Sair da visão completa" : "⛶ Visão completa";
}
$("focus-mode").addEventListener("click", () => setFocus(!focused));
$("tv-exit").addEventListener("click", () => setFocus(false));
$("camera-search").addEventListener("input", render);
$("watch-all").addEventListener("click", startAll);
$("stop-all").addEventListener("click", stopAll);
if (typeof window !== "undefined") window.addEventListener("pagehide", () => {
  const hadFeeds = feeds.size > 0 || desired.size > 0 || bulk;
  cancelAll();
  if (hadFeeds) post("/api/video/stop", {}, true).catch(() => {});
});
status().catch((error) => { $("message").textContent = error.message; });
