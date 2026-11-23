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
    }

    private enum class PendingSource { AUTO, NAVIGATION }
    private data class Pending(val url: String, val host: String, val source: PendingSource, val redirect: Boolean)

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
    private var currentUrl: String? = null
    private val visits = HashMap<String, Int>()
    private val rejected = HashSet<String>()
    private var pending: Pending? = null
    private var lastScored: List<ScoredCandidate> = emptyList()
    private var bestCandidate: ScoredCandidate? = null
    private var humanAuthHappened = false
    private var sawHttpAuthError = false
    private var waitingChallenge: ChallengeKind? = null
    private var startUrl: String? = null

    val isActive: Boolean get() = state != EngineState.IDLE && state != EngineState.FINISHED
    val currentDepth: Int get() = depth

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
        policy.clear(); steps.clear(); visits.clear(); rejected.clear()
        depth = 0; redirectsInStep = 0; scanAttempts = 0; pausedMs = 0; pauseStart = 0
        pending = null; lastScored = emptyList(); bestCandidate = null
        humanAuthHappened = false; sawHttpAuthError = false; waitingChallenge = null
        currentUrl = null; startUrl = null
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
            ask(Pending(url, host, PendingSource.NAVIGATION, redirect), if (redirect) "redirecionamento" else "navegação")
            return NavDecision.ASK
        }
        if (!registerVisit(url)) return NavDecision.BLOCK
        step(if (redirect) StepKind.REDIRECT else StepKind.NAVIGATE, url, if (redirect) "redirecionamento" else "navegação")
        return NavDecision.ALLOW
    }

    fun onPageStarted(url: String) {
        currentUrl = url
        step(StepKind.PAGE, url, "carregando")
    }

    fun onPageFinished(url: String) {
        currentUrl = url
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
        if (code == 401 || code == 403) sawHttpAuthError = true
    }

    fun onPageError(url: String, description: String) {
        step(StepKind.ERROR, url, "erro de carregamento: $description")
    }

    fun onSafeBrowsingHit(url: String, threat: String) {
        step(StepKind.BLOCKED, url, "Safe Browsing: $threat")
        if (isActive) finish(ResultState.BLOCKED, null, "Bloqueado pelo Safe Browsing ($threat)")
    }

    // ------------------------------------------------------------------ download

    fun onDownload(info: DownloadInfo) {
        if (!isActive) return
        val verdict = UrlSafety.check(info.url)
        if (verdict is UrlSafety.Verdict.Rejected) {
            step(StepKind.BLOCKED, info.url, "download bloqueado: ${verdict.reason}")
            finish(ResultState.BLOCKED, null, "URL de download recusada: ${verdict.reason}")
            return
        }
        val isFile = DownloadHeuristics.isFileMime(info.mimeType) || DownloadHeuristics.isAttachment(info.contentDisposition)
        step(StepKind.DOWNLOAD, info.url, "mime=${info.mimeType ?: "?"} tamanho=${DownloadHeuristics.formatSize(info.contentLength.takeIf { it > 0 })}")
        if (!isFile) {
            step(StepKind.ERROR, info.url, "download ignorado: conteúdo parece página HTML")
            return
        }
        val name = DownloadHeuristics.estimateFileName(info.url, info.contentDisposition)
        val size = info.contentLength.takeIf { it > 0 }
        val large = size != null && size >= limits.largeFileBytes
        val needsSession = humanAuthHappened
        val msg = buildString {
            if (needsSession) append("Arquivo alcançado após autenticação manual: a URL provavelmente só funciona dentro desta sessão. ")
            else append("Arquivo identificado pelo DownloadListener. ")
            if (large) append("Arquivo grande: NADA foi baixado automaticamente. ")
            else append("Nada foi baixado pelo aplicativo. ")
        }.trim()
        finish(
            if (needsSession) ResultState.REQUIRES_SESSION else ResultState.VERIFIED_FILE,
            info.url, msg, info.mimeType?.substringBefore(';')?.trim(), name, size,
        )
    }

    // ------------------------------------------------------------------ varredura

    fun onScan(scan: PageScan) {
        if (state != EngineState.RUNNING && state != EngineState.WAITING_HUMAN) return

        if (scan.challenge != null) {
            if (state != EngineState.WAITING_HUMAN) {
                waitingChallenge = scan.challenge
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
            if (bestCandidate == null || it.score > bestCandidate!!.score) bestCandidate = it
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
        if (!isActive || state == EngineState.WAITING_CONFIRMATION) return
        if (c.url == null || !c.safe || c.ad) {
            step(StepKind.BLOCKED, c.url, "candidato inseguro ou de anúncio não pode ser seguido")
            return
        }
        follow(c, manual = true)
    }

    private fun follow(c: ScoredCandidate, manual: Boolean) {
        val url = c.url!!
        if (depth >= limits.maxDepth) {
            finishWithBest("Profundidade máxima (${limits.maxDepth}) atingida", ResultState.INTERMEDIATE_LINK)
            return
        }
        val host = UrlSafety.host(url)!!
        if (!policy.isTrusted(host)) {
            if (policy.domains.size >= limits.maxDomains) {
                finish(ResultState.BLOCKED, null, "Limite de domínios atingido ao tentar seguir para $host")
                return
            }
            ask(Pending(url, host, PendingSource.AUTO, false), "candidato (${c.reasons.joinToString(", ")})")
            return
        }
        if (!registerVisit(url)) return
        depth++
        redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
        step(StepKind.FOLLOW, url, "${if (manual) "manual" else "auto"} etapa $depth/${limits.maxDepth}; pontuação=${c.score}; ${c.reasons.joinToString(", ")}")
        listener.navigate(url)
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
            if (p.source == PendingSource.AUTO) depth++
            redirectsInStep = 0; scanAttempts = 0; stepStartedAt = clock()
            if (p.source == PendingSource.AUTO && depth > limits.maxDepth) {
                finishWithBest("Profundidade máxima atingida", ResultState.INTERMEDIATE_LINK); return
            }
            listener.navigate(p.url)
        } else {
            step(StepKind.CONFIRM, p.url, "usuário NEGOU ${p.host}")
            rejected += UrlSafety.loopKey(p.url)
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
        val st = Step(clock(), kind, url?.let { UrlSafety.redact(it) }, note)
        if (steps.size < limits.maxLogSteps) steps += st
        listener.onStep(st)
    }

    private fun finishWithBest(reason: String, state: ResultState = ResultState.INTERMEDIATE_LINK) {
        val best = bestCandidate
        if (sawHttpAuthError && best == null) {
            finish(ResultState.REQUIRES_SESSION, null, "$reason. O servidor respondeu 401/403: provável necessidade de sessão/login.")
        } else if (best?.url != null) {
            finish(state, best.url, "$reason. Melhor candidato encontrado (não confirmado como arquivo).")
        } else {
            finish(ResultState.BLOCKED, null, reason)
        }
    }

    private fun finish(
        rs: ResultState, url: String?, message: String,
        mime: String? = null, name: String? = null, size: Long? = null,
    ) {
        if (state == EngineState.FINISHED) return
        endPause()
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
        )
        step(StepKind.END, url, "${rs.label}: $message")
        setState(EngineState.FINISHED, rs.label)
        listener.onResult(result.copy(steps = steps.toList()))
    }
}
