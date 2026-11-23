package app.linkresolver.core

import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.net.InetAddress
import java.net.InetSocketAddress

class HttpFileProbeTest {
    private lateinit var server: HttpServer
    private val methods = java.util.Collections.synchronizedList(mutableListOf<String>())
    private val agents = java.util.Collections.synchronizedList(mutableListOf<String>())
    private val ranges = java.util.Collections.synchronizedList(mutableListOf<String?>())
    private var port = 0
    private val trusted = setOf("127.0.0.1")
    private val wvUa = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36"

    private fun probe(ua: String = wvUa, lookup: (String) -> List<InetAddress> = { listOf(InetAddress.getByName("127.0.0.1")) },
                      blocked: (InetAddress) -> Boolean = { false }) =
        HttpFileProbe(ua, 2000, 15_000, 5, { UrlSafety.Verdict.Ok }, lookup, blocked)

    @Before fun up() {
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        port = server.address.port
        server.createContext("/") { ex ->
            methods += ex.requestMethod; ranges += ex.requestHeaders.getFirst("Range")
            val ua = ex.requestHeaders.getFirst("User-Agent") ?: ""; agents += ua
            when (ex.requestURI.path) {
                "/file.bin" -> {
                    ex.responseHeaders.add("Content-Type", "application/octet-stream")
                    ex.responseHeaders.add("Accept-Ranges", "bytes")
                    if (ex.requestMethod == "HEAD") { ex.responseHeaders.add("Content-Length", "104857600"); ex.sendResponseHeaders(200, -1) }
                    else { ex.sendResponseHeaders(206, 1); ex.responseBody.write(0); ex.responseBody.close() }
                }
                // Hipótese do bug real: servidor fecha sem responder para UA de WebView ("; wv").
                "/ua-sensitive.bin" -> if (ua.contains("; wv")) ex.close() else {
                    ex.responseHeaders.add("Content-Type", "application/octet-stream")
                    ex.responseHeaders.add("Content-Length", "104857600"); ex.sendResponseHeaders(200, -1)
                }
                "/nohead.bin" -> if (ex.requestMethod == "HEAD") ex.sendResponseHeaders(405, -1) else {
                    ex.responseHeaders.add("Content-Type", "application/zip")
                    ex.responseHeaders.add("Content-Range", "bytes 0-0/5000")
                    ex.sendResponseHeaders(206, 1); ex.responseBody.write(0); ex.responseBody.close()
                }
                "/head403.bin" -> if (ex.requestMethod == "HEAD") ex.sendResponseHeaders(403, -1) else {
                    ex.responseHeaders.add("Content-Type", "application/octet-stream")
                    ex.responseHeaders.add("Content-Range", "bytes 0-0/777")
                    ex.sendResponseHeaders(206, 1); ex.responseBody.write(0); ex.responseBody.close()
                }
                "/page" -> { ex.responseHeaders.add("Content-Type", "text/html; charset=utf-8"); ex.sendResponseHeaders(200, -1) }
                "/empty" -> ex.close()                                   // ERR_EMPTY_RESPONSE
                "/forbidden" -> ex.sendResponseHeaders(403, -1)
                "/redir" -> { ex.responseHeaders.add("Location", "http://localhost:$port/file.bin"); ex.sendResponseHeaders(302, -1) }
                "/redir-ok" -> { ex.responseHeaders.add("Location", "/file.bin"); ex.sendResponseHeaders(302, -1) }
                else -> ex.sendResponseHeaders(404, -1)
            }
            ex.close()
        }
        server.start()
    }

    @After fun down() = server.stop(0)

    private fun url(p: String) = "http://127.0.0.1:$port$p"

    @Test fun headConfirmsFileAndReportsDiagnostics() {
        val rep = probe().probe(url("/file.bin"), trusted)
        val r = rep.result as ProbeResult.File
        assertEquals("HEAD", r.method); assertEquals(104_857_600L, r.contentLength)
        assertEquals("application/octet-stream", r.mimeType)
        assertEquals(listOf("HEAD"), methods)
        assertTrue(rep.diagnostics.joinToString(), rep.diagnostics.any { it.contains("conexão ok") })
        assertTrue(rep.diagnostics.any { it.contains("HTTP 200") })
    }

    @Test fun fallsBackToRangeGetWhenHeadNotAllowed() {
        val r = probe().probe(url("/nohead.bin"), trusted).result as ProbeResult.File
        assertEquals("GET", r.method); assertEquals(5000L, r.contentLength)
        assertEquals(listOf("HEAD", "GET"), methods); assertEquals("bytes=0-0", ranges.last())
    }

