const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") { this.tagName = tag; this.children = []; this.handlers = {}; this.disabled = true; this.hidden = false; this._text = ""; this.styles={}; this.style={setProperty:(key,value)=>{this.styles[key]=value;}}; }
  set textContent(text) { this._text = text; this.children = []; }
  get textContent() { return this._text; }
  replaceChildren() { this.children = []; this._text = ""; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.handlers[name] = callback; }
}

function descendants(el) { return [el, ...el.children.flatMap(descendants)]; }

async function setup(networkResponse, statusOverride = {}, loginResponse = null, snapshotResponse = null, extra = {}) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const calls = [];
  const timers = new Map();
  let timerId = 0;
  let clock = 1000;
  const intervals = [];
  const status = { csrf: "test-csrf", configured: true, auth_mode: "account-experimental",
    authenticated: false, devices: [], video_available: false, ...statusOverride };
  get("login").elements = { username: { value: "" }, password: { value: "" }, country_code: { value: "55" } };
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (extra[url]) return typeof extra[url] === "function" ? extra[url](options) : extra[url];
    if (url === "/api/status") return { ok: true, json: async () => status };
    if (url === "/api/preferences") return {ok:true,json:async()=>({message:"Salvo"})};
    if (url === "/api/connectivity") return networkResponse;
    if (url === "/api/login" && loginResponse) return loginResponse;
    if (url === "/api/video/snapshot" && snapshotResponse) return snapshotResponse;
    throw new Error("Unexpected request: " + url);
  };
  const code = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8");
  vm.runInNewContext(code, { fetch, AbortSignal, Date: class extends Date { static now() { return clock; } },
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    document: { getElementById: get, createElement: (tag) => new Element(tag) } });
  await new Promise(setImmediate);
  return { get, calls, timers, runDelay: async (ms) => {
    const entry=[...timers].find(([,timer])=>timer.ms===ms);
    assert.ok(entry, `Expected timer ${ms}`);
    timers.delete(entry[0]); await entry[1].fn();
  }, advance: (ms) => { clock += ms; intervals.forEach((fn) => fn()); }, runTimer: async () => {
    const next = [...timers].sort((a,b) => a[1].ms-b[1].ms)[0];
    if (next) { timers.delete(next[0]); await next[1].fn(); }
  } };
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
  assert.equal(get("connect").textContent, "Entrar");
  assert.match(get("configuration").textContent, /conta Yoosee/);
  assert.match(get("configuration").textContent, /Entre com sua conta/);
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
  const button = descendants(card).find((el) => el.textContent === "Capturar");
  assert.equal(button.textContent, "Capturar");
  assert.equal(button.disabled, false);
  await button.handlers.click();
  const submitted = calls.filter((call) => call.url === "/api/video/snapshot");
  assert.equal(submitted.length, 1);
  assert.deepEqual(JSON.parse(submitted[0].options.body), { device_id: "owned" });
  const updated = get("cameras").children[0];
  assert.equal(descendants(updated).find((el) => el.tagName === "img").src, image);
  assert.ok(descendants(updated).some((el) => /Captura pontual/.test(el.textContent)));
});

test("unprepared capture stays disabled and explains the local requirement", async () => {
  const { get } = await setup(null, { auth_mode: "windows-experimental", authenticated: true,
    snapshot_ready: false, snapshot_message: "Prepare o adaptador local.", devices: [{ id: "owned", name: "Minha câmera" }] });
  assert.equal(descendants(get("cameras").children[0]).find((el) => el.textContent === "Capturar").disabled, true);
  assert.match(get("snapshot-status").textContent, /Prepare o adaptador/);
});

function liveResponses(failingId = null) {
  return {
    '/api/video/start': (options) => {
      const id = JSON.parse(options.body).device_id;
      return { ok: true, json: async () => ({ device_id: id, stream_id: 'handle-'+id }) };
    },
    '/api/video/frame': (options) => {
      const body = JSON.parse(options.body);
      return body.device_id === failingId ? { ok: false, json: async () => ({ message: 'Formato não suportado nesta câmera.' }) }
        : { ok: true, json: async () => ({ device_id: body.device_id, image: 'data:image/jpeg;base64,'+body.device_id,
          sequence: body.after+1, age_seconds: 0, state: 'receiving' }) };
    },
    '/api/video/stop': { ok: true, json: async () => ({ message: 'Transmissão encerrada.' }) },
  };
}
const liveStatus = { auth_mode: 'windows-experimental', authenticated: true, snapshot_ready: true,
  devices: [{ id: 'a', name: 'Entrada' }, { id: 'b', name: 'Pátio' }] };
