package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/** v0.4.3: seleção contextual (objetivo da página/usuário), arquivo válido de conteúdo diferente, hospedagens externas. */
class V5ContextTest {
    private val base = "https://raw.githack.com/T-Justino/PS4/gh-pages/v5/"
    private val fb = "https://cdn.jsdelivr.net/gh/T-Justino/PS4@gh-pages/v5/files/"
    private fun fx(name: String) = PageScanner.parse(javaClass.classLoader!!.getResource("scans/v5__$name.json")!!.readText())!!

    private fun mimeOf(u: String) = when (u.substringAfterLast('.')) {
        "mp4" -> "video/mp4"; "jpg" -> "image/jpeg"; "zip" -> "application/zip"; else -> "application/octet-stream"
    }
    private fun sim(limits: Limits = Limits()): Sim {
        val s = Sim(limits); s.answerDomain = true
        listOf("super-teste-app.zip", "guia-download.mp4", "guidedownloadgame.mp4", "filme-teste.mp4", "alpha-station.zip", "beta-runner.zip",
            "gamma-tools.zip", "tutorial-delta.mp4", "capa-delta.jpg", "mario-world.zip", "zelda-quest.zip", "file123.mp4", "setup-super-teste.zip")
            .forEach { s.file(fb + it, mimeOf(it), 50_000) }
        return s
    }
    private fun link(url: String, text: String) = RawCandidate(url, text, "a", "href", false, "", "", null, true)
    private fun scan(url: String, title: String, vararg c: RawCandidate, desc: String = "") =
        PageScan(url, title, c.toList(), null, null, description = desc, heading = title)

    // ---------------------------------------------------------------- GoalContext / Relevance (unidade)
    @Test fun goalIsInferredConservativelyFromTitleAndDescription() {
        val g = GoalContext.build("SNES Station PS4 PKG - Site.com", "SNES Station PS4 PKG", "Download SNES Station for PS4", null)
        assertEquals(listOf("snes", "station"), g.nameTokens); assertEquals(setOf("pkg"), g.formats)
        assertTrue(g.informative); assertFalse(g.userSpecified)
        val plain = GoalContext.build("Hetzner", "", "", null)
        assertFalse("1 palavra e nenhum formato: sem contexto suficiente", plain.informative); assertTrue(plain.formats.isEmpty())
        assertTrue(GoalContext.build("Filme Teste Livre (MP4)", "", "", null).allowedMedia.contains(MediaFamily.VIDEO))
        assertTrue("sem palavra de formato, nada é inferido", GoalContext.build("Alpha Station Deluxe", "", "", null).formats.isEmpty())
    }

    @Test fun userPreferenceOverridesInferenceAndParsesNameAndFormat() {
        val g = GoalContext.build("Coleção de Jogos Retro", "", "", "zelda quest .pkg")
        assertTrue(g.userSpecified); assertEquals(listOf("zelda", "quest"), g.nameTokens); assertEquals(setOf("pkg"), g.formats)
        assertEquals(setOf("zip"), GoalContext.build("x y z", "", "", "zip").formats)
        assertFalse(GoalContext.build("Alpha Station PKG", "", "", "   ").userSpecified)
    }

    @Test fun relevanceIsSeparateFromTechnicalScore() {
        val g = GoalContext.build("Super Teste App PKG", "", "", null)
        val pol = DomainPolicy().also { it.trust("site.com") }
        val raw = RawCandidate("https://site.com/files/guidedownloadgame.mp4", "Assistir guia", "a", "href", false, "", "", null, true)
        val base = DownloadHeuristics.score(raw, "site.com", pol); val c = Relevance.apply(base, g)
        assertEquals(base.technical, c.technical); assertTrue(c.relevance < 0); assertEquals(c.technical + c.relevance, c.score)
        assertTrue(c.relevanceReasons.any { it.contains("tutorial") })
        val pkg = Relevance.apply(DownloadHeuristics.score(RawCandidate("https://site.com/super-teste-app.zip", "Download Super Teste App", "a", "href", false, "", "", null, true), "site.com", pol), g)
        assertTrue(pkg.relevance > 0 && pkg.score > c.score + 60)
        assertSame("sem contexto: nada muda", base, Relevance.apply(base, null))
    }

