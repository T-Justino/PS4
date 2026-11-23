package app.linkresolver.core

import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * TESTE REAL (rede): só roda com LR_LIVE=1 e LR_LIVE_DIR (gerados por tools/live-scan.js sobre o GitHub de verdade).
 * Executa o motor COMPLETO sobre as varreduras reais do repositório, com verificação OkHttp real (HEAD/Range).
 */
class LiveGithubTest {
    @Test fun realRepositoryReachesTheRawUrlOfAtLeastOneRom() {
        val dirPath = System.getenv("LR_LIVE_DIR")
        assumeTrue("teste real desligado (defina LR_LIVE=1)", System.getenv("LR_LIVE") == "1" && dirPath != null)
        val dir = File(dirPath!!)
        val out = StringBuilder()
        fun log(s: String) { println(s); out.appendLine(s) }
        try {
            val dirScan = PageScanner.parse(File(dir, "dir.json").readText())!!
            val blobScan = PageScanner.parse(File(dir, "blob.json").readText())!!
            val policy = DomainPolicy().also { it.trust("github.com") }
            val scored = dirScan.candidates.map { DownloadHeuristics.score(it, "github.com", policy) }.sortedByDescending { it.score }
            log("[LIVE] candidatos da listagem: ${dirScan.totalCandidates} (mantidos ${scored.size})")
            for (n in listOf("astrohawk.smc", "blt.sfc", "bucket.smc")) {
                val c = scored.firstOrNull { it.url?.endsWith("/$n") == true }
                log("[LIVE] $n -> ${c?.let { "${it.linkClass.label}, pontuação ${it.score}" } ?: "AUSENTE"}")
            }
            log("[LIVE] top 3: " + scored.take(3).joinToString { "${it.raw.text} (${it.score}, ${it.linkClass})" })

            val s = Sim(); s.answerDomain = true
            val dirUrl = dirScan.url
            s.pages[dirUrl] = dirScan
            scored.filter { it.linkClass == LinkClass.FILE_VIEW_PAGE }.forEach { s.pages[it.url!!] = blobScan }
            val probe = HttpFileProbe("Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36")
            s.probeFn = { url, trusted ->
                val rep = probe.probe(url, trusted)
                log("[LIVE] probe ${UrlSafety.redact(url)} -> ${rep.result::class.simpleName} " + rep.result.toString().take(160))
                rep.diagnostics.take(8).forEach { log("[LIVE]    $it") }
                rep
            }
            val r = s.run(dirUrl)
            log("[LIVE] RESULTADO: ${r.state.label} — ${r.message}")
            log("[LIVE] URL: ${r.url}  MIME=${r.mimeType} tamanho=${r.sizeBytes} nome=${r.fileName}")
            log("[LIVE] domínios pedidos: ${s.asked}; navegou: ${s.navigated.map { UrlSafety.redact(it) }}")
            log("[LIVE] caminho:\n" + r.path.joinToString("\n") { it.format() })
            check(r.state == ResultState.VERIFIED_FILE) { "esperado Arquivo confirmado, obtido ${r.state.label}: ${r.message}" }
            check(r.url!!.contains("raw.githubusercontent.com")) { "URL final não é Raw: ${r.url}" }
        } finally {
            File(dir, "live-report.txt").writeText(out.toString())
        }
    }
}