function cardButton(get, index, text) { return descendants(get('cameras').children[index]).find((el) => el.tagName === 'button' && el.textContent.includes(text)); }

test('mosaic keeps two independent live connections and can stop one without closing the other', async () => {
  const { get, calls, runTimer, timers } = await setup(null, liveStatus, null, null, liveResponses());
  await cardButton(get, 0, 'Assistir').handlers.click();
  await runTimer();
  await cardButton(get, 1, 'Assistir').handlers.click();
  await runTimer();
  assert.equal(get('live-count').textContent, '2');
  assert.equal(calls.filter((c) => c.url === '/api/video/start').length, 2);
  assert.equal(calls.filter((c) => c.url === '/api/video/stop').length, 0);
  assert.match(descendants(get('cameras').children[0]).find((el) => el.tagName === 'img').src, /base64,a$/);
  assert.match(descendants(get('cameras').children[1]).find((el) => el.tagName === 'img').src, /base64,b$/);
  await cardButton(get, 0, 'Parar').handlers.click();
  assert.equal(get('live-count').textContent, '1');
  const stop = calls.find((c) => c.url === '/api/video/stop');
  assert.deepEqual(JSON.parse(stop.options.body), { device_id: 'a', stream_id: 'handle-a' });
  await get('stop-all').handlers.click();
  assert.equal(get('live-count').textContent, '0');
  assert.equal(timers.size, 0);
});

test('one failing camera leaves other feeds running and shows its own error', async () => {
  const { get, runTimer } = await setup(null, liveStatus, null, null, liveResponses('b'));
  await cardButton(get, 0, 'Assistir').handlers.click(); await runTimer();
  await cardButton(get, 1, 'Assistir').handlers.click(); await runTimer();
  assert.equal(get('live-count').textContent, '1');
  assert.ok(descendants(get('cameras').children[1]).some((el) => /Formato não suportado/.test(el.textContent)));
  assert.equal(cardButton(get, 0, 'Parar').disabled, false);
});

test('watch all starts at most eight cameras and enables focus layout', async () => {
  const devices = Array.from({ length: 9 }, (_, i) => ({ id: String(i), name: 'Câmera '+i }));
  const { get, calls, timers } = await setup(null, { ...liveStatus, devices }, null, null, liveResponses());
  await get('watch-all').handlers.click();
  assert.equal(calls.filter((c) => c.url === '/api/video/start').length, 8);
  assert.ok(calls.filter((c) => c.url === '/api/video/start').every((c) => JSON.parse(c.options.body).mosaic === true));
  assert.equal(get('dashboard').className, 'focus-mode');
  assert.equal(timers.size, 8);
  await get('stop-all').handlers.click();
  assert.equal(timers.size, 0);
});

test('search filters the camera cards without reconnecting streams', async () => {
  const { get, calls, runTimer } = await setup(null, liveStatus, null, null, liveResponses());
  await cardButton(get, 0, 'Assistir').handlers.click(); await runTimer();
  get('camera-search').value = 'ENTRADA';
  get('camera-search').handlers.input();
  assert.equal(get('cameras').children.length, 1);
  assert.equal(calls.filter((c) => c.url === '/api/video/start').length, 1);
  assert.equal(get('live-count').textContent, '1');
});

test('an old image loses the live indicator even if the next network response is delayed', async () => {
  const { get, runTimer, advance } = await setup(null, liveStatus, null, null, liveResponses());
  await cardButton(get, 0, 'Assistir').handlers.click(); await runTimer();
  assert.equal(get('live-count').textContent, '1');
  advance(4000);
  assert.equal(get('live-count').textContent, '0');
  assert.ok(descendants(get('cameras').children[0]).some((el) => /Sem novos quadros há 4/.test(el.textContent)));
  assert.equal(descendants(get('cameras').children[0]).some((el) => /AO VIVO/.test(el.textContent)), false);
});


