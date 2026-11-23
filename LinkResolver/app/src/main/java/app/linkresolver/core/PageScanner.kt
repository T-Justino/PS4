package app.linkresolver.core

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener

/**
 * Script de varredura executado via evaluateJavascript (somente leitura do DOM; não há
 * addJavascriptInterface) e parser do resultado. Detecta candidatos de download e desafios
 * (CAPTCHA / anti-robô / login) — estes últimos apenas para PAUSAR a automação.
 */
object PageScanner {

    const val SCRIPT = """
(function(){
try{
var out={url:location.href,title:document.title||'',cands:[],challenge:null,hint:null,wait:false,cd:0,ad:false,wo:false,desc:'',h1:''};
try{var md=document.querySelector('meta[name="description"],meta[property="og:description"]');out.desc=((md&&md.content)||'').slice(0,300);var h=document.querySelector('h1');out.h1=((h&&h.innerText)||'').replace(/\s+/g,' ').trim().slice(0,150)}catch(x){}
/* observador de mudanças dinâmicas (idempotente; somente leitura do DOM; não toca em relógios nem scripts do site) */
if(!window.__lrObs){try{
 window.__lrVer=0;
 var stl=document.createElement('style');stl.textContent='[data-lr-hl]{outline:4px solid #ff3d00 !important;outline-offset:3px !important;box-shadow:0 0 0 6px rgba(255,61,0,.25) !important}';
 (document.head||document.documentElement).appendChild(stl);
 var SEL='a[href],button,input[type=button],input[type=submit],[role=button]';
 var relv=function(n){return n.nodeType===1&&((n.matches&&n.matches(SEL))||(n.querySelector&&n.querySelector(SEL)))};
 window.__lrObs=new MutationObserver(function(ms){var bump=false;
  for(var i=0;i<ms.length;i++){var m=ms[i];
   if(m.type==='childList'){for(var j=0;j<m.addedNodes.length;j++){var n=m.addedNodes[j];
     if(relv(n)){bump=true;try{if(n.matches&&n.matches(SEL))n.setAttribute('data-lr-dyn','1');
      var ds=n.querySelectorAll?n.querySelectorAll(SEL):[];for(var k=0;k<ds.length&&k<20;k++)ds[k].setAttribute('data-lr-dyn','1')}catch(x){}}}}
   else if(m.type==='attributes'&&m.target.matches&&m.target.matches(SEL)){bump=true;try{m.target.setAttribute('data-lr-dyn','1')}catch(x){}}}
  if(bump)window.__lrVer++});
 window.__lrObs.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','aria-disabled','hidden','class','style','href']});
}catch(e){window.__lrObs=1;window.__lrVer=0}}
function abs(u){try{return new URL(u,location.href).href}catch(e){return null}}
function vis(e){try{var r=e.getBoundingClientRect();var s=getComputedStyle(e);
 return r.width>2&&r.height>2&&s.visibility!=='hidden'&&s.display!=='none'&&s.opacity!=='0'}catch(x){return false}}
function ctx(e){var s='',n=e,i=0;while(n&&i<4){s+=' '+(n.id||'')+' '+(typeof n.className==='string'?n.className:'');n=n.parentElement;i++}return s.toLowerCase().slice(0,200)}
function isDis(e){try{return !!(e.disabled||e.getAttribute('aria-disabled')==='true'||/(^|\s)disabled(\s|$)/.test(typeof e.className==='string'?e.className:'')||getComputedStyle(e).pointerEvents==='none')}catch(x){return false}}
function txt(e){return ((e.innerText||e.value||e.getAttribute('aria-label')||e.title||'')+'').replace(/\s+/g,' ').trim().slice(0,100)}
var body=(document.body&&document.body.innerText||'').slice(0,5000).toLowerCase();
var title=(document.title||'').toLowerCase();
/* ---- desafios ---- */
var ch=null,hint=null;
var capSel='iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"],iframe[src*="turnstile"],.g-recaptcha,.h-captcha,.cf-turnstile,#cf-challenge-running,#challenge-form,#challenge-stage,div[id^="cf-chl"]';
var caps=document.querySelectorAll(capSel);
for(var i=0;i<caps.length;i++){var c=caps[i];
 if(c.closest&&c.closest('.grecaptcha-badge'))continue;
 var r=c.getBoundingClientRect();
 if(vis(c)&&r.width>=100&&r.height>=40){ch='CAPTCHA';hint=(c.tagName+' '+(c.className||c.id||'')).toString().slice(0,60);break}}
if(!ch){
 var re=/(verify (that )?you are (a )?human|verifique (que )?(voc[eê] )?(é|e) (um )?humano|are you a robot|i'?m not a robot|n[aã]o sou (um )?rob[oô]|checking your browser|verificando (o )?seu navegador|unusual traffic|tr[aá]fego incomum|complete the security check|security check to access|human verification|verifica[cç][aã]o humana)/;
 if(re.test(body)||/^(just a moment|attention required|um momento|verifying)/.test(title)){ch='BOT_CHECK';hint='texto da página'}}
if(!ch){
 var pw=document.querySelectorAll('input[type=password]');var pv=false;
 for(var j=0;j<pw.length;j++){if(vis(pw[j])){pv=true;break}}
 if(pv&&(/(login|log-in|signin|sign-in|auth|sso|oauth|account|entrar|conta)/.test(location.pathname.toLowerCase())||/(sign in|log in|faça login|fa[cç]a o login|entrar na (sua )?conta|iniciar sess)/.test(body))){ch='LOGIN';hint='campo de senha visível'}}
out.challenge=ch;out.hint=hint;
/* ---- candidatos ---- */
var n=0,seen={},seenIdx={};
function add(e,url,source,dl){
 if(out.cands.length>=1500)return;
 var t=txt(e);var key=(url||'')+'|'+t+'|'+source;
 if(seen[key]){/* duplicata (ex.: célula de tela larga oculta + célula de tela pequena visível): fica a versão VISÍVEL */
  var oc0=out.cands[seenIdx[key]];if(oc0&&!oc0.vis&&vis(e)){var id2=String(++n);try{e.setAttribute('data-lr-id',id2)}catch(x){}oc0.id=id2;oc0.vis=true;oc0.dis=isDis(e)}return}
 seen[key]=1;seenIdx[key]=out.cands.length;
 var id=null;
 if(!url||source==='button'||true){id=String(++n);try{e.setAttribute('data-lr-id',id)}catch(x){}}
 out.cands.push({url:url,text:t,tag:e.tagName.toLowerCase(),source:source,dl:!!dl,rel:((e.getAttribute&&e.getAttribute('rel'))||'').toLowerCase(),ctx:ctx(e),id:id,vis:vis(e),dis:isDis(e),dyn:!!(e.hasAttribute&&e.hasAttribute('data-lr-dyn')),blank:!!(e.getAttribute&&e.getAttribute('target')==='_blank')})}
var as=document.querySelectorAll('a[href],area[href]');
for(var k=0;k<as.length;k++){var a=as[k];var h=a.getAttribute('href')||'';
 if(!h||h==='#'||/^javascript:/i.test(h)||/^(mailto|tel):/i.test(h))continue;
 var u=abs(h);if(!u)continue;add(a,u,a.hasAttribute('download')?'download-attr':'href',a.hasAttribute('download'))}
var els=document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button],[data-href],[data-url],[data-link],[data-download],[data-file],[onclick]');
var dattrs=['data-href','data-url','data-link','data-download','data-file','data-target-url','data-src','formaction'];
for(var m=0;m<els.length;m++){var e=els[m];var found=false;
 for(var d=0;d<dattrs.length;d++){var v=e.getAttribute(dattrs[d]);
  if(v&&!/^(javascript:|#)/i.test(v)){var u2=abs(v);if(u2&&/^https?:/i.test(u2)){add(e,u2,'data-attr',false);found=true}}}
 var oc=e.getAttribute('onclick')||'';
 if(oc){var mo=oc.match(/window\.open\(\s*['"]([^'"]+)['"]/);var mm=oc.match(/https?:\/\/[^'"\s)]+/);
  if(mo){var uo=abs(mo[1]);if(uo&&/^https?:/i.test(uo)){add(e,uo,'onclick',false);out.cands[out.cands.length-1].blank=true;found=true}}
  else if(mm){add(e,mm[0],'onclick',false);found=true}
  else{var m2=oc.match(/location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/);if(m2){var u3=abs(m2[1]);if(u3){add(e,u3,'onclick',false);found=true}}}}
 if(!found&&e.tagName!=='A'){var f=e.form;
  if(f&&f.action&&(f.method||'get').toLowerCase()==='get'){var fu=abs(f.action);if(fu){add(e,fu,'form',false);found=true}}}
 if(!found&&e.tagName!=='A'&&/(download|baixar|descargar|continue|continuar|get link|obter|gerar|iniciar|pr[oó]ximo|next|prosseguir|avan[cç]ar|liberar|proceed|free download|get file|mediafire|mega|1\s*file|1fichier|google\s*drive|dropbox|pixeldrain|gofile|krakenfiles|terabox|workupload)/i.test(txt(e)))add(e,null,'button',false)}
var mt=document.querySelector('meta[http-equiv="refresh" i]');
if(mt){var c2=mt.getAttribute('content')||'';var mr=c2.match(/url\s*=\s*['"]?([^'";]+)/i);
 if(mr){var u4=abs(mr[1].trim());if(u4){add(mt,u4,'meta-refresh',false);out.cands[out.cands.length-1].vis=true;out.cands[out.cands.length-1].text='(meta refresh '+(parseInt(c2,10)||0)+'s)'}}}
/* redirecionamentos por JavaScript (somente leitura do texto dos <script> inline) */
var scs=document.querySelectorAll('script:not([src])');var jr=0;
var jsre=[/(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=(?!=)\s*['"]([^'"]+)['"]/g,/location\.(?:replace|assign)\(\s*['"]([^'"]+)['"]\s*\)/g];
for(var q=0;q<scs.length&&q<20&&jr<5;q++){var st=(scs[q].textContent||'').slice(0,20000);
 for(var w=0;w<jsre.length;w++){jsre[w].lastIndex=0;var jm;
  while((jm=jsre[w].exec(st))&&jr<5){
   var before=st.slice(Math.max(0,jm.index-140),jm.index);
   /* redirecionamento dentro de handler de clique/função nomeada NÃO é automático: não adianta a espera do site */
   if(/addEventListener|onclick|\.on[a-z]+\s*=|\.click\s*\(|function\s+[A-Za-z_]\w*\s*\(/.test(before))continue;
   var u5=abs(jm[1]);if(u5&&/^https?:/i.test(u5)&&u5!==location.href){
   var key5=u5+'|js';if(!seen[key5]){seen[key5]=1;out.cands.push({url:u5,text:'(redirecionamento JavaScript)',tag:'script',source:'js-redirect',dl:false,rel:'',ctx:'',id:null,vis:true});jr++}}}}}
var cdn=0,rA=/(aguarde|espere|please wait|wait|restam|faltam|remaining|download (?:starts|begins) in|come[cç]a em|inicia em)[^0-9]{0,30}(\d{1,3})/g,mA;
while((mA=rA.exec(body))){var vA=parseInt(mA[2],10);if(vA>0&&vA<=120&&vA>cdn)cdn=vA}
var rB=/(\d{1,3})\s*(segundos?|seconds?|secs?)\b/g,mB;
while((mB=rB.exec(body))){var vB=parseInt(mB[1],10);if(vB>0&&vB<=120&&vB>cdn)cdn=vB}
var tims=document.querySelectorAll('[id*=count],[class*=count],[id*=timer],[class*=timer],[id*=segundos],[id*=seconds]');
for(var ti=0;ti<tims.length&&ti<10;ti++){var tv=((tims[ti].innerText||'')+'').trim();if(/^\d{1,3}$/.test(tv)){var vT=parseInt(tv,10);if(vT>0&&vT<=120&&vT>cdn)cdn=vT}}
out.cd=cdn;
out.wo=false;var sc2=document.querySelectorAll('script:not([src])');for(var si=0;si<sc2.length&&si<30;si++){if(/window\.open\s*\(/.test((sc2[si].textContent||'').slice(0,30000))){out.wo=true;break}}
out.ad=/(casino|cassino|bet365|apostas?|aposte|b[oô]nus de|ganhe\s+(um\s+)?pr[eê]mio|voc[eê] ganhou|you('ve| have)? won|claim your|click here to claim|vpn gr[aá]tis|free vpn|xxx|viagra)/.test(body);
out.wait=/(aguarde|please wait|redirecionando|redirecting|seu download (come|inici)|your download (will|is)|gerando (seu )?link|generating (your )?link|countdown|contagem regressiva|segundos|seconds)/.test(body);
/* prioridade ANTES do corte: arquivos/Raw/download sobem; nada relevante do fim da página se perde */
var EXTS='|zip|rar|7z|tar|gz|tgz|bz2|xz|zst|iso|img|bin|pkg|exe|msi|dmg|apk|aab|deb|rpm|appimage|jar|pdf|epub|mobi|djvu|doc|docx|xls|xlsx|ppt|pptx|csv|mp3|flac|wav|ogg|mp4|mkv|avi|mov|webm|part01|001|smc|sfc|fig|swc|nes|unf|fds|gba|gb|gbc|sgb|n64|z64|v64|nds|dsi|3ds|cia|sms|gg|gen|smd|32x|pce|sgx|a26|a78|j64|ngp|ngc|ws|wsc|vb|col|rom|chd|cso|pbp|wad|nsp|xci|';
function pri(c,i){var u=c.url||'',p=0,m=u.split('#')[0].split('?')[0],mm=m.match(/\.([A-Za-z0-9]{2,8})$/),ext=mm?mm[1].toLowerCase():'';
 var blob=/^https?:\/\/(www\.)?github\.com\/[^\/]+\/[^\/]+\/blob\//i.test(u);
 var raw=/^https?:\/\/(raw\.githubusercontent\.com\/|(www\.)?github\.com\/[^\/]+\/[^\/]+\/(raw|releases\/download)\/)/i.test(u);
 if(raw)p+=100;if(c.dl)p+=80;if(ext&&EXTS.indexOf('|'+ext+'|')>=0)p+=blob?70:90;
 if(/(download|baixar|descargar|\braw\b)/i.test(c.text))p+=40;if(/download|\/dl\//i.test(u))p+=20;
 if(c.source==='meta-refresh'||c.source==='js-redirect')p+=60;if(c.source!=='href')p+=10;if(c.vis)p+=1;if(c.dis)p-=30;return p*1000-i}
out.total=out.cands.length;
if(out.cands.length>150){for(var qi=0;qi<out.cands.length;qi++)out.cands[qi].__p=pri(out.cands[qi],qi);
 /* candidatos de ARQUIVO (prioridade >= 70) nunca são cortados enquanto couberem em 500; os demais, até 150 por relevância */
 var fl=[],ot=[];for(var qk=0;qk<out.cands.length;qk++){(out.cands[qk].__p>=70000?fl:ot).push(out.cands[qk])}
 ot.sort(function(a,b){return b.__p-a.__p});out.cands=fl.slice(0,500).concat(ot.slice(0,150));
 for(var qj=0;qj<out.cands.length;qj++)delete out.cands[qj].__p}
return JSON.stringify(out)
}catch(err){return JSON.stringify({url:location.href,title:'',cands:[],challenge:null,hint:'erro: '+err})}
})()
"""

