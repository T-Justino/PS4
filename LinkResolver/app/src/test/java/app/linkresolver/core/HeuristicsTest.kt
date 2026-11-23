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