test('queued camera is shown as waiting for its startup slot without a failure badge', async () => {
  const responses=liveResponses();
  responses['/api/video/frame']={ok:true,json:async()=>({device_id:'a',sequence:0,image:null,age_seconds:null,state:'queued'})};
  const {get,runTimer}=await setup(null,liveStatus,null,null,responses);
  await cardButton(get,0,'Assistir').handlers.click();await runTimer();
  assert.ok(descendants(get('cameras').children[0]).some((el)=>el.textContent==='NA FILA'));
  assert.ok(descendants(get('cameras').children[0]).some((el)=>/Na fila de conexão/.test(el.textContent)));
  assert.equal(get('live-count').textContent,'0');
  assert.equal(cardButton(get,0,'Parar').disabled,false);
});

test("successful login lists cameras and opens mosaic without a second click", async () => {
  let authenticated = false, listed = false;
  const response = (data) => ({ ok: true, json: async () => data });
  const { get, calls } = await setup(null, {}, null, null, {
    "/api/status": () => response({ csrf: "test-csrf", configured: true, authenticated,
      snapshot_ready: true, devices: listed ? [{id: "a", name: "Camera A"}] : [] }),
    "/api/login": () => { authenticated = true; return response({message: "Conectado"}); },
    "/api/devices": () => { listed = true; return response({devices: [{id: "a", name: "Camera A"}]}); },
    "/api/video/start": response({stream_id: "auto-handle"})
  });
  await get("login").handlers.submit({preventDefault() {}, currentTarget: get("login")});
  assert.equal(calls.filter(c => c.url === "/api/login").length, 1);
  assert.equal(calls.filter(c => c.url === "/api/devices").length, 1);
  assert.equal(calls.filter(c => c.url === "/api/video/start").length, 1);
});

test("quality selection restarts only that camera with requested definition", async () => {
  const response = data => ({ok:true,json:async()=>data});
  const {get,calls} = await setup(null, {authenticated:true,snapshot_ready:true,
    devices:[{id:"a",name:"Camera A"},{id:"b",name:"Camera B"}]}, null, null, {
    "/api/video/start": response({stream_id:"handle"}), "/api/video/stop": response({})
  });
  await get("watch-all").handlers.click();
  const select = descendants(get("cameras")).find(e => e.tagName === "select");
  select.value = "fhd";
  await select.handlers.change();
  const starts = calls.filter(c=>c.url==="/api/video/start").map(c=>JSON.parse(c.options.body));
  assert.equal(starts.length,3);
  assert.equal(starts[2].device_id,"a");
  assert.equal(starts[2].quality,"fhd");
  assert.equal(calls.filter(c=>c.url==="/api/video/stop").length,1);
});


test("temporary stream failure retries without login and Stop cancels pending retry", async () => {
  const responses = liveResponses();
  responses['/api/video/frame'] = {ok:false,status:422,json:async()=>({error:'video_timeout',message:'Sem conexão'})};
  const {get,calls,runTimer,timers} = await setup(null, liveStatus, null, null, responses);
  await cardButton(get,0,'Assistir').handlers.click();
  await runTimer();
  assert.ok([...timers.values()].some(timer=>timer.ms===2000));
  await runTimer();
  assert.equal(calls.filter(call=>call.url==='/api/video/start').length,2);
  assert.equal(calls.filter(call=>call.url==='/api/login').length,0);
  await runTimer();
  assert.equal(cardButton(get,0,'Parar').disabled,false);
  await cardButton(get,0,'Parar').handlers.click();
  assert.equal(timers.size,0);
});


test("data saver closes native stream after five minutes and reopens at thirty preserving last frame", async () => {
  const {get,calls,runTimer,runDelay,timers} = await setup(null,liveStatus,null,null,liveResponses());
  await cardButton(get,0,'Economia de dados').handlers.click();
  await runTimer();
  assert.equal(get('live-count').textContent,'1');
  await runDelay(5*60*1000);
  assert.equal(calls.filter(c=>c.url==='/api/video/stop').length,1);
  assert.equal(get('live-count').textContent,'0');
  const image=descendants(get('cameras').children[0]).find(el=>el.tagName==='img');
  assert.equal(image.hidden,false);
  assert.ok(descendants(get('cameras').children[0]).some(el=>/ECONOMIA · PAUSADA/.test(el.textContent)));
  await get('watch-all').handlers.click();
  assert.equal(calls.filter(c=>c.url==='/api/video/start' && JSON.parse(c.options.body).device_id==='a').length,1);
  await runDelay(30*60*1000);
  assert.equal(calls.filter(c=>c.url==='/api/video/start' && JSON.parse(c.options.body).device_id==='a').length,2);
  await get('stop-all').handlers.click();
  assert.equal(timers.size,0);
});

