package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

class ResolverEngineTest {
    class Fake : ResolverEngine.Listener {
        val navigated = mutableListOf<String>()
        val asked = mutableListOf<String>()
        var result: ResolveResult? = null
        var rescans = 0
        var denied = 0
        val probes = mutableListOf<String>()
        override fun navigate(url: String) { navigated += url }
        override fun askDomain(host: String, url: String, reason: String) { asked += host }
        override fun onStateChanged(state: EngineState, message: String) {}
        override fun onStep(step: Step) {}
        override fun onCandidates(candidates: List<ScoredCandidate>) {}
        override fun onResult(result: ResolveResult) { this.result = result }
        override fun requestRescan(delayMs: Long) { rescans++ }
        override fun onNavigationDenied(url: String) { denied++ }
        override fun requestProbe(url: String, trustedDomains: Set<String>) { probes += url }
    }

    private var now = 0L
    private fun engine(f: Fake, limits: Limits = Limits()) = ResolverEngine(limits, { now }, f)
    private fun c(url: String?, text: String, dl: Boolean = false) = RawCandidate(url, text, "a", "href", dl, "", "", null, true)
    private fun scan(url: String, vararg cs: RawCandidate, ch: ChallengeKind? = null) =
        PageScan(url, "t", cs.toList(), ch, null)

    @Test fun rejectsUnsafeStart() {
        val f = Fake(); val e = engine(f)
        e.start("http://localhost/")
        assertEquals(ResultState.BLOCKED, f.result?.state)
        assertTrue(f.navigated.isEmpty())
    }

