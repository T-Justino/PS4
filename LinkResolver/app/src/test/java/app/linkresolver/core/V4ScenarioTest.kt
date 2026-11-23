package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/** v0.4.0: guias, botões dinâmicos, temporizadores, pausa humana, popups maliciosos, retomada. */
class V4ScenarioTest {
    private val base = "https://raw.githack.com/T-Justino/PS4/gh-pages/v4/"
    private val fileUrl = "https://cdn.jsdelivr.net/gh/T-Justino/PS4@gh-pages/v3/files/teste.bin"

    private fun fx(name: String): PageScan =
        PageScanner.parse(javaClass.classLoader!!.getResource("scans/v4__$name.json")!!.readText())!!

    private fun sim(limits: Limits = Limits()) = Sim(limits).also { it.file(fileUrl); it.answerDomain = true }

    private fun btn(text: String, extra: RawCandidate.() -> RawCandidate = { this }) =
        RawCandidate(null, text, "button", "button", false, "", "", "1", true).extra()
    private fun lnk(url: String, text: String) = RawCandidate(url, text, "a", "href", false, "", "", null, true)
    private fun scan(url: String, vararg c: RawCandidate, ch: ChallengeKind? = null, wait: Boolean = false, cd: Int = 0, ad: Boolean = false) =
        PageScan(url, "t", c.toList(), ch, null, wait, ad, cd)

    // ------------------------------------------------------------------ 1. guias

    @Test fun buttonOpensNewTab_autoClickFails_humanTapOpensTab_tabIsPromoted_fileConfirmed() {
        val s = sim()
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0")
        s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(base + "tabs/start.html"); s.pump()
        assertEquals(listOf("Continuar"), s.clicked)                 // clique automático, intenção inequívoca
        assertEquals(EngineState.RUNNING, s.e.state)
        s.advance(5_000)                                              // popup sem gesto é bloqueado: nada acontece
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
        assertEquals(listOf("Continuar"), s.highlighted)              // pede o toque humano no botão destacado
        s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")            // o usuário toca: window.open com gesto
        s.pump()
        val r = s.result!!
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(listOf(1), s.workTabs.filter { it == 1 }.take(1))   // guia 1 virou guia de trabalho
        val tab = r.path.first { it.kind == PathKind.NEW_TAB }
        assertEquals(1, tab.tabId); assertTrue(tab.arrival.contains("guia 0")); assertNotNull(tab.url)
        assertTrue(tab.decision!!.contains("guia de trabalho"))
        assertEquals(PathKind.FILE, r.path.last().kind)
    }

    @Test fun openingATabIsNeverAFileConfirmation() {
        val s = sim(); s.holdProbes = true
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0")
        s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(base + "tabs/start.html"); s.pump(); s.advance(5_000)
        s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")
        assertNull(s.result)                                          // só abrir a guia não conclui nada
        assertTrue(s.e.isActive)
    }

    @Test fun adPopupIsClosedAndLegitimateTabIsPromoted() {
        val s = sim()
        s.pages[base + "popup-ad/start.html"] = fx("popup-ad__start__t0")
        s.pages[base + "popup-ad/anuncio.html"] = fx("popup-ad__anuncio__t0")
        s.pages[base + "popup-ad/download.html"] = fx("popup-ad__download__t0")
        s.start(base + "popup-ad/start.html"); s.pump(); s.advance(5_000)
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
        assertEquals(listOf("Continuar"), s.highlighted)              // "Receber prêmio" nunca é clicado
        assertEquals(listOf("Continuar"), s.clicked)
        s.userOpensTabs(0, 1 to base + "popup-ad/anuncio.html", 2 to base + "popup-ad/download.html")
        s.pump()
        assertEquals(listOf(1), s.closed)                             // anúncio fechado
        val r = s.result!!
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        val ad = r.path.first { it.tabId == 1 }
        assertTrue(ad.decision!!, ad.decision!!.contains("fechada") && ad.decision!!.contains("propaganda"))
        assertEquals(2, r.path.first { it.kind == PathKind.NEW_TAB && it.tabId == 2 }.tabId)
    }

    @Test fun popupRulesRequireGestureTrustedOriginAndLimits() {
        val s = sim(); s.pages[base + "popup-flood/start.html"] = fx("popup-flood__start__t0")
        s.holdProbes = true
        s.start(base + "popup-flood/start.html"); s.pump()
        val o = base + "popup-flood/start.html"
        assertFalse("sem gesto", s.e.onPopupRequest(0, o, false))
        assertFalse("origem não confiável", s.e.onPopupRequest(0, "https://desconhecido.example.org/x", true))
        assertTrue(s.e.onPopupRequest(0, o, true)); assertTrue(s.e.onPopupRequest(0, o, true)); assertTrue(s.e.onPopupRequest(0, o, true))
        assertFalse("4º popup da mesma página (flood)", s.e.onPopupRequest(0, o, true))
        s.e.onTabOpened(1, 0, o)
        assertFalse("popup aberto por guia secundária", s.e.onPopupRequest(1, base + "popup-flood/lixo.html", true))
    }

