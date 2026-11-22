import {chromium} from 'playwright';
import {spawn,spawnSync} from 'node:child_process';
import {readFile,mkdir,writeFile,readdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'artifacts');await mkdir(output,{recursive:true});
const python=path.join(root,'.venv','bin','python');
const setup=spawnSync(python,['scripts/browser_fixture.py'],{cwd:root,encoding:'utf8'});
if(setup.status!==0)throw new Error(setup.stderr);
const fixture=JSON.parse(await readFile(path.join(root,'.local/browser-fixture.json'),'utf8'));
async function freePort(){return new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});}
const children=[];
async function start(surface){
 const port=await freePort();
 const child=spawn(python,['-m','gunicorn','wormhole.wsgi:application','--bind',`127.0.0.1:${port}`,'--workers','1','--threads','2','--timeout','60'],{cwd:root,env:{...process.env,...fixture.env,WORMHOLE_SURFACE:surface,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});children.push(child);
 let log='';child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
 const url=`http://127.0.0.1:${port}`;
 for(let attempt=0;attempt<100;attempt++){
  if(child.exitCode!==null)throw new Error(log);
  try{const r=await fetch(url+'/health');const h=await r.json();if(r.ok&&h.surface===surface)return url;}catch{}
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 throw new Error('Fixture server did not become healthy: '+log);
}
let browser;
const checks=[];
try{
 const portal=await start('portal'),admin=await start('admin');
 const options={headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']};
 if(process.env.WORMHOLE_BROWSER_EXECUTABLE)options.executablePath=process.env.WORMHOLE_BROWSER_EXECUTABLE;
 browser=await chromium.launch(options);
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function login(url,user,password){await page.goto(url+'/login/');await page.locator('[name=username]').fill(user);await page.locator('[name=password]').fill(password);await Promise.all([page.waitForURL(url+'/**'),page.getByRole('button',{name:'Sign in'}).click()]);}
 await login(admin,fixture.username,fixture.password);await page.waitForURL(admin+'/admin/');
 await page.getByText('New bucket',{exact:true}).click();await page.locator('#bucket-form [name=name]').fill('Audio');await page.locator('#bucket-form [name=folder]').fill('audio');await page.locator('#bucket-form button').click();await page.waitForFunction(()=>document.getElementById('buckets').textContent.includes('Audio'));
 await page.getByText('New account',{exact:true}).click();await page.locator('#account-form [name=username]').fill('archivist');await page.locator('#account-form [name=password]').fill('synthetic-collector-password-538!');await page.locator('#account-form button').click();await page.waitForFunction(()=>document.getElementById('accounts').textContent.includes('archivist'));
 await page.locator('#grant-user').selectOption({label:'2 · archivist'});await page.locator('#grant-bucket').selectOption({label:'1 · Audio'});await page.locator('#grant-form button').click();await page.waitForFunction(()=>document.getElementById('grants').textContent.includes('archivist'));
 checks.push('Administrator creates real account, bucket and upload grant through browser');
 await page.screenshot({path:path.join(output,'admin-desktop.png'),fullPage:true});
 assert.equal((await context.request.get(portal+'/admin/')).status(),404);checks.push('Portal listener has no administration route');
 // Cookies are host scoped rather than port scoped; distinct surface cookie names preserve each login.
 await login(portal,'archivist','synthetic-collector-password-538!');await page.waitForURL(portal+'/');await page.waitForFunction(()=>window.wormhole?.ready&&document.getElementById('bucket').options.length===1);
 assert.equal(await page.evaluate(()=>window.wormhole.renderer),'threejs-webgl');
 await page.screenshot({path:path.join(output,'portal-desktop.png')});
 const bytes=Buffer.alloc(1200000);for(let i=0;i<bytes.length;i++)bytes[i]=i%251;
 await page.locator('#file').setInputFiles({name:'synthetic-recording.bin',mimeType:'application/octet-stream',buffer:bytes});await page.locator('#toss').click();
 await page.waitForFunction(()=>document.getElementById('mode').textContent==='ARCHIVED',{timeout:20000});
 const files=await readdir(path.join(fixture.root,'archive/audio'));assert.equal(files.length,1);
 assert.deepEqual(await readFile(path.join(fixture.root,'archive/audio',files[0])),bytes);assert.match(await page.locator('#status').textContent(),new RegExp(createHash('sha256').update(bytes).digest('hex')));
 checks.push('Browser uploads multiple chunks; exact stored bytes and displayed checksum agree');
 await page.screenshot({path:path.join(output,'portal-receipt.png')});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'portal-mobile.png')});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#file').setInputFiles({name:'reduced.txt',mimeType:'text/plain',buffer:Buffer.from('reduced-motion fixture')});await page.locator('#toss').click();await page.waitForFunction(()=>document.getElementById('mode').textContent==='ARCHIVED');checks.push('Mobile layout and reduced-motion real upload');
 await page.goto(admin+'/admin/');await page.locator('#accounts .bucket-row').filter({hasText:'archivist'}).getByRole('button',{name:'Disable',exact:true}).click();await page.waitForFunction(()=>document.getElementById('accounts').textContent.includes('Disabled'));
 await page.goto(portal+'/');await page.waitForURL(portal+'/login/**');checks.push('Disabling account invalidates subsequent portal access');
 assert.deepEqual(errors,[]);checks.push('No uncaught browser errors');
 await writeFile(path.join(output,'browser-verification.json'),JSON.stringify({checks,errors,synthetic:true},null,2));
 console.log(JSON.stringify({passed:checks.length,checks},null,2));
}finally{
 if(browser)await browser.close();
 for(const child of children){if(child.exitCode===null)child.kill('SIGTERM');}
 for(const child of children){if(child.exitCode===null)await Promise.race([new Promise(resolve=>child.once('exit',resolve)),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Fixture process failed to exit')),10000))]);}
 await rm(fixture.root,{recursive:true,force:true});
}
