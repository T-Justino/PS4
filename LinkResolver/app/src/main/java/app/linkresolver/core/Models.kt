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
    BLOCKED("Bloqueado"),
}

enum class EngineState { IDLE, RUNNING, WAITING_CONFIRMATION, WAITING_HUMAN, FINISHED }

enum class ChallengeKind(val label: String) {
    CAPTCHA("CAPTCHA"),
    BOT_CHECK("verificação anti-robô"),
    LOGIN("autenticação/login"),
}

enum class StepKind { START, NAVIGATE, REDIRECT, PAGE, SCAN, FOLLOW, POPUP, DOWNLOAD, CHALLENGE, RESUME, CONFIRM, BLOCKED, ERROR, END }

/** Limites do motor de navegação. */
data class Limits(
    val maxDepth: Int = 6,
    val maxTotalMs: Long = 180_000,
    val maxStepMs: Long = 45_000,
    val maxHumanWaitMs: Long = 10 * 60_000,
    val maxDomains: Int = 4,
    val maxVisitsPerUrl: Int = 3,
    val maxRedirectsPerStep: Int = 10,
    val maxScanAttempts: Int = 4,
    val autoScoreThreshold: Int = 40,
    val largeFileBytes: Long = 200L * 1024 * 1024,
    val maxLogSteps: Int = 500,
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
}

data class PageScan(
    val url: String,
    val title: String,
    val candidates: List<RawCandidate>,
    val challenge: ChallengeKind?,
    val challengeHint: String?,
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
)
