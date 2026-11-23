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

    private enum class PendingSource { AUTO, NAVIGATION }
    private data class Pending(
        val url: String, val host: String, val source: PendingSource, val redirect: Boolean,
        val candidate: ScoredCandidate?,
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
    private var bestCandidate: ScoredCandidate? = null
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
    private var finishedAt = 0L

    val isActive: Boolean get() = state != EngineState.IDLE && state != EngineState.FINISHED
    val currentDepth: Int get() = depth

    companion object {
        fun isErrorUrl(url: String?): Boolean =
            url != null && (url.startsWith("chrome-error:") || url.startsWith("about:neterror") || url.startsWith("data:text/html,chromewebdata"))
        private const val LATE_DOWNLOAD_WINDOW_MS = 30_000L
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
        pending = null; lastScored = emptyList(); bestCandidate = null
        humanAuthHappened = false; sawHttpAuthError = false
        startUrl = null; followedUrl = null; probingUrl = null; probingCandidate = null
        mainFrameError = false; networkFailure = null; failedUrl = null
        lastResult = null; finishedAt = 0
    }

    // ------------------------------------------------------------------ eventos de navegação

    /**
     * Chamado para cada navegação de quadro principal (links, redirecionamentos, popups).
     * ALLOW = deixar carregar; BLOCK = cancelar; ASK = cancelar e aguardar confirmação do usuário.
     */
    fun onNavigationRequest(url: String, redirect: Boolean): NavDecision {
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
        step(if (redirect) StepKind.REDIRECT else StepKind.NAVIGATE, url, if (redirect) "redirecionamento" else "navegação")
        return NavDecision.ALLOW
    }

    fun onPageStarted(url: String) {
        if (isErrorUrl(url)) { step(StepKind.PAGE, url, "página interna de erro do navegador (ignorada)"); return }
        mainFrameError = false
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
    fun onProbeResult(url: String, r: ProbeResult) {
        val pu = probingUrl
        if (!isActive || pu == null || UrlSafety.loopKey(url) != UrlSafety.loopKey(pu)) return
        probingUrl = null
        val c = probingCandidate; probingCandidate = null
        val key = UrlSafety.loopKey(url)
        when (r) {
            is ProbeResult.File -> {
                val line = "${r.method} ${r.status}: mime=${r.mimeType ?: "?"} tamanho=${DownloadHeuristics.formatSize(r.contentLength)}" +
                    (if (r.acceptRanges) " range=sim" else "")
                step(StepKind.SCAN, url, "sondagem confirmou arquivo — $line")
                evidence += line
                candidateStatus[key] = "arquivo confirmado"
                confirmFile(
                    r.finalUrl, r.mimeType, DownloadHeuristics.estimateFileName(r.finalUrl, r.contentDisposition)
                        ?: DownloadHeuristics.estimateFileName(url, null),
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
            is ProbeResult.HttpError -> {
                if (r.status == 401 || r.status == 403) sawHttpAuthError = true
                val d = "Sondagem HTTP ${r.status}"
                diagnostics += d
                step(StepKind.ERROR, url, "$d; tentando pelo navegador (pode ter sessão/cookies)")
                navigateAfterProbe(url)
            }
            is ProbeResult.NetworkError -> {
                val d = "Sondagem sem resposta: ${UrlSafety.scrubText(r.message)}"
                diagnostics += d
                step(StepKind.ERROR, url, "$d; tentando pelo navegador")
                navigateAfterProbe(url)
            }
            is ProbeResult.Inconclusive -> {
                diagnostics += "Sondagem inconclusiva: ${r.reason}"
                step(StepKind.SCAN, url, "sondagem inconclusiva: ${r.reason}; tentando pelo navegador")
                navigateAfterProbe(url)
            }
        }
    }

    private fun navigateAfterProbe(url: String) {
        stepStartedAt = clock()
        listener.navigate(url)
    }

    private fun confirmFile(url: String, mime: String?, name: String?, size: Long?, how: String) {
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
        listener.onCandidates(scored)
        scored.firstOrNull { it.safe && !it.ad && it.url != null && it.score > 0 }?.let {
            val b = bestCandidate
            if (b == null || it.score > b.score) bestCandidate = it
        }
        step(StepKind.SCAN, scan.url, "${scored.size} candidato(s); melhor pontuação=${scored.firstOrNull()?.score ?: "-"}")
        chooseAndFollow()
    }

    private fun chooseAndFollow() {
        val next = lastScored.firstOrNull {
            it.safe && !it.ad && it.url != null && it.score >= limits.autoScoreThreshold &&
                UrlSafety.loopKey(it.url!!) !in rejected && (visits[UrlSafety.loopKey(it.url!!)] ?: 0) == 0
        }
        if (next == null) {
            scanAttempts++
            if (scanAttempts < limits.maxScanAttempts) {
                listener.requestRescan(2000)
            } else {
                finishWithBest("Nenhum candidato confiável de download encontrado nesta página")
            }
            return
        }
        follow(next, manual = false)
    }

    /** Seguimento solicitado explicitamente pelo usuário (ignora o limiar de pontuação). */
    fun manualFollow(c: ScoredCandidate) {
        if (!isActive || state == EngineState.WAITING_CONFIRMATION || probingUrl != null) return
        if (c.url == null || !c.safe || c.ad) {
            step(StepKind.BLOCKED, c.url, "candidato inseguro ou de anúncio não pode ser seguido")
            return
        }
        follow(c, manual = true)
    }

    private fun follow(c: ScoredCandidate, manual: Boolean) {
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
        if (!registerVisit(url)) return
        depth++
        beginStep(url, c, "${if (manual) "manual" else "auto"} etapa $depth/${limits.maxDepth}; pontuação=${c.score}; ${c.reasons.joinToString(", ")}")
    }

    /** Candidato com cara de arquivo é validado por HEAD/Range antes de navegar. */
    private fun isProbable(c: ScoredCandidate?): Boolean {
        val u = c?.url ?: return false
        return DownloadHeuristics.looksLikeFileUrl(u) || c.raw.downloadAttr
    }

    private fun beginStep(url: String, c: ScoredCandidate?, note: String) {
        redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
        followedUrl = url
        mainFrameError = false
        candidateStatus[UrlSafety.loopKey(url)] = "seguido"
        step(StepKind.FOLLOW, url, note)
        val key = UrlSafety.loopKey(url)
        if (isProbable(c) && probed.add(key)) {
            probingUrl = url
            probingCandidate = c
            candidateStatus[key] = "verificando metadados"
            step(StepKind.SCAN, url, "URL provável de arquivo: validando via HEAD/Range 0-0 (sem baixar)")
            listener.requestProbe(url, policy.domains.toSet())
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
        if (allow) {
            if (rememberDomain) policy.trust(p.host)
            step(StepKind.CONFIRM, p.url, "usuário PERMITIU ${p.host}${if (rememberDomain) " (domínio lembrado)" else " (apenas desta vez)"}")
            setState(EngineState.RUNNING, "Seguindo para ${p.host}")
            if (!registerVisit(p.url)) return
            if (p.source == PendingSource.AUTO) {
                depth++
                if (depth > limits.maxDepth) { finishWithBest("Profundidade máxima atingida"); return }
                // "Só desta vez": sem sondagem (ela exige domínio confiável); navega direto.
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

    /**
     * Encerra SEM confirmação de arquivo, diferenciando: erro de rede (candidato preservado),
     * candidato não verificado (URL de arquivo), link intermediário (URL de página),
     * exige sessão, ou nenhum candidato.
     */
    private fun finishWithBest(reason: String) {
        val best = bestCandidate
        val bestUrl = best?.url
        when {
            networkFailure != null -> finish(
                ResultState.NETWORK_ERROR, failedUrl ?: bestUrl,
                "$reason. Candidato e histórico preservados; o servidor pode recusar o WebView ou estar indisponível.",
                errorInfo = networkFailure,
            )
            sawHttpAuthError && bestUrl == null ->
                finish(ResultState.REQUIRES_SESSION, null, "$reason. O servidor respondeu 401/403: provável necessidade de sessão/login.")
            bestUrl != null && (DownloadHeuristics.looksLikeFileUrl(bestUrl) || best.raw.downloadAttr) ->
                finish(ResultState.UNVERIFIED_CANDIDATE, bestUrl, "$reason. URL com aparência de arquivo, mas os metadados NÃO foram confirmados.")
            bestUrl != null ->
                finish(ResultState.INTERMEDIATE_LINK, bestUrl, "$reason. Melhor link encontrado (página intermediária, não confirmada como arquivo).")
            else -> finish(ResultState.NO_CANDIDATE, null, reason)
        }
    }

    private fun summaries(): List<CandidateSummary> = lastScored.take(15).map {
        val key = it.url?.let { u -> UrlSafety.loopKey(u) }
        val status = key?.let { k -> candidateStatus[k] }
            ?: when {
                it.ad -> "anúncio (ignorado)"
                !it.safe -> "inseguro (ignorado)"
                it.score < limits.autoScoreThreshold -> "não seguido (pontuação baixa)"
                else -> "não seguido"
            }
        CandidateSummary(it.url?.let { u -> UrlSafety.redact(u) } ?: "(sem URL)", it.raw.text, it.score, status)
    }

    private fun finish(
        rs: ResultState, url: String?, message: String,
        mime: String? = null, name: String? = null, size: Long? = null, errorInfo: String? = null,
    ) {
        if (state == EngineState.FINISHED) return
        endPause()
        probingUrl = null; probingCandidate = null
        val scoreOfUrl = url?.let { u -> lastScored.firstOrNull { it.url != null && UrlSafety.loopKey(it.url!!) == UrlSafety.loopKey(u) }?.score }
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
            candidateScore = scoreOfUrl ?: bestCandidate?.takeIf { it.url == url }?.score,
            candidates = summaries(),
            evidence = evidence.toList(),
            diagnostics = diagnostics.toList(),
            errorInfo = errorInfo,
        )
        lastResult = result
        finishedAt = clock()
        setState(EngineState.FINISHED, rs.label)
        listener.onResult(result)
    }
}
