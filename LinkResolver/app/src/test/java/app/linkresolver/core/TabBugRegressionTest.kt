package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/**
 * Regressão do bug do teste real v0.4.0 (v4/tabs/start.html): depois de "Arquivo confirmado", interações com as
 * guias reiniciavam a análise e o resultado virava "Loop detectado".
 */
class TabBugRegressionTest {
    private val base = "https://raw.githack.com/T-Justino/PS4/gh-pages/v4/"
    private val fileUrl = "https://cdn.jsdelivr.net/gh/T-Justino/PS4@gh-pages/v3/files/teste.bin"
    private fun fx(name: String): PageScan =
        PageScanner.parse(javaClass.classLoader!!.getResource("scans/v4__$name.json")!!.readText())!!

    /** Reproduz o teste real: usuário toca em "Continuar", a guia abre e o arquivo é confirmado por HEAD 200. */
    private fun confirmedScenario(): Sim {
        val s = Sim(); s.file(fileUrl); s.answerDomain = true
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0")
        s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(base + "tabs/start.html"); s.pump()
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
        s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")
        assertEquals(ResultState.VERIFIED_FILE, s.result?.state)
        return s
    }

    @Test fun twoTabsOpenFileConfirmedAndResultSurvivesEverythingAfterwards() {
        val s = confirmedScenario()
        val confirmed = s.result!!
        assertEquals(1, s.e.workTab)
        // usuário alterna entre as guias (seleção visual) e toca várias vezes em "Continuar" na guia 0
        for (t in listOf(0, 1, 0, 1, 0)) s.e.setWorkTab(t)
        s.userOpensTabs(0, 2 to base + "tabs/etapa2.html")
        s.userOpensTabs(0, 3 to base + "tabs/etapa2.html")
        s.scanNow(2); s.scanNow(3); s.scanNow(0); s.scanNow(1)
        s.e.onDomChanged(0); s.e.onDomChanged(1); s.pump()
        s.e.onTabClosed(2); s.e.onTabClosed(3); s.pump()
        assertEquals(EngineState.FINISHED, s.e.state)
        assertSame("o resultado confirmado não pode ser substituído", confirmed, s.result)
        assertEquals(ResultState.VERIFIED_FILE, s.e.results.first().state)
        assertEquals(1, s.e.results.size)
        assertEquals(1, s.e.workTab)                                  // seleção não muda a guia de trabalho concluída
        assertEquals(1, s.probed.count { it == fileUrl })              // nada foi verificado de novo
    }

    @Test fun selectingTabsAfterFinishNeverRestartsTheAnalysis() {
        val s = confirmedScenario()
        val probesBefore = s.probed.size; val navBefore = s.navigated.size; val stepsBefore = s.e.steps.size
        repeat(10) { i -> s.e.setWorkTab(i % 2) }
        s.pump()
        assertEquals(EngineState.FINISHED, s.e.state)
        assertEquals(probesBefore, s.probed.size); assertEquals(navBefore, s.navigated.size)
        assertTrue("só registra, não age", s.e.steps.size - stepsBefore <= 10)
        assertNull(s.result?.takeIf { it.state == ResultState.LOOP_DETECTED })
    }

    @Test fun explicitResumeKeepsConfirmedResultAndPresentsNewOneSeparately() {
        val s = confirmedScenario()
        val first = s.result!!
        s.userOpensTabs(0, 2 to base + "tabs/etapa2.html")              // guia nova, aberta depois do fim
        assertTrue(s.e.canResume())
        assertTrue(s.e.resumeOnTab(2)); s.pump()
        val all = s.e.results
        assertEquals(2, all.size)
        assertSame("o primeiro resultado continua o confirmado", first, all[0])
        assertFalse(all[0].isResume)
        assertTrue(all[1].isResume); assertEquals(1, all[1].resumeIndex)
        assertEquals(ResultState.VERIFIED_FILE, all[1].state)           // voltou à URL já confirmada: sucesso, não loop
        assertTrue(all[1].message, all[1].message.contains("já confirmado"))
        assertEquals(EngineState.FINISHED, s.e.state)
    }

    @Test fun returningToAConfirmedUrlIsNeverALoop() {
        val s = confirmedScenario()
        s.userOpensTabs(0, 2 to base + "tabs/etapa2.html")
        assertTrue(s.e.resumeOnTab(2))
        repeat(8) { assertEquals(NavDecision.ALLOW, s.e.onNavigationRequest(fileUrl, false)) }   // volta à URL confirmada várias vezes
        assertTrue("ainda ativa, sem loop", s.e.isActive)
        s.pump()
        assertTrue(s.e.results.none { it.state == ResultState.LOOP_DETECTED })
        assertTrue(s.e.results.first().state == ResultState.VERIFIED_FILE)
    }

