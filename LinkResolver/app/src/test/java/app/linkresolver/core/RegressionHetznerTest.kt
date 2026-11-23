package app.linkresolver.core

import app.linkresolver.core.ResolverEngineTest.Fake
import org.junit.Assert.*
import org.junit.Test

/** Regressão do 1º teste real: https://fsn1-speed.hetzner.com/ → /100MB.bin → net::ERR_EMPTY_RESPONSE. */
class RegressionHetznerTest {
    private val site = "https://fsn1-speed.hetzner.com/"
    private val f100 = "https://fsn1-speed.hetzner.com/100MB.bin"
    private var now = 0L

    private fun c(name: String) = RawCandidate("https://fsn1-speed.hetzner.com/$name", name, "a", "href", false, "", "", null, true)
    private fun listing() = PageScan(site, "Hetzner", listOf(c("100MB.bin"), c("1GB.bin"), c("10GB.bin")), null, null)
    private fun setup(f: Fake): ResolverEngine {
        val e = ResolverEngine(Limits(), { now }, f)
        e.start(site)
        e.onPageStarted(site); e.onPageFinished(site)
        e.onScan(listing())
        return e
    }

    @Test fun fileCandidateScores70AndIsProbedBeforeNavigating() {
        val f = Fake(); val e = setup(f)
        assertEquals(listOf(f100), f.probes)
        assertEquals(1, f.navigated.size)          // ainda não navegou até o arquivo
        assertEquals(EngineState.RUNNING, e.state)
    }

