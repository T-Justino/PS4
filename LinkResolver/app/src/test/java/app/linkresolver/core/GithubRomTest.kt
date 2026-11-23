package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

/** Repositórios GitHub (ex.: retrobrews/snes-games): ROMs, páginas /blob/, link Raw e validação HTTP. */
class GithubRomTest {
    private val dirUrl = "https://github.com/retrobrews/snes-games"
    private val blobUrl = "$dirUrl/blob/master/astrohawk.smc"
    private val rawUrl = "$dirUrl/raw/master/astrohawk.smc"
    private val finalRaw = "https://raw.githubusercontent.com/retrobrews/snes-games/master/astrohawk.smc"

    private fun scan(name: String) = PageScanner.parse(javaClass.classLoader!!.getResource("scans/$name.json")!!.readText())!!
    private val policy = DomainPolicy().also { it.trust("github.com") }
    private fun score(url: String, text: String = "", ctx: String = "") =
        DownloadHeuristics.score(RawCandidate(url, text, "a", "href", false, "", ctx, null, true), "github.com", policy)

    // ---------------------------------------------------------------- URLs
    @Test fun githubUrlRecognition() {
        assertTrue(GithubUrls.isBlobView(blobUrl))
        assertTrue(GithubUrls.isBlobView("$dirUrl/blob/main/pasta/sub/x.zip?plain=1"))
        assertFalse(GithubUrls.isBlobView("$dirUrl/tree/master/pasta")); assertFalse(GithubUrls.isBlobView(rawUrl))
        assertTrue(GithubUrls.isRawLink(rawUrl)); assertTrue(GithubUrls.isRawLink("$dirUrl/raw/refs/heads/master/a.smc?download="))
        assertTrue(GithubUrls.isRawLink(finalRaw)); assertFalse(GithubUrls.isRawLink(blobUrl))
        assertTrue(GithubUrls.isReleaseAsset("$dirUrl/releases/download/v1/a.zip"))
        assertEquals(rawUrl, GithubUrls.derivedRaw(blobUrl)); assertEquals("$dirUrl/raw/main/p/x.zip", GithubUrls.derivedRaw("$dirUrl/blob/main/p/x.zip?plain=1#L1"))
        assertNull(GithubUrls.derivedRaw("$dirUrl/tree/master"))
        assertEquals(UrlSafety.Verdict.Ok, UrlSafety.check(GithubUrls.derivedRaw(blobUrl)!!))
    }

    @Test fun romExtensionsAreRecognizedButMarkdownIsNot() {
        for (e in listOf("smc", "sfc", "nes", "gba", "gb", "gbc", "n64", "z64", "v64")) {
            assertTrue(e, DownloadHeuristics.looksLikeFileUrl("https://x.example.com/a/jogo.$e"))
        }
        assertFalse(DownloadHeuristics.looksLikeFileUrl("https://x.example.com/README.md"))
    }

    @Test fun blobPageWithRomExtensionIsAViewPageNotAFile() {
        assertFalse("página de visualização, não arquivo", DownloadHeuristics.looksLikeFileUrl(blobUrl))
        val c = score(blobUrl, "astrohawk.smc", " react-directory-row")
        assertEquals(LinkClass.FILE_VIEW_PAGE, c.linkClass)
        assertTrue(c.score >= Limits().autoScoreThreshold); assertTrue(c.reasons.any { it.contains("/blob/") })
        assertTrue(c.reasons.any { it.contains("nome de arquivo") }); assertTrue(c.reasons.any { it.contains("listagem") })
        val md = score("$dirUrl/blob/master/README.md", "README.md")
        assertEquals(LinkClass.PAGE, md.linkClass); assertTrue(md.score < Limits().autoScoreThreshold)
        assertTrue(score("$dirUrl/tree/master/pasta", "pasta").score < 40)
    }

    @Test fun rawLinkScoresFarHigherThanViewPageAndIsAFileCandidate() {
        val raw = score(rawUrl, "Raw file content"); val view = score(blobUrl, "astrohawk.smc")
        assertEquals(LinkClass.FILE_CANDIDATE, raw.linkClass)
        assertTrue(raw.score > view.score + 40); assertTrue(raw.reasons.any { it.contains("Raw") })
        assertTrue(score("$dirUrl/raw/master/x.bin", "View raw").reasons.any { it.contains("botão Raw") })
    }

