const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
async function setup(rejectClipboard=false){
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,{value:'',textContent:'',hidden:true,addEventListener(n,h){this[n]=h},focus(){},select(){this.selected=true}});return els.get(id)};
 const calls=[],copied=[];
 const context={document:{getElementById:get,execCommand:()=>false},window:{},innerWidth:1366,innerHeight:768,Intl,AbortSignal,
 navigator:{userAgent:'Chrome/143',clipboard:{writeText:async text=>{if(rejectClipboard)throw Error('denied');copied.push(text)}}},
 fetch:async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>path==='/api/status'?{authenticated:true,csrf:'private-csrf'}:{format:'DCS-diagnostics-v1',cameras:[{name:'Camera A',state:'paused'}]}}}};
 vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../web/diagnostics.js'),'utf8'),context);
 await get('copy-diagnostics').click();return {get,calls,copied};
}
test('diagnostic button copies only the explicit export, without the CSRF secret',async()=>{
 const {get,calls,copied}=await setup();assert.equal(copied.length,1);
 assert.match(copied[0],/Camera A/);assert.doesNotMatch(copied[0],/private-csrf/);
 assert.deepEqual(calls.map(c=>c.path),['/api/status','/api/diagnostics']);
 assert.equal(get('copy-diagnostics').disabled,false);assert.match(get('diagnostics-message').textContent,/copiados/);
});
test('clipboard denial offers selected text and Ctrl+C fallback',async()=>{
 const {get}=await setup(true);assert.equal(get('diagnostics-output').selected,true);
 assert.match(get('diagnostics-message').textContent,/Ctrl\+C/);assert.equal(get('diagnostics-output').hidden,false);
});
