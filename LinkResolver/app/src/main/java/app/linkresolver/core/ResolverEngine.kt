package app.linkresolver.core

enum class NavDecision { ALLOW, BLOCK, ASK }

/**
 * Motor de navegação em etapas. Puro Kotlin, single-thread (chamar da thread principal).
 * A UI/WebView alimenta o motor com eventos; o motor decide e pede ações via [Listener].
 */
class ResolverEngine(
    private val limits: Limits = Limits(),
    private val clock: () -> Long = { System.currentTimeMillis() },
    private val listener: Listener,
) {
    interface Listener {
        /** Carregar [url] (já validada) na guia [tabId]. */
        fun navigate(tabId: Int, url: String)
        fun askDomain(host: String, url: String, reason: String)
        fun onStateChanged(state: EngineState, message: String)
        fun onStep(step: Step)
        fun onCandidates(candidates: List<ScoredCandidate>)
        fun onResult(result: ResolveResult)
        /** Pedir nova varredura da guia [tabId] após [delayMs] (a UI deve juntar pedidos repetidos). */
        fun requestRescan(tabId: Int, delayMs: Long)
        /** Navegação pendente recusada pelo usuário (a UI pode fechar a guia de popup). */
        fun onNavigationDenied(tabId: Int, url: String)
        /**
         * Validar metadados de [url] fora da thread principal (HEAD / Range 0-0, sem baixar) e responder
         * com [onProbeResult] na thread principal.
         */
        fun requestProbe(url: String, trustedDomains: Set<String>)
        /** Clique programático em um botão inequívoco (pode não valer como gesto humano). */
        fun requestClick(tabId: Int, elementId: String, text: String) {}
        /** Destacar o elemento para o usuário tocar (gesto humano real). */
        fun requestHighlight(tabId: Int, elementId: String, text: String) {}
        fun closeTab(tabId: Int) {}
        fun onWorkTabChanged(tabId: Int) {}
    }

    private enum class PendingSource { AUTO, NAVIGATION, PROBE }
    private data class Pending(
        val url: String, val host: String, val source: PendingSource, val redirect: Boolean,
        val candidate: ScoredCandidate?, val origin: String? = null, val tabId: Int = 0,
    )
    private class TabInfo(val openerId: Int?, val openerUrl: String?, val pathIndex: Int, var relevant: Boolean? = null, var urlSet: Boolean = false)
    private class ClickAttempt(val c: ScoredCandidate, val at: Long)

    var state = EngineState.IDLE
        private set
    val policy = DomainPolicy()
    val steps = mutableListOf<Step>()

    private var startedAt = 0L
    private var pausedMs = 0L
    private var pauseStart = 0L
    private var stepStartedAt = 0L
    private var depth = 0
    private var redirectsInStep = 0
    private var scanAttempts = 0
    private val visits = HashMap<String, Int>()
    private val rejected = HashSet<String>()
    private val probed = HashSet<String>()
    private val candidateStatus = HashMap<String, String>()
    private val evidence = mutableListOf<String>()
    private val diagnostics = mutableListOf<String>()
    private var pending: Pending? = null
    private var lastScored: List<ScoredCandidate> = emptyList()
    /** Todos os candidatos vistos em todas as páginas (preservados para cópia mesmo em falha). */
    private val allCands = LinkedHashMap<String, ScoredCandidate>()
    private val path = mutableListOf<PathEntry>()
    private val redirectHints = HashMap<String, String>()
    private val probeHopKeys = HashSet<String>()
    private val seenCandidateUrls = HashSet<String>()
    private var stagnant = 0
    private var scannedPages = 0
    private var pageScanCounted = false
    private var lastIntermediate = false
    private var lastWaitHint = false
    private var humanAuthHappened = false
    private var sawHttpAuthError = false
    private var startUrl: String? = null
    private var followedUrl: String? = null
    private var probingUrl: String? = null
    private var probingCandidate: ScoredCandidate? = null
    /** Erro na navegação principal atual: onPageFinished não significa sucesso. */
    private var mainFrameError = false
    private var networkFailure: String? = null
    private var failedUrl: String? = null
    private var lastResult: ResolveResult? = null
    private val probeExtra = mutableSetOf<String>()
    private var finishedAt = 0L

    // --- v0.4.0: guias, dinamismo, temporizadores, cliques ---
    /** Guia em que a análise está trabalhando (0 = principal). */
    var workTab = 0
        private set
    private val tabInfos = HashMap<Int, TabInfo>()
    private val popupsOnPage = HashMap<String, Int>()
    private var popupsTotal = 0
    private var scansOnPage = 0
    private var lastScanAt = 0L
    private var lastScanUrl = ""
    private var lastCountdown = 0
    private var pageWaitStart = 0L
    private var autoClicks = 0
    private val clickedKeys = HashSet<String>()
    private var pendingClick: ClickAttempt? = null
    private var clickTarget: ScoredCandidate? = null
    private var manualResumes = 0
    private var ignoreChallengeOnPage = false
    /** Primeiro resultado da análise (um arquivo confirmado NUNCA é substituído por eventos posteriores). */
    private var primaryResult: ResolveResult? = null
    private val resumeResults = mutableListOf<ResolveResult>()
    /** URLs (chave de loop) já confirmadas como arquivo: voltar a elas não é loop. */
    private val confirmedKeys = HashSet<String>()
    /** Estamos numa retomada EXPLÍCITA (pedida pelo usuário) depois de a análise terminar. */
    private var inResume = false
    /** O botão destacado abre nova guia (window.open): só o gesto humano + a guia nova provam o efeito, não o DOM. */
    private var expectTab = false
    private var lastOpensWindows = false
    private var probingUrlKey: String? = null
    // --- v0.4.3: objetivo contextual ---
    private var goal: GoalContext? = null
    private var userPref: String? = null
    private val mismatches = mutableListOf<String>()
    private val mismatchKeys = HashSet<String>()

    val isActive: Boolean get() = state != EngineState.IDLE && state != EngineState.FINISHED
    val currentDepth: Int get() = depth

    companion object {
        fun isErrorUrl(url: String?): Boolean =
            url != null && (url.startsWith("chrome-error:") || url.startsWith("about:neterror") || url.startsWith("data:text/html,chromewebdata"))
        private const val LATE_DOWNLOAD_WINDOW_MS = 30_000L
        const val MISMATCH_STATUS = "Arquivo válido — conteúdo diferente"
        const val UNVERIFIED = "Link NÃO verificado — copie e teste manualmente."
    }

    // ------------------------------------------------------------------ início/fim

    fun start(rawUrl: String, preference: String? = null) {
        reset()
        userPref = preference?.trim()?.takeIf { it.isNotEmpty() }
        val input = rawUrl.trim()
        when (val v = UrlSafety.check(input)) {
            is UrlSafety.Verdict.Rejected -> {
                state = EngineState.RUNNING // para permitir finish()
                step(StepKind.BLOCKED, input, v.reason)
                finish(ResultState.BLOCKED, null, "URL inicial recusada: ${v.reason}")
                return
            }
            UrlSafety.Verdict.Ok -> Unit
        }
        val host = UrlSafety.host(input)!!
        startUrl = input
        policy.trust(host)
        startedAt = clock(); stepStartedAt = startedAt
        setState(EngineState.RUNNING, "Carregando página inicial")
        step(StepKind.START, input, "domínio confiável inicial: ${DomainPolicy.registrable(host)}")
        registerVisit(input)
        addPath(PathKind.START, input, "URL inicial informada pelo usuário", LinkClass.PAGE)
        listener.navigate(workTab, input)
    }

    fun stop() {
        if (!isActive) return
        finishWithBest("Interrompido pelo usuário")
    }

    private fun reset() {
        state = EngineState.IDLE
        policy.clear(); steps.clear(); visits.clear(); rejected.clear(); probed.clear()
        candidateStatus.clear(); evidence.clear(); diagnostics.clear()
        depth = 0; redirectsInStep = 0; scanAttempts = 0; pausedMs = 0; pauseStart = 0
        pending = null; lastScored = emptyList(); allCands.clear(); path.clear(); redirectHints.clear()
        probeHopKeys.clear(); seenCandidateUrls.clear(); stagnant = 0; scannedPages = 0; pageScanCounted = false
        lastIntermediate = false; lastWaitHint = false
        humanAuthHappened = false; sawHttpAuthError = false
        startUrl = null; followedUrl = null; probingUrl = null; probingCandidate = null
        mainFrameError = false; networkFailure = null; failedUrl = null
        lastResult = null; finishedAt = 0; probeExtra.clear()
        workTab = 0; tabInfos.clear(); popupsOnPage.clear(); popupsTotal = 0; scansOnPage = 0; lastScanAt = 0; lastScanUrl = ""
        lastCountdown = 0; pageWaitStart = 0; autoClicks = 0; clickedKeys.clear(); pendingClick = null; clickTarget = null
        manualResumes = 0; ignoreChallengeOnPage = false
        primaryResult = null; resumeResults.clear(); confirmedKeys.clear(); inResume = false; expectTab = false; lastOpensWindows = false
        goal = null; mismatches.clear(); mismatchKeys.clear()
    }

    private fun resetPageCounters() {
        scansOnPage = 0; pageWaitStart = 0; ignoreChallengeOnPage = false; pageScanCounted = false
    }

    // ------------------------------------------------------------------ eventos de navegação

    /**
     * Chamado para cada navegação de quadro principal (links, redirecionamentos, popups).
     * ALLOW = deixar carregar; BLOCK = cancelar; ASK = cancelar e aguardar confirmação do usuário.
     */
    fun onNavigationRequest(url: String, redirect: Boolean, userGesture: Boolean = false, tabId: Int = workTab): NavDecision {
        if (url == "about:blank") return NavDecision.ALLOW
        val verdict = UrlSafety.check(url)
        if (verdict is UrlSafety.Verdict.Rejected) {
            step(StepKind.BLOCKED, url, verdict.reason)
            if (isActive && tabId != workTab) closeSecondaryTab(tabId, "URL recusada: ${verdict.reason}")
            else if (isActive && redirect) finish(ResultState.BLOCKED, null, "Redirecionamento bloqueado: ${verdict.reason}")
            return NavDecision.BLOCK
        }
        if (!isActive) return NavDecision.ALLOW
        if (state == EngineState.WAITING_CONFIRMATION) {
            step(StepKind.BLOCKED, url, "navegação ignorada: aguardando confirmação anterior")
            return NavDecision.BLOCK
        }
        val host = UrlSafety.host(url)!!
        if (DownloadHeuristics.isAdHost(host)) {
            step(StepKind.BLOCKED, url, "rede de anúncios bloqueada")
            if (tabId != workTab) closeSecondaryTab(tabId, "guia de rede de anúncios")
            return NavDecision.BLOCK
        }
        if (redirect) {
            redirectsInStep++
            if (redirectsInStep > limits.maxRedirectsPerStep) {
                finish(ResultState.BLOCKED, null, "Excesso de redirecionamentos (>${limits.maxRedirectsPerStep}) nesta etapa")
                return NavDecision.BLOCK
            }
        }
        if (!policy.isTrusted(host)) {
            if (policy.domains.size >= limits.maxDomains) {
                step(StepKind.BLOCKED, url, "limite de ${limits.maxDomains} domínios atingido")
                finish(ResultState.BLOCKED, null, "Limite de domínios atingido ao tentar ir para $host")
                return NavDecision.BLOCK
            }
            ask(Pending(url, host, PendingSource.NAVIGATION, redirect, null, tabId = tabId),
                (if (tabId != workTab) "guia ${tabId}: " else "") + if (redirect) "redirecionamento" else "navegação")
            return NavDecision.ASK
        }
        if (!registerVisit(url)) return NavDecision.BLOCK
        val hint = redirectHints[UrlSafety.loopKey(url)]
        val (kind, arrival) = when {
            redirect -> PathKind.HTTP_REDIRECT to "redirecionamento HTTP (servidor; o WebView não expõe o código)"
            hint == "meta refresh" -> PathKind.META_REFRESH to "meta refresh da página anterior"
            hint == "JavaScript" -> PathKind.JS_REDIRECT to "redirecionamento JavaScript da página anterior"
            userGesture -> PathKind.NAVIGATION to "clique do usuário na página"
            else -> PathKind.NAVIGATION to "navegação iniciada pela página (JS/meta refresh não identificado)"
        }
        step(if (redirect || kind != PathKind.NAVIGATION) StepKind.REDIRECT else StepKind.NAVIGATE, url, arrival)
        val info = tabInfos[tabId]
        if (info != null && !info.urlSet) {
            // primeira navegação de uma guia nova: completa o nó "NOVA GUIA" em vez de criar outro
            info.urlSet = true
            if (info.pathIndex in path.indices) path[info.pathIndex] = path[info.pathIndex].copy(url = UrlSafety.redact(url), linkClass = LinkClass.PAGE)
        } else addPath(kind, url, arrival, LinkClass.PAGE, tabId = tabId)
        noteEffect("navegação")
        if (state == EngineState.WAITING_CLICK) resumeFromClick("a página reagiu ao toque (navegação)")
        if (path.count { it.kind != PathKind.FILE } > limits.maxPages) {
            finish(ResultState.BLOCKED, null, "Limite de ${limits.maxPages} páginas/etapas atingido")
            return NavDecision.BLOCK
        }
        return NavDecision.ALLOW
    }

    fun onPageStarted(url: String, tabId: Int = workTab) {
        if (isErrorUrl(url)) { step(StepKind.PAGE, url, "página interna de erro do navegador (ignorada)"); return }
        noteEffect("nova página")
        if (tabId != workTab) { step(StepKind.PAGE, url, "guia $tabId carregando"); return }
        mainFrameError = false
        resetPageCounters()
        step(StepKind.PAGE, url, "carregando")
    }

    fun onPageFinished(url: String, tabId: Int = workTab) {
        if (isErrorUrl(url) || (mainFrameError && tabId == workTab)) {
            // onPageFinished também dispara depois de um erro: NÃO é sucesso e NÃO deve ser analisada.
            step(StepKind.PAGE, url, "encerrada com erro — não analisada")
            return
        }
        step(StepKind.PAGE, url, if (tabId == workTab) "carregada" else "guia $tabId carregada")
        if (!isActive) return
        if (tabId != workTab) {
            if (tabInfos[tabId]?.relevant == null) listener.requestRescan(tabId, 1200) // classificar a guia nova
            return
        }
        if (state == EngineState.RUNNING) {
            scanAttempts = 0
            listener.requestRescan(workTab, 1200)
        }
    }

    // ------------------------------------------------------------------ guias (popups)

    /**
     * Decide se um popup pode virar guia. Exige gesto humano, origem confiável, que a origem não seja outra
     * guia secundária (sem cadeia de popups) e respeita os limites por página e totais.
     */
    fun onPopupRequest(openerTab: Int, openerUrl: String?, userGesture: Boolean): Boolean {
        val host = openerUrl?.let { UrlSafety.host(it) }
        fun deny(reason: String): Boolean {
            step(StepKind.POPUP, openerUrl, "popup bloqueado: $reason")
            return false
        }
        if (!userGesture) return deny("sem gesto do usuário")
        if (host == null) return deny("origem desconhecida")
        if (isActive && !policy.isTrusted(host)) return deny("origem não confiável ($host)")
        if (tabInfos.containsKey(openerTab)) return deny("popup aberto por guia secundária (sem cadeia de popups)")
        val key = UrlSafety.loopKey(openerUrl)
        val n = popupsOnPage[key] ?: 0
        if (isActive) {
            if (n >= limits.maxPopupsPerPage) return deny("excesso de popups nesta página (${n} já abertos): possível página maliciosa")
            if (popupsTotal >= limits.maxPopupsTotal) return deny("limite de ${limits.maxPopupsTotal} popups por análise")
        }
        popupsOnPage[key] = n + 1; popupsTotal++
        step(StepKind.POPUP, openerUrl, "popup permitido (gesto humano em origem confiável: $host)")
        return true
    }

    /** Uma guia foi criada (window.open / target=_blank). Abrir guia NÃO é evidência de arquivo. */
    fun onTabOpened(tabId: Int, openerId: Int, openerUrl: String?) {
        if (!isActive) {
            // Análise concluída: guias abertas pelo usuário NÃO alteram o resultado, o caminho nem o estado.
            step(StepKind.TAB, openerUrl, "guia $tabId aberta pelo usuário após o fim da análise (resultado preservado)")
            return
        }
        val idx = path.size
        if (path.size < 80) {
            path += PathEntry(
                path.size + 1, PathKind.NEW_TAB, null,
                "aberta pela página ${openerUrl?.let { UrlSafety.redact(it) } ?: "?"} (guia $openerId) via window.open/target=_blank/clique",
                null, "aguardando classificação (continuação ou propaganda?)", tabId = tabId,
            )
        }
        tabInfos[tabId] = TabInfo(openerId, openerUrl, idx)
        step(StepKind.TAB, openerUrl, "guia $tabId aberta pela guia $openerId")
        noteEffect("nova guia")
        expectTab = false
        if (state == EngineState.WAITING_CLICK) resumeFromClick("o toque abriu uma nova guia")
    }

    fun onTabClosed(tabId: Int) {
        val info = tabInfos.remove(tabId) ?: return
        if (!isActive) { step(StepKind.TAB, null, "guia $tabId fechada (análise já concluída; resultado preservado)"); return }
        step(StepKind.TAB, null, "guia $tabId fechada")
        if (workTab == tabId) {
            workTab = info.openerId ?: 0
            resetPageCounters()
            listener.onWorkTabChanged(workTab)
            if (isActive) listener.requestRescan(workTab, 500)
        }
    }

    private fun closeSecondaryTab(tabId: Int, reason: String) {
        if (tabId == 0 || tabId == workTab) return
        tabInfos[tabId]?.let { i ->
            i.relevant = false
            if (i.pathIndex in path.indices) path[i.pathIndex] = path[i.pathIndex].copy(decision = "guia fechada: $reason")
        }
        step(StepKind.TAB, null, "guia $tabId fechada: $reason")
        listener.closeTab(tabId)
    }

    private fun classifyPopupScan(tabId: Int, scan: PageScan) {
        val info = tabInfos[tabId] ?: return
        if (info.relevant != null) return
        if (isErrorUrl(scan.url)) { closeSecondaryTab(tabId, "página de erro"); return }
        val pageHost = UrlSafety.host(scan.url) ?: ""
        val scored = scan.candidates.map { Relevance.apply(DownloadHeuristics.score(it, pageHost, policy), goal) }.sortedByDescending { it.score }
        val actionable = scored.any {
            it.safe && !it.ad && it.url != null && (it.score >= limits.autoScoreThreshold || (isStepLike(it) && it.score >= limits.tier2MinScore))
        } || scored.any { DownloadHeuristics.isAutoClickEligible(it, limits.tier2MinScore) }
        val relevant = !scan.adLike && (actionable || scan.countdownSec > 0)
        if (!relevant) {
            closeSecondaryTab(tabId, if (scan.adLike) "propaganda (texto de cassino/prêmio/VPN…)" else "sem continuação de download")
            return
        }
        info.relevant = true
        val canPromote = (state == EngineState.RUNNING || state == EngineState.WAITING_CLICK) && workTab == info.openerId
        if (!canPromote) {
            step(StepKind.TAB, scan.url, "guia $tabId parece relevante, mantida em segundo plano (use \"Usar esta guia\" para continuar nela)")
            if (info.pathIndex in path.indices) path[info.pathIndex] = path[info.pathIndex].copy(decision = "possível continuação, mantida em segundo plano")
            return
        }
        promoteTab(tabId, "continuação do download (${scored.count { it.score >= limits.tier2MinScore }} candidato(s))")
        onScan(scan, tabId)
    }

    private fun promoteTab(tabId: Int, why: String) {
        workTab = tabId
        resetPageCounters()
        scanAttempts = 0; stepStartedAt = clock()
        tabInfos[tabId]?.let { i -> if (i.pathIndex in path.indices) path[i.pathIndex] = path[i.pathIndex].copy(decision = "guia de trabalho: $why") }
        step(StepKind.TAB, null, "guia $tabId promovida a guia de trabalho: $why")
        listener.onWorkTabChanged(tabId)
    }

    /**
     * Durante uma análise ATIVA, o usuário escolhe em qual guia ela deve continuar. Depois de concluída, NÃO faz nada:
     * alternar/selecionar guias é só visual. Para continuar depois do fim use [resumeOnTab] (ação explícita).
     */
    fun setWorkTab(tabId: Int) {
        if (!isActive) {
            if (state == EngineState.FINISHED) step(StepKind.TAB, null, "seleção de guia ignorada: a análise já terminou (use Retomar para continuar)")
            return
        }
        if (state == EngineState.WAITING_CONFIRMATION) return
        tabInfos[tabId]?.relevant = true
        promoteTab(tabId, "escolhida pelo usuário")
        listener.requestRescan(tabId, 300)
    }

    /** Pode haver retomada explícita (a análise terminou e ainda há orçamento de retomadas)? */
    fun canResume(): Boolean = state == EngineState.FINISHED && manualResumes < limits.maxManualResumes &&
        lastResult?.message?.contains("Safe Browsing") != true

    /**
     * AÇÃO EXPLÍCITA: retomar a análise na guia [tabId] depois do fim. Inicia uma nova etapa controlada e seu
     * resultado é apresentado SEPARADAMENTE; um resultado de arquivo confirmado anterior é mantido.
     */
    fun resumeOnTab(tabId: Int): Boolean {
        if (!canResume()) { step(StepKind.BLOCKED, null, "retomada não permitida (limite, Safe Browsing ou análise ainda ativa)"); return false }
        manualResumes++; inResume = true
        startedAt = clock(); pausedMs = 0; pauseStart = 0; stepStartedAt = clock(); scanAttempts = 0
        networkFailure = null; failedUrl = null; mainFrameError = false; probingUrl = null; pending = null
        pendingClick = null; clickTarget = null; expectTab = false
        depth = minOf(depth, limits.maxDepth - 1)
        step(StepKind.RESUME, null, "retomada manual #$manualResumes na guia $tabId (pedida pelo usuário)")
        setState(EngineState.RUNNING, "Retomado na guia $tabId")
        tabInfos[tabId]?.relevant = true
        promoteTab(tabId, "retomada explícita pelo usuário")
        listener.requestRescan(tabId, 300)
        return true
    }

    /** Efeito observável de um clique automático (navegação, nova guia, mudança no DOM...). */
    private fun noteEffect(what: String) {
        if (pendingClick != null) {
            step(StepKind.CLICK, null, "o clique automático teve efeito: $what")
            pendingClick = null
        }
    }

    private fun resumeFromClick(reason: String) {
        if (state != EngineState.WAITING_CLICK) return
        endPause(); clickTarget = null; expectTab = false
        step(StepKind.RESUME, null, "retomando: $reason")
        stepStartedAt = clock(); scanAttempts = 0
        setState(EngineState.RUNNING, "Retomado")
    }

    /** O DOM da guia mudou (botão criado/liberado). Pede nova varredura com limite de frequência. */
    fun onDomChanged(tabId: Int = workTab) {
        if (!isActive || state == EngineState.WAITING_CONFIRMATION || probingUrl != null) return
        if (tabId != workTab && tabInfos[tabId]?.relevant != null) return
        if (!expectTab) noteEffect("a página foi modificada") // alteração do DOM NÃO prova que uma guia abriu
        if (tabId == workTab && scansOnPage >= limits.maxScansPerPage) return
        val sinceLast = clock() - lastScanAt
        listener.requestRescan(tabId, maxOf(700L, limits.minScanIntervalMs - sinceLast))
    }

    /** Confirmação humana: o desafio/clique foi resolvido. Retoma e ignora a detecção na página atual. */
    fun userConfirmedResume() {
        when (state) {
            EngineState.WAITING_HUMAN -> {
                endPause(); ignoreChallengeOnPage = true
                step(StepKind.RESUME, null, "usuário confirmou que concluiu a verificação — retomando")
                stepStartedAt = clock(); scanAttempts = 0
                setState(EngineState.RUNNING, "Retomado pelo usuário")
                listener.requestRescan(workTab, 300)
            }
            EngineState.WAITING_CLICK -> {
                lastScored.filter { DownloadHeuristics.isAutoClickEligible(it, limits.tier2MinScore) }.forEach { clickedKeys += clickKey(it) }
                resumeFromClick("usuário confirmou o toque")
                listener.requestRescan(workTab, 300)
            }
            EngineState.RUNNING -> listener.requestRescan(workTab, 0)
            else -> Unit
        }
    }

    private fun clickKey(c: ScoredCandidate) = "$workTab|${UrlSafety.loopKey(lastScanUrl)}|${c.raw.text}|${c.raw.tag}"

    /** Exige gesto humano real: destaca o botão (ou pede escolha, se ambíguo) e espera. */
    private fun humanClick(c: ScoredCandidate?, reason: String, opensTab: Boolean = false) {
        clickTarget = c
        expectTab = opensTab
        beginPause()
        val msg = if (c != null) "Toque no botão destacado «${c.raw.text.take(40)}» na página ($reason)."
        else "Vários botões possíveis ($reason): escolha na aba Candidatos (Destacar) ou toque na página."
        step(StepKind.CLICK, lastScanUrl.ifEmpty { null }, msg)
        setDecision(msg)
        setState(EngineState.WAITING_CLICK, msg)
        c?.raw?.elementId?.let { listener.requestHighlight(workTab, it, c.raw.text) }
    }

    private fun doAutoClick(c: ScoredCandidate) {
        autoClicks++
        clickedKeys += clickKey(c)
        val msg = "clicou automaticamente em «${c.raw.text.take(40)}» (botão inequívoco, pontuação ${c.score}: ${c.reasons.joinToString(", ")})"
        step(StepKind.CLICK, lastScanUrl.ifEmpty { null }, msg)
        setDecision(msg)
        pendingClick = ClickAttempt(c, clock())
        stepStartedAt = clock()
        listener.requestClick(workTab, c.raw.elementId!!, c.raw.text)
    }

    /**
     * Retomada manual de um candidato depois do encerramento da análise: inicia uma NOVA etapa controlada
     * (novo orçamento de tempo, profundidade com ao menos uma etapa livre), mantendo histórico e candidatos.
     */
    fun resumeFromCandidate(c: ScoredCandidate): Boolean {
        if (state != EngineState.FINISHED) { if (isActive) manualFollow(c); return isActive }
        val url = c.url ?: return false
        if (!c.safe || c.ad) { step(StepKind.BLOCKED, url, "candidato inseguro ou de anúncio não pode ser retomado"); return false }
        if (lastResult?.message?.contains("Safe Browsing") == true) { step(StepKind.BLOCKED, url, "análise encerrada pelo Safe Browsing: não retomável"); return false }
        if (manualResumes >= limits.maxManualResumes) { step(StepKind.BLOCKED, url, "limite de ${limits.maxManualResumes} retomadas manuais atingido"); return false }
        manualResumes++; inResume = true; expectTab = false
        val key = UrlSafety.loopKey(url)
        visits.remove(key); rejected.remove(key); probed.remove(key); candidateStatus.remove(key)
        startedAt = clock(); pausedMs = 0; pauseStart = 0; stepStartedAt = clock()
        depth = minOf(depth, limits.maxDepth - 1)
        networkFailure = null; failedUrl = null; mainFrameError = false; probingUrl = null; pending = null
        pendingClick = null; clickTarget = null; scanAttempts = 0
        step(StepKind.RESUME, url, "retomada manual #$manualResumes a partir do candidato «${c.raw.text.take(40)}»")
        setState(EngineState.RUNNING, "Retomado manualmente")
        follow(c, manual = true, "retomada manual: ")
        return true
    }

    fun onPopup(opener: String?, url: String?, allowed: Boolean, reason: String) {
        step(StepKind.POPUP, url ?: opener, (if (allowed) "aba aberta: " else "popup bloqueado: ") + reason)
    }

    fun onHttpError(url: String, code: Int) {
        step(StepKind.ERROR, url, "HTTP $code")
        if (code == 401 || code == 403) { sawHttpAuthError = true; return } // pode ser tela de login: segue para a varredura
        if (code >= 400) onMainFrameError(url, code, "HTTP $code")
    }

    /** Erro na navegação do quadro principal (rede, DNS, SSL, HTTP 4xx/5xx). */
    fun onMainFrameError(url: String, code: Int, description: String, tabId: Int = workTab) {
        if (!isActive) return
        if (tabId != workTab) { // erro numa guia secundária não derruba a análise
            step(StepKind.ERROR, url, "erro na guia $tabId: ${UrlSafety.scrubText(description)} (código $code)")
            closeSecondaryTab(tabId, "erro de carregamento")
            return
        }
        mainFrameError = true
        val info = UrlSafety.scrubText("$description (código $code)")
        val where = if (url.isBlank() || isErrorUrl(url)) (followedUrl ?: startUrl) else url
        step(StepKind.ERROR, where, "erro na navegação principal: $info")
        diagnostics += "Navegação principal falhou em ${where?.let { UrlSafety.redact(it) } ?: "?"}: $info"
        where?.let { candidateStatus[UrlSafety.loopKey(it)] = "erro de rede: $description" }
        if (state != EngineState.RUNNING) return // em espera humana/confirmação: apenas registra
        networkFailure = info
        failedUrl = where
        if (lastScored.isEmpty()) {
            finish(ResultState.NETWORK_ERROR, null, "A página inicial não pôde ser carregada: $info", errorInfo = info)
        } else {
            finishWithBest("Falha de rede na navegação principal: $info")
        }
    }

    fun onSafeBrowsingHit(url: String, threat: String) {
        step(StepKind.BLOCKED, url, "Safe Browsing: $threat")
        if (isActive) finish(ResultState.BLOCKED, null, "Bloqueado pelo Safe Browsing ($threat)")
    }

    // ------------------------------------------------------------------ download / sondagem

    /** DownloadListener.onDownloadStart: evidência de que a URL entrega um arquivo (nada é baixado). */
    fun onDownload(info: DownloadInfo) {
        if (isActive) noteEffect("download iniciado")
        val canUpgrade = state == EngineState.FINISHED && isLateDownloadOfCandidate(info.url)
        if (!isActive && !canUpgrade) return
        val verdict = UrlSafety.check(info.url)
        if (verdict is UrlSafety.Verdict.Rejected) {
            step(StepKind.BLOCKED, info.url, "download bloqueado: ${verdict.reason}")
            if (isActive) finish(ResultState.BLOCKED, null, "URL de download recusada: ${verdict.reason}")
            return
        }
        val isFile = DownloadHeuristics.isFileMime(info.mimeType) || DownloadHeuristics.isAttachment(info.contentDisposition)
        step(StepKind.DOWNLOAD, info.url, "DownloadListener: mime=${info.mimeType ?: "?"} tamanho=${DownloadHeuristics.formatSize(info.contentLength.takeIf { it > 0 })}")
        if (!isFile) {
            step(StepKind.ERROR, info.url, "download ignorado: conteúdo parece página HTML")
            return
        }
        if (canUpgrade) { state = EngineState.RUNNING; step(StepKind.RESUME, info.url, "download tardio do candidato: promovendo resultado") }
        confirmFile(
            info.url, info.mimeType?.substringBefore(';')?.trim(),
            DownloadHeuristics.estimateFileName(info.url, info.contentDisposition),
            info.contentLength.takeIf { it > 0 }, "Arquivo identificado pelo DownloadListener.",
            "DownloadListener: ${info.mimeType ?: "mime desconhecido"}, ${DownloadHeuristics.formatSize(info.contentLength.takeIf { it > 0 })}",
        )
    }

    private fun isLateDownloadOfCandidate(url: String): Boolean {
        val r = lastResult ?: return false
        if (r.state !in setOf(ResultState.UNVERIFIED_CANDIDATE, ResultState.NETWORK_ERROR, ResultState.INTERMEDIATE_LINK)) return false
        if (clock() - finishedAt > LATE_DOWNLOAD_WINDOW_MS) return false
        val key = UrlSafety.loopKey(url)
        return key == r.url?.let { UrlSafety.loopKey(it) } || key == followedUrl?.let { UrlSafety.loopKey(it) }
    }

    /** Resposta da sondagem pedida via [Listener.requestProbe]. */
    fun onProbeResult(url: String, r: ProbeResult, diag: List<String> = emptyList(), hops: List<RedirectHop> = emptyList()) {
        val pu = probingUrl
        if (!isActive || pu == null || UrlSafety.loopKey(url) != UrlSafety.loopKey(pu)) return
        probingUrl = null
        val cand = probingCandidate; probingCandidate = null
        val key = UrlSafety.loopKey(url)
        probingUrlKey = key
        diag.take(60).forEach { diagnostics += UrlSafety.scrubText(it) }
        hops.take(10).forEach { h ->
            step(StepKind.REDIRECT, h.to, "HTTP ${h.code} observado na verificação (OkHttp): ${UrlSafety.host(h.from) ?: "?"} → ${UrlSafety.host(h.to) ?: "?"}")
            addPath(PathKind.HTTP_REDIRECT, h.to, "HTTP ${h.code} (verificação OkHttp)", LinkClass.PAGE, code = h.code)
            probeHopKeys += UrlSafety.loopKey(h.to)  // o WebView repetirá este redirect: não duplicar o nó
        }
        val fileLike = cand?.linkClass == LinkClass.FILE_CANDIDATE
        when (r) {
            is ProbeResult.File -> {
                val line = "${r.method} ${r.status}: mime=${r.mimeType ?: "?"} tamanho=${DownloadHeuristics.formatSize(r.contentLength)}" +
                    (if (r.acceptRanges) " range=sim" else "")
                step(StepKind.SCAN, url, "sondagem validou o arquivo — $line")
                confirmFile(
                    r.finalUrl, r.mimeType,
                    DownloadHeuristics.estimateFileName(r.finalUrl, r.contentDisposition) ?: DownloadHeuristics.estimateFileName(url, null),
                    r.contentLength, "Metadados confirmados por ${r.method} (sem baixar o corpo).", line,
                )
            }
            is ProbeResult.Blocked -> {
                step(StepKind.BLOCKED, url, "sondagem bloqueada: ${r.reason}")
                diagnostics += "Sondagem bloqueada: ${r.reason}"
                candidateStatus[key] = "bloqueado: ${r.reason}"
                finish(ResultState.BLOCKED, null, "Candidato bloqueado: ${r.reason}")
            }
            is ProbeResult.Page -> {
                step(StepKind.SCAN, url, "sondagem: é uma página (${r.mimeType ?: "?"}), seguindo no navegador")
                navigateAfterProbe(url)
            }
            is ProbeResult.NeedsDomain -> {
                if (policy.domains.size + probeExtra.size >= limits.maxDomains) {
                    candidateStatus[key] = "não verificado (limite de domínios)"
                    finish(ResultState.UNVERIFIED_CANDIDATE, url, "$UNVERIFIED Redirecionamento para ${r.host} excede o limite de domínios.")
                } else {
                    probingCandidate = cand
                    ask(Pending(r.nextUrl, r.host, PendingSource.PROBE, false, cand, origin = url), "redirecionamento do arquivo candidato")
                }
            }
            is ProbeResult.HttpError -> {
                val d = "Sondagem HTTP ${r.status}"
                diagnostics += d
                step(StepKind.ERROR, url, d)
                if (!fileLike) { if (r.status == 401 || r.status == 403) sawHttpAuthError = true; navigateAfterProbe(url); return }
                if (r.status == 401 || r.status == 403) {
                    sawHttpAuthError = true
                    candidateStatus[key] = "exige sessão (HTTP ${r.status})"
                    finish(ResultState.REQUIRES_SESSION, url, "O servidor respondeu HTTP ${r.status}: exige sessão/autenticação. $UNVERIFIED", errorInfo = d)
                } else {
                    candidateStatus[key] = "não verificado (HTTP ${r.status})"
                    finish(ResultState.UNVERIFIED_CANDIDATE, url, "$UNVERIFIED O servidor respondeu HTTP ${r.status}.", errorInfo = d)
                }
            }
            is ProbeResult.NetworkError -> {
                val info = "${r.category}: ${UrlSafety.scrubText(r.message)}"
                diagnostics += "Sondagem sem resposta — $info"
                step(StepKind.ERROR, url, "sondagem sem resposta — $info")
                if (!fileLike) { step(StepKind.SCAN, url, "página (não é arquivo): seguindo pelo navegador"); navigateAfterProbe(url); return }
                candidateStatus[key] = "não verificado (${r.category})"
                finish(ResultState.UNVERIFIED_CANDIDATE, url, "$UNVERIFIED Falha de rede na validação (${r.category}); o app NÃO navegou até o arquivo.", errorInfo = info)
            }
            is ProbeResult.Inconclusive -> {
                diagnostics += "Sondagem inconclusiva: ${r.reason}"
                step(StepKind.SCAN, url, "sondagem inconclusiva: ${r.reason}")
                if (!fileLike) { navigateAfterProbe(url); return }
                candidateStatus[key] = "não verificado"
                finish(ResultState.UNVERIFIED_CANDIDATE, url, "$UNVERIFIED Validação inconclusiva (${r.reason}); o app NÃO navegou até o arquivo.")
            }
        }
    }

    private fun navigateAfterProbe(url: String) {
        stepStartedAt = clock()
        listener.navigate(workTab, url)
    }

    private fun confirmFile(url: String, mime: String?, name: String?, size: Long?, how: String, evidenceLine: String) {
        // O arquivo é válido por HTTP; mas corresponde ao que se procurava? Se não, NÃO encerra com sucesso: segue procurando.
        val cand = followedUrl?.let { allCands[UrlSafety.loopKey(it)] } ?: allCands[UrlSafety.loopKey(url)]
        val compat = Relevance.compat(goal, FileFacts(url, name, mime, cand?.raw?.text ?: ""))
        if (compat.verdict == Verdict.MISMATCH) {
            recordMismatch(url, name, evidenceLine, compat.reason)
            continueAfterMismatch()
            return
        }
        evidence += evidenceLine
        probingUrlKey?.let { candidateStatus[it] = "arquivo confirmado" }
        confirmedKeys += UrlSafety.loopKey(url)
        followedUrl?.let { confirmedKeys += UrlSafety.loopKey(it) }
        probingUrlKey?.let { confirmedKeys += it }
        setDecision("arquivo identificado — ${how.trim()}")
        addPath(PathKind.FILE, url, how.trim(), LinkClass.CONFIRMED_FILE)
        val large = size != null && size >= limits.largeFileBytes
        val needsSession = humanAuthHappened
        val msg = buildString {
            if (needsSession) append("Arquivo alcançado após autenticação manual: a URL provavelmente só funciona dentro desta sessão. ")
            else append("$how ")
            append(if (large) "Arquivo grande: NADA foi baixado automaticamente." else "Nada foi baixado pelo aplicativo.")
        }.trim()
        finish(
            if (needsSession) ResultState.REQUIRES_SESSION else ResultState.VERIFIED_FILE,
            url, msg, mime, name, size,
        )
    }

    private fun recordMismatch(url: String, name: String?, evidenceLine: String, why: String) {
        val k = UrlSafety.loopKey(url)
        mismatchKeys += k
        followedUrl?.let { mismatchKeys += UrlSafety.loopKey(it) }
        probingUrlKey?.let { mismatchKeys += it; candidateStatus[it] = MISMATCH_STATUS }
        candidateStatus[k] = MISMATCH_STATUS
        mismatches += "${name ?: UrlSafety.redact(url)} — $evidenceLine — $why"
        step(StepKind.SCAN, url, "Arquivo válido — conteúdo diferente: $why ($evidenceLine)")
        diagnostics += "Arquivo válido — conteúdo diferente: ${name ?: UrlSafety.redact(url)} ($why)"
        setDecision("arquivo válido por HTTP, mas conteúdo diferente do objetivo: $why")
        addPath(PathKind.FILE, url, "$evidenceLine — conteúdo diferente do objetivo", LinkClass.WRONG_CONTENT)
    }

    /** Depois de um arquivo válido porém incompatível: investiga o próximo candidato relevante (respeitando os limites). */
    private fun continueAfterMismatch() {
        if (mismatches.size > limits.maxMismatches) { finishWithBest("Limite de ${limits.maxMismatches} arquivos de conteúdo diferente atingido"); return }
        val next = allCands.values.sortedByDescending { it.score }.firstOrNull {
            val k = UrlSafety.loopKey(it.url ?: return@firstOrNull false)
            it.safe && !it.ad && !it.raw.disabled && (visits[k] ?: 0) == 0 && k !in rejected && k !in mismatchKeys && k !in confirmedKeys &&
                it.score >= limits.tier2MinScore
        }
        if (next == null) { finishWithBest("Não há outros candidatos relevantes para investigar"); return }
        stepStartedAt = clock(); scanAttempts = 0
        follow(next, manual = false, "outro candidato relevante (o arquivo anterior tinha conteúdo diferente): ")
    }

    // ------------------------------------------------------------------ varredura

    fun onScan(scan: PageScan, tabId: Int = workTab) {
        if (!isActive) return
        if (tabId != workTab) { classifyPopupScan(tabId, scan); return }
        if (state != EngineState.RUNNING && state != EngineState.WAITING_HUMAN && state != EngineState.WAITING_CLICK) return
        if (probingUrl != null) return // etapa em andamento (verificação de rede em curso): varredura duplicada é ignorada
        if (isErrorUrl(scan.url) || mainFrameError) {
            step(StepKind.SCAN, scan.url, "varredura ignorada: página de erro")
            return
        }
        scansOnPage++
        lastScanAt = clock(); lastScanUrl = scan.url
        if (scansOnPage > limits.maxScansPerPage) {
            finishWithBest("Limite de ${limits.maxScansPerPage} verificações nesta página atingido (evita espera infinita)")
            return
        }

        if (scan.challenge != null && !ignoreChallengeOnPage) {
            if (state != EngineState.WAITING_HUMAN) {
                if (scan.challenge == ChallengeKind.LOGIN) humanAuthHappened = true
                beginPause()
                pendingClick = null; clickTarget = null
                step(StepKind.CHALLENGE, scan.url, "${scan.challenge.label} detectado (${scan.challengeHint ?: "-"}) — automação pausada")
                setState(
                    EngineState.WAITING_HUMAN,
                    "${scan.challenge.label}: resolva manualmente na página. A automação retoma quando a página liberar ou quando você tocar em \"Já resolvi\".",
                )
            }
            return
        }
        if (state == EngineState.WAITING_HUMAN) {
            endPause()
            step(StepKind.RESUME, scan.url, "desafio não detectado mais — retomando")
            stepStartedAt = clock()
            scanAttempts = 0
            setState(EngineState.RUNNING, "Retomado")
        }

        val pageHost = UrlSafety.host(scan.url) ?: UrlSafety.host(startUrl ?: "") ?: ""
        if (goal == null) {
            // Objetivo = contexto da PRIMEIRA página analisada (título/cabeçalho/descrição) + preferência opcional do usuário
            goal = GoalContext.build(scan.title, scan.heading, scan.description, userPref)
            step(StepKind.SCAN, scan.url, "objetivo da busca (${goal!!.describe()})" + if (goal!!.informative) "" else " — contexto insuficiente: sem filtro por relevância")
        }
        val derived = derivedRawCandidate(scan)
        val scored = (if (derived != null) scan.candidates + derived else scan.candidates)
            .map { Relevance.apply(DownloadHeuristics.score(it, pageHost, policy), goal) }
            .sortedByDescending { it.score }
        lastScored = scored
        lastWaitHint = scan.waitHint
        lastCountdown = scan.countdownSec
        lastOpensWindows = scan.opensWindows
        lastIntermediate = scan.waitHint || scan.countdownSec > 0 ||
            scored.count { it.safe && !it.ad && it.url != null && it.raw.visible } <= limits.maxIntermediateCandidates
        scored.forEach { c ->
            val u = c.url ?: return@forEach
            val k = UrlSafety.loopKey(u)
            val old = allCands[k]
            if (old == null || c.score > old.score) allCands[k] = c
            when (c.raw.source) {
                "meta-refresh" -> redirectHints[k] = "meta refresh"
                "js-redirect" -> redirectHints[k] = "JavaScript"
            }
        }
        listener.onCandidates(allCandsSorted())
        updateCurrentPage(scan.title)
        if (derived != null) step(StepKind.SCAN, scan.url, "GitHub não expôs o link Raw: derivando de /blob/ → ${UrlSafety.redact(derived.url!!)}")
        step(StepKind.SCAN, scan.url, "${scored.size} candidato(s)" + (if (scan.totalCandidates > scored.size) " (de ${scan.totalCandidates} na página, priorizados)" else "") + "; melhor pontuação=${scored.firstOrNull()?.score ?: "-"}" +
            (if (lastIntermediate) "; página intermediária" else "") + (if (scan.waitHint) "; indica espera" else "") +
            (if (scan.countdownSec > 0) "; contagem ${scan.countdownSec}s" else "") + (if (scored.any { it.raw.disabled }) "; botão desabilitado" else "") +
            (if (scored.any { it.raw.dynamic }) "; elementos dinâmicos" else ""))

        // Sem progresso: páginas seguidas que não revelam nenhuma URL nova.
        if (!pageScanCounted) {
            pageScanCounted = true
            val fresh = scored.mapNotNull { it.url }.count { seenCandidateUrls.add(UrlSafety.loopKey(it)) }
            stagnant = if (scannedPages > 0 && fresh == 0) stagnant + 1 else 0
            scannedPages++
            if (stagnant >= limits.maxStagnantPages) {
                finishWithBest("Sem progresso: ${limits.maxStagnantPages} páginas seguidas sem nenhuma URL nova")
                return
            }
        }
        chooseAndFollow()
    }

    /**
     * Página de visualização do GitHub (/blob/…/x.smc) sem link Raw próprio (a UI pode hidratar tarde): depois da
     * 1ª varredura, deriva o endereço Raw. Sempre preferimos o link fornecido pelo próprio GitHub.
     */
    private fun derivedRawCandidate(scan: PageScan): RawCandidate? {
        if (scansOnPage < 2) return null
        if (DownloadHeuristics.extensionOf(scan.url) !in DownloadHeuristics.FILE_EXTENSIONS) return null
        if (scan.candidates.any { it.url != null && GithubUrls.isRawLink(it.url) }) return null
        val raw = GithubUrls.derivedRaw(scan.url) ?: return null
        return RawCandidate(raw, "Raw (derivado de /blob/)", "a", "derived-raw", false, "", "", null, true)
    }

    /** "pontuação 155 (técnica 100 + contexto 55): motivos…" — técnica e contexto sempre separadas. */
    private fun describeScore(c: ScoredCandidate) =
        "pontuação ${c.score}" + (if (c.relevance != 0) " (técnica ${c.technical} ${if (c.relevance > 0) "+" else "−"} contexto ${Math.abs(c.relevance)})" else "") +
            ": ${(c.reasons + c.relevanceReasons).joinToString(", ")}"

    private fun isStepLike(c: ScoredCandidate) =
        c.raw.source == "meta-refresh" || c.raw.source == "js-redirect" || DownloadHeuristics.isStepText(c.raw.text) || DownloadHeuristics.isHostButton(c)

    private fun chooseAndFollow() {
        val usable = lastScored.filter {
            it.safe && !it.ad && it.url != null && UrlSafety.loopKey(it.url!!) !in rejected
        }
        usable.firstOrNull { UrlSafety.loopKey(it.url!!) in confirmedKeys }?.let { known ->
            if (inResume) {   // retomada que volta a um arquivo já confirmado: sucesso, não loop
                val prev = primaryResult
                step(StepKind.SCAN, known.url, "URL já confirmada como arquivo nesta sessão: voltar a ela não é loop")
                finish(ResultState.VERIFIED_FILE, known.url, "Arquivo já confirmado anteriormente (mesma URL); nada foi baixado.", prev?.mimeType, prev?.fileName, prev?.sizeBytes)
                return
            }
        }
        // Numa página de visualização de arquivo (GitHub /blob/) o objetivo é o link Raw: links para OUTROS arquivos
        // (árvore lateral) não competem com ele, mesmo antes de o link Raw aparecer.
        val onViewPage = GithubUrls.isBlobView(lastScanUrl)
        val unvisited = usable.filter {
            (visits[UrlSafety.loopKey(it.url!!)] ?: 0) == 0 && !it.raw.disabled && UrlSafety.loopKey(it.url!!) !in confirmedKeys &&
                !(onViewPage && it.linkClass == LinkClass.FILE_VIEW_PAGE)
        }
        var next = unvisited.firstOrNull { it.score >= limits.autoScoreThreshold }
        var tag = ""
        if (next == null && lastIntermediate) {
            // Página intermediária (poucos links / "aguarde"): segue o link de etapa (continuar/próximo/download).
            // Domínio desconhecido continua passando pela confirmação humana em follow()/ask().
            next = unvisited.filter { it.raw.visible && isStepLike(it) && it.score >= limits.tier2MinScore }
                .maxWithOrNull(compareBy<ScoredCandidate>({ if (it.trusted) 1 else 0 }, { it.score }))
            if (next != null) tag = "página intermediária: "
        }
        if (next != null) {
            if (state == EngineState.WAITING_CLICK) resumeFromClick("apareceu um link seguro para seguir")
            follow(next, manual = false, tag)
            return
        }

        // Botões sem URL (acionados por JavaScript): clique automático só se a intenção for inequívoca.
        val eligible = lastScored.filter { DownloadHeuristics.isAutoClickEligible(it, limits.tier2MinScore) }
        if (state == EngineState.WAITING_CLICK) {
            val t = clickTarget
            val stillThere = if (t != null) eligible.any { it.raw.text == t.raw.text && it.raw.tag == t.raw.tag } else eligible.size > 1
            if (stillThere) return // continua aguardando o toque humano
            if (expectTab) return  // esperava uma NOVA GUIA: mudança no DOM sozinha não prova que ela abriu
            resumeFromClick("a página mudou (o botão não está mais disponível)")
        }
        val clickable = eligible.filter { clickKey(it) !in clickedKeys }
        if (clickable.size == 1 && pendingClick == null) {
            val c = clickable[0]
            if (lastOpensWindows || c.raw.opensTab) {
                // window.open exige gesto humano real: um clique programático seria bloqueado. Não tenta.
                clickedKeys += clickKey(c)
                humanClick(c, "este botão abre uma nova guia (window.open): o navegador exige um gesto humano real", opensTab = true)
                return
            }
            if (autoClicks < limits.maxAutoClicks) doAutoClick(clickable[0])
            else humanClick(clickable[0], "limite de ${limits.maxAutoClicks} cliques automáticos")
            return
        }
        if (clickable.size > 1) { humanClick(null, "ambíguo"); return }
        if (pendingClick != null) return // aguardando o efeito do clique automático

        val selfKey = UrlSafety.loopKey(lastScanUrl)
        val revisit = usable.filter {
            (visits[UrlSafety.loopKey(it.url!!)] ?: 0) > 0 && UrlSafety.loopKey(it.url!!) != selfKey &&   // link para a própria página não é loop
                !(onViewPage && it.linkClass == LinkClass.FILE_VIEW_PAGE) &&
                (it.score >= limits.autoScoreThreshold || (lastIntermediate && isStepLike(it) && it.score >= limits.tier2MinScore))
        }
        if (revisit.isNotEmpty()) {
            step(StepKind.BLOCKED, revisit.first().url, "loop: o único caminho leva a página já visitada")
            if (primaryResult?.let { isConfirmed(it) } == true && !inResume) return   // resultado confirmado nunca é substituído
            finish(ResultState.LOOP_DETECTED, null, "Loop de navegação detectado: ${pathSummary()} → ${UrlSafety.host(revisit.first().url!!) ?: "?"} (já visitada)")
            return
        }

        // Temporizador legítimo / botão ainda desabilitado: aguarda sem mexer em relógios nem scripts do site.
        val waiting = lastWaitHint || lastCountdown > 0 || lastScored.any { it.raw.disabled && !it.ad && isStepLike(it) }
        if (waiting) {
            if (pageWaitStart == 0L) pageWaitStart = clock()
            if (clock() - pageWaitStart > limits.maxPageWaitMs) {
                finishWithBest("Tempo de espera do temporizador excedido (${limits.maxPageWaitMs / 1000}s)")
                return
            }
            val delay = if (lastCountdown > 0) (lastCountdown * 1000L + 700).coerceIn(1500, 5000) else 3000L
            step(StepKind.SCAN, lastScanUrl.ifEmpty { null }, "aguardando temporizador/liberação do botão" + (if (lastCountdown > 0) " (${lastCountdown}s)" else "") + "; nova verificação em ${delay / 1000}s")
            listener.requestRescan(workTab, delay)
            return
        }

        scanAttempts++
        if (scanAttempts < limits.maxScanAttempts) {
            listener.requestRescan(workTab, 2000)
        } else {
            finishWithBest(
                if (path.count { it.kind != PathKind.FILE } > 1)
                    "Página intermediária sem link válido (${pathSummary()})"
                else "Nenhum candidato confiável de download encontrado nesta página"
            )
        }
    }

    /** Seguimento solicitado explicitamente pelo usuário (ignora o limiar de pontuação). */
    fun manualFollow(c: ScoredCandidate) {
        if (!isActive || state == EngineState.WAITING_CONFIRMATION || probingUrl != null) return
        if (c.url == null || !c.safe || c.ad) {
            step(StepKind.BLOCKED, c.url, "candidato inseguro ou de anúncio não pode ser seguido")
            return
        }
        follow(c, manual = true, "")
    }

    private fun follow(c: ScoredCandidate, manual: Boolean, tag: String) {
        val url = c.url!!
        if (depth >= limits.maxDepth) {
            finishWithBest("Profundidade máxima (${limits.maxDepth}) atingida")
            return
        }
        val host = UrlSafety.host(url)!!
        if (!policy.isTrusted(host)) {
            if (policy.domains.size >= limits.maxDomains) {
                finish(ResultState.BLOCKED, null, "Limite de domínios atingido ao tentar seguir para $host")
                return
            }
            ask(Pending(url, host, PendingSource.AUTO, false, c, tabId = workTab), "candidato (${c.reasons.joinToString(", ")})")
            return
        }
        if (path.count { it.kind != PathKind.FILE } >= limits.maxPages) {
            finishWithBest("Limite de ${limits.maxPages} páginas/etapas atingido")
            return
        }
        if (!registerVisit(url)) return
        depth++
        val why = describeScore(c)
        setDecision("${if (manual) "usuário escolheu" else "seguiu automaticamente"} «${c.raw.text.take(40)}» (${c.linkClass.label}; $why)")
        addPath(PathKind.PAGE, url, "${tag}${if (manual) "escolha manual" else "decisão automática"}: $why", c.linkClass)
        beginStep(url, c, "$tag${if (manual) "manual" else "auto"} etapa $depth/${limits.maxDepth}; $why")
    }

    /** Todo candidato seguido é verificado por HEAD/Range antes de navegar (revela arquivo, página e códigos 3xx). */
    private fun isProbable(c: ScoredCandidate?): Boolean = c?.url != null

    private fun beginStep(url: String, c: ScoredCandidate?, note: String) {
        redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
        followedUrl = url
        mainFrameError = false
        pageScanCounted = false
        candidateStatus[UrlSafety.loopKey(url)] = "seguido"
        step(StepKind.FOLLOW, url, note)
        val key = UrlSafety.loopKey(url)
        if (isProbable(c) && probed.add(key)) {
            probingUrl = url
            probingCandidate = c
            candidateStatus[key] = "verificando metadados"
            step(StepKind.SCAN, url, "verificando destino via HEAD/Range 0-0 (sem baixar; registra redirecionamentos 3xx)")
            listener.requestProbe(url, policy.domains + probeExtra)
        } else {
            listener.navigate(workTab, url)
        }
    }

    // ------------------------------------------------------------------ confirmação de domínio

    private fun ask(p: Pending, reason: String) {
        pending = p
        beginPause()
        step(StepKind.CONFIRM, p.url, "aguardando confirmação para domínio desconhecido ${p.host} ($reason)")
        setState(EngineState.WAITING_CONFIRMATION, "Confirmar navegação para ${p.host}?")
        listener.askDomain(p.host, UrlSafety.redact(p.url), reason)
    }

    fun answerDomain(allow: Boolean, rememberDomain: Boolean) {
        val p = pending ?: return
        if (state != EngineState.WAITING_CONFIRMATION) return
        pending = null
        endPause()
        if (p.source == PendingSource.PROBE) {
            val origin = p.origin!!
            if (allow) {
                if (rememberDomain) policy.trust(p.host) else probeExtra += DomainPolicy.registrable(p.host)
                step(StepKind.CONFIRM, origin, "usuário PERMITIU ${p.host} para a validação${if (rememberDomain) " (domínio lembrado)" else " (apenas desta vez)"}")
                setState(EngineState.RUNNING, "Validando arquivo via ${p.host}")
                probingUrl = origin; probingCandidate = p.candidate; stepStartedAt = clock()
                listener.requestProbe(origin, policy.domains + probeExtra)
            } else {
                step(StepKind.CONFIRM, origin, "usuário NEGOU ${p.host}")
                candidateStatus[UrlSafety.loopKey(origin)] = "não verificado (domínio recusado)"
                finish(ResultState.UNVERIFIED_CANDIDATE, origin, "$UNVERIFIED Redirecionamento para ${p.host} recusado por você.")
            }
            return
        }
        if (allow) {
            if (rememberDomain) policy.trust(p.host)
            step(StepKind.CONFIRM, p.url, "usuário PERMITIU ${p.host}${if (rememberDomain) " (domínio lembrado)" else " (apenas desta vez)"}")
            setState(EngineState.RUNNING, "Seguindo para ${p.host}")
            if (!registerVisit(p.url)) return
            if (p.source == PendingSource.AUTO) {
                depth++
                if (depth > limits.maxDepth) { finishWithBest("Profundidade máxima atingida"); return }
                // "Só desta vez": sem sondagem (ela exige domínio confiável); navega direto.
                setDecision("domínio ${p.host} confirmado pelo usuário; seguiu «${p.candidate?.raw?.text?.take(40) ?: "?"}»")
                addPath(PathKind.PAGE, p.url, "decisão automática após confirmação humana do domínio ${p.host}", p.candidate?.linkClass ?: LinkClass.PAGE)
                beginStep(p.url, if (rememberDomain) p.candidate else null,
                    "auto (domínio confirmado) etapa $depth/${limits.maxDepth}" + (p.candidate?.let { "; ${describeScore(it)}" } ?: ""))
            } else {
                redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
                followedUrl = p.url; mainFrameError = false
                listener.navigate(p.tabId, p.url)
            }
        } else {
            step(StepKind.CONFIRM, p.url, "usuário NEGOU ${p.host}")
            rejected += UrlSafety.loopKey(p.url)
            candidateStatus[UrlSafety.loopKey(p.url)] = "domínio recusado"
            listener.onNavigationDenied(p.tabId, p.url)
            if (p.redirect) {
                finish(ResultState.BLOCKED, null, "Redirecionamento para domínio não autorizado (${p.host}) recusado")
            } else {
                stepStartedAt = clock()
                setState(EngineState.RUNNING, "Domínio recusado; avaliando outros candidatos")
                if (p.source == PendingSource.AUTO) chooseAndFollow()
            }
        }
    }

    // ------------------------------------------------------------------ tempo

    /** Chamar ~1x por segundo. */
    fun tick() {
        if (!isActive) return
        val now = clock()
        when (state) {
            EngineState.WAITING_HUMAN, EngineState.WAITING_CLICK -> if (now - pauseStart > limits.maxHumanWaitMs) {
                finish(ResultState.BLOCKED, null, "Tempo de espera pela interação humana esgotado")
            }
            EngineState.WAITING_CONFIRMATION -> Unit
            EngineState.RUNNING -> {
                pendingClick?.let { pc ->
                    if (now - pc.at > limits.clickEffectWaitMs) {
                        pendingClick = null
                        humanClick(pc.c, "o clique automático não teve efeito; o site pode exigir um gesto humano real")
                        return
                    }
                }
                if (now - startedAt - pausedMs > limits.maxTotalMs) {
                    finishWithBest("Tempo total máximo (${limits.maxTotalMs / 1000}s) excedido")
                } else if (now - stepStartedAt > limits.maxStepMs) {
                    finishWithBest("Tempo máximo da etapa (${limits.maxStepMs / 1000}s) excedido")
                }
            }
            else -> Unit
        }
    }

    // ------------------------------------------------------------------ utilitários

    private fun registerVisit(url: String): Boolean {
        val key = UrlSafety.loopKey(url)
        if (key in confirmedKeys || key in mismatchKeys) return true // voltar a uma URL já confirmada (ou válida de conteúdo diferente) nunca é loop
        val n = (visits[key] ?: 0) + 1
        visits[key] = n
        val allowed = if (humanAuthHappened) limits.maxVisitsPerUrl + 1 else limits.maxVisitsPerUrl
        if (n > allowed) {
            step(StepKind.BLOCKED, url, "loop detectado (URL visitada $n vezes)")
            finish(ResultState.LOOP_DETECTED, null, "Loop de navegação detectado (${UrlSafety.host(url) ?: "?"} visitado $n vezes)")
            return false
        }
        return true
    }

    private fun beginPause() { if (pauseStart == 0L) pauseStart = clock() }
    private fun endPause() { if (pauseStart != 0L) { pausedMs += clock() - pauseStart; pauseStart = 0L } }

    private fun setState(s: EngineState, msg: String) {
        state = s
        listener.onStateChanged(s, msg)
    }

    private fun step(kind: StepKind, url: String?, note: String) {
        val st = Step(clock(), kind, url?.let { UrlSafety.redact(it) }, UrlSafety.scrubText(note))
        if (steps.size < limits.maxLogSteps) steps += st
        listener.onStep(st)
    }

    // ------------------------------------------------------------------ caminho / candidatos

    private fun addPath(kind: PathKind, url: String?, arrival: String, cls: LinkClass? = null, code: Int? = null, tabId: Int = workTab) {
        val shown = url?.let { UrlSafety.redact(it) }
        val key = url?.let { UrlSafety.loopKey(it) }
        if (kind != PathKind.PAGE && kind != PathKind.START && kind != PathKind.FILE && key != null && probeHopKeys.remove(key)) return // já registrado pela verificação OkHttp
        val last = path.lastOrNull()
        if (last != null && last.url == shown && last.kind == kind) return
        if (path.size >= 80) return
        path += PathEntry(path.size + 1, kind, shown, UrlSafety.scrubText(arrival), cls, null, code, tabId = tabId)
    }

    private fun setDecision(text: String) {
        val i = path.indexOfLast { it.kind != PathKind.FILE }
        if (i >= 0) {
            val old = path[i].decision
            val keep = old?.takeIf { it.startsWith("guia de trabalho") }   // não perde o motivo da promoção da guia
            path[i] = path[i].copy(decision = UrlSafety.scrubText(if (keep != null) "$keep → $text" else text))
        }
    }

    private fun updateCurrentPage(title: String) {
        val i = path.indexOfLast { it.kind != PathKind.FILE }
        if (i >= 0) path[i] = path[i].copy(title = title.take(80), linkClass = path[i].linkClass ?: LinkClass.PAGE)
    }

    private fun pathSummary(): String =
        path.filter { it.kind != PathKind.FILE }.joinToString(" → ") { entry -> entry.url?.let { UrlSafety.host(it) }?.let { h ->
            h + (UrlSafety.parse(entry.url!!)?.path?.takeIf { it.length > 1 }?.let { it.takeLast(24) } ?: "")
        } ?: "?" }

    private fun isConfirmed(r: ResolveResult) =
        (r.state == ResultState.VERIFIED_FILE || r.state == ResultState.REQUIRES_SESSION) && r.evidence.isNotEmpty()

    /** Resultado principal (o primeiro; arquivo confirmado nunca é substituído) e retomadas posteriores. */
    val results: List<ResolveResult> get() = listOfNotNull(primaryResult) + resumeResults

    private fun allCandsSorted(): List<ScoredCandidate> = allCands.values.sortedByDescending { it.score }

    /**
     * Encerra SEM confirmação de arquivo, diferenciando: erro de rede (candidato preservado),
     * candidato não verificado (URL de arquivo), link intermediário (URL de página),
     * exige sessão, ou nenhum candidato.
     */
    private fun finishWithBest(reason: String) {
        val all = allCandsSorted().filter { it.safe && !it.ad && it.url != null && UrlSafety.loopKey(it.url!!) !in mismatchKeys }
        val file = all.firstOrNull { it.linkClass == LinkClass.FILE_CANDIDATE && it.score > 0 }
        val page = all.firstOrNull {
            (it.linkClass == LinkClass.PAGE || it.linkClass == LinkClass.FILE_VIEW_PAGE) && it.score >= limits.tier2MinScore &&
                (visits[UrlSafety.loopKey(it.url!!)] ?: 0) == 0
        }
        val bestUrl = (file ?: page)?.url
        when {
            networkFailure != null -> finish(
                ResultState.NETWORK_ERROR, failedUrl ?: bestUrl,
                "$reason. Candidato e histórico preservados; o servidor pode recusar o WebView ou estar indisponível.",
                errorInfo = networkFailure,
            )
            sawHttpAuthError && bestUrl == null ->
                finish(ResultState.REQUIRES_SESSION, null, "$reason. O servidor respondeu 401/403: provável necessidade de sessão/login.")
            mismatches.isNotEmpty() || goal?.userSpecified == true || goal?.formats?.isNotEmpty() == true ->
                finish(
                    ResultState.TARGET_NOT_FOUND, (file ?: page)?.takeIf { it.relevance >= 0 }?.url,
                    "$reason. Arquivo desejado não encontrado" +
                        (if (mismatches.isNotEmpty()) ": ${mismatches.size} arquivo(s) válido(s) por HTTP tinham conteúdo diferente do objetivo (ver abaixo)" else "") +
                        ". Os melhores candidatos NÃO verificados estão na lista; $UNVERIFIED",
                )
            file != null ->
                finish(ResultState.UNVERIFIED_CANDIDATE, file.url, "$reason. URL com aparência de arquivo, mas os metadados NÃO foram confirmados. $UNVERIFIED")
            page != null ->
                finish(ResultState.INTERMEDIATE_LINK, page.url, "$reason. Melhor link encontrado (página intermediária, não confirmada como arquivo).")
            else -> finish(ResultState.NO_CANDIDATE, null, reason)
        }
    }

    private fun summaries(): List<CandidateSummary> = allCandsSorted().take(40).map {
        val key = it.url?.let { u -> UrlSafety.loopKey(u) }
        val confirmed = key?.let { k -> candidateStatus[k] } == "arquivo confirmado"
        val status = key?.let { k -> candidateStatus[k] }
            ?: when {
                it.ad -> "anúncio (ignorado)"
                !it.safe -> "inseguro (ignorado)"
                key != null && (visits[key] ?: 0) > 0 -> "página visitada"
                it.linkClass == LinkClass.FILE_CANDIDATE -> "candidato de download — não verificado"
                it.linkClass == LinkClass.FILE_VIEW_PAGE -> "página de visualização (GitHub /blob/): ainda sem o link Raw"
                it.score < limits.autoScoreThreshold -> "não seguido (pontuação baixa)"
                else -> "não seguido"
            }
        CandidateSummary(
            it.url?.let { u -> UrlSafety.redact(u) } ?: "(sem URL)", it.raw.text, it.score, status,
            url = it.url, kind = when {
                key != null && key in mismatchKeys -> LinkClass.WRONG_CONTENT
                confirmed -> LinkClass.CONFIRMED_FILE
                else -> it.linkClass
            },
        )
    }

    private fun finish(
        rs: ResultState, url: String?, message: String,
        mime: String? = null, name: String? = null, size: Long? = null, errorInfo: String? = null,
    ) {
        if (state == EngineState.FINISHED) return
        val prim = primaryResult
        if (prim != null && isConfirmed(prim) && !inResume) return // arquivo confirmado: nenhum evento posterior o substitui
        endPause()
        probingUrl?.let { u ->   // verificação interrompida: o candidato volta a ser "não visitado" (permite retomar)
            val k = UrlSafety.loopKey(u); visits.remove(k); probed.remove(k)
        }
        probingUrl = null; probingCandidate = null; pendingClick = null; clickTarget = null
        candidateStatus.replaceAll { _, v -> if (v == "verificando metadados") "verificação interrompida (não verificado)" else v }
        val scoreOfUrl = url?.let { u -> allCands[UrlSafety.loopKey(u)]?.score }
        step(StepKind.END, url, "${rs.label}: $message")
        val result = ResolveResult(
            state = rs,
            url = url,
            displayUrl = url?.let { UrlSafety.redact(it) },
            host = url?.let { UrlSafety.host(it) },
            mimeType = mime,
            fileName = name ?: url?.let { DownloadHeuristics.estimateFileName(it, null) },
            sizeBytes = size,
            message = message,
            steps = steps.toList(),
            urlHasSensitiveParams = url?.let { UrlSafety.hasSensitiveParams(it) } ?: false,
            candidateScore = scoreOfUrl,
            candidates = summaries(),
            evidence = evidence.toList(),
            diagnostics = diagnostics.toList(),
            errorInfo = errorInfo,
            path = path.toList(),
            isResume = false,
            goal = goal?.takeIf { it.informative }?.describe(),
            mismatches = mismatches.toList(),
        )
        // Retomada explícita: se já havia arquivo confirmado, o novo resultado é apresentado SEPARADAMENTE.
        val asExtra = inResume && prim != null && isConfirmed(prim)
        val published = if (inResume) result.copy(isResume = asExtra, resumeIndex = manualResumes) else result
        if (asExtra) resumeResults += published else { primaryResult = published; lastResult = published }
        inResume = false; expectTab = false
        finishedAt = clock()
        setState(EngineState.FINISHED, rs.label)
        listener.onResult(published)
    }
}