    @Test fun head403FallsBackToRangeGet() {
        val r = probe().probe(url("/head403.bin"), trusted).result as ProbeResult.File
        assertEquals("GET", r.method); assertEquals(777L, r.contentLength)
        assertEquals(listOf("HEAD", "GET"), methods)
    }

    @Test fun serverRejectingWebViewUserAgentIsRecoveredWithChromeLikeProfile() {
        val rep = probe().probe(url("/ua-sensitive.bin"), trusted)
        assertTrue(rep.result.toString(), rep.result is ProbeResult.File)
        assertFalse(agents.last().contains("; wv"))
        assertFalse(agents.last().contains("Version/4.0"))
    }

    @Test fun chromeLikeUserAgentStripsWebViewMarkers() {
        val c = UserAgents.chromeLike(wvUa)
        assertFalse(c.contains("wv")); assertFalse(c.contains("Version/4.0")); assertTrue(c.contains("Chrome/130"))
    }

    @Test fun htmlIsPage() = assertTrue(probe().probe(url("/page"), trusted).result is ProbeResult.Page)

    @Test fun emptyResponseIsClassifiedAndDiagnosed() {
        val rep = probe().probe(url("/empty"), trusted)
        val r = rep.result as ProbeResult.NetworkError
        assertEquals(rep.diagnostics.joinToString(), "RESPOSTA_VAZIA", r.category)
        assertTrue("GET" in methods)
        assertTrue(rep.diagnostics.any { it.contains("FALHA RESPOSTA_VAZIA") })
        assertTrue(rep.diagnostics.any { it.contains("chrome-h1") })      // tentou os outros perfis
    }

    @Test fun forbiddenIsHttpError() = assertEquals(403, (probe().probe(url("/forbidden"), trusted).result as ProbeResult.HttpError).status)

    @Test fun redirectToUntrustedDomainAsksForDomainAndIsNotFollowed() {
        val rep = probe().probe(url("/redir"), trusted)
        val r = rep.result
        assertTrue(r.toString(), r is ProbeResult.NeedsDomain)
        assertEquals("localhost", (r as ProbeResult.NeedsDomain).host)
        assertEquals(listOf("HEAD"), methods)               // nenhuma requisição ao domínio não confiável
        assertTrue(rep.diagnostics.any { it.contains("redirecionamento 302") })
    }

    @Test fun relativeRedirectIsFollowed() = assertTrue(probe().probe(url("/redir-ok"), trusted).result is ProbeResult.File)

    @Test fun hostResolvingToPrivateAddressIsBlockedBeforeConnecting() {
        val p = probe(lookup = { listOf(InetAddress.getByName("10.0.0.5")) }, blocked = { UrlSafety.isPrivateAddress(it) })
        // nome (não IP literal): o DNS do próprio cliente é que decide — não há janela entre checar e conectar
        val r = p.probe("http://cdn.rebind.example:$port/file.bin", setOf("rebind.example")).result
        assertTrue(r.toString(), r is ProbeResult.Blocked); assertTrue(methods.isEmpty())
    }

    @Test fun unsafeUrlIsBlockedByDefaultChecks() {
        val p = HttpFileProbe(wvUa)
        assertTrue(p.probe("http://example.com/a.bin", setOf("example.com")).result is ProbeResult.Blocked)
        assertTrue(p.probe("https://127.0.0.1/a.bin", setOf("127.0.0.1")).result is ProbeResult.Blocked)
        assertTrue(UrlSafety.isPrivateAddress(InetAddress.getByName("192.168.1.1")))
        assertTrue(UrlSafety.isPrivateAddress(InetAddress.getByName("fd00::1")))
        assertFalse(UrlSafety.isPrivateAddress(InetAddress.getByName("8.8.8.8")))
    }

    @Test fun diagnosticsNeverLeakQueryTokens() {
        val rep = probe().probe(url("/empty?token=SEGREDO&sig=XYZ"), trusted)
        assertFalse(rep.diagnostics.joinToString().contains("SEGREDO"))
        assertFalse(rep.diagnostics.joinToString().contains("XYZ"))
        assertFalse((rep.result as ProbeResult.NetworkError).message.contains("SEGREDO"))
    }

    @Test fun classifyCoversCategories() {
        assertEquals("DNS", HttpFileProbe.classify(java.net.UnknownHostException("x")))
        assertEquals("TLS", HttpFileProbe.classify(javax.net.ssl.SSLHandshakeException("x")))
        assertEquals("TIMEOUT", HttpFileProbe.classify(java.net.SocketTimeoutException("timeout")))
        assertEquals("CONEXAO", HttpFileProbe.classify(java.net.ConnectException("refused")))
        assertEquals("RESPOSTA_VAZIA", HttpFileProbe.classify(java.io.IOException("unexpected end of stream on x")))
    }
}
