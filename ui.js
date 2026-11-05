// ui.js: (1) أيقونة العين لإظهار/إخفاء كلمة السر  (2) دويرة تحميل في أي بوطون يبعث طلب للسيرفر
(()=>{
const css=`.pw{position:relative;display:block}.pw>input{padding-inline-end:46px!important}
.eye{position:absolute;inset-inline-end:8px;top:0;bottom:0;margin:auto 0;width:34px;height:34px;display:flex;align-items:center;justify-content:center;background:none;border:0;padding:0;cursor:pointer;color:var(--mu,#94a3b8);border-radius:8px}
.eye:hover{color:var(--tx,#fff)}.eye svg{width:20px;height:20px;pointer-events:none}
button.busy{position:relative;color:transparent!important;pointer-events:none}
button.busy::after{content:"";position:absolute;left:50%;top:50%;width:18px;height:18px;margin:-9px 0 0 -9px;border:2.5px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:50%;animation:uisp .7s linear infinite}
@keyframes uisp{to{transform:rotate(360deg)}}`;
const st=document.createElement("style");st.textContent=css;document.head.appendChild(st);

// دويرة التحميل: البوطون لي تضغط عليه يتلقى الدويرة حتى يخلص الطلب
let cur=null;
document.addEventListener("click",e=>{
 const b=e.target.closest&&e.target.closest("button");
 if(b&&!b.disabled&&!b.classList.contains("eye")){cur=b;setTimeout(()=>{cur=null},0)}
},true);
const of=window.fetch;
window.fetch=function(...a){
 const b=cur,p=of.apply(this,a);
 if(b){b._n=(b._n||0)+1;b.classList.add("busy");const done=()=>{if(--b._n<=0)b.classList.remove("busy")};p.then(done,done)}
 return p;
};

// العين
const S='fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"';
const EYE=`<svg ${S}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>`;
const OFF=`<svg ${S}><path d="M3 3l18 18M10.6 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4M6.6 6.6A16.6 16.6 0 0 0 2 12s3.5 7 10 7a10 10 0 0 0 4.4-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>`;
function enhance(i){
 if(i.dataset.eye)return;i.dataset.eye=1;
 const w=document.createElement("span");w.className="pw";i.parentNode.insertBefore(w,i);w.appendChild(i);
 const b=document.createElement("button");b.type="button";b.className="eye";b.tabIndex=-1;b.innerHTML=EYE;
 b.onclick=()=>{const hid=i.type==="password";i.type=hid?"text":"password";b.innerHTML=hid?OFF:EYE};
 w.appendChild(b);
}
const run=()=>document.querySelectorAll("input[type=password]").forEach(enhance);
document.readyState==="loading"?document.addEventListener("DOMContentLoaded",run):run();
})();