test("8-second native frame failure reconnects but economy pause cancels retries", async () => {
  const responses=liveResponses();
  responses['/api/video/frame']={ok:false,status:422,json:async()=>({error:'video_native',message:'A câmera parou de entregar quadros por 15 segundos.'})};
  const {get,calls,runTimer,runDelay,timers}=await setup(null,liveStatus,null,null,responses);
  await cardButton(get,0,'Economia de dados').handlers.click();
  await runTimer();
  await runDelay(2000);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,2);
  await runTimer();
  await runDelay(5*60*1000);
  assert.ok(![...timers.values()].some(t=>t.ms===5000||t.ms===10000));
  await get('stop-all').handlers.click();
  assert.equal(timers.size,0);
});


test("saved 12-camera layout and economy preferences restore on a new browser visit", async () => {
  const devices=Array.from({length:13},(_,i)=>({id:String(i),name:'Camera '+i}));
  const {get,calls,timers}=await setup(null,{...liveStatus,devices,preferences_key:'account-test',
    preferences:{mosaic_limit:12,economy_ids:['0']}},null,null,liveResponses());
  assert.equal(get('mosaic-limit').value,'12');
  assert.equal(get('cameras').children.length,12);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,12);
  assert.ok([...timers.values()].some(t=>t.ms===300000));
  assert.ok([...timers.values()].some(t=>t.ms===1800000));
  await get('stop-all').handlers.click();
  assert.equal(timers.size,0);
});

test("economy choices and mosaic size are saved for the account", async () => {
  const {get,calls}=await setup(null,liveStatus,null,null,liveResponses());
  await cardButton(get,0,'Economia de dados').handlers.click();
  let saved=calls.filter(c=>c.url==='/api/preferences').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(saved.at(-1),{economy_ids:['a'],detection_ids:[],mosaic_limit:8,webcam_enabled_ids:[]});
  get('mosaic-limit').value='12';
  await get('mosaic-limit').handlers.change();
  saved=calls.filter(c=>c.url==='/api/preferences').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(saved.at(-1),{economy_ids:['a'],detection_ids:[],mosaic_limit:12,webcam_enabled_ids:[]});
});


test("person detection is opt-in, saved per camera, and restored", async () => {
  const {get,calls}=await setup(null,{...liveStatus,preferences_key:'owner',
    preferences:{economy_ids:[],detection_ids:['b'],mosaic_limit:8}},null,null,liveResponses());
  await cardButton(get,0,'Detectar pessoas').handlers.click();
  let saved=calls.filter(c=>c.url==='/api/preferences').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(saved.at(-1).detection_ids,['b','a']);
  await cardButton(get,1,'Detectar pessoas').handlers.click();
  saved=calls.filter(c=>c.url==='/api/preferences').map(c=>JSON.parse(c.options.body));
  assert.deepEqual(saved.at(-1).detection_ids,['a']);
});


test("HTML gateway failures show a connection message and retry without raw HTML", async () => {
  const responses=liveResponses();
  responses['/api/video/frame']={ok:false,status:502,json:async()=>{throw new SyntaxError('Unexpected token < <!DOCTYPE html> private-details');}};
  const {get,calls,runTimer,runDelay}=await setup(null,liveStatus,null,null,responses);
  await cardButton(get,0,'Assistir').handlers.click();await runTimer();
  const texts=descendants(get('cameras').children[0]).map(el=>el.textContent).join(' ');
  assert.match(texts,/HTTP 502/);assert.match(texts,/Nova tentativa/);
  assert.doesNotMatch(texts,/DOCTYPE|private-details|Unexpected token/);
  await runDelay(2000);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,2);
});


