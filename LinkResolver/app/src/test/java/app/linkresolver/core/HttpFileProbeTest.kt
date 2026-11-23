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
    private val methods = mutableListOf<String>()
    private val ranges = mutableListOf<String?>()
    private var port = 0
    private val trusted = setOf("127.0.0.1")

    private fun probe(resolver: (String) -> List<InetAddress> = { listOf(InetAddress.getByName("8.8.8.8")) }) =
        HttpFileProbe("test-agent", 3000, 5, { UrlSafety.Verdict.Ok }, resolver)

    @Before fun up() {
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        port = server.address.port
        server.createContext("/") { ex ->
            methods += ex.requestMethod; ranges += ex.requestHeaders.getFirst("Range")
            when (ex.requestURI.path) {
                "/file.bin" -> {
                    ex.responseHeaders.add("Content-Type", "application/octet-stream")
                    ex.responseHeaders.add("Accept-Ranges", "bytes")
                    if (ex.requestMethod == "HEAD") { ex.responseHeaders.add("Content-Length", "104857600"); ex.sendResponseHeaders(200, -1) }
                    else ex.sendResponseHeaders(200, 0).also { ex.responseBody.close() }
                }
                "/nohead.bin" -> if (ex.requestMethod == "HEAD") ex.sendResponseHeaders(405, -1) else {
                    ex.responseHeaders.add("Content-Type", "application/zip")
                    ex.responseHeaders.add("Content-Range", "bytes 0-0/5000")
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

    @Test fun headConfirmsFile() {
        val r = probe().probe(url("/file.bin"), trusted) as ProbeResult.File
        assertEquals("HEAD", r.method); assertEquals(104_857_600L, r.contentLength)
        assertEquals("application/octet-stream", r.mimeType)
        assertEquals(listOf("HEAD"), methods)
    }

    @Test fun fallsBackToRangeGetWhenHeadNotAllowed() {
        val r = probe().probe(url("/nohead.bin"), trusted) as ProbeResult.File
        assertEquals("GET", r.method); assertEquals(5000L, r.contentLength)
        assertEquals(listOf("HEAD", "GET"), methods); assertEquals("bytes=0-0", ranges.last())
    }

    @Test fun htmlIsPage() = assertTrue(probe().probe(url("/page"), trusted) is ProbeResult.Page)

    @Test fun emptyResponseIsNetworkError() {
        val r = probe().probe(url("/empty"), trusted)
        assertTrue(r.toString(), r is ProbeResult.NetworkError)
        assertTrue("GET" in methods)                          // tentou o fallback (o JDK ainda repete cada requisição)
    }

    @Test fun forbiddenIsHttpError() = assertEquals(403, (probe().probe(url("/forbidden"), trusted) as ProbeResult.HttpError).status)

    @Test fun redirectToUntrustedDomainIsInconclusiveAndNotFollowed() {
        val r = probe().probe(url("/redir"), trusted)
        assertTrue(r.toString(), r is ProbeResult.Inconclusive)
        assertEquals(listOf("HEAD"), methods)               // não fez requisição ao domínio não confiável
    }

    @Test fun relativeRedirectIsFollowed() = assertTrue(probe().probe(url("/redir-ok"), trusted) is ProbeResult.File)

    @Test fun hostResolvingToPrivateAddressIsBlocked() {
        val r = probe { listOf(InetAddress.getByName("10.0.0.5")) }.probe(url("/file.bin"), trusted)
        assertTrue(r is ProbeResult.Blocked); assertTrue(methods.isEmpty())
    }

    @Test fun unsafeUrlIsBlockedByDefaultChecks() {
        val p = HttpFileProbe("ua")
        assertTrue(p.probe("http://example.com/a.bin", setOf("example.com")) is ProbeResult.Blocked)
        assertTrue(p.probe("https://127.0.0.1/a.bin", setOf("127.0.0.1")) is ProbeResult.Blocked)
        assertTrue(UrlSafety.isPrivateAddress(InetAddress.getByName("192.168.1.1")))
        assertTrue(UrlSafety.isPrivateAddress(InetAddress.getByName("fd00::1")))
        assertFalse(UrlSafety.isPrivateAddress(InetAddress.getByName("8.8.8.8")))
    }
}
