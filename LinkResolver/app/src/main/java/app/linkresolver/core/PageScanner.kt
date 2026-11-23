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
var out={url:location.href,title:document.title||'',cands:[],challenge:null,hint:null};
function abs(u){try{return new URL(u,location.href).href}catch(e){return null}}
function vis(e){try{var r=e.getBoundingClientRect();var s=getComputedStyle(e);
 return r.width>2&&r.height>2&&s.visibility!=='hidden'&&s.display!=='none'&&s.opacity!=='0'}catch(x){return false}}
function ctx(e){var s='',n=e,i=0;while(n&&i<4){s+=' '+(n.id||'')+' '+(typeof n.className==='string'?n.className:'');n=n.parentElement;i++}return s.toLowerCase().slice(0,200)}
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
var n=0,seen={};
function add(e,url,source,dl){
 if(out.cands.length>=150)return;
 var t=txt(e);var key=(url||'')+'|'+t+'|'+source;if(seen[key])return;seen[key]=1;
 var id=null;
 if(!url||source==='button'||true){id=String(++n);try{e.setAttribute('data-lr-id',id)}catch(x){}}
 out.cands.push({url:url,text:t,tag:e.tagName.toLowerCase(),source:source,dl:!!dl,rel:((e.getAttribute&&e.getAttribute('rel'))||'').toLowerCase(),ctx:ctx(e),id:id,vis:vis(e)})}
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
 if(oc){var mm=oc.match(/https?:\/\/[^'"\s)]+/);if(mm){add(e,mm[0],'onclick',false);found=true}
  else{var m2=oc.match(/location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/);if(m2){var u3=abs(m2[1]);if(u3){add(e,u3,'onclick',false);found=true}}}}
 if(!found&&e.tagName!=='A'){var f=e.form;
  if(f&&f.action&&(f.method||'get').toLowerCase()==='get'){var fu=abs(f.action);if(fu){add(e,fu,'form',false);found=true}}}
 if(!found&&e.tagName!=='A'&&/(download|baixar|descargar|continue|continuar|get link|obter|gerar|iniciar)/i.test(txt(e)))add(e,null,'button',false)}
var mt=document.querySelector('meta[http-equiv="refresh" i]');
if(mt){var c2=mt.getAttribute('content')||'';var mr=c2.match(/url\s*=\s*['"]?([^'";]+)/i);
 if(mr){var u4=abs(mr[1].trim());if(u4)add(mt,u4,'meta-refresh',false)}}
return JSON.stringify(out)
}catch(err){return JSON.stringify({url:location.href,title:'',cands:[],challenge:null,hint:'erro: '+err})}
})()
"""

    /** Script para clique MANUAL (solicitado pelo usuário) em um elemento marcado na varredura. */
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
            )
        } catch (e: Exception) {
            null
        }
    }
}
