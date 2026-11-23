package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/**
 * Cenários da v0.3.0 com um "navegador" simulado: páginas = PageScan, verificações = ProbeResult.
 * O simulador processa as ações do motor numa fila (como o loop de eventos do Android).
 */
class V3ScenarioTest {
    private val site = "https://t.example.com"

    private fun link(url: String, text: String, src: String = "href") = RawCandidate(url, text, "a", src, false, "", "", null, true)

    @Test fun aToBToCToFile() {
        val s = Sim()
        s.page("$site/a", link("$site/b", "Continuar"))
        s.page("$site/b", link("$site/c", "Continuar"))
        s.page("$site/c", link("$site/files/teste.bin", "Baixar arquivo"))
        s.file("$site/files/teste.bin")
        val r = s.run("$site/a")
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertEquals("$site/files/teste.bin", r.url)
        assertEquals("teste.bin", r.fileName)
        assertFalse("não deve navegar até o binário", s.navigated.any { it.endsWith(".bin") })
        assertEquals(listOf("$site/b", "$site/c", "$site/files/teste.bin"), s.probed)
        val kinds = r.path.map { it.kind }
        assertEquals(PathKind.START, kinds.first()); assertEquals(PathKind.FILE, kinds.last())
        assertTrue(r.path.size >= 5)
        assertTrue("toda página tem motivo da decisão", r.path.filter { it.kind != PathKind.FILE }.all { it.decision != null })
        assertTrue(r.path[0].decision!!.contains("Continuar"))
        assertTrue(r.path.last().linkClass == LinkClass.CONFIRMED_FILE)
        assertTrue(r.candidates.any { it.kind == LinkClass.CONFIRMED_FILE })
        assertTrue(r.candidates.any { it.kind == LinkClass.PAGE })
    }

