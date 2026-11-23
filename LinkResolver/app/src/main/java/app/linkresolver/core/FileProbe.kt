package app.linkresolver.core

import okhttp3.Call
import okhttp3.ConnectionPool
import okhttp3.Dns
import okhttp3.EventListener
import okhttp3.Handshake
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import java.io.EOFException
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NoRouteToHostException
import java.net.Proxy
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

sealed class ProbeResult {
    data class File(
        val finalUrl: String, val status: Int, val mimeType: String?, val contentLength: Long?,
        val contentDisposition: String?, val method: String, val acceptRanges: Boolean,
    ) : ProbeResult()
    /** Resposta é uma página (HTML/texto), não um arquivo. */
    data class Page(val finalUrl: String, val status: Int, val mimeType: String?) : ProbeResult()
    data class HttpError(val finalUrl: String, val status: Int) : ProbeResult()
    /** [category]: DNS, TLS, TIMEOUT, CONEXAO, RESPOSTA_VAZIA, H2_RESET, IO. */
    data class NetworkError(val message: String, val category: String = "IO") : ProbeResult()
    /** Sondagem não pôde concluir. */
    data class Inconclusive(val reason: String) : ProbeResult()
    /** Redirecionamento para domínio ainda não confiável: precisa de confirmação do usuário. */
    data class NeedsDomain(val host: String, val nextUrl: String) : ProbeResult()
    /** Violação de segurança (URL perigosa, host que resolve para IP interno). */
    data class Blocked(val reason: String) : ProbeResult()
}

/** Salto de redirecionamento HTTP observado (código real 301/302/303/307/308). */
data class RedirectHop(val code: Int, val from: String, val to: String)

data class ProbeReport(val result: ProbeResult, val diagnostics: List<String>, val hops: List<RedirectHop> = emptyList())

interface FileProbe {
    /** Bloqueante: chamar fora da thread principal. [trustedDomains] = domínios registráveis confiáveis. */
    fun probe(url: String, trustedDomains: Set<String>): ProbeReport
}

object UserAgents {
    /** Remove os marcadores de WebView ("; wv", "Version/4.0") para se parecer com o Chrome. */
    fun chromeLike(webViewUa: String): String =
        webViewUa.replace("; wv", "").replace(" Version/4.0", "").trim()
}

/**
 * Valida metadados de um arquivo SEM baixá-lo, com OkHttp: HEAD; se não suportado/falhar,
 * GET com `Range: bytes=0-0`. Só cabeçalhos são lidos e a resposta é fechada sem consumir o corpo.
 *
 * Robustez: tenta perfis de cliente (UA estilo Chrome em h2+http/1.1, UA Chrome só http/1.1, UA do WebView
 * em http/1.1) quando há falha de rede (ex.: servidor que fecha a conexão sem responder).
 * Segurança: sem cookies/credenciais; cada salto passa por validação de URL e domínio confiável; o DNS é
 * resolvido pelo próprio cliente e qualquer endereço interno é recusado (sem janela de DNS rebinding);
 * redirecionamentos seguidos manualmente (máx. [maxRedirects]).
 * Diagnóstico por tentativa: DNS, TCP, TLS (versão/cifra), protocolo, HTTP, timeouts, redirecionamentos —
 * sem IPs, cookies, cabeçalhos ou valores de query.
 */
