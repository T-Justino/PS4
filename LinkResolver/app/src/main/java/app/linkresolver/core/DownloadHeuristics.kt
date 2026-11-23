package app.linkresolver.core

import java.util.Locale

/** Heurísticas puras de pontuação de candidatos e classificação de downloads. */
object DownloadHeuristics {

    val FILE_EXTENSIONS = setOf(
        "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "iso", "img", "bin",
        "pkg", "exe", "msi", "dmg", "apk", "aab", "deb", "rpm", "appimage", "jar",
        "pdf", "epub", "mobi", "djvu", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv",
        "mp3", "flac", "wav", "ogg", "mp4", "mkv", "avi", "mov", "webm",
        "part01", "001",
    )

    private val DOWNLOAD_WORDS = Regex(
        """(?i)\b(download|baixar|baixe|descargar|descarga|t[eé]l[eé]charger|herunterladen|scarica|get\s+(the\s+)?file|direct\s+link|link\s+direto|obter\s+link|get\s+link|gerar\s+link|generate\s+link|start\s+download|iniciar\s+download|free\s+download|download\s+now|baixar\s+agora)\b"""
    )
    private val STEP_WORDS = Regex(
        """(?i)\b(continue|continuar|prosseguir|proceed|next|pr[oó]ximo|continuar\s+para|click\s+here|clique\s+aqui|aqui|slow\s+download|download\s+lento|create\s+link|continuar\s+download|i\s+am\s+human)\b"""
    )
    private val NEGATIVE_WORDS = Regex(
        """(?i)\b(ad|ads|advert\w*|an[uú]ncio|publicidade|sponsor\w*|patrocin\w*|casino|bet|betting|bonus|b[oô]nus|premium|buy|comprar|subscribe|assine|install\s+now|update\s+now|vpn|cookie|facebook|twitter|instagram|telegram|whatsapp|share|compartilhar|report|denunciar|dmca|login|sign\s*up|register|cadastr\w*|win|prize|pr[eê]mio|sexy|dating|crypto|free\s+gift)\b"""
    )
    private val URL_HINT = Regex("""(?i)(download|/dl/|[?&]dl=|attachment|/file/|/files/|getfile|/get/|export=download)""")
    private val AD_CONTEXT = Regex("""(?i)(\bad\b|\bads\b|adv|banner|sponsor|popup|pop-up|promo|taboola|outbrain|advert|publicidade|patrocin)""")

    /** Hosts de redes de anúncios/redirecionadores de tráfego mais comuns. */
    private val AD_HOSTS = listOf(
        "doubleclick.net", "googlesyndication.com", "googleadservices.com", "adservice.google.com",
        "popads.net", "propellerads.com", "adsterra.com", "exoclick.com", "taboola.com", "outbrain.com",
        "onclickads.net", "clickadu.com", "juicyads.com", "trafficjunky.com", "mgid.com", "revcontent.com",
        "adcash.com", "bidvertiser.com", "popcash.net", "zeroredirect1.com", "hilltopads.net",
        "monetag.com", "a-ads.com", "adnxs.com", "criteo.com", "pubmatic.com", "rubiconproject.com",
    )

    fun isAdHost(host: String): Boolean {
        val h = host.lowercase()
        return AD_HOSTS.any { h == it || h.endsWith(".$it") }
    }

    fun extensionOf(url: String): String? {
        val p = UrlSafety.parse(url) ?: return null
        val last = UrlSafety.decode(p.path.substringAfterLast('/'))
        if (!last.contains('.')) return null
        return last.substringAfterLast('.').lowercase(Locale.ROOT).takeIf { it.length in 2..8 }
    }

    fun looksLikeFileUrl(url: String): Boolean = extensionOf(url) in FILE_EXTENSIONS

