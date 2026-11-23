package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/**
 * Reproduz as páginas de teste PUBLICADAS (testpages/v3) com as varreduras REAIS do PageScanner capturadas
 * no Chromium (src/test/resources/scans) — valida scanner + pontuação + motor de ponta a ponta.
 */
class RealPagesFixtureTest {
    private val base = "https://raw.githack.com/T-Justino/PS4/gh-pages/v3/"
    private val fileUrl = "https://cdn.jsdelivr.net/gh/T-Justino/PS4@gh-pages/v3/files/teste.bin"

    private fun load(rel: String): PageScan {
        val name = "scans/v3__" + rel.replace("/", "__").removeSuffix(".html") + ".json"
        val raw = javaClass.classLoader!!.getResource(name)!!.readText()
        return PageScanner.parse(raw)!!
    }

    private fun sim(vararg pages: String): Sim {
        val s = Sim()
        for (p in pages) s.pages[base + p] = load(p)
        s.file(fileUrl)
        s.answerDomain = true
        return s
    }

    @Test fun abcChainOnRealPages() {
        val s = sim("abc/a.html", "abc/b.html", "abc/c.html")
        val r = s.run(base + "abc/a.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(fileUrl, r.url); assertEquals("teste.bin", r.fileName)
        assertEquals(listOf("cdn.jsdelivr.net"), s.asked)            // arquivo em outro domínio: confirmação humana
        assertEquals(listOf("${base}abc/b.html", "${base}abc/c.html", fileUrl), s.probed)
        assertFalse(s.navigated.any { it.endsWith(".bin") })      // nunca navega até o binário
    }

    @Test fun longChainOnRealPages() {
        val s = sim("long/1.html", "long/2.html", "long/3.html", "long/4.html")
        val r = s.run(base + "long/1.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(4, r.path.count { (it.kind == PathKind.START || it.kind == PathKind.PAGE) && it.linkClass == LinkClass.PAGE })
        assertEquals(LinkClass.FILE_CANDIDATE, r.path.first { it.url?.endsWith(".bin") == true }.linkClass)
    }

    @Test fun metaRefreshOnRealPages() {
        val s = sim("meta/start.html", "meta/destino.html")
        val r = s.run(base + "meta/start.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.path.any { it.arrival.contains("meta refresh") })
    }

    @Test fun javascriptRedirectOnRealPages() {
        val s = sim("js/start.html", "js/destino.html")
        val r = s.run(base + "js/start.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.path.any { it.arrival.contains("JavaScript") })
    }

    @Test fun httpRedirectsOnRealPages() {
        for (code in listOf(301, 302, 303, 307, 308)) {
            val s = sim("http/$code.html", "http/destino.html")
            val hopUrl = s.pages[base + "http/$code.html"]!!.candidates.single().url!!
            s.probes[hopUrl] = ProbeReport(ProbeResult.Page("${base}http/destino.html", 200, "text/html"), emptyList(),
                listOf(RedirectHop(code, hopUrl, "${base}http/destino.html")))
            s.alias[hopUrl] = "${base}http/destino.html"
            val r = s.run(base + "http/$code.html")
            assertEquals("HTTP $code: ${r.message}", ResultState.VERIFIED_FILE, r.state)
            assertEquals(listOf("httpbin.dev", "cdn.jsdelivr.net"), s.asked)   // domínios desconhecidos pediram confirmação humana
            assertTrue(r.path.any { it.kind == PathKind.HTTP_REDIRECT && it.code == code })
        }
    }

    @Test fun rawGithub302RedirectAsksAgainAndConfirmsWithoutNavigating() {
        val s = sim("http/raw302.html")
        val raw = s.pages[base + "http/raw302.html"]!!.candidates.single().url!!
        assertTrue(raw.startsWith("https://github.com/"))
        s.probeFn = { url, trusted ->
            if (url != raw) null
            else if ("githubusercontent.com" in trusted) ProbeReport(
                ProbeResult.File("https://raw.githubusercontent.com/T-Justino/PS4/gh-pages/v3/files/teste.bin", 200, "application/octet-stream", 204800, null, "HEAD", true),
                emptyList(), listOf(RedirectHop(302, raw, "https://raw.githubusercontent.com/T-Justino/PS4/gh-pages/v3/files/teste.bin")))
            else ProbeReport(ProbeResult.NeedsDomain("raw.githubusercontent.com", "https://raw.githubusercontent.com/T-Justino/PS4/gh-pages/v3/files/teste.bin"), emptyList())
        }
        val r = s.run(base + "http/raw302.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(listOf("github.com", "raw.githubusercontent.com"), s.asked)
        assertTrue(r.path.any { it.code == 302 })
        assertFalse(s.navigated.any { it.contains("teste.bin") })
    }

    @Test fun unknownDomainDeniedStopsWithoutRequests() {
        val s = sim("http/302.html", "http/destino.html"); s.answerDomain = false
        val r = s.run(base + "http/302.html")
        assertTrue(s.probed.isEmpty())
        assertNotEquals(ResultState.VERIFIED_FILE, r.state)
    }

    @Test fun loopOnRealPages() {
        val r = sim("loop/a.html", "loop/b.html").run(base + "loop/a.html")
        assertEquals(ResultState.BLOCKED, r.state); assertTrue(r.message.contains("Loop"))
    }

    @Test fun deadEndOnRealPages() {
        val r = sim("dead/start.html", "dead/fim.html").run(base + "dead/start.html")
        assertEquals(r.message, ResultState.NO_CANDIDATE, r.state)
        assertTrue(r.message.contains("sem link válido"))
        assertTrue(r.candidates.any { it.url == "${base}dead/privacidade.html" })
    }

    @Test fun adsIgnoredOnRealPages() {
        val s = sim("ads/start.html", "abc/b.html", "abc/c.html")
        val r = s.run(base + "ads/start.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue((s.navigated + s.probed).none { it.contains("doubleclick") || it.contains("propellerads") })
    }
}
