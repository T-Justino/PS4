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
        /** Carregar [url] (já validada) na aba de trabalho. */
        fun navigate(url: String)
        fun askDomain(host: String, url: String, reason: String)
        fun onStateChanged(state: EngineState, message: String)
        fun onStep(step: Step)
        fun onCandidates(candidates: List<ScoredCandidate>)
        fun onResult(result: ResolveResult)
        /** Pedir nova varredura da página ativa após [delayMs]. */
        fun requestRescan(delayMs: Long)
        /** Navegação pendente recusada pelo usuário (a UI pode fechar a aba de popup). */
        fun onNavigationDenied(url: String)
        /**
         * Validar metadados de [url] fora da thread principal (HEAD / Range 0-0, sem baixar) e responder
         * com [onProbeResult] na thread principal.
         */
        fun requestProbe(url: String, trustedDomains: Set<String>)
    }

    private enum class PendingSource { AUTO, NAVIGATION, PROBE }
    private data class Pending(
        val url: String, val host: String, val source: PendingSource, val redirect: Boolean,
        val candidate: ScoredCandidate?, val origin: String? = null,
    )

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

    val isActive: Boolean get() = state != EngineState.IDLE && state != EngineState.FINISHED
    val currentDepth: Int get() = depth

    companion object {
        fun isErrorUrl(url: String?): Boolean =
            url != null && (url.startsWith("chrome-error:") || url.startsWith("about:neterror") || url.startsWith("data:text/html,chromewebdata"))
        private const val LATE_DOWNLOAD_WINDOW_MS = 30_000L
        const val UNVERIFIED = "Link NÃO verificado — copie e teste manualmente."
    }

    // ------------------------------------------------------------------ início/fim

    fun start(rawUrl: String) {
        reset()
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
        listener.navigate(input)
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
    }

    // ------------------------------------------------------------------ eventos de navegação

    /**
     * Chamado para cada navegação de quadro principal (links, redirecionamentos, popups).
     * ALLOW = deixar carregar; BLOCK = cancelar; ASK = cancelar e aguardar confirmação do usuário.
     */
    fun onNavigationRequest(url: String, redirect: Boolean, userGesture: Boolean = false): NavDecision {
        if (url == "about:blank") return NavDecision.ALLOW
        val verdict = UrlSafety.check(url)
        if (verdict is UrlSafety.Verdict.Rejected) {
            step(StepKind.BLOCKED, url, verdict.reason)
            if (isActive && redirect) finish(ResultState.BLOCKED, null, "Redirecionamento bloqueado: ${verdict.reason}")
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
            ask(Pending(url, host, PendingSource.NAVIGATION, redirect, null), if (redirect) "redirecionamento" else "navegação")
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
        addPath(kind, url, arrival, LinkClass.PAGE)
        if (path.count { it.kind != PathKind.FILE } > limits.maxPages) {
            finish(ResultState.BLOCKED, null, "Limite de ${limits.maxPages} páginas/etapas atingido")
            return NavDecision.BLOCK
        }
        return NavDecision.ALLOW
    }

    fun onPageStarted(url: String) {
        if (isErrorUrl(url)) { step(StepKind.PAGE, url, "página interna de erro do navegador (ignorada)"); return }
        mainFrameError = false
        pageScanCounted = false
        step(StepKind.PAGE, url, "carregando")
    }

    fun onPageFinished(url: String) {
        if (isErrorUrl(url) || mainFrameError) {
            // onPageFinished também dispara depois de um erro: NÃO é sucesso e NÃO deve ser analisada.
            step(StepKind.PAGE, url, "encerrada com erro — não analisada")
            return
        }
        step(StepKind.PAGE, url, "carregada")
        if (state == EngineState.RUNNING) {
            scanAttempts = 0
            listener.requestRescan(1200)
        }
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
    fun onMainFrameError(url: String, code: Int, description: String) {
        if (!isActive) return
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
        evidence += "DownloadListener: ${info.mimeType ?: "mime desconhecido"}, ${DownloadHeuristics.formatSize(info.contentLength.takeIf { it > 0 })}"
        confirmFile(
            info.url, info.mimeType?.substringBefore(';')?.trim(),
            DownloadHeuristics.estimateFileName(info.url, info.contentDisposition),
            info.contentLength.takeIf { it > 0 }, "Arquivo identificado pelo DownloadListener.",
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
                step(StepKind.SCAN, url, "sondagem confirmou arquivo — $line")
                evidence += line
                candidateStatus[key] = "arquivo confirmado"
                confirmFile(
                    r.finalUrl, r.mimeType,
                    DownloadHeuristics.estimateFileName(r.finalUrl, r.contentDisposition) ?: DownloadHeuristics.estimateFileName(url, null),
                    r.contentLength, "Metadados confirmados por ${r.method} (sem baixar o corpo).",
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
        listener.navigate(url)
    }

    private fun confirmFile(url: String, mime: String?, name: String?, size: Long?, how: String) {
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

    // ------------------------------------------------------------------ varredura

    fun onScan(scan: PageScan) {
        if (state != EngineState.RUNNING && state != EngineState.WAITING_HUMAN) return
        if (probingUrl != null) return // etapa em andamento (verificação de rede em curso): varredura duplicada é ignorada
        if (isErrorUrl(scan.url) || mainFrameError) {
            step(StepKind.SCAN, scan.url, "varredura ignorada: página de erro")
            return
        }

        if (scan.challenge != null) {
            if (state != EngineState.WAITING_HUMAN) {
                if (scan.challenge == ChallengeKind.LOGIN) humanAuthHappened = true
                beginPause()
                step(StepKind.CHALLENGE, scan.url, "${scan.challenge.label} detectado (${scan.challengeHint ?: "-"}) — automação pausada")
                setState(
                    EngineState.WAITING_HUMAN,
                    "${scan.challenge.label}: resolva manualmente na página. A automação retoma sozinha quando o desafio sumir.",
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
        val scored = scan.candidates
            .map { DownloadHeuristics.score(it, pageHost, policy) }
            .sortedByDescending { it.score }
        lastScored = scored
        lastWaitHint = scan.waitHint
        lastIntermediate = scan.waitHint ||
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
        step(StepKind.SCAN, scan.url, "${scored.size} candidato(s); melhor pontuação=${scored.firstOrNull()?.score ?: "-"}" +
            (if (lastIntermediate) "; página intermediária" else "") + (if (scan.waitHint) "; indica espera/contagem" else ""))

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

    private fun isStepLike(c: ScoredCandidate) =
        c.raw.source == "meta-refresh" || c.raw.source == "js-redirect" || DownloadHeuristics.isStepText(c.raw.text)

    private fun chooseAndFollow() {
        val usable = lastScored.filter {
            it.safe && !it.ad && it.url != null && UrlSafety.loopKey(it.url!!) !in rejected
        }
        val unvisited = usable.filter { (visits[UrlSafety.loopKey(it.url!!)] ?: 0) == 0 }
        var next = unvisited.firstOrNull { it.score >= limits.autoScoreThreshold }
        var tag = ""
        if (next == null && lastIntermediate) {
            // Página intermediária (poucos links / "aguarde"): segue o link de etapa (continuar/próximo/download).
            // Domínio desconhecido continua passando pela confirmação humana em follow()/ask().
            next = unvisited.filter { it.raw.visible && isStepLike(it) && it.score >= limits.tier2MinScore }
                .maxWithOrNull(compareBy<ScoredCandidate>({ if (it.trusted) 1 else 0 }, { it.score }))
            if (next != null) tag = "página intermediária: "
        }
        if (next == null) {
            val revisit = usable.filter {
                (visits[UrlSafety.loopKey(it.url!!)] ?: 0) > 0 &&
                    (it.score >= limits.autoScoreThreshold || (lastIntermediate && isStepLike(it) && it.score >= limits.tier2MinScore))
            }
            if (revisit.isNotEmpty()) {
                step(StepKind.BLOCKED, revisit.first().url, "loop: o único caminho leva a página já visitada")
                finish(ResultState.BLOCKED, null, "Loop de navegação detectado: ${pathSummary()} → ${UrlSafety.host(revisit.first().url!!) ?: "?"} (já visitada)")
                return
            }
            scanAttempts++
            val maxAttempts = limits.maxScanAttempts + if (lastWaitHint) 3 else 0
            if (scanAttempts < maxAttempts) {
                listener.requestRescan(if (lastWaitHint) 3000 else 2000)
            } else {
                finishWithBest(
                    if (path.count { it.kind != PathKind.FILE } > 1)
                        "Página intermediária sem link válido (${pathSummary()})"
                    else "Nenhum candidato confiável de download encontrado nesta página"
                )
            }
            return
        }
        follow(next, manual = false, tag)
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
            ask(Pending(url, host, PendingSource.AUTO, false, c), "candidato (${c.reasons.joinToString(", ")})")
            return
        }
        if (path.count { it.kind != PathKind.FILE } >= limits.maxPages) {
            finishWithBest("Limite de ${limits.maxPages} páginas/etapas atingido")
            return
        }
        if (!registerVisit(url)) return
        depth++
        val why = "pontuação ${c.score}: ${c.reasons.joinToString(", ")}"
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
            listener.navigate(url)
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
                beginStep(p.url, if (rememberDomain) p.candidate else null, "auto (domínio confirmado) etapa $depth/${limits.maxDepth}")
            } else {
                redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
                followedUrl = p.url; mainFrameError = false
                listener.navigate(p.url)
            }
        } else {
            step(StepKind.CONFIRM, p.url, "usuário NEGOU ${p.host}")
            rejected += UrlSafety.loopKey(p.url)
            candidateStatus[UrlSafety.loopKey(p.url)] = "domínio recusado"
            listener.onNavigationDenied(p.url)
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
            EngineState.WAITING_HUMAN -> if (now - pauseStart > limits.maxHumanWaitMs) {
                finish(ResultState.BLOCKED, null, "Tempo de espera pela interação humana esgotado")
            }
            EngineState.WAITING_CONFIRMATION -> Unit
            EngineState.RUNNING -> {
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
        val n = (visits[key] ?: 0) + 1
        visits[key] = n
        val allowed = if (humanAuthHappened) limits.maxVisitsPerUrl + 1 else limits.maxVisitsPerUrl
        if (n > allowed) {
            step(StepKind.BLOCKED, url, "loop detectado (URL visitada $n vezes)")
            finish(ResultState.BLOCKED, null, "Loop de navegação detectado")
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

    private fun addPath(kind: PathKind, url: String?, arrival: String, cls: LinkClass? = null, code: Int? = null) {
        val shown = url?.let { UrlSafety.redact(it) }
        val key = url?.let { UrlSafety.loopKey(it) }
        if (kind != PathKind.PAGE && kind != PathKind.START && kind != PathKind.FILE && key != null && probeHopKeys.remove(key)) return // já registrado pela verificação OkHttp
        val last = path.lastOrNull()
        if (last != null && last.url == shown && last.kind == kind) return
        if (path.size >= 80) return
        path += PathEntry(path.size + 1, kind, shown, UrlSafety.scrubText(arrival), cls, null, code)
    }

    private fun setDecision(text: String) {
        val i = path.indexOfLast { it.kind != PathKind.FILE }
        if (i >= 0) path[i] = path[i].copy(decision = UrlSafety.scrubText(text))
    }

    private fun updateCurrentPage(title: String) {
        val i = path.indexOfLast { it.kind != PathKind.FILE }
        if (i >= 0) path[i] = path[i].copy(title = title.take(80), linkClass = path[i].linkClass ?: LinkClass.PAGE)
    }

    private fun pathSummary(): String =
        path.filter { it.kind != PathKind.FILE }.joinToString(" → ") { entry -> entry.url?.let { UrlSafety.host(it) }?.let { h ->
            h + (UrlSafety.parse(entry.url!!)?.path?.takeIf { it.length > 1 }?.let { it.takeLast(24) } ?: "")
        } ?: "?" }

    private fun allCandsSorted(): List<ScoredCandidate> = allCands.values.sortedByDescending { it.score }

    /**
     * Encerra SEM confirmação de arquivo, diferenciando: erro de rede (candidato preservado),
     * candidato não verificado (URL de arquivo), link intermediário (URL de página),
     * exige sessão, ou nenhum candidato.
     */
    private fun finishWithBest(reason: String) {
        val all = allCandsSorted().filter { it.safe && !it.ad && it.url != null }
        val file = all.firstOrNull { it.linkClass == LinkClass.FILE_CANDIDATE && it.score > 0 }
        val page = all.firstOrNull {
            it.linkClass == LinkClass.PAGE && it.score >= limits.tier2MinScore && (visits[UrlSafety.loopKey(it.url!!)] ?: 0) == 0
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
                it.score < limits.autoScoreThreshold -> "não seguido (pontuação baixa)"
                else -> "não seguido"
            }
        CandidateSummary(
            it.url?.let { u -> UrlSafety.redact(u) } ?: "(sem URL)", it.raw.text, it.score, status,
            url = it.url, kind = if (confirmed) LinkClass.CONFIRMED_FILE else it.linkClass,
        )
    }

    private fun finish(
        rs: ResultState, url: String?, message: String,
        mime: String? = null, name: String? = null, size: Long? = null, errorInfo: String? = null,
    ) {
        if (state == EngineState.FINISHED) return
        endPause()
        probingUrl = null; probingCandidate = null
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
        )
        lastResult = result
        finishedAt = clock()
        setState(EngineState.FINISHED, rs.label)
        listener.onResult(result)
    }
}
