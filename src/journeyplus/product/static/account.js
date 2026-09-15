let identity=null;
const channel=new BroadcastChannel('journeyplus-account');
channel.onmessage=()=>{sessionStorage.clear();location.reload();};
async function check(){const r=await fetch('/auth/me',{cache:'no-store'});if(!r.ok){sessionStorage.clear();location.replace('/login');return;}const me=await r.json();if(identity&&identity!==me.id){sessionStorage.clear();location.reload();return;}identity=me.id;const label=document.querySelector('#account-name');if(label)label.textContent=me.username;}
const header=document.querySelector('header');if(header){const box=document.createElement('span');box.id='account-name';const button=document.createElement('button');button.textContent='退出';button.onclick=async()=>{await fetch('/auth/logout',{method:'POST'});sessionStorage.clear();channel.postMessage('logout');location.replace('/login');};header.append(box,button);}
window.addEventListener('focus',check);document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});check();

window.addEventListener('journeyplus-workspace-created',()=>channel.postMessage('workspace'));
