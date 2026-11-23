package app.linkresolver.core

/** Estado final apresentado ao usuário. */
enum class ResultState(val label: String) {
    /** Metadados confirmados (HEAD/Range e/ou DownloadListener). */
    VERIFIED_FILE("Arquivo confirmado"),
    /** URL com cara de arquivo, mas sem confirmação de metadados. */
    UNVERIFIED_CANDIDATE("Candidato não verificado"),
    /** Link para outra página (precisa de mais etapas). */
    INTERMEDIATE_LINK("Link intermediário"),
    REQUIRES_SESSION("Exige sessão"),
    NETWORK_ERROR("Erro de rede"),
    NO_CANDIDATE("Nenhum candidato encontrado"),
    LOOP_DETECTED("Loop detectado"),
    BLOCKED("Bloqueado"),
}

/** WAITING_CLICK: a página exige um toque humano real (ou há vários botões ambíguos). */
enum class EngineState { IDLE, RUNNING, WAITING_CONFIRMATION, WAITING_HUMAN, WAITING_CLICK, FINISHED }

enum class ChallengeKind(val label: String) {
    CAPTCHA("CAPTCHA"),
    BOT_CHECK("verificação anti-robô"),
    LOGIN("autenticação/login"),
}

/** Classificação de um link na jornada. */
enum class LinkClass(val label: String) {
    PAGE("página intermediária"),
    FILE_CANDIDATE("candidato de download"),
    CONFIRMED_FILE("arquivo confirmado"),
}

enum class PathKind(val label: String) {
    START("INÍCIO"), PAGE("PÁGINA"), HTTP_REDIRECT("REDIRECIONAMENTO HTTP"), JS_REDIRECT("REDIRECIONAMENTO JS"),
    META_REFRESH("META REFRESH"), NAVIGATION("NAVEGAÇÃO"), NEW_TAB("NOVA GUIA"), CLICK("CLIQUE"), FILE("ARQUIVO"),
}

/** Um nó do caminho percorrido (página, salto de redirecionamento ou arquivo). */
data class PathEntry(
    val index: Int,
    val kind: PathKind,
    /** URL higienizada. */
    val url: String?,
    /** Como a automação/navegador chegou aqui. */
    val arrival: String,
    val linkClass: LinkClass?,
    /** Motivo da decisão automática tomada nesta página. */
    val decision: String?,
    val code: Int? = null,
    val title: String? = null,
    /** Guia (aba) onde ocorreu; 0 = guia principal. */
    val tabId: Int = 0,
) {
    fun format(): String = buildString {
        append(index).append(". [").append(kind.label).append(code?.let { " $it" } ?: "").append(if (tabId != 0) " · guia $tabId" else "").append("] ").append(url ?: "—")
        title?.takeIf { it.isNotBlank() }?.let { append("  «").append(it.take(60)).append("»") }
        append("\n     chegou por: ").append(arrival)
        linkClass?.let { append("\n     classe: ").append(it.label) }
        decision?.let { append("\n     decisão: ").append(it) }
    }
}

enum class StepKind { START, NAVIGATE, REDIRECT, PAGE, SCAN, FOLLOW, POPUP, TAB, CLICK, DOWNLOAD, CHALLENGE, RESUME, CONFIRM, BLOCKED, ERROR, END }

/** Limites do motor de navegação. */
data class Limits(
    val maxDepth: Int = 6,
    val maxTotalMs: Long = 180_000,
    val maxStepMs: Long = 45_000,
    val maxHumanWaitMs: Long = 10 * 60_000,
    val maxDomains: Int = 4,
    val maxVisitsPerUrl: Int = 2,
    val maxPages: Int = 15,
    val maxStagnantPages: Int = 2,
    val tier2MinScore: Int = 20,
    val maxIntermediateCandidates: Int = 10,
    val maxRedirectsPerStep: Int = 10,
    val maxScanAttempts: Int = 4,
    val autoScoreThreshold: Int = 40,
    val largeFileBytes: Long = 200L * 1024 * 1024,
    val maxLogSteps: Int = 500,
    // --- v0.4.0 ---
    val maxPopupsPerPage: Int = 3,
    val maxPopupsTotal: Int = 6,
    val maxScansPerPage: Int = 20,
    val minScanIntervalMs: Long = 1500,
    /** Tempo máximo esperando um temporizador/botão liberar numa mesma página. */
    val maxPageWaitMs: Long = 40_000,
    val maxAutoClicks: Int = 6,
    /** Quanto esperar por um efeito (navegação, nova guia, mudança no DOM) depois de um clique automático. */
    val clickEffectWaitMs: Long = 4_000,
    val maxManualResumes: Int = 5,
)

