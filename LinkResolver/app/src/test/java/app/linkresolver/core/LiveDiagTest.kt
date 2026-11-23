package app.linkresolver.core

import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** DIAGNÓSTICO (rede, opcional): pontua a varredura real de uma página de jogo; não navega nem baixa. Só com LR_LIVE=1. */
class LiveDiagTest {
    @Test fun diagnoseRealPage() {
        val d = System.getenv("LR_LIVE_DIR")
        assumeTrue(System.getenv("LR_LIVE") == "1" && d != null && File(d, "diag.json").exists())
        val out = StringBuilder()
        fun log(s: String) { println(s); out.appendLine(s) }
        try {
            val scan = PageScanner.parse(File(d!!, "diag.json").readText())!!
            val goal = GoalContext.build(scan.title, scan.heading, scan.description, null)
            log("[DIAG] objetivo: ${goal.describe()}  (informativo=${goal.informative})")
            val policy = DomainPolicy().also { it.trust(UrlSafety.host(scan.url) ?: "") }
            val host = UrlSafety.host(scan.url) ?: ""
            val scored = scan.candidates.map { DownloadHeuristics.score(it, host, policy) }
            val withCtx = scored.map { Relevance.apply(it, goal) }.sortedByDescending { it.score }
            log("[DIAG] ${scan.totalCandidates} candidatos; top 12 (total = técnica ± contexto):")
            withCtx.take(12).forEach {
                log("[DIAG]  ${it.score} = ${it.technical} ${if (it.relevance >= 0) "+" else "−"} ${Math.abs(it.relevance)}  «${it.raw.text.take(40)}» ${it.url?.let { u -> UrlSafety.redact(u).takeLast(70) }} [${it.linkClass}] ${it.relevanceReasons.joinToString("; ").take(80)}")
            }
            val guide = withCtx.firstOrNull { it.raw.text.contains("guide", ignoreCase = true) }
            guide?.let { log("[DIAG] «${it.raw.text}»: técnica ${it.technical} → total ${it.score}") }
            for (c in withCtx.filter { it.url != null && DownloadHeuristics.extensionOf(it.url!!) == "mp4" }.take(3)) {
                val v = Relevance.compat(goal, FileFacts(c.url!!, null, "video/mp4", c.raw.text))
                log("[DIAG] arquivo ${c.url!!.substringAfterLast('/')} → ${v.verdict}: ${v.reason}")
            }
            val hosts = withCtx.filter { DownloadHeuristics.isHostButton(it) }
            log("[DIAG] botões de hospedagem externos: ${hosts.joinToString { "${it.raw.text}${if (it.raw.disabled) "(desabilitado)" else ""}" }.ifEmpty { "nenhum" }}")
        } finally { File(d!!, "diag-report.txt").writeText(out.toString()) }
    }
}
