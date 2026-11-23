package app.linkresolver.core

import java.io.IOException
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URI
import java.net.URL

sealed class ProbeResult {
    data class File(
        val finalUrl: String, val status: Int, val mimeType: String?, val contentLength: Long?,
        val contentDisposition: String?, val method: String, val acceptRanges: Boolean,
    ) : ProbeResult()
    /** Resposta é uma página (HTML/texto), não um arquivo. */
    data class Page(val finalUrl: String, val status: Int, val mimeType: String?) : ProbeResult()
    data class HttpError(val finalUrl: String, val status: Int) : ProbeResult()
    data class NetworkError(val message: String) : ProbeResult()
    /** Sondagem não pôde concluir (ex.: redirecionamento para domínio não confiável). */
    data class Inconclusive(val reason: String) : ProbeResult()
    /** Violação de segurança (URL perigosa, host que resolve para IP interno). */
    data class Blocked(val reason: String) : ProbeResult()
}

interface FileProbe {
    /** Bloqueante: chamar fora da thread principal. [trustedDomains] = domínios registráveis confiáveis. */
    fun probe(url: String, trustedDomains: Set<String>): ProbeResult
}

/**
 * Valida metadados de um arquivo SEM baixá-lo: HEAD; se não suportado/falhar, GET com
 * `Range: bytes=0-0` — em ambos só os cabeçalhos são lidos e a conexão é fechada.
 * Sem cookies/credenciais. Redirecionamentos são seguidos manualmente (máx. [maxRedirects]) e cada
 * salto passa por validação de URL, domínio confiável e resolução DNS (rejeita IP interno).
 */
class HttpFileProbe(
    private val userAgent: String,
    private val timeoutMs: Int = 8000,
    private val maxRedirects: Int = 5,
    private val urlCheck: (String) -> UrlSafety.Verdict = { UrlSafety.check(it) },
    private val resolver: (String) -> List<InetAddress> = { InetAddress.getAllByName(it).toList() },
) : FileProbe {

    override fun probe(url: String, trustedDomains: Set<String>): ProbeResult {
        val head = run(url, trustedDomains, "HEAD")
        val needGet = head is ProbeResult.NetworkError ||
            (head is ProbeResult.HttpError && head.status in setOf(400, 405, 501))
        if (!needGet) return head
        val get = run(url, trustedDomains, "GET")
        return if (get is ProbeResult.NetworkError && head is ProbeResult.NetworkError) {
            ProbeResult.NetworkError("HEAD: ${head.message}; GET Range: ${get.message}")
        } else get
    }

    private fun run(start: String, trusted: Set<String>, method: String): ProbeResult {
        var cur = start
        for (hop in 0..maxRedirects) {
            val v = urlCheck(cur)
            if (v is UrlSafety.Verdict.Rejected) return ProbeResult.Blocked("URL recusada: ${v.reason}")
            val host = UrlSafety.host(cur) ?: return ProbeResult.Blocked("URL sem host")
            if (DomainPolicy.registrable(host) !in trusted) {
                return ProbeResult.Inconclusive("redirecionamento para domínio não confiável: $host")
            }
            val addrs = try { resolver(host) } catch (e: IOException) {
                return ProbeResult.NetworkError("DNS: ${UrlSafety.scrubText(e.message ?: e.javaClass.simpleName)}")
            }
            if (addrs.isEmpty()) return ProbeResult.NetworkError("DNS sem resultado para $host")
            if (addrs.any { UrlSafety.isPrivateAddress(it) }) {
                return ProbeResult.Blocked("$host resolve para endereço interno (possível DNS rebinding)")
            }
            val conn = try { URL(cur).openConnection() as HttpURLConnection } catch (e: Exception) {
                return ProbeResult.NetworkError("conexão: ${e.javaClass.simpleName}")
            }
            try {
                conn.instanceFollowRedirects = false
                conn.requestMethod = method
                conn.connectTimeout = timeoutMs
                conn.readTimeout = timeoutMs
                conn.useCaches = false
                conn.setRequestProperty("User-Agent", userAgent)
                conn.setRequestProperty("Accept", "*/*")
                conn.setRequestProperty("Accept-Encoding", "identity")
                if (method == "GET") conn.setRequestProperty("Range", "bytes=0-0")
                val code = conn.responseCode
                if (code in 300..399 && code != 304) {
                    val loc = conn.getHeaderField("Location") ?: return ProbeResult.HttpError(cur, code)
                    cur = try { URI(cur).resolve(loc.trim()).toString() } catch (e: Exception) {
                        return ProbeResult.Blocked("Location inválido")
                    }
                    continue
                }
                val mime = conn.contentType?.substringBefore(';')?.trim()?.lowercase()
                val cd = conn.getHeaderField("Content-Disposition")
                val len: Long? = if (code == 206) {
                    conn.getHeaderField("Content-Range")?.substringAfter('/', "")?.trim()?.toLongOrNull()
                } else {
                    conn.getHeaderField("Content-Length")?.trim()?.toLongOrNull()
                }
                val ranges = code == 206 || conn.getHeaderField("Accept-Ranges")?.contains("bytes", true) == true
                return if (code == 200 || code == 206) {
                    val isFile = DownloadHeuristics.isFileMime(mime) || DownloadHeuristics.isAttachment(cd) ||
                        (mime.isNullOrEmpty() && DownloadHeuristics.looksLikeFileUrl(cur))
                    if (isFile) ProbeResult.File(cur, code, mime, len, cd, method, ranges)
                    else ProbeResult.Page(cur, code, mime)
                } else ProbeResult.HttpError(cur, code)
            } catch (e: IOException) {
                return ProbeResult.NetworkError("${e.javaClass.simpleName}: ${UrlSafety.scrubText(e.message ?: "")}".trim())
            } finally {
                conn.disconnect() // nunca lê o corpo
            }
        }
        return ProbeResult.Inconclusive("redirecionamentos demais (>$maxRedirects)")
    }
}