    @Test fun fileFoundAfterFourOrMoreSteps() {
        val s = Sim()
        for (i in 1..4) s.page("$site/p$i", link(if (i < 4) "$site/p${i + 1}" else "$site/f/video.zip", if (i < 4) "Continuar" else "Download"))
        s.file("$site/f/video.zip", "application/zip")
        val r = s.run("$site/p1")
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.path.count { it.kind == PathKind.PAGE } >= 4)
    }

    @Test fun httpRedirectCodesAreRecordedForPages() {
        for (code in listOf(301, 302, 303, 307, 308)) {
            val s = Sim()
            s.page("$site/a", link("$site/go/$code", "Continuar para o download"))
            s.probes["$site/go/$code"] = ProbeReport(
                ProbeResult.Page("$site/final", 200, "text/html"), emptyList(),
                listOf(RedirectHop(code, "$site/go/$code", "$site/final")),
            )
            s.page("$site/final", link("$site/f/a.zip", "Baixar"))
            s.alias["$site/go/$code"] = "$site/final"
            s.file("$site/f/a.zip", "application/zip")
            val r = s.run("$site/a")
            assertEquals("código $code", ResultState.VERIFIED_FILE, r.state)
            assertEquals("sem nó duplicado", 1, r.path.count { it.kind == PathKind.HTTP_REDIRECT })
            val hop = r.path.single { it.kind == PathKind.HTTP_REDIRECT && it.code == code }
            assertTrue(hop.arrival.contains("HTTP $code"))
            assertEquals("$site/final", hop.url)
        }
    }

    @Test fun webViewRedirectIsNotDuplicatedAfterProbeHop() {
        val s = Sim()
        s.page("$site/a", link("$site/go", "Continuar para o download"))
        s.probes["$site/go"] = ProbeReport(ProbeResult.Page("$site/final", 200, "text/html"), emptyList(), listOf(RedirectHop(302, "$site/go", "$site/final")))
        s.page("$site/final")
        s.alias["$site/go"] = "$site/final"                          // o WebView repete o redirect
        val r = s.run("$site/a")
        assertEquals(1, r.path.count { it.kind == PathKind.HTTP_REDIRECT })
    }

    @Test fun redirectDirectlyToFileConfirmsWithoutNavigating() {
        val s = Sim()
        s.page("$site/a", link("$site/get?id=7", "Download"))
        s.probes["$site/get?id=7"] = ProbeReport(
            ProbeResult.File("$site/cdn/x.iso", 200, "application/octet-stream", 5000, null, "HEAD", true), emptyList(),
            listOf(RedirectHop(307, "$site/get?id=7", "$site/cdn/x.iso")),
        )
        val r = s.run("$site/a")
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertEquals("$site/cdn/x.iso", r.url)
        assertTrue(r.path.any { it.code == 307 })
        assertEquals(listOf<String>(), s.navigated.drop(1))
    }

    @Test fun javascriptRedirectIsDetectedAndFollowed() {
        val s = Sim()
        s.page("$site/js", link("$site/destino", "(redirecionamento JavaScript)", "js-redirect"), wait = true)
        s.page("$site/destino", link("$site/f/a.zip", "Baixar"))
        s.file("$site/f/a.zip", "application/zip")
        val r = s.run("$site/js")
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.path[0].decision!!.contains("JavaScript") || r.path[1].arrival.contains("JavaScript"))
    }

    @Test fun javascriptRedirectDoneByThePageItselfIsLabeled() {
        val s = Sim()
        s.page("$site/js", link("$site/destino", "(redirecionamento JavaScript)", "js-redirect"))
        val e = ResolverEngine(Limits(), { 0L }, s); s.e = e
        e.start("$site/js"); e.onScan(s.pages["$site/js"]!!)
        assertEquals(NavDecision.ALLOW, e.onNavigationRequest("$site/destino", false, false))   // a página navegou sozinha
        e.onProbeResult("$site/destino", ProbeResult.Page("$site/destino", 200, "text/html"))
    }

    @Test fun metaRefreshIsDetectedAndFollowed() {
        val s = Sim()
        s.page("$site/meta", link("$site/destino", "(meta refresh 2s)", "meta-refresh"), wait = true)
        s.page("$site/destino", link("$site/f/a.zip", "Baixar"))
        s.file("$site/f/a.zip", "application/zip")
        val r = s.run("$site/meta")
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.path.any { it.arrival.contains("meta refresh") })
    }

    @Test fun pageDrivenNavigationUsesRedirectHintKind() {
        val s = Sim()
        val e = ResolverEngine(Limits(), { 0L }, s); s.e = e
        e.start("$site/meta")
        e.onScan(PageScan("$site/meta", "t", listOf(link("$site/destino", "(meta refresh 2s)", "meta-refresh")), null, null))
        // simula a página navegar sozinha antes de a sondagem responder
        e.onNavigationRequest("$site/destino", false, false)
        e.onProbeResult("$site/destino", ProbeResult.Page("$site/destino", 200, "text/html"))
        e.stop()
        assertTrue(s.result!!.path.any { it.kind == PathKind.META_REFRESH })
    }

    @Test fun loopBetweenTwoPagesIsDetected() {
        val s = Sim()
        s.page("$site/a", link("$site/b", "Continuar"))
        s.page("$site/b", link("$site/a", "Continuar"))
        val r = s.run("$site/a")
        assertEquals(ResultState.LOOP_DETECTED, r.state)
        assertTrue(r.message, r.message.contains("Loop"))
        assertTrue(s.navigated.size <= 3)
    }

    @Test fun loopThroughHttpRedirectsIsStopped() {
        val s = Sim(); val e = ResolverEngine(Limits(), { 0L }, s); s.e = e
        e.start("$site/a")
        repeat(5) { e.onNavigationRequest("$site/b", true); e.onNavigationRequest("$site/a", true) }
        assertEquals(ResultState.LOOP_DETECTED, s.result?.state)
    }

    @Test fun intermediatePageWithoutValidLinkEndsWithPreservedCandidates() {
        val s = Sim()
        s.page("$site/a", link("$site/b", "Continuar"))
        s.page("$site/b", link("$site/privacidade", "Política de privacidade"), wait = true)
        val r = s.run("$site/a")
        assertEquals(ResultState.NO_CANDIDATE, r.state)
        assertTrue(r.message, r.message.contains("Tempo de espera"))      // página diz "aguarde": espera o limite e para
        val kept = r.candidates.firstOrNull { it.url == "$site/privacidade" }
        assertNotNull("candidato preservado para cópia", kept)
        assertTrue(r.path.size >= 2)
    }

    @Test fun staticIntermediatePageWithoutValidLinkSaysSo() {
        val s = Sim()
        s.page("$site/a", link("$site/b", "Continuar"))
        s.page("$site/b", link("$site/privacidade", "Política de privacidade"))
        val r = s.run("$site/a")
        assertEquals(ResultState.NO_CANDIDATE, r.state)
        assertTrue(r.message, r.message.contains("sem link válido"))
    }

    @Test fun noProgressStopsPagesThatRevealNothingNew() {
        val s = Sim()
        s.page("$site/a", link("$site/b", "Download"), link("$site/c", "Download"))
        s.page("$site/b", link("$site/b", "Download"), link("$site/c", "Download"))
        s.page("$site/c", link("$site/b", "Download"), link("$site/c", "Download"))
        val r = s.run("$site/a")
        assertTrue(r.message, r.message.contains("Sem progresso") || r.message.contains("Loop"))
    }

    @Test fun unknownDomainInChainRequiresHumanConfirmation() {
        val s = Sim(); s.answerDomain = null
        s.page("$site/a", link("https://outro.example.net/x.zip", "Baixar download"))
        val e = ResolverEngine(Limits(), { 0L }, s); s.e = e
        e.start("$site/a"); e.onScan(s.pages["$site/a"]!!)
        assertEquals(listOf("outro.example.net"), s.asked)
        assertEquals(EngineState.WAITING_CONFIRMATION, e.state)
        assertTrue(s.probed.isEmpty())                       // nada é consultado antes da confirmação humana
    }

    @Test fun adsAreNeverFollowedInChains() {
        val s = Sim()
        s.page("$site/ok")
        s.page("$site/a",
            RawCandidate("https://ads.doubleclick.net/c", "Download now", "a", "href", false, "", " banner ad", null, true),
            RawCandidate("$site/ok", "Continuar", "a", "href", false, "", "", null, true))
        val r = s.run("$site/a")
        assertFalse(s.navigated.any { it.contains("doubleclick") }); assertFalse(s.probed.any { it.contains("doubleclick") })
        assertTrue(r.candidates.any { it.status.contains("anúncio") })
    }

    @Test fun pageLimitStopsRunawayChains() {
        val s = Sim(Limits(maxPages = 4, maxDepth = 50))
        for (i in 1..30) s.page("$site/p$i", link("$site/p${i + 1}", "Continuar para o download"))
        val r = s.run("$site/p1")
        assertTrue(r.message, r.message.contains("Limite") || r.message.contains("Profundidade"))
        assertTrue(s.navigated.size <= 6)
    }

    @Test fun failureKeepsEveryCandidateCopyable() {
        val s = Sim()
        s.page("$site/a", link("$site/f/1.zip", "Download A"), link("$site/f/2.zip", "Download B"))
        s.probes["$site/f/1.zip"] = ProbeReport(ProbeResult.NetworkError("EOF", "RESPOSTA_VAZIA"), listOf("[chrome-h2 HEAD] FALHA RESPOSTA_VAZIA"))
        val r = s.run("$site/a")
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, r.state)
        assertTrue(r.candidates.map { it.url }.containsAll(listOf("$site/f/1.zip", "$site/f/2.zip")))
        assertTrue(r.candidates.all { it.kind != LinkClass.CONFIRMED_FILE })
        assertTrue(r.message.contains("NÃO verificado"))
    }
}