    @Test fun romNamesWithSuspiciousWordsAreNotTreatedAsAds() {
        val c = score("$dirUrl/blob/master/Super%20Bet%20Win.smc", "Super Bet Win.smc")
        assertTrue(c.reasons.toString(), c.reasons.none { it.contains("suspeito") }); assertTrue(c.score >= 40)
        val ad = DownloadHeuristics.score(RawCandidate("https://ads.doubleclick.net/c", "Win a prize! Casino bonus", "a", "href", false, "", " banner ad", null, true), "github.com", policy)
        assertTrue(ad.ad && ad.score < 0)
    }

    @Test fun scannerExtensionListStaysInSyncWithKotlin() {
        for (e in DownloadHeuristics.FILE_EXTENSIONS) assertTrue("scanner JS sem .$e", PageScanner.SCRIPT.contains("|$e|"))
    }

    // ---------------------------------------------------------------- scanner (DOM real do Chromium sobre HTML estilo GitHub)
    @Test fun directoryScanKeepsEveryRomEvenAtTheEndOfAPageWithMoreThan150Links() {
        val d = scan("gh__dir")
        assertTrue("a página tem mais de 150 links", d.totalCandidates > 150)
        val urls = d.candidates.mapNotNull { it.url }
        for (n in listOf("astrohawk.smc", "blt.sfc", "bucket.smc", "zzz-last.smc")) assertTrue(n, urls.any { it.endsWith("/$n") })
        assertEquals(201, urls.count { Regex("""\.(smc|sfc|nes|gba|gb|gbc|n64|z64|v64)$""").containsMatchIn(it) })
        assertTrue(d.candidates.size < d.totalCandidates + 1)
    }

    @Test fun everyRomOfTheDirectoryIsScoredAsPromisingViewPage() {
        val d = scan("gh__dir")
        val scored = d.candidates.map { DownloadHeuristics.score(it, "github.com", policy) }
        val roms = scored.filter { it.url?.contains("/blob/") == true && DownloadHeuristics.extensionOf(it.url!!) in DownloadHeuristics.FILE_EXTENSIONS }
        assertEquals(201, roms.size)
        assertTrue(roms.all { it.linkClass == LinkClass.FILE_VIEW_PAGE && it.score >= 60 })
        assertTrue("duplicata escondida (tela larga) + visível (tela pequena): fica a visível", roms.all { it.raw.visible })
        val noise = scored.filter { it.url?.contains("/blob/") == true && it.url!!.endsWith("README.md") || it.url?.contains("/tree/") == true }
        assertTrue(noise.all { it.score < 40 })
        assertTrue(scored.first { it.url!!.contains("doubleclick") }.ad)
    }

    @Test fun blobPageScansExposeGithubsOwnRawLink() {
        val a = scan("gh__blob_raw_button").candidates.filter { it.url?.contains("/raw/") == true }
        assertTrue(a.any { it.text == "Raw file content" } && a.any { it.text == "Download raw file" })
        assertTrue(scan("gh__blob_view_raw").candidates.any { it.text == "View raw" && it.url!!.contains("/raw/") })
        assertTrue(scan("gh__blob_no_raw").candidates.none { it.url?.contains("/raw/") == true })
    }

    // ---------------------------------------------------------------- motor: diretório → /blob/ → Raw → HEAD
    private fun sim(blobScan: String, trustedRaw: Boolean = false): Sim {
        val s = Sim(); s.answerDomain = true
        s.pages[dirUrl] = scan("gh__dir")
        if (blobScan.isNotEmpty()) s.pages[blobUrl] = scan(blobScan)
        s.probeFn = { url, trusted ->
            if (!url.startsWith(rawUrl)) null            // o botão "Download raw file" usa ?download=
            else if (trustedRaw || "githubusercontent.com" in trusted) ProbeReport(
                ProbeResult.File(finalRaw, 200, "application/octet-stream", 262_144, null, "HEAD", true), listOf("[chrome-h2 HEAD] HTTP 200"),
                listOf(RedirectHop(302, rawUrl, finalRaw)))
            else ProbeReport(ProbeResult.NeedsDomain("raw.githubusercontent.com", finalRaw), emptyList())
        }
        return s
    }