    /** Script para clique MANUAL (solicitado pelo usuário) em um elemento marcado na varredura. */
    /** Versão do observador de DOM (muda quando botões/links são criados, habilitados ou alterados); -1 = ainda não instalado. */
    const val VERSION_SCRIPT = "(function(){return window.__lrVer===undefined?-1:window.__lrVer})()"

    /** Destaca o elemento (contorno + rolagem) para o usuário tocar nele: um gesto humano real. */
    fun highlightScript(elementId: String): String {
        val safe = elementId.filter { it.isDigit() }
        return "(function(){var o=document.querySelectorAll('[data-lr-hl]');for(var i=0;i<o.length;i++)o[i].removeAttribute('data-lr-hl');" +
            "var e=document.querySelector('[data-lr-id=\"$safe\"]');if(!e)return false;" +
            "try{e.scrollIntoView({block:'center',behavior:'smooth'})}catch(x){}e.setAttribute('data-lr-hl','1');" +
            "setTimeout(function(){try{e.removeAttribute('data-lr-hl')}catch(x){}},20000);return true})()"
    }

    fun clickScript(elementId: String): String {
        val safe = elementId.filter { it.isDigit() }
        return "(function(){var e=document.querySelector('[data-lr-id=\"$safe\"]');if(e){e.click();return true}return false})()"
    }