test("server-managed detection economy uses no browser schedule and displays paused last frame", async () => {
  const responses=liveResponses();
  responses['/api/video/frame']=options=>({ok:true,json:async()=>({device_id:JSON.parse(options.body).device_id,
    sequence:1,image:'data:image/jpeg;base64,paused',state:'paused',age_seconds:1,next_open_seconds:1500})});
  const {get,timers,runTimer,calls}=await setup(null,{...liveStatus,server_monitoring:true,
    preferences_key:'bg-owner',background_status:{configured:1,paused:1},
    preferences:{detection_ids:['a'],economy_ids:['a'],mosaic_limit:8}},null,null,responses);
  assert.ok(![...timers.values()].some(t=>t.ms===300000||t.ms===1800000));
  await runTimer();
  assert.ok(descendants(get('cameras').children[0]).some(el=>/ECONOMIA · PAUSADA/.test(el.textContent)));
  assert.equal(get('live-count').textContent,'0');
  await get('stop-all').handlers.click();
  assert.match(get('message').textContent,/continuam monitorando no servidor/);
  assert.equal(calls.filter(c=>c.url==='/api/logout').length,0);
});


test("server economy button does not claim a configuration that was not acknowledged", async () => {
  const responses=liveResponses();
  responses['/api/preferences']={ok:false,status:503,json:async()=>({message:'Sem comunicação'})};
  const {get}=await setup(null,{...liveStatus,server_monitoring:true,preferences_key:'owner',
    preferences:{detection_ids:['a'],economy_ids:[],mosaic_limit:8}},null,null,responses);
  await cardButton(get,0,'Economia de dados').handlers.click();
  assert.equal(cardButton(get,0,'Economia de dados').className,'data-saver');
  assert.match(get('message').textContent,/confirmar as preferências/);
});

test('expanding a camera preserves its source without reconnecting the mosaic',async()=>{
  const {get,calls}=await setup(null,{authenticated:true,snapshot_ready:true,devices:[{id:'a',name:'Entrada'}]},null,null,{
    '/api/video/start':{ok:true,json:async()=>({device_id:'a',stream_id:'handle'})},
    '/api/video/stop':{ok:true,json:async()=>({})}
  });
  await descendants(get('cameras')).find(e=>e.className==='camera-expand').handlers.click();
  let starts=calls.filter(c=>c.url==='/api/video/start');
  assert.equal(JSON.parse(starts.at(-1).options.body).quality,'balanced');
  assert.ok(descendants(get('cameras')).some(e=>e.className?.includes('camera-expanded')));
  await descendants(get('cameras')).find(e=>e.className==='camera-expand').handlers.click();
  starts=calls.filter(c=>c.url==='/api/video/start');
  assert.equal(JSON.parse(starts.at(-1).options.body).quality,'balanced');
  assert.equal(starts.length,1);
  assert.equal(calls.filter(c=>c.url==='/api/video/stop').length,0);
});

test('camera health shows measured FPS and person analysis without claiming the target rate',async()=>{
  const {get,runTimer}=await setup(null,{authenticated:true,snapshot_ready:true,devices:[{id:'a',name:'Entrada'}]},null,null,{
    '/api/video/start':{ok:true,json:async()=>({device_id:'a',stream_id:'handle'})},
    '/api/video/frame':{ok:true,json:async()=>({device_id:'a',sequence:1,image:'data:image/jpeg;base64,AA==',age_seconds:.1,state:'receiving',health:{fps:7.8,resolution:[1280,720],detection:{age_seconds:.5,people:1}}})}
  });
  await descendants(get('cameras')).find(e=>e.className==='play').handlers.click();
  await runTimer();
  const caption=descendants(get('cameras')).find(e=>e.className==='camera-caption').textContent;
  assert.match(caption,/7.8 fps/);assert.match(caption,/1280 × 720/);assert.match(caption,/1 pessoa/);
});

test('continuous MJPEG keeps its image element on layout changes and requests metadata only', async()=>{
  const {get,calls,runTimer}=await setup(null,{...liveStatus,mjpeg_available:true},null,null,liveResponses());
  await cardButton(get,0,'Assistir').handlers.click();await runTimer();
  const image=descendants(get('cameras').children[0]).find(el=>el.tagName==='img');
  assert.match(image.src,/^\/api\/video\/mjpeg\?/);
  const request=calls.find(c=>c.url==='/api/video/frame');
  assert.equal(JSON.parse(request.options.body).metadata_only,true);
  get('camera-search').value='Entrada';get('camera-search').handlers.input();
  assert.equal(descendants(get('cameras').children[0]).find(el=>el.tagName==='img'),image);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,1);
});