    @Test fun compatibilityVerdicts() {
        val app = GoalContext.build("Super Teste App PKG", "", "", null)
        fun v(g: GoalContext?, name: String, mime: String = "application/octet-stream", text: String = "") = Relevance.compat(g, FileFacts("https://x.com/$name", name, mime, text)).verdict
        assertEquals(Verdict.MISMATCH, v(app, "guidedownloadgame.mp4", "video/mp4"))          // tutorial colado no nome
        assertEquals(Verdict.MISMATCH, v(app, "intro.mp4", "video/mp4"))                      // vídeo ≠ pkg
        assertEquals(Verdict.COMPATIBLE, v(app, "super-teste-app.zip", "application/zip"))
        assertEquals(Verdict.UNKNOWN, v(app, "a1b2c3.zip", "application/zip"))                // nome opaco: não afirma nada
        val video = GoalContext.build("Filme Teste Livre (MP4)", "", "", null)
        assertEquals(Verdict.COMPATIBLE, v(video, "filme-teste.mp4", "video/mp4"))
        assertEquals(Verdict.UNKNOWN, v(null, "x.mp4", "video/mp4"))                          // sem contexto: não rejeita
        assertEquals(Verdict.UNKNOWN, v(GoalContext.build("Hetzner", "", "", null), "100MB.bin"))
        val user = GoalContext.build("Retro", "", "", "doom")
        assertEquals(Verdict.MISMATCH, v(user, "mario-world.zip", "application/zip"))
    }

    // ---------------------------------------------------------------- cenários do motor
    @Test fun appPageWithTutorialVideoPrefersThePackage() {
        val s = sim(); s.pages[base + "app/index.html"] = fx("app")
        val r = s.run(base + "app/index.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "super-teste-app.zip", r.url)
        assertTrue("o vídeo tutorial nem é verificado", s.probed.none { it.endsWith(".mp4") })
        assertFalse("a página de guia não é seguida", s.navigated.any { it.endsWith("guide.html") })
        val guide = r.candidates.first { it.url!!.endsWith("guide.html") }
        assertTrue("guia com contexto negativo: ${guide.score}", guide.score < 40)
        assertTrue("objetivo: ${r.goal}", r.goal!!.contains("pkg"))
        assertTrue(r.steps.any { it.note.contains("objetivo da busca") && it.note.contains("pkg") })
        assertTrue(r.steps.map { it.note }.toString(), r.steps.any { it.kind == StepKind.FOLLOW && it.note.contains("técnica") && it.note.contains("contexto") })
    }

    @Test fun validButDifferentFileDoesNotEndTheSearchAsSuccess() {
        val s = sim(); val u = base + "app/p1"
        s.pages[u] = scan(u, "Super Teste App PKG - Site", link(fb + "file123.mp4", "Download"), link(base + "app/p2", "Next page"))
        s.pages[base + "app/p2"] = scan(base + "app/p2", "Página 2", link(fb + "setup-super-teste.zip", "Download Super Teste App"))
        val r = s.run(u)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "setup-super-teste.zip", r.url)
        assertEquals(1, r.mismatches.size); assertTrue(r.mismatches[0].contains("file123.mp4"))
        val mp4 = r.candidates.first { it.url == fb + "file123.mp4" }
        assertEquals("Arquivo válido — conteúdo diferente", mp4.status); assertEquals(LinkClass.WRONG_CONTENT, mp4.kind)
        assertTrue(r.path.any { it.linkClass == LinkClass.WRONG_CONTENT })
        assertTrue("evidência só do arquivo compatível", r.evidence.none { it.contains("file123") } && r.evidence.isNotEmpty())
    }

    @Test fun pageWhoseGoalIsAVideoConfirmsNormally() {
        val s = sim(); s.pages[base + "video/index.html"] = fx("video")
        val r = s.run(base + "video/index.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "filme-teste.mp4", r.url)
        assertEquals("video/mp4", r.mimeType); assertTrue(r.mismatches.isEmpty())
    }

    @Test fun hostButtonsStartDisabledAndAreOnlyFollowedWhenEnabled() {
        val s = sim(); val u = base + "hosts/index.html"
        s.seq[u] = listOf(fx("hosts__t0"), fx("hosts__t6"))
        s.pages[base + "hosts/host-mega.html"] = fx("host_mega"); s.pages[base + "hosts/host-mediafire.html"] = fx("host_mediafire")
        val r = s.run(u)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "beta-runner.zip", r.url)
        assertTrue("nunca clicou em botão desabilitado nem em botão de hospedagem sem URL", s.clicked.isEmpty())
        assertTrue(r.steps.any { it.note.contains("aguardando temporizador/liberação") })      // esperou a habilitação normal
        assertEquals(base + "hosts/host-mega.html", s.probed.first())                          // só depois de habilitado
        assertTrue(r.steps.any { it.note.contains("hospedagem externa") || r.candidates.isNotEmpty() })
        assertTrue(s.scans >= 3)
    }