    @Test fun directoryToBlobToRawIsConfirmedByHeadWithHumanDomainConfirmation() {
        val s = sim("gh__blob_raw_button")
        val r = s.run(dirUrl)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertEquals(finalRaw, r.url); assertEquals("astrohawk.smc", r.fileName); assertEquals("application/octet-stream", r.mimeType)
        assertEquals("raw.githubusercontent.com pede confirmação humana", listOf("raw.githubusercontent.com"), s.asked)
        assertTrue("o app não navega até o arquivo", s.navigated.none { it.contains("/raw/") || it.contains("githubusercontent") })
        assertTrue(s.probed.indexOf(blobUrl) in 0 until s.probed.indexOfFirst { it.startsWith(rawUrl) })     // /blob/ verificada (HTML), depois o Raw
        assertTrue(r.path.any { it.code == 302 }); assertTrue(r.evidence.any { it.startsWith("HEAD 200") })
        val view = r.candidates.first { it.url == blobUrl }
        assertEquals("o /blob/ nunca vira arquivo confirmado", LinkClass.FILE_VIEW_PAGE, view.kind)
    }

    @Test fun providedRawLinkIsPreferredOverDerivedOne() {
        val s = sim("gh__blob_view_raw"); val r = s.run(dirUrl)
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.steps.none { it.note.contains("derivando") })
    }

    @Test fun whenGithubExposesNoRawLinkTheRawUrlIsDerivedFromBlobAfterTheFirstScan() {
        val s = sim("gh__blob_no_raw"); val r = s.run(dirUrl)
        assertEquals(r.message, ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.steps.any { it.note.contains("derivando de /blob/") })
        assertFalse("não vai a arquivos irmãos da árvore lateral", s.navigated.any { it.endsWith("blt.sfc") || it.endsWith("bucket.smc") })
        assertEquals(1, s.navigated.count { it.contains("/blob/") })
    }

    @Test fun extensionAloneNeverConfirmsAFile() {
        val s = Sim(); s.answerDomain = true
        s.pages[dirUrl] = scan("gh__dir"); s.pages[blobUrl] = scan("gh__blob_raw_button")
        s.probeFn = { url, _ -> if (url.startsWith(rawUrl)) ProbeReport(ProbeResult.Page(rawUrl, 200, "text/html"), emptyList()) else null }  // HTML, não arquivo
        s.start(dirUrl); s.pump(); s.advance(60_000)                 // o destino é HTML: nada a confirmar; o tempo da etapa acaba
        val r = s.result!!
        assertNotEquals(ResultState.VERIFIED_FILE, r.state); assertTrue(r.evidence.isEmpty())
        val s2 = Sim(); s2.answerDomain = true
        s2.pages[dirUrl] = scan("gh__dir"); s2.pages[blobUrl] = scan("gh__blob_raw_button")
        s2.probeFn = { url, _ -> if (url.startsWith(rawUrl)) ProbeReport(ProbeResult.NetworkError("EOF", "RESPOSTA_VAZIA"), emptyList()) else null }
        val r2 = s2.run(dirUrl)
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, r2.state); assertTrue(r2.evidence.isEmpty())
    }

    @Test fun deniedRawDomainKeepsUnverifiedLinkAndAdsAreIgnored() {
        val s = sim("gh__blob_raw_button"); s.answerDomain = false
        val r = s.run(dirUrl)
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, r.state)
        assertTrue(r.url!!.startsWith(rawUrl))
        assertTrue((s.navigated + s.probed).none { it.contains("doubleclick") })
    }

    @Test fun genericBehaviourStaysTheSameForOtherSites() {
        assertEquals(LinkClass.FILE_CANDIDATE, score("https://cdn.exemplo.com/a/b.zip", "Baixar").linkClass)
        assertEquals(LinkClass.PAGE, score("https://exemplo.com/sobre", "Sobre").linkClass)
        assertTrue(score("https://exemplo.com/a/b.zip", "Baixar").score >= 80)
    }
}
