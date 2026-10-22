let csrf = "";
let busy = false;
let bulk = false;
let batchToken = 0;
let currentStatus = null;
let focused = false;
let expandedCamera = null;
let expandedPrevious = null;
let mosaicLimit = 8;
let preferenceKey = null;
let preferenceSave = Promise.resolve();
const preferredEconomy = new Set();
const detectionIds = new Set();
const detectionPending = new Set();
const economy = new Map();
const desired = new Map();
const qualities = new Map();
const snapshots = new Map();
const feeds = new Map();
const errors = new Map();
let views = new Map();
let cameraControls = [];
const $ = (id) => document.getElementById(id);

function serverManaged(id) { return !!currentStatus?.server_monitoring && detectionIds.has(id); }
function frameAge(feed) {
  return feed.updatedAt ? (feed.age || 0) + (Date.now() - feed.updatedAt) / 1000 : Infinity;
}
function updateMetrics() {
  $("camera-count").textContent = String(currentStatus?.devices.length || 0);
  $("live-count").textContent = String([...feeds.values()].filter((f) => f.image && f.state !== "paused" && frameAge(f) <= 3).length);
  $("capture-count").textContent = String(snapshots.size);
}
function buttons() {
  const auth = !!currentStatus?.authenticated;
  const ready = auth && !!currentStatus?.snapshot_ready;
  $("mosaic-limit").disabled = busy || bulk;
  $("network").disabled = busy || !csrf;
  $("credentials").disabled = busy || bulk || !currentStatus?.configured;
  $("connect").disabled = busy || bulk || !currentStatus?.configured;
  $("refresh").disabled = busy || bulk || !auth;
  $("logout").disabled = busy || !auth;
  $("watch-all").disabled = busy || bulk || !ready || !currentStatus?.devices.length;
  $("stop-all").disabled = busy || (!feeds.size && !desired.size && !economy.size && !bulk);
  for (const { id, capture, watch, stop, quality, saver, detector } of cameraControls) {
    quality.disabled = busy || bulk || !ready;
    detector.disabled = busy || bulk || !ready || detectionPending.has(id);
    saver.disabled = busy || bulk || !ready;
    capture.disabled = busy || bulk || !ready || (!!economy.get(id)?.paused || feeds.get(id)?.state === "paused") || (feeds.has(id) && !feeds.get(id).image);
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
  if(serverManaged(id)){stopEconomy(id);return startOne(id,true);}
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
function savePreferences() {
  const ids = [...preferredEconomy].filter(id => currentStatus?.devices.some(camera => camera.id === id));
  const payload = {economy_ids: ids, detection_ids:[...detectionIds].filter(id=>currentStatus?.devices.some(camera=>camera.id===id)), mosaic_limit: mosaicLimit};
  const owner=currentStatus?.preferences_key;
  preferenceSave = preferenceSave.then(() => {
    if(owner!==currentStatus?.preferences_key)throw new Error("A conta mudou. Salve novamente.");
    return post("/api/preferences", payload).then(data=>{
      if(data.background_status && currentStatus){
        currentStatus.background_status=data.background_status;
        $("background-status").textContent=`Monitoramento em segundo plano: ${data.background_status.configured} câmera(s) habilitada(s). Fechar a página não interrompe os registros.`;
      }
      return data;
    });
  }).catch(error => {
    $("message").textContent = `Não foi possível confirmar as preferências. Recarregue para verificar: ${error.message}`;
  });
  return preferenceSave;
}
async function toggleDetection(id) {
  if(detectionPending.has(id))return;
  const wasEnabled=detectionIds.has(id);
  if(wasEnabled)detectionIds.delete(id);else detectionIds.add(id);
  detectionPending.add(id);render();
  const wasViewing=feeds.has(id)||economy.has(id);
  const saved=await savePreferences();
  if(!saved){if(wasEnabled)detectionIds.add(id);else detectionIds.delete(id);}
  if(saved && currentStatus?.server_monitoring && wasViewing){
    stopEconomy(id);await stopOne(id,true);await watchCamera(id);
  }
  detectionPending.delete(id);render();
}
async function watchCamera(id) {
  if(serverManaged(id))return startOne(id,true);
  if (preferredEconomy.has(id)) {
    if (!economy.has(id)) economy.set(id, {paused:false});
    await economyCycle(id);
  } else await startOne(id);
}
async function toggleEconomy(id) {
  if(serverManaged(id)){
    const wasSaving=preferredEconomy.has(id);
    if(wasSaving)preferredEconomy.delete(id);else preferredEconomy.add(id);
    const saved=await savePreferences();
    if(!saved){if(wasSaving)preferredEconomy.add(id);else preferredEconomy.delete(id);render();return;}
    stopEconomy(id);await stopOne(id,true);await startOne(id,true);render();return;
  }
  if (preferredEconomy.has(id)) {
    preferredEconomy.delete(id);
    stopEconomy(id);
    await startOne(id);
  } else {
    preferredEconomy.add(id);
    economy.set(id, { paused: false });
    await economyCycle(id);
  }
  await savePreferences();
  render();
}
function paint(id) {
  const view = views.get(id);
  if (!view) return;
  const feed = feeds.get(id);
  const saving = economy.get(id);
  const snapshot = snapshots.get(id);
  const image = feed ? feed.image : snapshot;
  const fresh = feed && feed.image && feed.state !== "paused" && frameAge(feed) <= 3;
  view.card.className = "camera-card" + (id===expandedCamera ? " camera-expanded" : "") + (fresh ? " is-live" : errors.has(id) ? " is-error" : "");
  view.badge.textContent = feed ? feed.state === "paused" ? "ECONOMIA · PAUSADA" : fresh ? "● AO VIVO" : feed.image ? "AGUARDANDO" : feed.state === "queued" ? "NA FILA" : "CONECTANDO" : errors.has(id) ? "ATENÇÃO" : snapshot ? "CAPTURA" : "EM ESPERA";
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
  view.overlay.textContent = (saving?.paused || feed?.state === "paused") ? "IMAGEM PAUSADA · ECONOMIA DE DADOS" : feed ? fresh ? "TRANSMISSÃO CONTÍNUA · SEM ÁUDIO" : "AGUARDANDO NOVOS QUADROS" : snapshot ? "CAPTURA PONTUAL" : "DCS · MONITORAMENTO";
}
function render() {
  $("cameras").className = "camera-grid" + (mosaicLimit === 12 ? " mosaic-12" : "");
  $("cameras").replaceChildren();
  views = new Map();
  cameraControls = [];
  const devices = currentStatus?.devices || [];
  const search = ($("camera-search").value || "").trim().toLocaleLowerCase("pt-BR");
  const selected = devices.slice(0, mosaicLimit).filter((camera) => camera.name.toLocaleLowerCase("pt-BR").includes(search));
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
    expand.addEventListener("click", async () => {
      if(expandedCamera===camera.id){await closeExpanded();return;}
      expandedCamera=camera.id;
      expandedPrevious=qualities.get(camera.id)||"balanced";
      // Keep the 4G source selection: enlarging must not silently increase its data use.
      qualities.set(camera.id,preferredEconomy.has(camera.id)?expandedPrevious:"fhd");
      document.documentElement?.requestFullscreen?.().catch(()=>{});
      await stopOne(camera.id,true);await startOne(camera.id);render();
    });
    if(expandedCamera===camera.id){expand.textContent="✕";expand.title="Voltar ao mosaico";}
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
    watch.addEventListener("click", () => watchCamera(camera.id));
    const stop = element("button", "quiet stop", "Parar");
    stop.addEventListener("click", () => stopOne(camera.id));
    group.append(watch, stop, capture);
    const saver = element("button", "data-saver" + (preferredEconomy.has(camera.id) ? " selected" : ""), "Economia de dados");
    saver.setAttribute?.("aria-pressed", String(preferredEconomy.has(camera.id)));
    saver.title = "5 minutos ao vivo a cada 30 minutos; conexão fechada durante a pausa";
    saver.addEventListener("click", () => toggleEconomy(camera.id));
    const detector=element("button","person-detector"+(detectionIds.has(camera.id)?" selected":""),"Detectar pessoas");
    detector.setAttribute?.("aria-pressed",String(detectionIds.has(camera.id)));
    detector.title="Salvar fotos e vídeos de até 2 minutos quando detectar pessoas";
    detector.addEventListener("click",()=>toggleDetection(camera.id));
    controls.append(group, saver, detector);
    media.append(quality);
    card.append(header, media, caption, controls);
    views.set(camera.id, { card, img, placeholder, badge, caption, overlay });
    cameraControls.push({ id: camera.id, capture, watch, stop, quality, saver, detector });
    paint(camera.id);
    $("cameras").append(card);
  }
  if (devices.length && !selected.length) $("cameras").append(element("p", "hint", "Nenhuma câmera encontrada para esta busca."));
  buttons();
}
async function readResponse(response) {
  try {
    const data=await response.json();
    if(!data || typeof data!=="object" || Array.isArray(data))throw new Error("Invalid response");
    return data;
  } catch {
    const code=Number.isInteger(response.status)?response.status:0;
    const error=new Error(code>=500
      ? `O servidor ou túnel está temporariamente indisponível (HTTP ${code}).`
      : "O painel recebeu uma resposta inválida do servidor ou túnel. Verifique a conexão.");
    error.status=code>=500 || code===429?code:503;
    error.kind="connection";
    throw error;
  }
}
async function status() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (response.status === 401 && typeof window !== "undefined") window.location.replace("/access");
  const data = await readResponse(response);
  if (!response.ok) throw new Error(data.message || "Não foi possível consultar o servidor.");
  csrf = data.csrf;
  const wasAuthenticated = currentStatus?.authenticated;
  currentStatus = data;
  let restored = false;
  if (!data.authenticated) { preferenceKey=null; preferredEconomy.clear(); detectionIds.clear(); }
  if (data.authenticated && data.preferences_key && data.preferences_key !== preferenceKey) {
    preferenceKey=data.preferences_key;
    preferredEconomy.clear(); detectionIds.clear();
    for (const id of data.preferences?.detection_ids || []) detectionIds.add(id);
    for (const id of data.preferences?.economy_ids || []) preferredEconomy.add(id);
    mosaicLimit=data.preferences?.mosaic_limit === 12 ? 12 : 8;
    $("mosaic-limit").value=String(mosaicLimit);
    restored=true;
  }
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
  $("snapshot-status").textContent = data.auth_mode === "windows-experimental" ? data.snapshot_ready ? `Mosaico de até ${mosaicLimit} câmeras. Preferências salvas por conta.` : data.snapshot_message || "" : "";
  if (data.detection_message) $("snapshot-status").textContent += " " + data.detection_message;
  $("mosaic-label").textContent = `MOSAICO · ATÉ ${mosaicLimit} CÂMERAS`;
  render();
  const monitoring=data.background_status;
  $("background-status").textContent=data.authenticated && data.server_monitoring
    ? `Monitoramento em segundo plano: ${monitoring?.configured || 0} câmera(s) habilitada(s), ${monitoring?.paused || 0} em pausa. Fechar a página não interrompe os registros.` : "";
  if (restored && !busy && data.snapshot_ready) await startAll();
}
async function post(path, body, keepalive = false) {
  try {
    const response = await fetch(path, { method: "POST", cache: "no-store", keepalive,
      signal: keepalive ? undefined : AbortSignal.timeout(12000),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
    if (response.status === 401 && typeof window !== "undefined") window.location.replace("/access");
    const data = await readResponse(response);
    if (!response.ok) { const error = new Error(data.message || "Falha na consulta."); error.status = response.status; error.kind = data.error; throw error; }
    return data;
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") throw new Error("O painel não respondeu a tempo. Tente novamente.");
    if(error instanceof TypeError) throw new Error("A conexão com o painel foi perdida. Verifique o servidor, o túnel e a internet.");
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
  const delay = Math.min(60000, 2000 * 2 ** Math.min(intent.attempts++, 5));
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
  try { await post("/api/video/stop", {}); $("message").textContent = currentStatus?.server_monitoring ? "Visualizações encerradas. Câmeras com Detectar pessoas continuam monitorando no servidor." : "Todas as transmissões foram encerradas."; }
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
    const chosen=qualities.get(id)||'balanced';
    const attempts=desired.get(id)?.attempts||0;
    const effective=attempts>=4?'balanced':attempts>=2&&chosen==='fhd'?'hd':chosen;
    const data = await post("/api/video/start", { device_id: id, mosaic, quality: effective });
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
  for (const camera of (currentStatus?.devices || []).slice(0, mosaicLimit)) {
    if (token !== batchToken) break;
    if (serverManaged(camera.id)) { await startOne(camera.id,true); continue; }
    if (preferredEconomy.has(camera.id)) {
      if (!economy.has(camera.id)) { economy.set(camera.id, {paused:false}); await economyCycle(camera.id); }
      continue;
    }
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
    feed.health = data.health;
    feed.state = data.state;
    feed.age = data.age_seconds;
    feed.updatedAt = Date.now();
    feed.caption = data.state === "paused" ? `${feed.image ? "Último quadro · conexão fechada" : "Câmera pausada para economizar dados"}. Nova janela em ${Math.ceil((data.next_open_seconds || 0)/60)} min. Agendamento mantido pelo servidor.`
      : data.state === "retrying" ? `${data.message || "Reconectando a câmera."} Nova tentativa em ${data.retry_seconds || 0}s pelo servidor.`
      : data.age_seconds > 3 ? `Sem novos quadros há ${Math.floor(data.age_seconds)} segundos…`
      : feed.image ? `Recebendo imagens · ${data.health?.fps ?? "—"} fps · ${data.health?.resolution?.join(" × ") || "resolução em leitura"} · sem áudio.${data.health?.detection?.error ? " Falha na análise; nova tentativa automática." : data.health?.detection?.age_seconds !== undefined ? " Análise há "+data.health.detection.age_seconds+"s · "+data.health.detection.people+" pessoa(s)." : ""}` : data.state === "queued" ? "Na fila de conexão. As câmeras abrem em etapas para manter a estabilidade." : "Conectando. Aguardando o primeiro quadro…";
    paint(feed.id); buttons();
    feed.timer = setTimeout(() => pollFeed(feed), data.state === "paused" ? 1000 : data.image ? 70 : 100);
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
    const data = await readResponse(response);
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
    .then(response => response.ok ? readResponse(response) : null)
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
    if (feed.image && feed.state !== "paused" && frameAge(feed) > 3) feed.caption = `Sem novos quadros há ${Math.floor(frameAge(feed))} segundos…`;
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
$("mosaic-limit").value="8";
$("mosaic-limit").addEventListener("change", async () => {
  mosaicLimit=$("mosaic-limit").value === "12" ? 12 : 8;
  $("mosaic-label").textContent=`MOSAICO · ATÉ ${mosaicLimit} CÂMERAS`;
  await savePreferences();
  const active=feeds.size>0 || economy.size>0;
  const keep=new Set((currentStatus?.devices || []).slice(0,mosaicLimit).map(camera=>camera.id));
  for(const id of new Set([...feeds.keys(),...economy.keys()])) if(!keep.has(id)) await stopOne(id);
  render();
  if(active) await startAll();
});
$("camera-search").addEventListener("input", render);
$("watch-all").addEventListener("click", startAll);
$("stop-all").addEventListener("click", stopAll);
if (typeof window !== "undefined") window.addEventListener("pagehide", () => {
  const hadFeeds = feeds.size > 0 || desired.size > 0 || bulk;
  cancelAll();
  if (hadFeeds) post("/api/video/stop", {}, true).catch(() => {});
});
status().catch((error) => { $("message").textContent = error.message; });

async function closeExpanded(){
  const id=expandedCamera;if(!id)return;
  expandedCamera=null;qualities.set(id,expandedPrevious||'balanced');expandedPrevious=null;
  if(document.fullscreenElement)document.exitFullscreen?.().catch(()=>{});
  if(feeds.has(id)){await stopOne(id,true);await startOne(id,true);}else render();
}
document.addEventListener?.('fullscreenchange',()=>{if(!document.fullscreenElement&&expandedCamera)closeExpanded();});
document.addEventListener?.('keydown',event=>{if(event.key==='Escape'&&expandedCamera)closeExpanded();});
