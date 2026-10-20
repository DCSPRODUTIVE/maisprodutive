let csrf = "";
let busy = false;
let currentStatus = null;
const $ = (id) => document.getElementById(id);
function buttons() {
  $("network").disabled = busy || !csrf;
  $("credentials").disabled = busy || !currentStatus?.configured;
  $("connect").disabled = busy || !currentStatus?.configured;
  $("refresh").disabled = busy || !currentStatus?.authenticated;
  $("logout").disabled = busy || !currentStatus?.authenticated;
}
async function status() {
  const response = await fetch("/api/status", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Não foi possível consultar o servidor.");
  csrf = data.csrf;
  currentStatus = data;
  $("configuration").textContent = data.configured
    ? (data.authenticated ? "Conta autenticada nesta sessão." : "Pronto para testar a autenticação. Compatibilidade ainda não validada.")
    : "Login indisponível: a integração de desenvolvedor com a Yoosee ainda precisa ser configurada. Você pode usar o teste de comunicação acima sem informar sua senha.";
  $("cameras").replaceChildren();
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
    $("cameras").append(card);
  }
  buttons();
}
async function action(path, body) {
  if (busy) return;
  busy = true;
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
  form.elements.password.value = "";
  action("/api/login", { username, password });
});
$("refresh").addEventListener("click", () => action("/api/devices", {}));
$("network").addEventListener("click", () => action("/api/connectivity", {}));
$("logout").addEventListener("click", () => { $("login").reset(); action("/api/logout", {}); });
status().catch((error) => { $("message").textContent = error.message; });
