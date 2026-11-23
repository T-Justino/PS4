package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

class HeuristicsTest {
    private fun cand(url: String?, text: String, dl: Boolean = false, ctx: String = "", vis: Boolean = true, src: String = "href") =
        RawCandidate(url, text, "a", src, dl, "", ctx, null, vis)

    private val policy = DomainPolicy().also { it.trust("site.com") }

    @Test fun fileLinkScoresHigh() {
        val s = DownloadHeuristics.score(cand("https://cdn.site.com/a/file.zip", "Download"), "site.com", policy)
        assertTrue(s.score >= 80); assertTrue(s.safe); assertTrue(s.trusted)
    }

    @Test fun adsAreRejected() {
        val s = DownloadHeuristics.score(cand("https://ads.doubleclick.net/x", "Download now"), "site.com", policy)
        assertTrue(s.ad); assertTrue(s.score < 0)
        val s2 = DownloadHeuristics.score(cand("https://other.com/x", "Win a prize! Casino bonus", ctx = " banner ad"), "site.com", policy)
        assertTrue(s2.score < 0)
    }

    @Test fun hiddenAndUnsafeAreLow() {
        val s = DownloadHeuristics.score(cand("http://192.168.0.1/a.zip", "Download"), "site.com", policy)
        assertFalse(s.safe)
        val h = DownloadHeuristics.score(cand("https://site.com/x", "Continue", vis = false), "site.com", policy)
        assertTrue(h.score < 40)
    }

    @Test fun fileNames() {
        assertEquals("a b.zip", DownloadHeuristics.estimateFileName("https://x.com/dl", "attachment; filename=\"a b.zip\""))
        assertEquals("ñ.zip", DownloadHeuristics.estimateFileName("https://x.com/dl", "attachment; filename*=UTF-8''%C3%B1.zip"))
        assertEquals("g.iso", DownloadHeuristics.estimateFileName("https://x.com/p/g.iso?x=1", null))
        assertEquals("evil.exe", DownloadHeuristics.estimateFileName("https://x.com/dl", "attachment; filename=\"../../evil.exe\"")?.substringAfterLast('_'))
        assertEquals("f.rar", DownloadHeuristics.estimateFileName("https://x.com/get?file=f.rar", null))
    }

    @Test fun mimeAndRegistrable() {
        assertTrue(DownloadHeuristics.isFileMime("application/zip"))
        assertFalse(DownloadHeuristics.isFileMime("text/html; charset=utf-8"))
        assertEquals("site.co.uk", DomainPolicy.registrable("cdn.a.site.co.uk"))
        assertEquals("site.com.br", DomainPolicy.registrable("www.site.com.br"))
        assertEquals("site.com", DomainPolicy.registrable("a.b.site.com"))
    }

    @Test fun scannerParsesEvaluateJavascriptOutput() {
        val inner = """{"url":"https://s.com/","title":"t","cands":[{"url":"https://s.com/a.zip","text":"Baixar","tag":"a","source":"href","dl":false,"rel":"","ctx":"","id":"1","vis":true},{"url":null,"text":"Go","tag":"button","source":"button","dl":false,"rel":"","ctx":"","id":"2","vis":true}],"challenge":"CAPTCHA","hint":"x"}"""
        val encoded = "\"" + inner.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
        val scan = PageScanner.parse(encoded)!!
        assertEquals(2, scan.candidates.size)
        assertNull(scan.candidates[1].url)
        assertEquals(ChallengeKind.CAPTCHA, scan.challenge)
        assertNull(PageScanner.parse("null"))
    }
}

class HeuristicsV4Test {
    private val policy = DomainPolicy().also { it.trust("site.com") }
    private fun scored(c: RawCandidate) = DownloadHeuristics.score(c, "site.com", policy)
    private fun button(text: String, dis: Boolean = false, dyn: Boolean = false, vis: Boolean = true, ctx: String = "") =
        RawCandidate(null, text, "button", "button", false, "", ctx, "1", vis, dis, dyn)

    @Test fun disabledButtonScoresLowAndIsNotEligible() {
        val d = scored(button("Baixar arquivo", dis = true)); val e = scored(button("Baixar arquivo"))
        assertTrue(d.score < e.score - 40)
        assertFalse(DownloadHeuristics.isAutoClickEligible(d, 20)); assertTrue(DownloadHeuristics.isAutoClickEligible(e, 20))
    }

    @Test fun dynamicBonusAndReasons() {
        val c = scored(button("Continuar", dyn = true))
        assertTrue(c.reasons.any { it.contains("dinamicamente") }); assertTrue(c.score >= 20)
    }

    @Test fun eligibilityRules() {
        assertTrue(DownloadHeuristics.isAutoClickEligible(scored(button("Continuar")), 20))
        assertFalse(DownloadHeuristics.isAutoClickEligible(scored(button("Sou humano")), 20))
        assertFalse(DownloadHeuristics.isAutoClickEligible(scored(button("Continuar", ctx = " ad banner")), 20))
        assertFalse(DownloadHeuristics.isAutoClickEligible(scored(button("Continuar", vis = false)), 20))
        assertFalse(DownloadHeuristics.isAutoClickEligible(scored(button("Assine premium e baixe")), 20))
        val link = scored(RawCandidate("https://site.com/x", "Continuar", "a", "href", false, "", "", "1", true))
        assertFalse("link com URL não é clique", DownloadHeuristics.isAutoClickEligible(link, 20))
    }

    @Test fun portugueseAndEnglishStepWords() {
        for (t in listOf("Continuar", "Próximo", "Prosseguir", "Baixar arquivo", "Download", "Next", "Continue", "Proceed")) {
            assertTrue(t, DownloadHeuristics.isStepText(t))
        }
        assertFalse(DownloadHeuristics.isStepText("Política de privacidade"))
    }

    @Test fun scannerParsesNewFields() {
        val raw = "\"" + """{"url":"https://s.com/","title":"t","cands":[{"url":null,"text":"Baixar","tag":"button","source":"button","dl":false,"rel":"","ctx":"","id":"1","vis":true,"dis":true,"dyn":true,"blank":true}],"challenge":null,"hint":null,"wait":true,"cd":7,"ad":true}""".replace("\"", "\\\"") + "\""
        val s = PageScanner.parse(raw)!!
        assertEquals(7, s.countdownSec); assertTrue(s.adLike); assertTrue(s.waitHint)
        val c = s.candidates.single(); assertTrue(c.disabled && c.dynamic && c.opensTab)
    }

    @Test fun realTimerFixtureHasCountdownAndDisabledButton() {
        val t0 = PageScanner.parse(javaClass.classLoader!!.getResource("scans/v4__timer__start__t0.json")!!.readText())!!
        assertTrue(t0.countdownSec >= 5); assertTrue(t0.waitHint)
        assertTrue(t0.candidates.single { it.text == "Baixar arquivo" }.disabled)
        val t8 = PageScanner.parse(javaClass.classLoader!!.getResource("scans/v4__timer__start__t8.json")!!.readText())!!
        val b = t8.candidates.single { it.text == "Baixar arquivo" }; assertFalse(b.disabled); assertTrue(b.dynamic)
    }
}