    @Test fun followsTrustedCandidateAndVerifiesDownload() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/page")
        assertEquals(listOf("https://site.com/page"), f.navigated)
        e.onScan(scan("https://site.com/page", c("https://site.com/get/123", "Download"), c("https://ads.doubleclick.net/x", "Download now")))
        assertEquals("https://site.com/get/123", f.navigated.last())
        e.onDownload(DownloadInfo("https://cdn.site.com/f.zip?token=SECRET", "application/zip", null, 5_000))
        val r = f.result!!
        assertEquals(ResultState.VERIFIED_FILE, r.state)
        assertEquals("f.zip", r.fileName)
        assertFalse(r.displayUrl!!.contains("SECRET"))
        assertTrue(r.urlHasSensitiveParams)
        assertTrue(r.steps.none { it.url?.contains("SECRET") == true })
    }

    @Test fun unknownDomainRequiresConfirmation() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/", c("https://files.other.org/a.zip", "Download")))
        assertEquals(listOf("files.other.org"), f.asked)
        assertEquals(1, f.navigated.size)
        e.answerDomain(true, true)
        assertEquals(listOf("https://files.other.org/a.zip"), f.probes) // arquivo provável: sondagem antes de navegar
        assertTrue(e.policy.isTrusted("x.other.org"))
    }

    @Test fun denyingDomainEndsWithoutNavigating() {
        val f = Fake(); val e = engine(f, Limits(maxScanAttempts = 1))
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/", c("https://files.other.org/a.zip", "Download")))
        e.answerDomain(false, false)
        assertEquals(1, f.navigated.size)
        assertEquals(1, f.denied)
        assertEquals(EngineState.FINISHED, e.state)
    }

    @Test fun redirectToUntrustedAsks() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        assertEquals(NavDecision.ASK, e.onNavigationRequest("https://evil.net/x", true))
        e.answerDomain(false, false)
        assertEquals(ResultState.BLOCKED, f.result?.state)
    }

    @Test fun blocksDangerousNavigation() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        assertEquals(NavDecision.BLOCK, e.onNavigationRequest("intent://x#Intent;end", false))
        assertEquals(NavDecision.BLOCK, e.onNavigationRequest("https://127.0.0.1/", false))
        assertEquals(EngineState.RUNNING, e.state)
    }

    @Test fun captchaPausesAndResumesOnlyWhenCleared() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/", c("https://site.com/get/a", "Download"), ch = ChallengeKind.CAPTCHA))
        assertEquals(EngineState.WAITING_HUMAN, e.state)
        assertEquals(1, f.navigated.size)
        e.onScan(scan("https://site.com/", c("https://site.com/get/a", "Download"), ch = ChallengeKind.CAPTCHA))
        assertEquals(1, f.navigated.size)
        e.onScan(scan("https://site.com/", c("https://site.com/get/a", "Download")))
        assertEquals(EngineState.RUNNING, e.state)
        assertEquals("https://site.com/get/a", f.navigated.last())
    }

    @Test fun loginThenDownloadRequiresSession() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/login", ch = ChallengeKind.LOGIN))
        e.onScan(scan("https://site.com/ok", c("https://site.com/get/a", "Download")))
        e.onDownload(DownloadInfo("https://site.com/a.zip", "application/zip", null, 10))
        assertEquals(ResultState.REQUIRES_SESSION, f.result?.state)
    }

    @Test fun waitTimeIsNotCountedAgainstLimits() {
        val f = Fake(); val e = engine(f, Limits(maxTotalMs = 100_000, maxStepMs = 100_000))
        e.start("https://site.com/")
        now = 10_000
        e.onScan(scan("https://site.com/", ch = ChallengeKind.CAPTCHA))
        now = 200_000; e.tick()
        assertEquals(EngineState.WAITING_HUMAN, e.state)
        e.onScan(scan("https://site.com/", c("https://site.com/get/a", "Download")))
        e.tick()
        assertEquals(EngineState.RUNNING, e.state)
    }

    @Test fun humanWaitTimesOut() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/", ch = ChallengeKind.BOT_CHECK))
        now += Limits().maxHumanWaitMs + 1; e.tick()
        assertEquals(ResultState.BLOCKED, f.result?.state)
    }

    @Test fun timeoutYieldsIntermediateWhenCandidateKnown() {
        val f = Fake(); val e = engine(f, Limits(maxStepMs = 5_000))
        e.start("https://site.com/")
        e.onScan(scan("https://site.com/", c("https://site.com/get/1", "Continuar")))
        now = 6_000; e.tick()
        assertEquals(ResultState.INTERMEDIATE_LINK, f.result?.state)
        assertEquals("https://site.com/get/1", f.result?.url)
    }

    @Test fun depthLimit() {
        val f = Fake(); val e = engine(f, Limits(maxDepth = 2))
        e.start("https://site.com/0")
        e.onScan(scan("https://site.com/0", c("https://site.com/dl/1", "Download")))
        e.onScan(scan("https://site.com/dl/1", c("https://site.com/dl/2", "Download")))
        e.onScan(scan("https://site.com/dl/2", c("https://site.com/dl/3", "Download")))
        assertEquals(ResultState.INTERMEDIATE_LINK, f.result?.state)
        assertEquals(2, f.navigated.size - 1)
    }

    @Test fun loopDetection() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/a")
        repeat(3) {
            e.onNavigationRequest("https://site.com/b", true)
            e.onNavigationRequest("https://site.com/a", true)
        }
        assertEquals(ResultState.BLOCKED, f.result?.state)
        assertTrue(f.result!!.message.contains("Loop"))
    }

    @Test fun domainLimit() {
        val f = Fake(); val e = engine(f, Limits(maxDomains = 2))
        e.start("https://site.com/")
        e.onNavigationRequest("https://a.org/", false); e.answerDomain(true, true)
        e.onNavigationRequest("https://b.org/", false)
        assertEquals(ResultState.BLOCKED, f.result?.state)
    }

    @Test fun htmlDownloadIsIgnored() {
        val f = Fake(); val e = engine(f)
        e.start("https://site.com/")
        e.onDownload(DownloadInfo("https://site.com/p", "text/html", null, -1))
        assertNull(f.result)
    }
}