class HttpFileProbe(
    private val webViewUserAgent: String,
    private val timeoutMs: Long = 7000,
    private val totalBudgetMs: Long = 25_000,
    private val maxRedirects: Int = 5,
    private val urlCheck: (String) -> UrlSafety.Verdict = { UrlSafety.check(it) },
    private val resolve: (String) -> List<InetAddress> = { Dns.SYSTEM.lookup(it) },
    private val isBlockedAddress: (InetAddress) -> Boolean = { UrlSafety.isPrivateAddress(it) },
) : FileProbe {

    private class Profile(val name: String, val ua: String, val protocols: List<Protocol>)

    private val profiles: List<Profile> = run {
        val chrome = UserAgents.chromeLike(webViewUserAgent)
        val list = mutableListOf(
            Profile("chrome-h2", chrome, listOf(Protocol.HTTP_2, Protocol.HTTP_1_1)),
            Profile("chrome-h1", chrome, listOf(Protocol.HTTP_1_1)),
        )
        if (chrome != webViewUserAgent) list += Profile("webview-h1", webViewUserAgent, listOf(Protocol.HTTP_1_1))
        list
    }

    private class Holder { var blockedHost: String? = null; val hops = mutableListOf<RedirectHop>() }

    private sealed class Hop {
        class Done(val r: ProbeResult) : Hop()
        class Redirect(val next: String, val code: Int) : Hop()
    }

    override fun probe(url: String, trustedDomains: Set<String>): ProbeReport {
        val diag = mutableListOf<String>()
        val deadline = System.nanoTime() + totalBudgetMs * 1_000_000
        val holder = Holder()
        val failures = mutableListOf<ProbeResult.NetworkError>()
        for (p in profiles) {
            if (System.nanoTime() > deadline) { diag += "orçamento de tempo da sondagem esgotado"; break }
            val head = run(p, url, trustedDomains, "HEAD", diag, holder)
            val needGet = head is ProbeResult.NetworkError ||
                (head is ProbeResult.HttpError && head.status in setOf(400, 405, 501))
            val r = if (needGet) {
                val g = run(p, url, trustedDomains, "GET", diag, holder)
                if (g is ProbeResult.NetworkError && head is ProbeResult.HttpError) head else g
            } else head
            if (r !is ProbeResult.NetworkError) return ProbeReport(r, diag, holder.hops.toList())
            failures += r
        }
        val summary = failures.joinToString("; ") { it.category }.ifEmpty { "sem tentativas" }
        val last = failures.lastOrNull()
        return ProbeReport(
            ProbeResult.NetworkError("todas as tentativas falharam ($summary): ${last?.message ?: ""}".trim(), last?.category ?: "IO"),
            diag, holder.hops.toList(),
        )
    }

    private fun run(
        p: Profile, start: String, trusted: Set<String>, method: String,
        diag: MutableList<String>, holder: Holder,
    ): ProbeResult {
        var cur = start
        holder.hops.clear()
        for (hop in 0..maxRedirects) {
            val v = urlCheck(cur)
            if (v is UrlSafety.Verdict.Rejected) return ProbeResult.Blocked("URL recusada: ${v.reason}")
            val host = UrlSafety.host(cur) ?: return ProbeResult.Blocked("URL sem host")
            if (DomainPolicy.registrable(host) !in trusted) {
                return if (hop == 0) ProbeResult.Inconclusive("domínio não confiável: $host")
                else ProbeResult.NeedsDomain(host, cur)
            }
            val httpUrl = cur.toHttpUrlOrNull() ?: return ProbeResult.Blocked("URL inválida")
            val tag = "${p.name} $method"
            val trace = Trace(tag)
            val dns = object : Dns {
                override fun lookup(hostname: String): List<InetAddress> {
                    val addrs = resolve(hostname)
                    if (addrs.any { isBlockedAddress(it) }) {
                        holder.blockedHost = hostname
                        throw UnknownHostException("endereço interno bloqueado")
                    }
                    return addrs
                }
            }
            val client = OkHttpClient.Builder()
                .protocols(p.protocols)
                .followRedirects(false).followSslRedirects(false)
                .retryOnConnectionFailure(true)
                .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                .callTimeout(timeoutMs * 2, TimeUnit.MILLISECONDS)
                .connectionPool(ConnectionPool(0, 1, TimeUnit.NANOSECONDS)) // conexão nova a cada tentativa
                .dns(dns)
                .eventListener(trace)
                .build()
            val rb = Request.Builder().url(httpUrl)
                .header("User-Agent", p.ua)
                .header("Accept", "*/*")
                .header("Accept-Language", "pt-BR,pt;q=0.9,en;q=0.8")
                .header("Accept-Encoding", "identity")
                .header("Referer", "${httpUrl.scheme}://${httpUrl.host}/")
            val req = if (method == "HEAD") rb.head().build() else rb.get().header("Range", "bytes=0-0").build()
            val outcome: Hop = try {
                client.newCall(req).execute().use { resp -> interpret(resp, cur, method) }
            } catch (e: IOException) {
                diag += trace.lines
                holder.blockedHost?.let { return ProbeResult.Blocked("$it resolve para endereço interno (possível DNS rebinding)") }
                val cat = classify(e)
                val msg = UrlSafety.scrubText("${e.javaClass.simpleName}: ${e.message ?: ""}").trim()
                diag += "[$tag] FALHA $cat: $msg"
                return ProbeResult.NetworkError(msg, cat)
            }
            diag += trace.lines
            when (outcome) {
                is Hop.Done -> return outcome.r
                is Hop.Redirect -> {
                    diag += "[$tag] redirecionamento ${outcome.code} → ${UrlSafety.host(outcome.next) ?: "?"}"
                    holder.hops += RedirectHop(outcome.code, cur, outcome.next)
                    cur = outcome.next
                }
            }
        }
        return ProbeResult.Inconclusive("redirecionamentos demais (>$maxRedirects)")
    }

    /** Lê SOMENTE cabeçalhos; o corpo nunca é consumido. */
    private fun interpret(resp: Response, cur: String, method: String): Hop {
        val code = resp.code
        if (code in 300..399 && code != 304) {
            val loc = resp.header("Location") ?: return Hop.Done(ProbeResult.HttpError(cur, code))
            val next = resp.request.url.resolve(loc.trim())?.toString()
                ?: return Hop.Done(ProbeResult.Blocked("Location inválido"))
            return Hop.Redirect(next, code)
        }
        val mime = resp.header("Content-Type")?.substringBefore(';')?.trim()?.lowercase()
        val cd = resp.header("Content-Disposition")
        val len: Long? = if (code == 206) {
            resp.header("Content-Range")?.substringAfter('/', "")?.trim()?.toLongOrNull()
        } else resp.header("Content-Length")?.trim()?.toLongOrNull()
        val ranges = code == 206 || resp.header("Accept-Ranges")?.contains("bytes", true) == true
        if (code != 200 && code != 206) return Hop.Done(ProbeResult.HttpError(cur, code))
        val isFile = DownloadHeuristics.isFileMime(mime) || DownloadHeuristics.isAttachment(cd) ||
            (mime.isNullOrEmpty() && DownloadHeuristics.looksLikeFileUrl(cur))
        return Hop.Done(if (isFile) ProbeResult.File(cur, code, mime, len, cd, method, ranges) else ProbeResult.Page(cur, code, mime))
    }

    companion object {
        fun classify(e: Throwable): String {
            val m = (e.message ?: "").lowercase()
            return when {
                e is UnknownHostException -> "DNS"
                e is SSLException -> "TLS"
                e is InterruptedIOException || m.contains("timeout") || m.contains("timed out") -> "TIMEOUT"
                e is ConnectException || e is NoRouteToHostException -> "CONEXAO"
                e is EOFException || m.contains("unexpected end of stream") || m.contains("unexpected eof") ||
                    m.contains("connection reset") || m.contains("connection closed") -> "RESPOSTA_VAZIA"
                m.contains("stream was reset") || m.contains("http/2") -> "H2_RESET"
                else -> "IO"
            }
        }
    }

    /** Linha do tempo de uma requisição (sem IPs, cookies, cabeçalhos ou query). */
    private class Trace(private val tag: String) : EventListener() {
        val lines = mutableListOf<String>()
        private var t0 = System.nanoTime()
        private var dnsAt = 0L
        private var connAt = 0L
        private fun ms() = (System.nanoTime() - t0) / 1_000_000

        override fun callStart(call: Call) { t0 = System.nanoTime() }
        override fun dnsStart(call: Call, domainName: String) { dnsAt = ms() }
        override fun dnsEnd(call: Call, domainName: String, inetAddressList: List<InetAddress>) {
            val v6 = inetAddressList.count { it.address.size == 16 }
            lines += "[$tag] DNS ok em ${ms() - dnsAt}ms (${inetAddressList.size - v6} IPv4, $v6 IPv6)"
        }
        override fun connectStart(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy) { connAt = ms() }
        override fun secureConnectEnd(call: Call, handshake: Handshake?) {
            lines += "[$tag] TLS ${handshake?.tlsVersion?.javaName ?: "?"} ${handshake?.cipherSuite?.javaName ?: "?"}"
        }
        override fun connectEnd(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy, protocol: Protocol?) {
            lines += "[$tag] conexão ok (${protocol ?: "?"}) em ${ms() - connAt}ms"
        }
        override fun connectFailed(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy, protocol: Protocol?, ioe: IOException) {
            lines += "[$tag] conexão falhou (${classify(ioe)}) após ${ms() - connAt}ms"
        }
        override fun responseHeadersEnd(call: Call, response: Response) {
            lines += "[$tag] HTTP ${response.code} (${response.protocol}) em ${ms()}ms"
        }
    }
}