    @Test fun headConfirmsFileWithoutDownloading() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.File(f100, 200, "application/octet-stream", 104_857_600, null, "HEAD", true))
        val r = f.result!!
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertEquals(f100, r.url); assertEquals("100MB.bin", r.fileName)
        assertEquals(104_857_600L, r.sizeBytes); assertEquals("application/octet-stream", r.mimeType)
        assertEquals(1, f.navigated.size)
        assertTrue(r.evidence.any { it.startsWith("HEAD 200") })
        assertEquals(70, r.candidateScore)
    }

    @Test fun inconclusiveProbeNeverNavigatesToBinaryAndKeepsLink() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.NetworkError("EOFException: unexpected end of stream", "RESPOSTA_VAZIA"),
            listOf("[chrome-h2 HEAD] FALHA RESPOSTA_VAZIA: EOFException: unexpected end of stream"))
        val r = f.result!!
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, r.state)
        assertEquals(1, f.navigated.size)                 // NÃO navegou até o .bin
        assertEquals(f100, r.url)                         // link preservado (copiável)
        assertEquals(70, r.candidateScore)
        assertTrue(r.message.contains("NÃO verificado"))
        assertTrue(r.errorInfo!!.startsWith("RESPOSTA_VAZIA"))
        assertTrue(r.diagnostics.any { it.contains("chrome-h2 HEAD") })
        assertEquals(3, r.candidates.size)
        assertTrue(r.candidates.first().status.startsWith("não verificado"))
        assertEquals(EngineState.FINISHED, e.state)
    }

    @Test fun mainFrameErrorOnPageEndsStepKeepsCandidateAndIgnoresErrorPage() {
        val f = Fake(); val e = ResolverEngine(Limits(), { now }, f)
        e.start(site)
        e.onScan(PageScan(site, "Hetzner", listOf(RawCandidate("https://fsn1-speed.hetzner.com/files/", "Download files", "a", "href", false, "", "", null, true)), null, null))
        assertEquals("https://fsn1-speed.hetzner.com/files/", f.navigated.last())
        val rescansBefore = f.rescans
        e.onPageStarted("https://fsn1-speed.hetzner.com/files/")
        e.onMainFrameError("https://fsn1-speed.hetzner.com/files/", -6, "net::ERR_EMPTY_RESPONSE")
        e.onPageStarted("chrome-error://chromewebdata/")
        e.onPageFinished("chrome-error://chromewebdata/")
        e.onScan(PageScan("chrome-error://chromewebdata/", "", emptyList(), null, null))
        val r = f.result!!
        assertEquals(ResultState.NETWORK_ERROR, r.state)
        assertEquals("https://fsn1-speed.hetzner.com/files/", r.url)
        assertTrue(r.errorInfo!!.contains("ERR_EMPTY_RESPONSE"))
        assertEquals(rescansBefore, f.rescans)
    }

    @Test fun errorPageIsNeverScannedNorCountedAsSuccess() {
        val f = Fake(); val e = ResolverEngine(Limits(), { now }, f)
        e.start(site)
        e.onPageStarted(site)
        val before = f.rescans
        // erro durante a espera humana: só registra, sem encerrar
        e.onScan(PageScan(site, "x", emptyList(), ChallengeKind.CAPTCHA, null))
        e.onMainFrameError(site, -2, "net::ERR_NAME_NOT_RESOLVED")
        e.onPageFinished(site)
        assertEquals(before, f.rescans)
        assertEquals(EngineState.WAITING_HUMAN, e.state)
    }

    @Test fun initialPageFailureIsNetworkErrorNotNoCandidate() {
        val f = Fake(); val e = ResolverEngine(Limits(), { now }, f)
        e.start(site)
        e.onMainFrameError(site, -6, "net::ERR_EMPTY_RESPONSE")
        e.onPageFinished("chrome-error://chromewebdata/")
        assertEquals(ResultState.NETWORK_ERROR, f.result?.state)
        assertEquals(0, f.rescans)
    }

    @Test fun downloadListenerIsAdditionalEvidenceAfterInconclusiveProbe() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.Inconclusive("resposta incompleta"))
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, f.result?.state)
        e.onDownload(DownloadInfo(f100, "application/octet-stream", null, 104_857_600))
        val r = f.result!!
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertTrue(r.evidence.any { it.startsWith("DownloadListener") })
        assertTrue(r.diagnostics.any { it.contains("inconclusiva") })
    }

    @Test fun lateDownloadUpgradesUnverifiedCandidateButOnlyForSameUrl() {
        val f = Fake(); val e = ResolverEngine(Limits(maxStepMs = 5_000), { now }, f)
        e.start(site); e.onScan(listing())
        e.onProbeResult(f100, ProbeResult.Inconclusive("x"))
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, f.result?.state)
        e.onDownload(DownloadInfo("https://fsn1-speed.hetzner.com/OUTRO.bin", "application/octet-stream", null, 10))
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, f.result?.state)   // download não solicitado: ignorado
        e.onDownload(DownloadInfo(f100, "application/octet-stream", null, 104_857_600))
        assertEquals(ResultState.VERIFIED_FILE, f.result?.state)
    }

    @Test fun probeBlockedByDnsRebindingBlocksResult() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.Blocked("fsn1-speed.hetzner.com resolve para endereço interno"))
        assertEquals(ResultState.BLOCKED, f.result?.state)
        assertEquals(1, f.navigated.size)
    }

    @Test fun httpForbiddenOnFileIsRequiresSessionWithoutNavigating() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.HttpError(f100, 403))
        assertEquals(ResultState.REQUIRES_SESSION, f.result?.state)
        assertEquals(f100, f.result?.url); assertEquals(1, f.navigated.size)
    }

    @Test fun redirectToNewDomainAsksThenReprobesOriginal() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.NeedsDomain("cdn.exemplo.net", "https://cdn.exemplo.net/x.bin?t=1"))
        assertEquals(listOf("cdn.exemplo.net"), f.asked)
        assertEquals(EngineState.WAITING_CONFIRMATION, e.state)
        e.answerDomain(true, false)                         // só desta vez: não vira domínio confiável
        assertEquals(listOf(f100, f100), f.probes)
        assertFalse(e.policy.isTrusted("cdn.exemplo.net"))
        e.onProbeResult(f100, ProbeResult.File("https://cdn.exemplo.net/x.bin", 200, "application/octet-stream", 5, null, "HEAD", true))
        assertEquals(ResultState.VERIFIED_FILE, f.result?.state)
        assertEquals(1, f.navigated.size)
    }

    @Test fun deniedRedirectDomainKeepsUnverifiedLink() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.NeedsDomain("cdn.exemplo.net", "https://cdn.exemplo.net/x.bin"))
        e.answerDomain(false, false)
        assertEquals(ResultState.UNVERIFIED_CANDIDATE, f.result?.state)
        assertEquals(f100, f.result?.url)
    }

    @Test fun pageProbeNavigatesNormally() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.Page(f100, 200, "text/html"))
        assertEquals(f100, f.navigated.last())
    }

    @Test fun staleProbeResultIsIgnored() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult("https://fsn1-speed.hetzner.com/1GB.bin", ProbeResult.File("x", 200, "a/b", 1, null, "HEAD", false))
        assertNull(f.result)
    }

    @Test fun noCandidateIsDistinctFromOthers() {
        val f = Fake(); val e = ResolverEngine(Limits(maxScanAttempts = 1), { now }, f)
        e.start(site); e.onScan(PageScan(site, "t", emptyList(), null, null))
        assertEquals(ResultState.NO_CANDIDATE, f.result?.state)
    }

    @Test fun secretsNeverAppearInResultDiagnostics() {
        val f = Fake(); val e = setup(f)
        e.onProbeResult(f100, ProbeResult.NetworkError("EOFException on https://h.com/a.bin?token=SEGREDO123", "RESPOSTA_VAZIA"),
            listOf("[x] FALHA: https://h.com/a.bin?sig=ABC"))
        val r = f.result!!
        val all = r.diagnostics.joinToString() + r.steps.joinToString { it.note + it.url } + r.errorInfo + r.message
        assertFalse(all.contains("SEGREDO123")); assertFalse(all.contains("sig=ABC"))
    }
}