    @Test fun maliciousPopupFloodNeverLoopsAndLegitimateLinkStillWins() {
        val s = sim()
        s.pages[base + "popup-flood/start.html"] = fx("popup-flood__start__t0")
        s.pages[base + "popup-flood/destino.html"] = fx("popup-flood__destino__t0")
        val lixo = fx("popup-flood__lixo__t0")
        s.pages[base + "popup-flood/lixo.html"] = lixo
        s.start(base + "popup-flood/start.html")
        val o = base + "popup-flood/start.html"
        val allowed = (1..10).count { s.e.onPopupRequest(0, o, true) }   // 10 tentativas de popup
        assertEquals(3, allowed)
        for (id in 1..3) { s.e.onTabOpened(id, 0, o); s.current[id] = base + "popup-flood/lixo.html" }
        for (id in 1..3) s.e.onScan(lixo, id)                           // todas classificadas como propaganda
        s.pump()
        assertEquals(listOf(1, 2, 3), s.closed)
        val r = s.result!!
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue("navegou poucas vezes", s.navigated.size <= 3)
    }

    @Test fun popupToUnknownDomainAsksAndDenialClosesTheTab() {
        val s = sim(); s.answerDomain = false
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0")
        s.start(base + "tabs/start.html"); s.pump(); s.advance(5_000)
        s.userOpensTabs(0, 1 to "https://dominio-novo.example.net/x")
        s.pump()
        assertEquals(listOf("dominio-novo.example.net"), s.asked)
        assertTrue(1 in s.closed)
        assertTrue(s.e.isActive)
    }

    @Test fun userCanMoveWorkToAnotherTabAndResumeAfterFinish() {
        val s = sim(); s.holdProbes = true
        s.pages[base + "tabs/start.html"] = fx("tabs__start__t0")
        s.pages[base + "tabs/etapa2.html"] = fx("tabs__etapa2__t0")
        s.start(base + "tabs/start.html"); s.pump(); s.advance(5_000)
        s.userOpensTabs(0, 1 to base + "tabs/etapa2.html")
        s.holdProbes = false
        s.e.stop(); s.pump()
        assertEquals(EngineState.FINISHED, s.e.state)
        s.e.setWorkTab(1); s.pump()                       // "Usar esta guia" depois do fim
        assertEquals(ResultState.VERIFIED_FILE, s.result?.state)
    }

    // ------------------------------------------------------------------ 2/3. dinâmico e temporizadores

    @Test fun timerPageWaitsForCountdownThenClicksOnlyWhenEnabled() {
        val s = sim()
        val u = base + "timer/start.html"
        s.seq[u] = listOf(fx("timer__start__t0"), fx("timer__start__t8"))
        s.pages[base + "timer/destino.html"] = fx("timer__destino__t0")
        s.onClick["Baixar arquivo"] = { s.pageNavigates(0, base + "timer/destino.html") }
        val r = s.run(u)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(listOf("Baixar arquivo"), s.clicked)               // um único clique
        assertTrue("só clicou depois de o botão ser liberado", s.scansWhenClicked.single() >= 2)
        assertTrue("verificações moderadas", s.scans <= 6)
        assertTrue(r.steps.any { it.note.contains("aguardando temporizador") })
    }

    @Test fun disabledButtonIsNeverClickedAndTimerBudgetEnds() {
        val s = sim()
        val u = base + "timer/start.html"
        s.pages[u] = fx("timer__start__t0")                              // o botão nunca é liberado
        val r = s.run(u)
        assertTrue(s.clicked.isEmpty())
        assertEquals(ResultState.NO_CANDIDATE, r.state)
        assertTrue(r.message, r.message.contains("Tempo de espera"))
        assertTrue(s.scans <= Limits().maxScansPerPage)
    }

    @Test fun dynamicButtonInsertedLaterIsClicked() {
        val s = sim()
        val u = base + "dynamic/start.html"
        s.seq[u] = listOf(fx("dynamic__start__t0"), fx("dynamic__start__t3"))
        s.pages[base + "dynamic/destino.html"] = fx("dynamic__destino__t0")
        s.onClick["Baixar arquivo"] = { s.pageNavigates(0, base + "dynamic/destino.html") }
        val r = s.run(u)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(listOf("Baixar arquivo"), s.clicked)
        assertTrue(s.scansWhenClicked.single() >= 2)
    }

