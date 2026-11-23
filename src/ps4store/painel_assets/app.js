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

const TIPO_CAPA = { capa: "capa", ilustrativa: "imagem ilustrativa" };
function inicial(nome) { const m = (nome || "?").match(/[A-Za-z0-9À-ÿ]/); return m ? m[0].toUpperCase() : "?"; }
function imagem(capa, nome, cls) {
  const box = el("div", "capa " + (cls || ""));
  const ph = el("div", "placeholder", inicial(nome));
  ph.setAttribute("aria-hidden", "true");
  box.appendChild(ph);
  if (capa && /^\/capa\/Q[0-9]+$/.test(capa.url || "")) {
    const img = document.createElement("img");
    img.loading = "lazy"; img.decoding = "async"; img.alt = (TIPO_CAPA[capa.tipo] || "imagem") + " de " + nome; img.src = capa.url;
    img.addEventListener("error", () => img.remove());
    box.appendChild(img);
    box.appendChild(el("span", "selo", TIPO_CAPA[capa.tipo] || "imagem"));
  } else box.appendChild(el("span", "selo vazio", "sem imagem"));
  return box;
}

let ultimaBusca = null, carregados = 0;
function cartaoJogo(it) {
  const li = el("li", "card jogo" + (it.qid ? " clicavel" : ""));
  li.appendChild(imagem(it.capa, it.nome));
  const info = el("div", "info");
  info.appendChild(el("div", "nome", it.nome + (it.ano ? " (" + it.ano + ")" : "")));
  info.appendChild(el("div", "meta", "Fonte: " + (it.fonteNome || it.fonte || "desconhecida") + (it.qid ? " · " + it.qid : " · sem Q-id")));
  if (!it.qid) info.appendChild(el("span", "badge", "sem Q-id: não dá para vincular versões"));
  else if (!it.nRegistros) info.appendChild(el("span", "badge", "sem versões cadastradas"));
  else {
    info.appendChild(el("span", "badge ok", it.nRegistros + " registro(s) · " + it.nCusas + " CUSA(s)"));
    if (it.nWikidata) info.appendChild(el("span", "badge wd", it.nWikidata + " alegado(s) no Wikidata"));
  }
  if (it.ptbr && it.ptbr.includes("oficial")) info.appendChild(el("span", "badge ptbr", "PT-BR" + (it.ptbr.includes("audio") ? " · áudio" : "")));
  else if (it.ptbr && it.ptbr.includes("wikidata")) info.appendChild(el("span", "badge", "PT-BR? (Wikidata)"));
  li.appendChild(info);
  if (it.qid) { li.tabIndex = 0; li.addEventListener("click", () => abrirJogo(it.qid)); li.addEventListener("keydown", (e) => { if (e.key === "Enter") abrirJogo(it.qid); }); }
  return li;
}

function mostrarLista(dados, anexar) {
  const ul = $("lista");
  if (!anexar) ul.replaceChildren();
  carregados = dados.offset + dados.itens.length;
  $("msg-lista").textContent = dados.total + " jogo(s)" + (carregados < dados.total ? " (mostrando " + carregados + ")" : "") + (dados.viaApelido ? " · apelido conhecido, vínculo explícito" : "") + (dados.aviso ? " · " + dados.aviso : "");
  dados.itens.forEach((it) => ul.appendChild(cartaoJogo(it)));
  $("mais").hidden = !dados.temMais;
}

function mostrarSugestoes(lista) {
  const box = $("sugestoes");
  box.replaceChildren();
  box.hidden = !lista.length;
  if (!lista.length) return;
  box.appendChild(el("span", "meta", "Nenhum resultado exato. Você quis dizer:"));
  lista.forEach((s) => {
    const b = el("button", "sugestao", s.nome); b.type = "button";
    b.addEventListener("click", () => { $("q").value = s.nome; buscar(false); });
    box.appendChild(b);
  });
}

