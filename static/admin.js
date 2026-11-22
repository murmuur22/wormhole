'use strict';
const $=id=>document.getElementById(id);
const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]').value;
async function api(path,data){
 const response=await fetch('/admin/api/'+path,{method:data?'POST':'GET',credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:data?JSON.stringify(data):undefined});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed');return result;
}
function row(parent,values,action){
 const node=document.createElement('div');node.className='bucket-row';
 for(const value of values){const span=document.createElement('span');span.textContent=value;node.append(span);}
 if(action){const button=document.createElement('button');button.className='text-button';button.textContent=action.label;button.onclick=()=>run(action.perform);node.append(button);}
 $(parent).append(node);
}
function options(id,items,empty){$(id).replaceChildren();if(empty){const o=document.createElement('option');o.value='';o.textContent=empty;$(id).append(o);}for(const item of items){const o=document.createElement('option');o.value=item.id;o.textContent=`${item.id} · ${item.name}`;$(id).append(o);}}
async function refresh(){
 const s=await api('state');
 for(const id of ['accounts','buckets','grants','tokens','uploads'])$(id).replaceChildren();
 const account=id=>s.accounts.find(u=>u.id===id)?.name||String(id);
 const bucket=id=>s.buckets.find(b=>b.id===id)?.name||String(id);
 s.accounts.forEach(u=>row('accounts',[u.name,u.admin?'Administrator':u.active?'Active':'Disabled'],u.admin?null:{label:u.active?'Disable':'Enable',perform:()=>api('accounts/status',{user_id:u.id,active:!u.active})}));
 s.buckets.forEach(b=>row('buckets',[`${b.id} · ${b.name}`,b.folder]));
 s.grants.forEach(g=>row('grants',[account(g.user_id),bucket(g.bucket_id),'Upload only']));
 s.tokens.forEach(t=>row('tokens',[t.label,account(t.user_id),t.active?'Active':'Revoked'],t.active?{label:'Revoke',perform:()=>api('tokens/revoke',{id:t.id})}:null));
 s.uploads.forEach(u=>row('uploads',[u.name,account(u.user_id),bucket(u.bucket_id),`${u.offset} / ${u.size} bytes`,u.state]));
 options('parent-select',s.buckets,'No parent');options('grant-bucket',s.buckets);options('grant-user',s.accounts.filter(u=>u.active));options('token-user',s.accounts.filter(u=>u.active));
}
async function run(action){try{$('notice').textContent='Saving…';await action();await refresh();$('notice').textContent='Saved.';}catch(e){$('notice').textContent='Not saved: '+e.message;}}
$('bucket-form').onsubmit=e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));run(async()=>{await api('buckets',{name:d.name,folder:d.folder,parent_id:d.parent_id?Number(d.parent_id):null});e.target.reset();});};
$('account-form').onsubmit=e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));run(async()=>{await api('accounts',d);e.target.reset();});};
$('grant-form').onsubmit=e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));run(()=>api('grants',{user_id:Number(d.user_id),bucket_id:Number(d.bucket_id),allowed:d.allowed==='true'}));};
$('token-form').onsubmit=e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));run(async()=>{const result=await api('tokens',{user_id:Number(d.user_id),label:d.label,bucket_ids:d.scope.split(',').map(x=>Number(x.trim()))});$('token-output').hidden=false;$('token-output').textContent='Copy privately — shown once: '+result.token;e.target.reset();});};
refresh().catch(e=>{$('notice').textContent=e.message;});