test('server webcam starts disabled and explicit activation persists its enable flag',async()=>{
  const status={...liveStatus,webcam_available:true,server_monitoring:true,devices:[{id:'webcam:video0',name:'Webcam',local:true}]};
  const {get,calls}=await setup(null,status,null,null,liveResponses());
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,0);
  assert.equal(cardButton(get,0,'Detectar pessoas').disabled,true);
  await cardButton(get,0,'Ativar webcam').handlers.click();
  const save=calls.find(c=>c.url==='/api/preferences');
  assert.deepEqual(JSON.parse(save.options.body).webcam_enabled_ids,['webcam:video0']);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,1);
  await cardButton(get,0,'Desativar webcam').handlers.click();
  const saves=calls.filter(c=>c.url==='/api/preferences');
  assert.deepEqual(JSON.parse(saves.at(-1).options.body).webcam_enabled_ids,[]);
});

test('camera wall fits eight and twelve sources into the available viewport',async()=>{
  for(const count of [8,12]){
    const devices=Array.from({length:count},(_,i)=>({id:String(i),name:'Camera '+i}));
    const preferences={mosaic_limit:count,economy_ids:[],detection_ids:[],webcam_enabled_ids:[]};
    const {get}=await setup(null,{...liveStatus,devices,preferences_key:'owner',preferences},null,null,liveResponses());
    await new Promise(setImmediate);
    assert.equal(get('dashboard').className,'focus-mode');
    assert.equal(get('cameras').styles['--tv-cols'],count===8?'3':'4');
    assert.equal(get('cameras').styles['--tv-rows'],'3');
  }
});
test('economy cache stays visible through a transport error and a reconnect',async()=>{
  let fail=false;
  const responses=liveResponses();
  responses['/api/video/frame']=options=>{
    const body=JSON.parse(options.body);
    return fail?{ok:false,status:503,json:async()=>({message:'Sem conexão'})}:{ok:true,json:async()=>({device_id:body.device_id,sequence:5,age_seconds:90,state:'paused',image:body.metadata_only?null:'data:image/jpeg;base64,last-frame',next_open_seconds:1200})};
  };
  const {get,runTimer,runDelay,calls}=await setup(null,{...liveStatus,mjpeg_available:true},null,null,responses);
  await cardButton(get,0,'Assistir').handlers.click();await runTimer();
  assert.equal(descendants(get('cameras').children[0]).find(e=>e.tagName==='img').src,'data:image/jpeg;base64,last-frame');
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,1);
  fail=true;await runDelay(1500);await runDelay(2000);
  const still=descendants(get('cameras').children[0]).find(e=>e.className==='camera-still');
  assert.equal(still.src,'data:image/jpeg;base64,last-frame');assert.equal(still.hidden,false);
  assert.notEqual(get('live-count').textContent,'1');
});


test('touch menu exit leaves the wall without stopping or reconnecting cameras',async()=>{
  const {get,calls}=await setup(null,liveStatus,null,null,liveResponses());
  await get('watch-all').handlers.click();
  assert.equal(get('fullscreen-actions').hidden,false);
  const starts=calls.filter(c=>c.url==='/api/video/start').length;
  const stops=calls.filter(c=>c.url==='/api/video/stop').length;
  await get('tv-exit').handlers.click();
  assert.equal(get('dashboard').className,'');
  assert.equal(get('fullscreen-actions').hidden,true);
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,starts);
  assert.equal(calls.filter(c=>c.url==='/api/video/stop').length,stops);
});

test('touch menu exit also leaves an expanded camera without fullscreen API support',async()=>{
  const {get,calls}=await setup(null,liveStatus,null,null,liveResponses());
  await cardButton(get,0,'Assistir').handlers.click();
  const starts=calls.filter(c=>c.url==='/api/video/start').length;
  const expand=descendants(get('cameras').children[0]).find(e=>e.className==='camera-expand');
  await expand.handlers.click();
  assert.equal(get('fullscreen-actions').hidden,false);
  await get('tv-exit').handlers.click();
  assert.equal(get('fullscreen-actions').hidden,true);
  assert.ok(!descendants(get('cameras')).some(e=>e.className?.includes('camera-expanded')));
  assert.equal(calls.filter(c=>c.url==='/api/video/start').length,starts);
});