    /** [raw] é o valor devolvido por evaluateJavascript (string JSON codificada em JSON). */
    fun parse(raw: String?): PageScan? {
        if (raw == null || raw == "null") return null
        return try {
            val inner = JSONTokener(raw).nextValue() as? String ?: return null
            val o = JSONObject(inner)
            val arr: JSONArray = o.optJSONArray("cands") ?: JSONArray()
            val list = ArrayList<RawCandidate>(arr.length())
            for (i in 0 until arr.length()) {
                val c = arr.getJSONObject(i)
                list += RawCandidate(
                    url = c.optString("url", "").takeIf { it.isNotEmpty() && !c.isNull("url") },
                    text = c.optString("text", ""),
                    tag = c.optString("tag", ""),
                    source = c.optString("source", ""),
                    downloadAttr = c.optBoolean("dl", false),
                    rel = c.optString("rel", ""),
                    context = c.optString("ctx", ""),
                    elementId = c.optString("id", "").takeIf { it.isNotEmpty() && !c.isNull("id") },
                    visible = c.optBoolean("vis", true),
                    disabled = c.optBoolean("dis", false),
                    dynamic = c.optBoolean("dyn", false),
                    opensTab = c.optBoolean("blank", false),
                )
            }
            val kind = o.optString("challenge", "").takeIf { !o.isNull("challenge") && it.isNotEmpty() }
                ?.let { runCatching { ChallengeKind.valueOf(it) }.getOrNull() }
            PageScan(
                url = o.optString("url", ""),
                title = o.optString("title", ""),
                candidates = list,
                challenge = kind,
                challengeHint = o.optString("hint", "").takeIf { !o.isNull("hint") && it.isNotEmpty() },
                waitHint = o.optBoolean("wait", false),
                adLike = o.optBoolean("ad", false),
                countdownSec = o.optInt("cd", 0),
                opensWindows = o.optBoolean("wo", false),
                totalCandidates = o.optInt("total", list.size),
                description = o.optString("desc", ""),
                heading = o.optString("h1", ""),
            )
        } catch (e: Exception) {
            null
        }
    }
}