async function buscar(soVersoes, anexar) {
  const q = $("q").value.trim();
  if (!anexar) { ultimaBusca = { q: q, sv: soVersoes, pb: $("f-ptbr").value }; carregados = 0; $("msg-lista").textContent = "buscando…"; $("mais").hidden = true; }
  const alvo = ultimaBusca;
  try {
    const d = await api("/api/jogos", { q: alvo.q, com_versoes: alvo.sv ? "1" : "", ptbr: alvo.pb, limite: 48, offset: anexar ? carregados : "" });
    mostrarLista(d, anexar);
    if (!anexar) {
      mostrarSugestoes(d.sugestoes || []);
      if (!d.itens.length) $("msg-lista").textContent = alvo.q ? "Nenhum jogo encontrado para \"" + alvo.q + "\"" + (alvo.pb ? " com o filtro PT-BR." : ".") : (alvo.pb ? "Nenhum jogo com PT-BR informado nas fontes consultadas (jogos sem dado continuam na busca geral)." : "Nenhum jogo com versões cadastradas.");
    }
  } catch (e) {
    $("lista").replaceChildren(); $("mais").hidden = true; $("sugestoes").hidden = true;
    $("msg-lista").textContent = "";
    $("lista").appendChild(el("p", "erro", e.message));
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
  campo(dl, "Versão do pacote (registro)", r.versao, !r.versao);
  (r.oficial || []).forEach((o) => {
    const txt = Object.entries(o.idiomas).map(([p, l]) => ({ audio: "áudio", texto: "texto", legendas: "legendas", geral: "idiomas" }[p] || p) + ": " + l.join(", ")).join(" · ");
    const dd = campo(dl, "Idiomas oficiais deste CUSA", txt + (o.listaCompleta ? "" : " (lista parcial)"), false);
    dd.appendChild(el("div", "meta", o.escopo + " · " + o.fonte + " · " + o.obtidoEm + " · " + o.verificacao));
  });
  const a = r.atualizacao;
  if (!a) campo(dl, "Atualização (patch)", "", true).textContent = "não consultada (rode ps4store.metadados)";
  else if (a.status === "ok") {
    const dd = campo(dl, "Atualização mais recente (patch)", a.versao + (a.tamanhoBytes ? " · " + (a.tamanhoBytes / 1e9).toFixed(2) + " GB" : ""), false);
    dd.appendChild(el("div", "meta", "versão do patch ≠ versão do jogo-base ≠ versão do PKG · " + a.fonte + " · " + (a.consultadoEm || "").slice(0, 10) + (a.grau !== "oficial" ? " · " + a.grau : "")));
    if (a.contentId) dd.appendChild(el("div", "meta", "o XML da Sony descreve o produto " + a.contentId + (r.contentId && r.contentId !== a.contentId ? " (diferente do Content ID deste registro: o patch pode não ser desta edição/região)" : "")));
    const fw = campo(dl, "Firmware exigido pelo patch", a.firmwareMinimo || "", !a.firmwareMinimo);
    if (a.firmwareMinimo) fw.appendChild(el("div", a.firmwareAcimaDe900 ? "aviso-box" : "meta", a.firmwareAcimaDe900 ? "ACIMA de 9.00: este patch não instala no 9.00 (requisito declarado pela Sony)" : "requisito declarado ≤ 9.00; isso NÃO garante compatibilidade"));
    if (a.historico && a.historico.length) campo(dl, "Versões vistas antes (local)", a.historico.map((h) => h.versao).join(", "), false);
  } else campo(dl, "Atualização (patch)", a.status === "sem-atualizacao" ? "nenhuma listada pela Sony (" + (a.consultadoEm || "").slice(0, 10) + ")" : "desconhecida (" + (a.erro || a.status) + ")", a.status !== "sem-atualizacao");
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

const PARTE = { audio: "Áudio", texto: "Texto/interface", legendas: "Legendas", tela: "Texto ou legendas (tela)" };
const STATUS_PT = { confirmado: "confirmado (fonte oficial)", informado: "só no Wikidata (geral, não verificado)", "nao-consta": "não consta na lista oficial", desconhecido: "desconhecido" };
function blocoPtbr(loc) {
  const c = el("section", "card ptbr-box");
  c.appendChild(el("div", "nome", "Português do Brasil"));
  c.appendChild(el("div", "meta", loc.resumo));
  const dl = el("dl");
  ["audio", "texto", "legendas", "tela"].forEach((p) => {
    const s = loc.partes[p];
    const dd = campo(dl, PARTE[p], STATUS_PT[s.status], s.status === "desconhecido");
    if (s.status === "confirmado") dd.className = "ok-txt";
    else if (s.status === "informado") dd.className = "aviso-txt";
    s.fontes.slice(0, 3).forEach((f) => dd.appendChild(el("div", "meta", f.fonte + " · " + f.rotuloGrau + (f.consultadoEm ? " · " + f.consultadoEm.slice(0, 10) : ""))));
  });
  if (loc.semParte.length) campo(dl, "PT-BR sem parte", "informado sem dizer se é áudio, texto ou legenda", false).appendChild(el("div", "meta", loc.semParte.map((f) => f.fonte).join("; ")));
  if (loc.ptSemVariante.length) campo(dl, "Português (sem variante)", "não classificado como PT-BR", false);
  if (loc.ptPT.length) campo(dl, "Português europeu", "informado (pt-PT ≠ pt-BR)", false);
  c.appendChild(dl);
  c.appendChild(el("p", "meta", "A região do jogo não define o idioma. Sem fonte, fica desconhecido."));
  return c;
}

function secaoBusca(qid, caixaAnalise) {
  const c = el("section", "card link-box");
  c.appendChild(el("div", "nome", "Links nas fontes cadastradas"));
  c.appendChild(el("div", "meta", "Consulta só as fontes de config/fontes-links.json (homebrew e distribuição autorizada), pelo CUSA, Content ID e nome exato. Nada é baixado."));
  const bt = el("button", "primario", "Buscar links"); bt.type = "button"; bt.id = "buscar-links";
  const out = el("div", "link-resultado"); out.id = "links-encontrados";
  c.appendChild(bt); c.appendChild(out);
  bt.addEventListener("click", async () => {
    bt.disabled = true; out.replaceChildren(el("p", "msg", "consultando as fontes…"));
    try {
      const u = new URL("/api/links", window.location.origin); u.searchParams.set("qid", qid);
      const r = await fetch(u.toString(), { headers: { Accept: "application/json", "X-PS4Store": "1" } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.erro || ("erro " + r.status));
      out.replaceChildren(el("p", "msg", d.texto));
      d.resultados.forEach((x) => {
        const k = el("div", "card");
        k.appendChild(el("div", "nome", x.arquivo));
        k.appendChild(el("span", "badge " + (x.autorizado ? "ok" : "aviso"), x.autorizado ? "distribuição autorizada" : "link externo não verificado"));
        k.appendChild(el("span", "badge", x.formato));
        const dl = el("dl");
        campo(dl, "Origem", x.origem, false);
        campo(dl, "Tipo", x.tipo, false);
        campo(dl, "Versão", x.versao || "", !x.versao);
        if (x.tamanho) campo(dl, "Tamanho", (x.tamanho / 1e6).toFixed(1) + " MB", false);
        campo(dl, "Correspondência", x.correspondencia.texto, false);
        campo(dl, "Verificação", x.verificacao, false);
        campo(dl, "Autorização", x.autorizacao, false);
        k.appendChild(dl);
        const an = el("button", "secundario", "Analisar e preparar para SSPI"); an.type = "button";
        an.addEventListener("click", () => { const i = $("link-url"); if (i) i.value = x.url; const cx = caixaAnalise(); cx.scrollIntoView({ block: "start" }); analisarLink(x.url, qid, cx, an); });
        k.appendChild(an);
        out.appendChild(k);
      });
      d.fontes.forEach((f) => out.appendChild(el("div", "meta", "fonte " + f.fonte + ": " + f.achados + " de " + f.itens + " · " + f.origem)));
    } catch (e) { out.replaceChildren(el("p", "erro", e.message)); }
    bt.disabled = false;
  });
  return c;
}

function secaoLink(qid) {
  const c = el("section", "card link-box");
  c.appendChild(el("div", "nome", "Analisar link e preparar para o SSPI"));
  c.appendChild(el("div", "meta", "Página ou link direto (PKG/RAR). Hosts permitidos: config/resolver-hosts.json. Nada é baixado: só os primeiros bytes."));
  const lin = el("div", "linha");
  const inp = el("input"); inp.type = "url"; inp.id = "link-url"; inp.maxLength = 2048; inp.placeholder = "https://…"; inp.autocapitalize = "off"; inp.spellcheck = false;
  const bt = el("button", "primario", "Analisar"); bt.type = "button"; bt.id = "link-analisar";
  lin.appendChild(inp); lin.appendChild(bt); c.appendChild(lin);
  const out = el("div", "link-resultado"); out.id = "link-resultado"; c.appendChild(out);
  bt.addEventListener("click", () => analisarLink(inp.value.trim(), qid, out, bt));
  return c;
}

async function analisarLink(url, qid, out, bt) {
  if (!url) return;
  bt.disabled = true; out.replaceChildren(el("p", "msg", "analisando… (pode levar alguns segundos)"));
  try {
    const u = new URL("/api/link", window.location.origin); u.searchParams.set("url", url); if (qid) u.searchParams.set("qid", qid);
    const r = await fetch(u.toString(), { headers: { Accept: "application/json", "X-PS4Store": "1" } });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ("erro " + r.status));
    out.replaceChildren(el("p", "msg", d.texto));
    (d.arquivos || []).forEach((a) => {
      const k = el("div", "card");
      k.appendChild(el("div", "nome", a.arquivo || a.url));
      const id = a.identificacao || {};
      const dl = el("dl");
      campo(dl, "Tipo", id.tipo || a.formato || "desconhecido", !(id.tipo || a.formato));
      campo(dl, "CUSA", id.cusa || "", !id.cusa);
      campo(dl, "Content ID", id.contentId || "", !id.contentId);
      campo(dl, "Versão", [id.versaoApp ? "app " + id.versaoApp : "", id.versaoPkg ? "pkg " + id.versaoPkg : "", id.versao ? id.versao + " (nome)" : ""].filter(Boolean).join(" · "), !(id.versaoApp || id.versaoPkg || id.versao));
      if (a.tamanhoBytes) campo(dl, "Tamanho", (a.tamanhoBytes / 1e6).toFixed(1) + " MB", false);
      campo(dl, "Base", id.base || "", !id.base);
      k.appendChild(dl);
      const cmp = a.comparacao || {};
      k.appendChild(el("div", cmp.resultado === "corresponde" ? "badge ok" : (cmp.resultado === "diferente" || cmp.resultado === "conflito" ? "aviso-box" : "meta"), cmp.texto || ""));
      out.appendChild(k);
    });
    (d.naoArquivos || []).forEach((n) => out.appendChild(el("div", "meta", n.status + ": " + (n.motivo || ""))));
    const s = d.sspi;
    if (s) {
      s.blocos.forEach((b) => {
        const k = el("div", "card");
        k.appendChild(el("div", "nome", (b.pronto ? "PRONTO para o SSPI · " : "NÃO pronto · ") + b.titulo));
        b.bloqueio.forEach((x) => k.appendChild(el("div", "aviso-box", x)));
        b.avisos.forEach((x) => k.appendChild(el("div", "meta", x)));
        if (b.pronto) {
          const pre = el("pre", "urls", b.urls.join("\n")); k.appendChild(pre);
          const cp = el("button", "secundario", "Copiar para colar no SSPI"); cp.type = "button";
          cp.addEventListener("click", async () => { try { await navigator.clipboard.writeText(b.urls.join("\n")); cp.textContent = "Copiado"; } catch (e) { cp.textContent = "Copie manualmente o texto acima"; } });
          k.appendChild(cp);
        }
        out.appendChild(k);
      });
      (s.naoEnviar || []).forEach((n) => out.appendChild(el("div", "meta", "não enviar: " + n.url + " · " + n.motivo)));
    }
  } catch (e) { out.replaceChildren(el("p", "erro", e.message)); }
  bt.disabled = false;
}

let todasFontes = false;
function mostrarJogo(d) {
  const box = $("jogo");
  box.replaceChildren();
  const j = d.jogo;
  const hero = el("div", "hero");
  hero.appendChild(imagem(d.capa, j.nome, "grande"));
  const ht = el("div", "info");
  ht.appendChild(el("h2", null, j.nome + (j.ano ? " (" + j.ano + ")" : "")));
  const meta = el("div", "meta"); meta.appendChild(document.createTextNode("Wikidata " + j.qid + " · "));
  if (j.url) meta.appendChild(link(j.url, "página de referência"));
  ht.appendChild(meta);
  if (d.capa) {
    const at = el("details", "atribuicao");
    at.appendChild(el("summary", null, (TIPO_CAPA[d.capa.tipo] || "imagem") + " · origem e licença"));
    at.appendChild(el("p", "meta", d.capa.atribuicao || ""));
    if (d.capa.tipo !== "capa") at.appendChild(el("p", "meta", "Imagem ilustrativa: NÃO é a capa oficial do produto."));
    const p = el("p", "meta"); p.appendChild(link(d.capa.paginaUrl, "página do arquivo no Commons")); at.appendChild(p);
    ht.appendChild(at);
  } else ht.appendChild(el("p", "meta", "Sem imagem local (placeholder). Nenhuma imagem foi inventada."));
  hero.appendChild(ht);
  box.appendChild(hero);
  if (d.localizacao) box.appendChild(blocoPtbr(d.localizacao));
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
    box.appendChild(secaoBusca(j.qid, () => $("link-resultado")));
    box.appendChild(secaoLink(j.qid));
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
  box.appendChild(secaoBusca(j.qid, () => $("link-resultado")));
  box.appendChild(secaoLink(j.qid));
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
$("f-ptbr").addEventListener("change", () => { voltar(); buscar(false); });
$("voltar").addEventListener("click", voltar);
$("mais").addEventListener("click", () => buscar(false, true));
["f-cusa", "f-regiao", "f-idioma"].forEach((id) => $(id).addEventListener("change", () => { if (jogoAtual) abrirJogo(jogoAtual, true); }));
window.addEventListener("hashchange", () => { const h = window.location.hash.slice(1); if (/^Q[0-9]+$/.test(h) && h !== jogoAtual) abrirJogo(h); else if (!h && jogoAtual) voltar(); });
estado();
if (/^#Q[0-9]+$/.test(window.location.hash)) abrirJogo(window.location.hash.slice(1));