    @Test fun dynamicLinkInsertedLaterIsFollowedAndVerified() {
        val s = sim()
        val u = base + "dynamic/link.html"
        s.seq[u] = listOf(fx("dynamic__link__t0"), fx("dynamic__link__t3"))
        val r = s.run(u)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue(s.clicked.isEmpty())                                  // link não precisa de clique
        assertFalse(s.navigated.any { it.contains("teste.bin") })
    }

    @Test fun domChangeRequestsRescanWithRateLimit() {
        val s = sim()
        s.page(base + "p", btn("Continuar").copy(disabled = true))
        s.start(base + "p"); s.step(3)                                   // página carregada e 1ª varredura feita
        assertEquals(EngineState.RUNNING, s.e.state)
        s.e.onDomChanged(0)
        assertTrue("nunca imediatamente: ${s.rescanDelays}", s.rescanDelays.last() >= 700)
        repeat(100) { s.e.onDomChanged(0) }
        s.pump()
        assertTrue("limite de varreduras por página", s.scans <= Limits().maxScansPerPage + 1)
    }

    // ------------------------------------------------------------------ cliques: ambiguidade e limites

    @Test fun ambiguousButtonsAreNotAutoClicked() {
        val s = sim()
        s.page(base + "amb", btn("Continuar"), btn("Próximo").copy(elementId = "2"))
        s.start(base + "amb"); s.pump()
        assertTrue(s.clicked.isEmpty()); assertTrue(s.highlighted.isEmpty())
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
    }

    @Test fun suspiciousOrAdOrHiddenButtonsAreNeverClicked() {
        for (c in listOf(
            btn("Download grátis casino bônus"), btn("Baixar agora").copy(context = " banner ad"),
            btn("Baixar agora").copy(visible = false), btn("Baixar agora").copy(disabled = true), btn("Entrar na VPN premium"),
        )) {
            val s = sim(); s.page(base + "x", c)
            s.start(base + "x"); s.pump()
            assertTrue("não deveria clicar em ${c.text}", s.clicked.isEmpty())
        }
    }

    @Test fun autoClickBudgetEscalatesToHumanClick() {
        val s = sim(Limits(maxAutoClicks = 1))
        s.page(base + "a", btn("Continuar")); s.page(base + "b", btn("Próximo"))
        s.onClick["Continuar"] = { s.pageNavigates(0, base + "b") }
        s.start(base + "a"); s.pump()
        assertEquals(listOf("Continuar"), s.clicked)
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
        assertEquals(listOf("Próximo"), s.highlighted)
    }

    @Test fun userConfirmationResumesAfterTapWithoutDomEffect() {
        val s = sim()
        s.page(base + "a", btn("Continuar")); s.start(base + "a"); s.pump(); s.advance(5_000)
        assertEquals(EngineState.WAITING_CLICK, s.e.state)
        s.e.userConfirmedResume(); s.pump()
        assertEquals(EngineState.RUNNING, s.e.state.takeIf { it != EngineState.FINISHED } ?: EngineState.RUNNING)
        assertEquals(listOf("Continuar"), s.clicked)                      // não clica de novo no mesmo botão
    }

    // ------------------------------------------------------------------ 4. verificação humana