    @Test fun resumeLoopOnOtherPagesStillBlocksButNeverTouchesConfirmedResult() {
        val s = confirmedScenario()
        val first = s.result!!
        s.page(base + "x", RawCandidate(base + "y", "Continuar", "a", "href", false, "", "", null, true))
        s.page(base + "y", RawCandidate(base + "x", "Continuar", "a", "href", false, "", "", null, true))
        s.userOpensTabs(0, 2 to base + "x")
        assertTrue(s.e.resumeOnTab(2)); s.pump()
        assertEquals(ResultState.LOOP_DETECTED, s.e.results.last().state)   // loop real continua detectado
        assertTrue(s.e.results.last().isResume)
        assertSame(first, s.e.results.first())                              // ...mas o confirmado permanece
        assertEquals(ResultState.VERIFIED_FILE, s.e.results.first().state)
    }

    @Test fun resumeLimitIsEnforcedAndOldResultKept() {
        val s = Sim(Limits(maxManualResumes = 1)); s.file(fileUrl); s.answerDomain = true
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0"); s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(base + "tabs/start.html"); s.pump(); s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")
        assertTrue(s.e.resumeOnTab(1)); s.pump()
        assertFalse(s.e.canResume()); assertFalse(s.e.resumeOnTab(1))
        assertEquals(ResultState.VERIFIED_FILE, s.e.results.first().state)
    }

    @Test fun windowOpenButtonIsNotAutoClickedAndDomChangeIsNotProofOfANewTab() {
        val s = Sim(); s.file(fileUrl); s.answerDomain = true
        val u = base + "tabs/start.html"
        s.seq[u] = listOf(fx("tabs__start__t0"), PageScan(u, "t", emptyList(), null, null))   // depois do toque o botão some
        s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(u); s.pump()
        assertTrue(s.clicked.isEmpty()); assertEquals(EngineState.WAITING_CLICK, s.e.state)
        repeat(5) { s.e.onDomChanged(0); s.pump() }                      // o DOM muda, mas nenhuma guia abriu
        assertEquals("continua aguardando o toque/guia", EngineState.WAITING_CLICK, s.e.state)
        assertNull(s.result)
        assertTrue(s.e.steps.none { it.note.contains("teve efeito") })
        s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")               // agora sim: guia aberta pelo gesto humano
        assertEquals(ResultState.VERIFIED_FILE, s.result?.state)
    }

    @Test fun repeatedContinueTapsWhileActiveAreBoundedAndNeverLoop() {
        val s = Sim(); s.file(fileUrl); s.answerDomain = true
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0"); s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.holdProbes = true
        s.start(base + "tabs/start.html"); s.pump()
        val o = base + "tabs/start.html"
        val allowed = (1..8).count { s.e.onPopupRequest(0, o, true) }
        assertEquals(3, allowed)                                         // 3 por página; o resto é bloqueado
        assertFalse(s.e.steps.any { it.note.contains("Loop") })
        assertNotEquals(ResultState.LOOP_DETECTED, s.result?.state)
    }

    @Test fun lateNavigationEventsCannotTurnConfirmedIntoLoop() {
        val s = confirmedScenario()
        val confirmed = s.result!!
        repeat(8) { s.e.onNavigationRequest(base + "a", true); s.e.onNavigationRequest(base + "b", true) }
        s.e.onPageStarted(base + "a"); s.e.onPageFinished(base + "a")
        s.e.onPopupRequest(0, base + "tabs/start.html", true); s.e.onTabOpened(5, 0, base + "tabs/start.html")
        s.pump()
        assertSame(confirmed, s.result); assertEquals(EngineState.FINISHED, s.e.state)
    }

    @Test fun unconfirmedResultIsStillUpgradedByExplicitResume() {
        val s = Sim(); s.file(base + "f/2.zip", "application/zip"); s.answerDomain = true
        s.page(base + "a", RawCandidate(base + "f/1.zip", "Download A", "a", "href", false, "", "", null, true),
            RawCandidate(base + "f/2.zip", "Download B", "a", "href", false, "", "", null, true))
        s.probes[base + "f/1.zip"] = ProbeReport(ProbeResult.NetworkError("EOF", "RESPOSTA_VAZIA"), emptyList())
        s.run(base + "a")
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, s.e.results.first().state)
        s.result = null
        assertTrue(s.e.resumeFromCandidate(s.lastCandidates.first { it.url == base + "f/2.zip" })); s.pump()
        assertEquals(1, s.e.results.size)                                  // não havia confirmado: o novo substitui
        assertEquals(ResultState.VERIFIED_FILE, s.e.results.first().state)
        assertFalse(s.e.results.first().isResume)
    }
}
