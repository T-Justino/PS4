package app.linkresolver.core

/**
 * "Navegador" simulado (multi-guias): páginas = PageScan (estáticas ou sequências no tempo), verificações =
 * ProbeReport. Processa as ações do motor numa fila (como o loop de eventos do Android) e simula as ações do
 * usuário (toque real que abre guias, resolução de desafios).
 */
internal class Sim(val limits: Limits = Limits()) : ResolverEngine.Listener {
    val pages = HashMap<String, PageScan>()
    /** Varreduras sucessivas por URL (a página muda com o tempo: temporizador, botão dinâmico...). */
    val seq = HashMap<String, List<PageScan>>()
    private val seqIdx = HashMap<String, Int>()
    val probes = HashMap<String, ProbeReport>()
    var probeFn: ((String, Set<String>) -> ProbeReport?)? = null
    var holdProbes = false
    val navigated = mutableListOf<String>()
    val asked = mutableListOf<String>()
    val probed = mutableListOf<String>()
    val clicked = mutableListOf<String>()
    val highlighted = mutableListOf<String>()
    val closed = mutableListOf<Int>()
    val workTabs = mutableListOf<Int>()
    var scans = 0
    val scansWhenClicked = mutableListOf<Int>()
    var lastCandidates: List<ScoredCandidate> = emptyList()
    var result: ResolveResult? = null
    var answerDomain: Boolean? = null           // null = deixa pendente
    var now = 0L                                  // relógio simulado: avança com os atrasos pedidos
    val queue = ArrayDeque<() -> Unit>()
    val alias = HashMap<String, String>()       // URL pedida -> URL final após redirecionamentos do servidor
    val current = HashMap<Int, String>()        // URL atual de cada guia
    /** Efeito de um clique PROGRAMÁTICO (por texto do botão). */
    val onClick = HashMap<String, () -> Unit>()
    lateinit var e: ResolverEngine

    private fun scanOf(url: String): PageScan? {
        seq[url]?.let { list ->
            val i = seqIdx.getOrDefault(url, 0)
            seqIdx[url] = minOf(i + 1, list.size - 1)
            return list[i]
        }
        return pages[url]
    }

    private fun scanTab(tabId: Int) { current[tabId]?.let { u -> scanOf(u)?.let { scans++; e.onScan(it, tabId) } } }

    override fun navigate(tabId: Int, url: String) {
        navigated += url
        val shown = alias[url] ?: url
        current[tabId] = shown
        queue += {
            if (shown != url) e.onNavigationRequest(shown, true, false, tabId)
            e.onPageStarted(shown, tabId); e.onPageFinished(shown, tabId)   // onPageFinished pede a varredura (como no app)
        }
    }
    override fun askDomain(host: String, url: String, reason: String) {
        asked += host
        answerDomain?.let { a -> queue += { e.answerDomain(a, true) } }
    }
    override fun onStateChanged(state: EngineState, message: String) {}
    override fun onStep(step: Step) {}
    override fun onCandidates(candidates: List<ScoredCandidate>) { lastCandidates = candidates }
    override fun onResult(result: ResolveResult) { this.result = result }
    val rescanDelays = mutableListOf<Long>()
    private val pendingRescan = HashSet<Int>()
    override fun requestRescan(tabId: Int, delayMs: Long) {
        rescanDelays += delayMs; now += delayMs
        if (pendingRescan.add(tabId)) queue += { pendingRescan.remove(tabId); scanTab(tabId) }   // a UI junta pedidos repetidos (debounce)
    }
    override fun onNavigationDenied(tabId: Int, url: String) { if (tabId != 0) closeTab(tabId) }
    override fun requestProbe(url: String, trustedDomains: Set<String>) {
        probed += url
        if (holdProbes) return
        queue += {
            val rep = probeFn?.invoke(url, trustedDomains) ?: probes[url] ?: ProbeReport(ProbeResult.Page(url, 200, "text/html"), emptyList())
            e.onProbeResult(url, rep.result, rep.diagnostics, rep.hops)
        }
    }
    override fun requestClick(tabId: Int, elementId: String, text: String) {
        clicked += text; scansWhenClicked += scans
        onClick[text]?.let { queue += it }
    }
    override fun requestHighlight(tabId: Int, elementId: String, text: String) { highlighted += text }
    override fun closeTab(tabId: Int) { closed += tabId; queue += { e.onTabClosed(tabId) } }
    override fun onWorkTabChanged(tabId: Int) { workTabs += tabId }

    fun start(url: String) { e = ResolverEngine(limits, { now }, this); e.start(url) }
    fun step(n: Int) { repeat(n) { queue.removeFirstOrNull()?.invoke() } }
    fun pump() { var guard = 0; while (queue.isNotEmpty() && guard++ < 800) queue.removeFirst()() }
    fun run(url: String): ResolveResult {
        start(url); pump()
        return result ?: error("motor não terminou; estado=${e.state}")
    }
    /** Passa o tempo (dispara os temporizadores do motor) e processa as consequências. */
    fun advance(ms: Long) { now += ms; e.tick(); pump() }
    /** Varredura periódica (como o ticker do app durante esperas humanas). */
    fun scanNow(tabId: Int = e.workTab) { queue += { scanTab(tabId) }; pump() }

    fun page(url: String, vararg c: RawCandidate, wait: Boolean = false) {
        pages[url] = PageScan(url, "p ${url.substringAfterLast('/')}", c.toList(), null, null, wait)
    }
    fun file(url: String, mime: String = "application/octet-stream", len: Long = 104_857_600) {
        probes[url] = ProbeReport(ProbeResult.File(url, 200, mime, len, null, "HEAD", true), listOf("[chrome-h2 HEAD] HTTP 200 (h2) em 80ms"))
    }

    /** A própria página navega a guia (efeito de um clique/JS), sem gesto humano. */
    fun pageNavigates(tabId: Int, url: String) {
        if (e.onNavigationRequest(url, false, false, tabId) == NavDecision.ALLOW) {
            current[tabId] = url
            queue += { e.onPageStarted(url, tabId); e.onPageFinished(url, tabId) }
        }
    }

    /** O USUÁRIO toca num elemento (gesto real) que abre uma ou mais guias. */
    fun userOpensTabs(openerTab: Int, vararg tabs: Pair<Int, String>) {
        val openerUrl = current[openerTab]
        for ((tabId, url) in tabs) {
            if (!e.onPopupRequest(openerTab, openerUrl, true)) continue
            e.onTabOpened(tabId, openerTab, openerUrl)
            when (e.onNavigationRequest(url, false, true, tabId)) {
                NavDecision.ALLOW -> {
                    current[tabId] = url
                    queue += { e.onPageStarted(url, tabId); e.onPageFinished(url, tabId) }
                }
                else -> Unit
            }
        }
        pump()
    }
}