    @Test fun disabledHostLinksAreNeverFollowedWhileDisabled() {
        val s = sim(); val u = base + "hosts/index.html"
        s.pages[u] = fx("hosts__t0")                                                            // nunca habilita
        val r = s.run(u)
        assertTrue(s.probed.isEmpty() && s.clicked.isEmpty())
        assertNotEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.message, r.message.contains("Tempo de espera"))
    }

    @Test fun manyValidFilesButOnlyOneRelatedToTheTitle() {
        val s = sim(); s.pages[base + "multi/index.html"] = fx("multi")
        val r = s.run(base + "multi/index.html")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "alpha-station.zip", r.url)
        assertEquals(listOf(fb + "alpha-station.zip"), s.probed)                                // gamma/beta nem foram consultados
    }

    @Test fun pageWithoutCompatibleFileDoesNotInventAResult() {
        val s = sim(); s.pages[base + "none/index.html"] = fx("none"); s.pages[base + "none/guide.html"] = fx("none_guide")
        val r = s.run(base + "none/index.html")
        assertEquals(r.message, ResultState.TARGET_NOT_FOUND, r.state); assertEquals("Arquivo desejado não encontrado", r.state.label)
        assertTrue(r.evidence.isEmpty()); assertNull("não apresenta tutorial/imagem como resultado", r.url)
        assertTrue("melhores candidatos preservados", r.candidates.size >= 3 && r.candidates.all { it.url != null })
        assertTrue(r.message.contains("NÃO verificado") || r.message.contains("não verificados"))
    }

    @Test fun userPreferenceSelectsTheNamedFile() {
        val s = sim(); s.pages[base + "user/index.html"] = fx("user")
        val r = s.run(base + "user/index.html", "zelda")
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state); assertEquals(fb + "zelda-quest.zip", r.url)
        assertEquals(listOf(fb + "zelda-quest.zip"), s.probed); assertTrue(r.goal!!.contains("usuário"))
    }

    @Test fun userPreferenceThatMatchesNothingEndsAsNotFoundWithMismatchesListed() {
        val s = sim(); s.pages[base + "user/index.html"] = fx("user")
        val r = s.run(base + "user/index.html", "doom")
        assertEquals(r.message, ResultState.TARGET_NOT_FOUND, r.state)
        assertEquals(2, r.mismatches.size); assertTrue(r.evidence.isEmpty())
        assertTrue(r.candidates.count { it.status == "Arquivo válido — conteúdo diferente" } == 2)
        // formato pedido ≠ formato dos arquivos
        val s2 = sim(); s2.pages[base + "user/index.html"] = fx("user")
        assertEquals(ResultState.TARGET_NOT_FOUND, s2.run(base + "user/index.html", ".mp4").state)
    }

    @Test fun mismatchBudgetIsBoundedByLimits() {
        val s = sim(Limits(maxMismatches = 1)); s.pages[base + "user/index.html"] = fx("user")
        val r = s.run(base + "user/index.html", "doom")
        assertEquals(ResultState.TARGET_NOT_FOUND, r.state); assertTrue(r.mismatches.size <= 2)
    }

    @Test fun externalHostingDomainStillNeedsHumanConfirmationAndAdsStayBlocked() {
        val s = sim(); s.answerDomain = null; val u = base + "x"
        s.pages[u] = scan(u, "Alpha Station PKG", link("https://www.mediafire.com/file/abc/alpha-station.zip", "Mediafire"),
            RawCandidate("https://ads.doubleclick.net/c", "Download now Mediafire", "a", "href", false, "", " banner ad", null, true))
        s.start(u); s.pump()
        assertEquals(listOf("mediafire.com").map { "www.$it" }, s.asked)
        assertTrue("nada é consultado antes da confirmação humana", s.probed.isEmpty())
        assertEquals(EngineState.WAITING_CONFIRMATION, s.e.state)
        assertTrue((s.navigated + s.probed).none { it.contains("doubleclick") })
    }

    @Test fun dynamicallyAddedMatchingLinkIsReevaluatedAgainstTheGoal() {
        val s = sim(); val u = base + "dyn"
        s.seq[u] = listOf(
            scan(u, "Alpha Station PKG").copy(waitHint = true),                                  // a página ainda está montando os links
            scan(u, "Alpha Station PKG", link(fb + "gamma-tools.zip", "Download Gamma Tools"),
                RawCandidate(fb + "alpha-station.zip", "Download Alpha Station", "a", "href", false, "", "", null, true, dynamic = true)),
        )
        val r = s.run(u)
        assertEquals(fb + "alpha-station.zip", r.url)                                           // o link novo e relacionado venceu
    }
}