    fun score(raw: RawCandidate, pageHost: String, policy: DomainPolicy): ScoredCandidate {
        val reasons = mutableListOf<String>()
        var score = 0
        val url = raw.url
        var safe = false
        var ad = false
        var trusted = false
        var host: String? = null

        if (url != null) {
            safe = UrlSafety.check(url) is UrlSafety.Verdict.Ok
            host = UrlSafety.host(url)
            if (!safe) reasons += "URL insegura"
            if (host != null) {
                trusted = policy.isTrusted(host)
                if (isAdHost(host)) { ad = true; score -= 100; reasons += "rede de anúncios" }
                if (DomainPolicy.registrable(host) == DomainPolicy.registrable(pageHost)) { score += 10; reasons += "mesmo site" }
                else if (!trusted) { score -= 10; reasons += "domínio externo" }
            }
            if (looksLikeFileUrl(url)) { score += 60; reasons += "extensão de arquivo (.${extensionOf(url)})" }
            else if (URL_HINT.containsMatchIn(url)) { score += 15; reasons += "padrão de download na URL" }
        }
        if (raw.downloadAttr) { score += 50; reasons += "atributo download" }
        val text = raw.text.lowercase()
        if (DOWNLOAD_WORDS.containsMatchIn(text)) { score += 30; reasons += "texto de download" }
        else if (STEP_WORDS.containsMatchIn(text)) { score += 12; reasons += "texto de etapa" }
        if (NEGATIVE_WORDS.containsMatchIn(text)) { score -= 35; reasons += "texto suspeito/propaganda" }
        if (AD_CONTEXT.containsMatchIn(raw.context)) { score -= 50; reasons += "contexto de anúncio" }
        if (raw.rel.contains("sponsored") || raw.rel.contains("nofollow") && raw.rel.contains("noopener") && !raw.downloadAttr) {
            score -= 15; reasons += "rel patrocinado/nofollow"
        }
        if (raw.source == "data-attr" || raw.source == "onclick") { score += 5; reasons += "URL em atributo de script" }
        if (raw.source == "meta-refresh") { score += 55; reasons += "redirecionamento automático da página (meta refresh)" }
        if (raw.source == "js-redirect") { score += 55; reasons += "redirecionamento automático da página (JavaScript)" }
        if (!raw.visible) { score -= 25; reasons += "elemento oculto" }
        return ScoredCandidate(raw, score, reasons, safe, trusted, ad)
    }

    fun isStepText(text: String): Boolean = STEP_WORDS.containsMatchIn(text) || DOWNLOAD_WORDS.containsMatchIn(text)

    // ---------- classificação de download ----------

    fun isFileMime(mime: String?): Boolean {
        val m = mime?.substringBefore(';')?.trim()?.lowercase(Locale.ROOT) ?: return false
        if (m.isEmpty()) return false
        return m != "text/html" && m != "application/xhtml+xml" && m != "text/plain" && m != "text/xml"
    }

    fun isAttachment(contentDisposition: String?): Boolean =
        contentDisposition?.trimStart()?.startsWith("attachment", ignoreCase = true) == true

    /** Nome estimado: Content-Disposition > último segmento do caminho > parâmetro filename/file/name. */
    fun estimateFileName(url: String, contentDisposition: String?): String? {
        contentDisposition?.let { cd ->
            Regex("""(?i)filename\*\s*=\s*([^']*)'[^']*'([^;]+)""").find(cd)?.let {
                return sanitizeName(UrlSafety.decode(it.groupValues[2].trim().trim('"')))
            }
            Regex("""(?i)filename\s*=\s*"([^"]+)"""").find(cd)?.let { return sanitizeName(it.groupValues[1]) }
            Regex("""(?i)filename\s*=\s*([^;]+)""").find(cd)?.let { return sanitizeName(it.groupValues[1].trim()) }
        }
        val p = UrlSafety.parse(url) ?: return null
        val seg = UrlSafety.decode(p.path.substringAfterLast('/'))
        if (seg.contains('.') && seg.length <= 255) return sanitizeName(seg)
        p.query?.split('&')?.forEach { kv ->
            val k = kv.substringBefore('=').lowercase()
            if (k in setOf("filename", "file", "name", "fn", "f")) {
                val v = UrlSafety.decode(kv.substringAfter('=', ""))
                if (v.contains('.')) return sanitizeName(v)
            }
        }
        return seg.takeIf { it.isNotBlank() }?.let { sanitizeName(it) }
    }

    fun sanitizeName(name: String): String? {
        val cleaned = name.replace(Regex("""[\\/:*?"<>|\u0000-\u001f]"""), "_").trim().trim('.').take(255)
        return cleaned.ifEmpty { null }
    }

    fun formatSize(bytes: Long?): String {
        if (bytes == null || bytes < 0) return "desconhecido"
        val units = arrayOf("B", "KB", "MB", "GB", "TB")
        var v = bytes.toDouble()
        var i = 0
        while (v >= 1024 && i < units.lastIndex) { v /= 1024; i++ }
        return if (i == 0) "$bytes B" else String.format(Locale.US, "%.1f %s", v, units[i])
    }
}
