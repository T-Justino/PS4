package app.linkresolver.core

/**
 * Reconhecimento de URLs do GitHub (genérico, para qualquer repositório): páginas de visualização
 * (/blob/), links Raw (/raw/ e raw.githubusercontent.com) e assets de releases. Sem dependências de Android.
 *
 * Uma URL `/blob/…/arquivo.smc` termina com extensão de arquivo, mas é uma PÁGINA HTML de visualização.
 * O arquivo real é o link "Raw" (`/raw/…`) que o próprio GitHub mostra nessa página.
 */
object GithubUrls {
    data class Blob(val owner: String, val repo: String, val ref: String, val path: String)

    private val BLOB = Regex("""^https://(?:www\.)?github\.com/([^/?#]+)/([^/?#]+)/blob/([^/?#]+)/([^?#]+)(?:[?#].*)?$""", RegexOption.IGNORE_CASE)
    private val RAW = Regex("""^https://(?:www\.)?github\.com/[^/?#]+/[^/?#]+/raw/[^?#]+""", RegexOption.IGNORE_CASE)
    private val RELEASE_ASSET = Regex("""^https://(?:www\.)?github\.com/[^/?#]+/[^/?#]+/releases/download/[^?#]+""", RegexOption.IGNORE_CASE)

    fun parseBlob(url: String): Blob? =
        BLOB.matchEntire(url.trim())?.let { Blob(it.groupValues[1], it.groupValues[2], it.groupValues[3], it.groupValues[4]) }

    /** Página de visualização de arquivo (HTML), mesmo quando a URL termina em .smc/.zip/… */
    fun isBlobView(url: String): Boolean = parseBlob(url) != null

    /** Link bruto fornecido pelo GitHub: github.com/…/raw/… (redireciona) ou raw.githubusercontent.com. */
    fun isRawLink(url: String): Boolean =
        RAW.containsMatchIn(url) || UrlSafety.host(url)?.let { it == "raw.githubusercontent.com" } == true

    fun isReleaseAsset(url: String): Boolean = RELEASE_ASSET.containsMatchIn(url)

    /**
     * Endereço Raw DERIVADO de uma URL /blob/ (troca posicional `/blob/` → `/raw/`; o GitHub responde 302 para
     * raw.githubusercontent.com). Só é usado quando a página não expõe o link Raw próprio.
     */
    fun derivedRaw(blobUrl: String): String? {
        if (parseBlob(blobUrl) == null) return null
        return blobUrl.trim().substringBefore('#').substringBefore('?').replaceFirst("/blob/", "/raw/")
    }
}
