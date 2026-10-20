let csrf = "";
let busy = false;
let currentStatus = null;
const snapshots = new Map();
const $ = (id) => document.getElementById(id);
function buttons() {
  $("network").disabled = busy || !csrf;
  $("credentials").disabled = busy || !currentStatus?.configured;
  $("connect").disabled = busy || !currentStatus?.configured;
  $("refresh").disabled = busy || !currentStatus?.authenticated;
  $("logout").disabled = busy || !currentStatus?.authenticated;
  for (const button of snapshotButtons) button.disabled = busy || !currentStatus?.authenticated || !currentStatus?.snapshot_ready;
}
let snapshotButtons = [];
async function status() {
  const response = await fetch("/api/status", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Não foi possível consultar o servidor.");
  csrf = data.csrf;
  currentStatus = data;
  $("connect").textContent = data.auth_mode === "windows-experimental" ? "Testar login Windows" : "Testar login experimental";
  $("configuration").textContent = data.configured
    ? (data.authenticated ? "Conta autenticada nesta sessão. O vídeo ainda não está disponível." :
      (data.auth_mode === "windows-experimental"
        ? "Perfil Windows preparado. O próximo teste usa a API identificada no instalador enviado. Acesso à conta e ao vídeo ainda precisam ser confirmados."
        : data.auth_mode === "account-experimental"
        ? "Modo antigo experimental. Para testar a API identificada no Windows, importe primeiro o instalador conforme as instruções do projeto."
        : "Pronto para testar a autenticação com a configuração SDK. Compatibilidade ainda não validada."))
    : data.configuration_message;
  $("cameras").replaceChildren();
  snapshotButtons = [];
  $("snapshot-status").textContent = data.auth_mode === "windows-experimental" ? data.snapshot_message || "" : "";
  $("empty").hidden = data.devices.length > 0;
  for (const camera of data.devices) {
    const card = document.createElement("article");
    const title = document.createElement("h3");
    title.textContent = camera.name;
    const id = document.createElement("p");
    id.textContent = `ID: ${camera.id}`;
    const note = document.createElement("p");
    note.textContent = "Vídeo ainda indisponível nesta integração.";
    card.append(title, id, note);
    if (data.auth_mode === "windows-experimental") {
      const capture = document.createElement("button");
      capture.textContent = "Testar imagem";
      capture.addEventListener("click", () => action("/api/video/snapshot", { device_id: camera.id }));
      snapshotButtons.push(capture);
      card.append(capture);
      if (snapshots.has(camera.id)) {
        const img = document.createElement("img");
        img.src = snapshots.get(camera.id);
        img.alt = `Captura pontual de ${camera.name}`;
        const caption = document.createElement("p");
        caption.textContent = "Imagem capturada neste teste. Não é transmissão ao vivo.";
        card.append(img, caption);
      }
    }
    $("cameras").append(card);
  }
  buttons();
}
async function action(path, body) {
  if (busy) return;
  busy = true;
  if (["/api/login", "/api/logout", "/api/devices"].includes(path)) snapshots.clear();
  buttons();
  $("message").textContent = "Consultando…";
  if (path === "/api/connectivity") $("network-results").textContent = "Testando a comunicação com os servidores…";
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Falha na consulta.");
    if (path === "/api/video/snapshot" && typeof data.image === "string" && data.image.startsWith("data:image/jpeg;base64,")) snapshots.set(body.device_id, data.image);
    if (path === "/api/connectivity") {
      $("network-results").replaceChildren();
      for (const observation of data.observations) {
        const line = document.createElement("p");
        const result = observation.protocol_response ? "API respondeu" :
          (observation.reachable ? "servidor acessível; API não confirmada" : "sem comunicação");
        line.textContent = `${observation.host}: ${result}.`;
        $("network-results").append(line);
      }
      const summary = document.createElement("p");
      summary.textContent = data.message;
      $("network-results").append(summary);
    }
    $("message").textContent = data.message || "Consulta concluída. Isso não confirma acesso ao vídeo.";
  } catch (error) {
    $("message").textContent = error.message;
    if (path === "/api/connectivity") $("network-results").textContent = error.message;
  } finally {
    try { await status(); } catch (error) { $("message").textContent = error.message; }
    busy = false;
    buttons();
  }
}
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
status().catch((error) => { $("message").textContent = error.message; });