/** Elemento bruto encontrado pelo script de varredura da página. */
data class RawCandidate(
    val url: String?,
    val text: String,
    val tag: String,
    /** href, download-attr, data-attr, onclick, form, meta-refresh, button */
    val source: String,
    val downloadAttr: Boolean,
    val rel: String,
    val context: String,
    val elementId: String?,
    val visible: Boolean,
    /** Botão/link desabilitado (aguardando liberação). */
    val disabled: Boolean = false,
    /** Criado ou liberado depois do carregamento (MutationObserver). */
    val dynamic: Boolean = false,
    /** Abre nova guia (target=_blank / window.open). */
    val opensTab: Boolean = false,
)

data class ScoredCandidate(
    val raw: RawCandidate,
    val score: Int,
    val reasons: List<String>,
    /** URL passou nas verificações de segurança (esquema, host interno etc.). */
    val safe: Boolean,
    /** Domínio já confiável nesta sessão. */
    val trusted: Boolean,
    /** Rede de anúncios conhecida: nunca é seguido nem oferecido para confirmação. */
    val ad: Boolean,
) {
    val url: String? get() = raw.url
    /** Candidato de download (URL/atributo de arquivo) ou página intermediária. */
    val linkClass: LinkClass
        get() = if (url != null && (DownloadHeuristics.looksLikeFileUrl(url!!) || raw.downloadAttr)) LinkClass.FILE_CANDIDATE else LinkClass.PAGE
}

data class PageScan(
    val url: String,
    val title: String,
    val candidates: List<RawCandidate>,
    val challenge: ChallengeKind?,
    val challengeHint: String?,
    /** Página indica espera/contagem regressiva/geração de link. */
    val waitHint: Boolean = false,
    /** Texto/elementos típicos de propaganda (cassino, prêmio, VPN…). */
    val adLike: Boolean = false,
    /** Maior contagem regressiva visível (segundos); 0 = nenhuma. */
    val countdownSec: Int = 0,
)

data class DownloadInfo(
    val url: String,
    val mimeType: String?,
    val contentDisposition: String?,
    val contentLength: Long,
)

data class Step(
    val timeMs: Long,
    val kind: StepKind,
    /** URL já higienizada (sem credenciais/tokens). */
    val url: String?,
    val note: String,
)

data class CandidateSummary(
    val displayUrl: String,
    val text: String,
    val score: Int,
    val status: String,
    /** URL completa (para copiar). Nunca vai para logs. */
    val url: String? = null,
    val kind: LinkClass = LinkClass.PAGE,
)

data class ResolveResult(
    val state: ResultState,
    /** URL completa (pode conter token). Use [displayUrl] para exibição/logs. */
    val url: String?,
    val displayUrl: String?,
    val host: String?,
    val mimeType: String?,
    val fileName: String?,
    val sizeBytes: Long?,
    val message: String,
    val steps: List<Step>,
    val urlHasSensitiveParams: Boolean,
    val candidateScore: Int? = null,
    val candidates: List<CandidateSummary> = emptyList(),
    /** Evidências que sustentam o estado (ex.: "HEAD 200 …", "DownloadListener …"). */
    val evidence: List<String> = emptyList(),
    /** Diagnóstico de erros/sondagens, já higienizado. */
    val diagnostics: List<String> = emptyList(),
    val errorInfo: String? = null,
    val path: List<PathEntry> = emptyList(),
)
