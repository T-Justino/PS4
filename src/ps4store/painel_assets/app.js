"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const seguro = (u) => typeof u === "string" && u.startsWith("https://");
let jogoAtual = null;

async function api(caminho, params) {
  const u = new URL(caminho, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") u.searchParams.set(k, v); });
  const r = await fetch(u.toString(), { headers: { Accept: "application/json" } });
  let j = {};
  try { j = await r.json(); } catch (e) { /* corpo vazio */ }
  if (!r.ok) throw new Error(j.erro || ("erro " + r.status));
  return j;
}

function filtros() {
  return { cusa: $("f-cusa").value.trim().toUpperCase(), regiao: $("f-regiao").value, idioma: $("f-idioma").value.trim() };
}

function link(url, texto) {
  if (!seguro(url)) return el("span", "desc", texto || "(sem link)");
  const a = el("a", null, texto || url);
  a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
  return a;
}

function mostrarLista(dados) {
  const ul = $("lista");
  ul.replaceChildren();
  $("msg-lista").textContent = dados.total + " jogo(s)" + (dados.mostrando < dados.total ? " (mostrando " + dados.mostrando + ")" : "") + (dados.aviso ? " · " + dados.aviso : "");
  dados.itens.forEach((it) => {
    const li = el("li", "card" + (it.qid ? " clicavel" : ""));
    li.appendChild(el("div", "nome", it.nome + (it.ano ? " (" + it.ano + ")" : "")));
    li.appendChild(el("div", "meta", "Fonte: " + (it.fonteNome || it.fonte || "desconhecida") + (it.qid ? " · " + it.qid : " · sem Q-id")));
    if (!it.qid) li.appendChild(el("span", "badge", "sem Q-id: não dá para vincular versões"));
    else if (!it.nRegistros) li.appendChild(el("span", "badge", "sem versões cadastradas"));
    else {
      li.appendChild(el("span", "badge ok", it.nRegistros + " registro(s) · " + it.nCusas + " CUSA(s)"));
      if (it.nWikidata) li.appendChild(el("span", "badge wd", it.nWikidata + " alegado(s) no Wikidata"));
    }
    if (it.qid) { li.tabIndex = 0; li.addEventListener("click", () => abrirJogo(it.qid)); li.addEventListener("keydown", (e) => { if (e.key === "Enter") abrirJogo(it.qid); }); }
    ul.appendChild(li);
  });
}

async function buscar(soVersoes) {
  const q = $("q").value.trim();
  $("msg-lista").textContent = "buscando…";
  try {
    const d = await api("/api/jogos", { q: q, com_versoes: soVersoes ? "1" : "" });
    mostrarLista(d);
    if (!d.itens.length) $("msg-lista").textContent = q ? "Nenhum jogo encontrado para \"" + q + "\"." : "Nenhum jogo com versões cadastradas.";
  } catch (e) {
    $("lista").replaceChildren();
    $("msg-lista").textContent = "";
    const p = el("p", "erro", e.message); $("lista").appendChild(p);
  }
}

function campo(dl, rotulo, valor, desconhecido) {
  dl.appendChild(el("dt", null, rotulo));
  const dd = el("dd", desconhecido ? "desc" : null, desconhecido ? "desconhecido" : valor);
  dl.appendChild(dd);
  return dd;
}

function cartaoVersao(r, todasFontes) {
  const c = el("div", "card");
  c.appendChild(el("div", "nome", r.cusa));
  c.appendChild(el("div", "meta", "CUSA: identificador do título"));
  const wd = r.origem === "wikidata";
  const conf = r.status === "confirmado";
  const cf = r.confirmacao || {};
  if (wd) c.appendChild(el("span", "badge wd", "WIKIDATA: alegado, NÃO verificado em fonte oficial"));
  else c.appendChild(el("span", "badge " + (conf ? "ok" : "aviso"), conf ? "CONFIRMADO por " + (cf.por || "?") + " em " + (cf.em || "?") : "CITADO: fonte vista, página não conferida"));
  const dl = el("dl");
  const cids = (r.contentIds && r.contentIds.length) ? r.contentIds : (r.contentId ? [r.contentId] : []);
  const cid = campo(dl, cids.length > 1 ? "Content IDs" : "Content ID", cids.join(", "), !cids.length);
  if (cids.length) cid.appendChild(el("div", "meta", "identifica este produto/edição; NÃO é o CUSA" + (wd ? " (valor informado no Wikidata)" : "")));
  const ed = campo(dl, "Edição", r.edicao, !r.edicao);
  if (r.edicao) ed.appendChild(el("div", "meta", "registro de edição/produto da loja, não de jogo-base"));
  const rg = campo(dl, "Região", r.regiao ? r.regiao.codigo : "", !r.regiao);
  if (r.regiao) rg.appendChild(el("div", "meta", "base: " + r.regiao.base));
  const id = campo(dl, "Idiomas", (r.idiomas || []).join(", "), !(r.idiomas && r.idiomas.length));
  if (r.idiomas && r.idiomas.length) id.appendChild(el("div", "meta", "base: " + (r.idiomasBase || "?")));
  else id.textContent = "desconhecidos (a região não define o idioma)", id.className = "desc";
  campo(dl, "Versão do pacote", r.versao, !r.versao);
  if (r.lojas && r.lojas.length) campo(dl, "Lojas onde aparece", r.lojas.join(", "), false);
  const fontes = todasFontes ? r.evidencias : r.evidencias.slice(0, 1);
  fontes.forEach((x) => { const dd = campo(dl, "Fonte", "", false); dd.appendChild(link(x.url, x.fonte)); if (x.trecho) dd.appendChild(el("div", "meta", x.trecho)); });
  if (r.corroboradoPorWikidata && r.corroboradoPorWikidata.length) {
    const dd = campo(dl, "Também no Wikidata", "", false);
    r.corroboradoPorWikidata.forEach((x) => { const d = el("div", "meta"); d.appendChild(link(x.url, x.fonte)); d.appendChild(document.createTextNode(" · " + (x.trecho || ""))); dd.appendChild(d); });
  }
  if (todasFontes && r.nota) campo(dl, "Nota", r.nota, false);
  c.appendChild(dl);
  return c;
}

let todasFontes = false;
function mostrarJogo(d) {
  const box = $("jogo");
  box.replaceChildren();
  const j = d.jogo;
  box.appendChild(el("h2", null, j.nome + (j.ano ? " (" + j.ano + ")" : "")));
  const meta = el("div", "meta"); meta.appendChild(document.createTextNode("Wikidata " + j.qid + " · "));
  if (j.url) meta.appendChild(link(j.url, "página de referência"));
  box.appendChild(meta);
  d.avisos.forEach((a) => box.appendChild(el("div", "aviso-box", a)));
  if (d.conflitos && d.conflitos.length) {
    const det = el("details", "conflitos");
    det.appendChild(el("summary", null, d.conflitos.length + " CUSA(s) em conflito (não associados a este jogo)"));
    const ul = el("ul");
    d.conflitos.slice(0, 8).forEach((c) => {
      const outros = c.outrosJogos.length ? " · também atribuído a: " + c.outrosJogos.join("; ") + (c.maisOutros ? " (+" + c.maisOutros + ")" : "") : "";
      ul.appendChild(el("li", null, c.cusa + " · " + c.motivo + outros + " · " + c.rotulo));
    });
    if (d.conflitos.length > 8) ul.appendChild(el("li", "desc", "… e mais " + (d.conflitos.length - 8)));
    det.appendChild(ul);
    box.appendChild(det);
  }
  if (!d.total) {
    box.appendChild(el("div", "card", "Nenhuma versão CUSA cadastrada para " + j.qid + ". Isso NÃO quer dizer que o jogo não tenha CUSA: só que ainda não há registro com fonte. Nada foi inventado."));
    return;
  }
  const f = d.filtros, ativos = Object.keys(f).filter((k) => f[k]).map((k) => k + "=" + f[k]);
  const org = d.origens || {};
  box.appendChild(el("p", "msg", d.total + " registro(s) (" + (org.curado || 0) + " curado(s), " + (org.wikidata || 0) + " alegado(s) no Wikidata), " + d.cusasDistintos + " CUSA(s) distinto(s) · filtros: " + (ativos.length ? ativos.join(", ") : "nenhum (todos os registros)")));
  if (!d.temJogoBase) box.appendChild(el("div", "aviso-box", "Nenhum registro está marcado como jogo-base: o que aparece são produtos/edições da loja."));
  const bt = el("button", "secundario", todasFontes ? "Mostrar só a primeira fonte" : "Mostrar todas as fontes e notas");
  bt.type = "button"; bt.addEventListener("click", () => { todasFontes = !todasFontes; abrirJogo(j.qid, true); });
  box.appendChild(bt);
  if (!d.registros.length) box.appendChild(el("div", "card", "Nenhum registro passa nos filtros" + (d.omitidos ? " (" + d.omitidos + " sem o campo conhecido ficaram de fora: o valor desconhecido não é presumido)" : "") + ". Limpe os filtros para ver todos."));
  d.registros.forEach((r) => box.appendChild(cartaoVersao(r, todasFontes)));
  if (d.omitidos && d.registros.length) box.appendChild(el("p", "msg", d.omitidos + " registro(s) sem o campo filtrado ficaram de fora: o valor desconhecido não é presumido."));
}

async function abrirJogo(qid, manter) {
  jogoAtual = qid;
  $("vista-lista").hidden = true; $("vista-jogo").hidden = false;
  if (!manter) $("jogo").replaceChildren(el("p", "msg", "carregando…"));
  if (window.location.hash !== "#" + qid) window.location.hash = qid;
  try { mostrarJogo(await api("/api/jogo", Object.assign({ qid: qid }, filtros()))); }
  catch (e) { $("jogo").replaceChildren(el("p", "erro", e.message)); }
  window.scrollTo(0, 0);
}

function voltar() {
  jogoAtual = null;
  $("vista-jogo").hidden = true; $("vista-lista").hidden = false;
  if (window.location.hash) history.replaceState(null, "", window.location.pathname);
}

const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
async function estado() {
  const ul = $("estado");
  try {
    const e = await api("/api/estado");
    ul.replaceChildren();
    [["Jogos pesquisáveis", e.jogosPesquisaveis, ""], ["Jogos com CUSA", e.jogosComCusa, ""], ["CUSAs distintos", e.cusasDistintos, ""],
     ["Registros manuais", e.registrosManuais, ""], ["Conflitos pendentes", e.conflitosPendentes, e.conflitosPendentes ? "pend" : ""]].forEach((c) => {
      const li = el("li", c[2]); li.appendChild(el("b", null, fmt(c[1]))); li.appendChild(document.createTextNode(c[0])); ul.appendChild(li);
    });
    if (!e.jogosPesquisaveis) $("msg-lista").textContent = "Índice de busca vazio: só aparecem jogos com versões cadastradas (gere o índice com ps4store.wikidata --atualizar).";
  } catch (err) { ul.replaceChildren(el("li", "carregando", "sem resposta do servidor")); }
}

$("form-busca").addEventListener("submit", (ev) => { ev.preventDefault(); voltar(); buscar(false); });
$("so-versoes").addEventListener("click", () => { voltar(); buscar(true); });
$("voltar").addEventListener("click", voltar);
["f-cusa", "f-regiao", "f-idioma"].forEach((id) => $(id).addEventListener("change", () => { if (jogoAtual) abrirJogo(jogoAtual, true); }));
window.addEventListener("hashchange", () => { const h = window.location.hash.slice(1); if (/^Q[0-9]+$/.test(h) && h !== jogoAtual) abrirJogo(h); else if (!h && jogoAtual) voltar(); });
estado();
if (/^#Q[0-9]+$/.test(window.location.hash)) abrirJogo(window.location.hash.slice(1));
