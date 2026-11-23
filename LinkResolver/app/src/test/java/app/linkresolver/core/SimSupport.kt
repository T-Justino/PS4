package app.linkresolver.core

/**
 * "Navegador" simulado: páginas = PageScan, verificações = ProbeReport. Processa as ações do motor numa
 * fila (como o loop de eventos do Android).
 */
internal class Sim(val limits: Limits = Limits()) : ResolverEngine.Listener {
    val pages = HashMap<String, PageScan>()
    val probes = HashMap<String, ProbeReport>()
    val navigated = mutableListOf<String>()
    val asked = mutableListOf<String>()
    val probed = mutableListOf<String>()
    var result: ResolveResult? = null
    var answerDomain: Boolean? = null           // null = deixa pendente
    val queue = ArrayDeque<() -> Unit>()
    var probeFn: ((String, Set<String>) -> ProbeReport?)? = null
    val alias = HashMap<String, String>()       // URL pedida -> URL final após redirecionamentos do servidor
    private var current: String? = null
    lateinit var e: ResolverEngine

    override fun navigate(url: String) {
        navigated += url
        val shown = alias[url] ?: url
        current = shown
        queue += {
            if (shown != url) e.onNavigationRequest(shown, true)
            e.onPageStarted(shown); e.onPageFinished(shown)
        }
        queue += { pages[shown]?.let { e.onScan(it) } }
    }
    override fun askDomain(host: String, url: String, reason: String) {
        asked += host
        answerDomain?.let { a -> queue += { e.answerDomain(a, true) } }
    }
    override fun onStateChanged(state: EngineState, message: String) {}
    override fun onStep(step: Step) {}
    override fun onCandidates(candidates: List<ScoredCandidate>) {}
    override fun onResult(result: ResolveResult) { this.result = result }
    override fun requestRescan(delayMs: Long) { queue += { current?.let { c -> pages[c]?.let { e.onScan(it) } } } }
    override fun onNavigationDenied(url: String) {}
    override fun requestProbe(url: String, trustedDomains: Set<String>) {
        probed += url
        queue += {
            val rep = probeFn?.invoke(url, trustedDomains) ?: probes[url] ?: ProbeReport(ProbeResult.Page(url, 200, "text/html"), emptyList())
            e.onProbeResult(url, rep.result, rep.diagnostics, rep.hops)
        }
    }
    fun run(start: String): ResolveResult {
        e = ResolverEngine(limits, { 0L }, this)
        e.start(start)
        var guard = 0
        while (queue.isNotEmpty() && guard++ < 500) queue.removeFirst()()
        return result ?: error("motor não terminou; estado=${e.state}")
    }
    fun page(url: String, vararg c: RawCandidate, wait: Boolean = false) {
        pages[url] = PageScan(url, "p ${url.substringAfterLast('/')}", c.toList(), null, null, wait)
    }
    fun file(url: String, mime: String = "application/octet-stream", len: Long = 104_857_600) {
        probes[url] = ProbeReport(ProbeResult.File(url, 200, mime, len, null, "HEAD", true), listOf("[chrome-h2 HEAD] HTTP 200 (h2) em 80ms"))
    }
}