    @Test fun humanCheckPausesThenResumesOnlyAfterPageReleases() {
        val s = sim()
        val u = base + "human/start.html"
        s.seq[u] = listOf(fx("human__start__t0"), fx("human__start__t0"), fx("human__start__solved"))
        s.pages[base + "human/destino.html"] = fx("human__destino__t0")
        s.start(u); s.pump()
        assertEquals(EngineState.WAITING_HUMAN, s.e.state)
        s.scanNow()                                                       // ainda há desafio: continua pausado
        assertEquals(EngineState.WAITING_HUMAN, s.e.state)
        assertTrue(s.clicked.isEmpty() && s.probed.isEmpty())
        s.scanNow(); s.pump()                                             // liberado
        val r = s.result!!
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.steps.any { it.kind == StepKind.CHALLENGE }); assertTrue(r.steps.any { it.kind == StepKind.RESUME })
    }

    @Test fun userConfirmationResumesEvenIfDetectionPersists() {
        val s = sim()
        val u = base + "h"
        s.page(u, lnk(base + "destino", "Continuar"), btn("Sou humano")); s.pages[u] = scan(u, lnk(base + "destino", "Continuar"), ch = ChallengeKind.CAPTCHA)
        s.page(base + "destino", lnk(fileUrl, "Baixar arquivo"))
        s.start(u); s.pump()
        assertEquals(EngineState.WAITING_HUMAN, s.e.state)
        s.e.userConfirmedResume(); s.pump()
        assertEquals(ResultState.VERIFIED_FILE, s.result?.state)
    }

    @Test fun humanWaitDoesNotCountTowardsLimitsAndKeepsTab() {
        val s = sim(Limits(maxTotalMs = 60_000, maxStepMs = 60_000))
        val u = base + "h"
        s.pages[u] = scan(u, ch = ChallengeKind.CAPTCHA)
        s.start(u); s.pump(); s.advance(300_000)
        assertEquals(EngineState.WAITING_HUMAN, s.e.state)
        assertNull(s.result)
    }

    // ------------------------------------------------------------------ combinado

    @Test fun comboButtonNewTabTimerHumanCheckFile() {
        val s = sim()
        s.pages[base + "combo/start.html"] = fx("combo__start__t0")
        s.seq[base + "combo/timer.html"] = listOf(fx("combo__timer__t0"), fx("combo__timer__t7"))
        s.seq[base + "combo/verifica.html"] = listOf(fx("combo__verifica__t0"), fx("combo__verifica__solved"))
        s.onClick["Continuar"] = { if (s.current[1] == base + "combo/timer.html") s.pageNavigates(1, base + "combo/verifica.html") }
        s.start(base + "combo/start.html"); s.pump(); s.advance(5_000)
        assertEquals(EngineState.WAITING_CLICK, s.e.state)                 // passo 1: precisa do toque humano
        s.userOpensTabs(0, 1 to base + "combo/timer.html")
        s.pump()                                                            // passo 2: guia nova com temporizador
        assertEquals(1, s.e.workTab)
        s.advance(1000)
        assertEquals("passo 3: pausa humana", EngineState.WAITING_HUMAN, s.e.state)
        s.scanNow(); s.pump()                                               // usuário concluiu
        val r = s.result!!
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        val kinds = r.path.map { it.kind }
        assertTrue(PathKind.START in kinds && PathKind.NEW_TAB in kinds && PathKind.FILE in kinds)
        assertTrue(r.path.any { it.tabId == 1 })
        assertTrue(r.steps.any { it.kind == StepKind.CHALLENGE })
    }

    // ------------------------------------------------------------------ motor: retomada, estados, loop

    @Test fun manualResumeAfterFinishStartsControlledStepAndKeepsHistory() {
        val s = sim()
        s.page(base + "a", lnk(base + "f/1.zip", "Download A"), lnk(base + "f/2.zip", "Download B"))
        s.probes[base + "f/1.zip"] = ProbeReport(ProbeResult.NetworkError("EOF", "RESPOSTA_VAZIA"), emptyList())
        s.file(base + "f/2.zip", "application/zip")
        val r1 = s.run(base + "a")
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, r1.state)
        val second = s.lastCandidates.first { it.url == base + "f/2.zip" }
        s.result = null
        assertTrue(s.e.resumeFromCandidate(second)); s.pump()
        val r2 = s.result!!
        assertEquals(ResultState.VERIFIED_FILE, r2.state)
        assertEquals(base + "f/2.zip", r2.url)
        assertTrue("histórico preservado", r2.steps.size > r1.steps.size)
        assertTrue(r2.steps.any { it.kind == StepKind.RESUME && it.note.contains("retomada manual") })
    }

    @Test fun manualResumeIsLimitedAndRefusesAds() {
        val s = sim(Limits(maxManualResumes = 1))
        s.page(base + "a", lnk(base + "f/1.zip", "Download A"))
        s.probes[base + "f/1.zip"] = ProbeReport(ProbeResult.NetworkError("EOF", "RESPOSTA_VAZIA"), emptyList())
        s.run(base + "a")
        val c = s.lastCandidates.first()
        s.result = null; assertTrue(s.e.resumeFromCandidate(c)); s.pump()
        s.result = null; assertFalse("limite de retomadas", s.e.resumeFromCandidate(c))
        val ad = c.copy(ad = true)
        assertFalse(s.e.resumeFromCandidate(ad))
    }

    @Test fun staleVerifyingStatusIsCleanedWhenAnalysisEnds() {
        val s = sim(); s.holdProbes = true
        s.page(base + "a", lnk(base + "f/1.zip", "Download A"))
        s.start(base + "a"); s.pump()
        s.e.stop(); s.pump()
        val r = s.result!!
        assertTrue(r.candidates.none { it.status.contains("verificando metadados") })
        assertTrue(r.candidates.any { it.status.contains("interrompida") })
    }

    @Test fun loopHasItsOwnState() {
        val s = sim()
        s.page(base + "a", lnk(base + "b", "Continuar")); s.page(base + "b", lnk(base + "a", "Continuar"))
        val r = s.run(base + "a")
        assertEquals(ResultState.LOOP_DETECTED, r.state); assertEquals("Loop detectado", r.state.label)
    }

    @Test fun jsRedirectInsideClickHandlerIsNotTreatedAsAutomatic() {
        // regressão: página com temporizador não pode ser "pulada" por location.href dentro do handler do botão
        val t0 = fx("timer__start__t0")
        assertTrue(t0.candidates.none { it.source == "js-redirect" })
        assertTrue(fx("dynamic__start__t0").candidates.none { it.source == "js-redirect" })
    }
}
