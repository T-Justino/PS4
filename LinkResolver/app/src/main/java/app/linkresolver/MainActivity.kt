package app.linkresolver

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PersistableBundle
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.CookieManager
import android.webkit.WebStorage
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import app.linkresolver.core.DownloadHeuristics
import app.linkresolver.core.DownloadInfo
import app.linkresolver.core.EngineState
import app.linkresolver.core.HttpFileProbe
import app.linkresolver.core.NavDecision
import app.linkresolver.core.PageScanner
import app.linkresolver.core.ResolveResult
import app.linkresolver.core.ResultState
import app.linkresolver.core.ResolverEngine
import app.linkresolver.core.ScoredCandidate
import app.linkresolver.core.Step
import app.linkresolver.core.StepKind
import app.linkresolver.core.UrlSafety
import app.linkresolver.databinding.ActivityMainBinding
import com.google.android.material.chip.Chip
import com.google.android.material.tabs.TabLayout
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity(), TabManager.Callbacks, ResolverEngine.Listener {

    private lateinit var b: ActivityMainBinding
    private lateinit var tabs: TabManager
    private lateinit var engine: ResolverEngine
    private lateinit var adapter: CandidateAdapter
    private val handler = Handler(Looper.getMainLooper())
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.US)
    private val logBuf = StringBuilder()
    private var lastResult: ResolveResult? = null
    /** Aba que originou uma navegação pendente de confirmação (ex.: popup). */
    private var navTab: BrowserTab? = null
    private var lastPollAt = 0L
    private val probeExecutor = java.util.concurrent.Executors.newSingleThreadExecutor()
    private val probe by lazy { HttpFileProbe(android.webkit.WebSettings.getDefaultUserAgent(this)) }

    private val ticker = object : Runnable {
        override fun run() {
            engine.tick()
            if (engine.state == EngineState.WAITING_HUMAN && System.currentTimeMillis() - lastPollAt >= 2500) scanNow()
            if (engine.isActive) handler.postDelayed(this, 1000)
        }
    }
    private val scanRunnable = Runnable { scanNow() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)

        if (savedInstanceState == null) clearSession()
        if (WebViewFeature.isFeatureSupported(WebViewFeature.START_SAFE_BROWSING)) {
            WebViewCompat.startSafeBrowsing(applicationContext) { }
        }
        if (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0) {
            android.webkit.WebView.setWebContentsDebuggingEnabled(true)
        }

        b.versionText.text = "Link Resolver v${BuildConfig.VERSION_NAME} · commit ${BuildConfig.GIT_COMMIT}"
        engine = ResolverEngine(listener = this)
        tabs = TabManager(this, b.webContainer, this)
        tabs.openMain()

        adapter = CandidateAdapter({ onCandidateAction(it) }, { copyCandidate(it) })
        b.candList.layoutManager = LinearLayoutManager(this)
        b.candList.adapter = adapter

        for (name in listOf(R.string.tab_browser, R.string.tab_candidates, R.string.tab_log, R.string.tab_result)) {
            b.paneTabs.addTab(b.paneTabs.newTab().setText(name))
        }
        b.paneTabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showPane(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })

        b.btnStart.setOnClickListener { startAnalysis() }
        b.urlInput.setOnEditorActionListener { _, id, _ ->
            if (id == EditorInfo.IME_ACTION_GO) { startAnalysis(); true } else false
        }
        b.btnStop.setOnClickListener { engine.stop() }
        b.btnResume.setOnClickListener { scanNow() } // só retoma se a página não tiver mais desafio
        b.btnClearSession.setOnClickListener {
            clearSession()
            toast("Cookies e dados do site apagados")
        }
        b.btnCopy.setOnClickListener { copyUrl() }
        b.btnNew.setOnClickListener { showPane(0); b.urlInput.requestFocus() }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val t = tabs.active
                when {
                    b.paneTabs.selectedTabPosition != 0 -> b.paneTabs.selectTab(b.paneTabs.getTabAt(0))
                    t != null && t.webView.canGoBack() -> t.webView.goBack()
                    t != null && t.openerId != null -> tabs.close(t)
                    else -> { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
                }
            }
        })
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(i: Intent?) {
        if (i?.action == Intent.ACTION_SEND) {
            val text = i.getStringExtra(Intent.EXTRA_TEXT) ?: return
            Regex("""https?://\S+""").find(text)?.let { b.urlInput.setText(it.value) }
        }
    }

    override fun onPause() { super.onPause(); tabs.onPause() }
    override fun onResume() { super.onResume(); tabs.onResume() }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        probeExecutor.shutdownNow()
        if (isFinishing) {
            tabs.destroyAll()
            clearSession() // cookies só vivem enquanto o app está aberto
        }
        super.onDestroy()
    }

    private fun clearSession() {
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
        WebStorage.getInstance().deleteAllData()
    }

    // ------------------------------------------------------------------ UI

    private fun showPane(i: Int) {
        b.paneBrowser.visibility = if (i == 0) View.VISIBLE else View.GONE
        b.paneCandidates.visibility = if (i == 1) View.VISIBLE else View.GONE
        b.paneLog.visibility = if (i == 2) View.VISIBLE else View.GONE
        b.paneResult.visibility = if (i == 3) View.VISIBLE else View.GONE
        if (b.paneTabs.selectedTabPosition != i) b.paneTabs.selectTab(b.paneTabs.getTabAt(i))
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()

    private fun startAnalysis() {
        var input = b.urlInput.text?.toString()?.trim().orEmpty()
        if (input.isEmpty()) { toast("Informe uma URL"); return }
        if (!input.contains("://") && !input.contains(':')) input = "https://$input"
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(b.urlInput.windowToken, 0)
        handler.removeCallbacks(scanRunnable)
        tabs.closePopups()
        navTab = null
        logBuf.setLength(0); b.logText.text = ""
        adapter.submit(emptyList()); b.candEmpty.visibility = View.VISIBLE
        lastResult = null
        b.resState.setText(R.string.no_result); b.resDetails.text = ""; b.resSteps.text = ""; b.btnCopy.isEnabled = false
        showPane(0)
        engine.start(input)
        handler.removeCallbacks(ticker)
        if (engine.isActive) handler.postDelayed(ticker, 1000)
    }

    private fun scanNow() {
        if (engine.state != EngineState.RUNNING && engine.state != EngineState.WAITING_HUMAN) return
        val tab = tabs.active ?: return
        if (ResolverEngine.isErrorUrl(tab.webView.url)) return // nunca varrer páginas internas de erro
        lastPollAt = System.currentTimeMillis()
        tab.webView.evaluateJavascript(PageScanner.SCRIPT) { raw ->
            PageScanner.parse(raw)?.let { engine.onScan(it) }
        }
    }

    private fun onCandidateAction(c: ScoredCandidate) {
        if (c.url != null) {
            if (!engine.isActive) { toast("Inicie uma análise primeiro"); return }
            engine.manualFollow(c)
        } else if (c.raw.elementId != null) {
            // Clique manual solicitado pelo usuário em um botão sem URL.
            logLine(Step(System.currentTimeMillis(), StepKind.FOLLOW, null, "clique manual em \"${c.raw.text}\""))
            tabs.active?.webView?.evaluateJavascript(PageScanner.clickScript(c.raw.elementId!!), null)
            showPane(0)
            handler.postDelayed(scanRunnable, 2000)
        }
    }

    private fun refreshChips() {
        b.tabChips.removeAllViews()
        for (t in tabs.all) {
            val chip = Chip(this).apply {
                text = t.title.take(20)
                isCheckable = true
                isChecked = t === tabs.active
                isCloseIconVisible = t.openerId != null
                setOnClickListener { tabs.select(t) }
                setOnCloseIconClickListener { tabs.close(t) }
            }
            b.tabChips.addView(chip)
        }
    }

    private fun logLine(s: Step) {
        logBuf.append(timeFmt.format(Date(s.timeMs))).append("  [").append(s.kind).append("] ")
        if (s.url != null) logBuf.append(s.url).append("  ")
        logBuf.append("— ").append(s.note).append('\n')
        b.logText.text = logBuf
    }

    private fun copyToClipboard(url: String, sensitive: Boolean, verified: Boolean) {
        val clip = ClipData.newPlainText("URL", url)
        if (Build.VERSION.SDK_INT >= 33 && sensitive) {
            clip.description.extras = PersistableBundle().apply { putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true) }
        }
        (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(clip)
        val msg = StringBuilder(getString(R.string.copied))
        if (!verified) msg.append(" — NÃO verificada")
        if (sensitive) msg.append(" (contém token/assinatura — não compartilhe)")
        toast(msg.toString())
    }

    private fun copyUrl() {
        val r = lastResult ?: return
        val url = r.url ?: return
        copyToClipboard(url, r.urlHasSensitiveParams, r.state == ResultState.VERIFIED_FILE)
    }

    private fun copyCandidate(c: ScoredCandidate) {
        val url = c.url ?: return
        val verified = lastResult?.state == ResultState.VERIFIED_FILE &&
            lastResult?.url?.let { UrlSafety.loopKey(it) == UrlSafety.loopKey(url) } == true
        copyToClipboard(url, UrlSafety.hasSensitiveParams(url), verified)
    }

    // ------------------------------------------------------------------ ResolverEngine.Listener

    override fun navigate(url: String) {
        val t = navTab?.takeIf { !it.closed } ?: tabs.active ?: tabs.main
        navTab = null
        t.webView.loadUrl(url)
    }

    override fun askDomain(host: String, url: String, reason: String) {
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_title)
            .setMessage("O fluxo quer navegar para um domínio que ainda não é confiável:\n\n$host\n\n$url\n\nOrigem: $reason")
            .setCancelable(false)
            .setPositiveButton(R.string.confirm_allow_domain) { _, _ -> engine.answerDomain(true, true) }
            .setNeutralButton(R.string.confirm_once) { _, _ -> engine.answerDomain(true, false) }
            .setNegativeButton(R.string.confirm_deny) { _, _ -> engine.answerDomain(false, false) }
            .show()
    }

    override fun onStateChanged(state: EngineState, message: String) {
        b.statusText.text = message
        b.btnStop.visibility = if (engine.isActive) View.VISIBLE else View.GONE
        b.btnResume.visibility = if (state == EngineState.WAITING_HUMAN) View.VISIBLE else View.GONE
        if (state == EngineState.WAITING_HUMAN) showPane(0)
    }

    override fun onStep(step: Step) = logLine(step)

    override fun onCandidates(candidates: List<ScoredCandidate>) {
        adapter.submit(candidates)
        b.candEmpty.visibility = if (candidates.isEmpty()) View.VISIBLE else View.GONE
    }

    override fun onResult(result: ResolveResult) {
        lastResult = result
        handler.removeCallbacks(ticker); handler.removeCallbacks(scanRunnable)
        b.resState.text = result.state.label
        adapter.setStatuses(result.candidates.map { it.status })
        b.resDetails.text = buildString {
            if (result.url != null && result.state != ResultState.VERIFIED_FILE) {
                append("⚠ LINK NÃO VERIFICADO — os metadados do arquivo não foram confirmados. Use “Copiar URL” e teste manualmente.\n\n")
            }
            append("URL: ").append(result.displayUrl ?: "—").append('\n')
            if (result.urlHasSensitiveParams) append("(valores sensíveis mascarados aqui; “Copiar URL” copia a URL completa)\n")
            append("Host: ").append(result.host ?: "—").append('\n')
            append("Tipo MIME: ").append(result.mimeType ?: "—").append('\n')
            append("Nome estimado: ").append(result.fileName ?: "—").append('\n')
            append("Tamanho: ").append(DownloadHeuristics.formatSize(result.sizeBytes)).append('\n')
            result.candidateScore?.let { append("Pontuação do candidato: ").append(it).append('\n') }
            append('\n').append(result.message)
            result.errorInfo?.let { append("\n\nErro: ").append(it) }
            if (result.evidence.isNotEmpty()) append("\n\nEvidências:\n").append(result.evidence.joinToString("\n") { "• $it" })
            if (result.diagnostics.isNotEmpty()) append("\n\nDiagnóstico:\n").append(result.diagnostics.joinToString("\n") { "• $it" })
            if (result.path.isNotEmpty()) {
                append("\n\nCaminho percorrido (${result.path.size}):\n")
                append(result.path.joinToString("\n") { it.format() })
            }
            if (result.candidates.isNotEmpty()) {
                append("\n\nCandidatos (${result.candidates.size}):\n")
                append(result.candidates.joinToString("\n") { "• [${it.score}] ${it.kind.label}: ${it.text.ifBlank { "(sem texto)" }} — ${it.displayUrl} — ${it.status}" })
            }
        }
        val sdf = timeFmt
        b.resSteps.text = "Histórico de etapas (${result.steps.size}):\n" + result.steps.joinToString("\n") {
            "${sdf.format(Date(it.timeMs))} [${it.kind}] ${it.url ?: ""} — ${it.note}"
        }
        b.btnCopy.isEnabled = result.url != null
        showPane(3)
    }

    override fun requestProbe(url: String, trustedDomains: Set<String>) {
        probeExecutor.execute {
            val rep = probe.probe(url, trustedDomains)
            handler.post { if (!isDestroyed) engine.onProbeResult(url, rep.result, rep.diagnostics, rep.hops) }
        }
    }

    override fun requestRescan(delayMs: Long) {
        handler.removeCallbacks(scanRunnable)
        handler.postDelayed(scanRunnable, delayMs)
    }

    override fun onNavigationDenied(url: String) {
        navTab?.let { if (it.openerId != null) tabs.close(it) }
        navTab = null
    }

    // ------------------------------------------------------------------ TabManager.Callbacks

    override fun onNavigationRequest(tab: BrowserTab, url: String, redirect: Boolean, hasGesture: Boolean): NavDecision {
        val d = engine.onNavigationRequest(url, redirect, hasGesture)
        if (d == NavDecision.ASK) navTab = tab
        return d
    }

    override fun onPageStarted(tab: BrowserTab, url: String) {
        if (!engine.isActive) return
        // Rede de segurança: a 1ª navegação de um popup pode não passar por shouldOverrideUrlLoading.
        if (tab.openerId != null && url != "about:blank") {
            val host = UrlSafety.host(url)
            if (host == null) {
                tab.webView.stopLoading(); tabs.close(tab); return
            }
            if (!engine.policy.isTrusted(host)) {
                tab.webView.stopLoading()
                if (engine.onNavigationRequest(url, false) == NavDecision.ASK) navTab = tab else tabs.close(tab)
                return
            }
        }
        engine.onPageStarted(url)
    }

    override fun onPageFinished(tab: BrowserTab, url: String) {
        if (engine.isActive && tab === tabs.active) engine.onPageFinished(url)
    }

    override fun onProgress(tab: BrowserTab, percent: Int) {
        if (tab !== tabs.active) return
        b.progress.visibility = if (percent in 1..99) View.VISIBLE else View.INVISIBLE
        b.progress.progress = percent
    }

    override fun onDownload(tab: BrowserTab, info: DownloadInfo) {
        // O WebView NÃO baixa nada: apenas entrega URL e metadados. O app nunca inicia o download.
        if (engine.state == EngineState.IDLE) toast("Download detectado — inicie uma análise para registrá-lo")
        else engine.onDownload(info)
        if (tab.openerId != null) tabs.close(tab)
    }

    override fun onHttpError(tab: BrowserTab, url: String, code: Int) { if (engine.isActive) engine.onHttpError(url, code) }
    override fun onMainFrameError(tab: BrowserTab, url: String, code: Int, description: String) {
        if (tab === tabs.active || tab.openerId == null) engine.onMainFrameError(url, code, description)
    }

    override fun onSafeBrowsingHit(tab: BrowserTab, url: String, threat: String) {
        if (engine.isActive) engine.onSafeBrowsingHit(url, threat) else toast("Safe Browsing bloqueou a página ($threat)")
    }

    override fun allowPopup(opener: BrowserTab, userGesture: Boolean): Boolean {
        val openerUrl = opener.webView.url
        val host = openerUrl?.let { UrlSafety.host(it) }
        val trusted = host != null && (!engine.isActive || engine.policy.isTrusted(host))
        val allowed = userGesture && trusted
        val reason = when {
            !userGesture -> "sem gesto do usuário"
            !trusted -> "origem não confiável (${host ?: "?"})"
            else -> "gesto do usuário em origem confiável (${host})"
        }
        engine.onPopup(openerUrl, null, allowed, reason)
        return allowed
    }

    override fun onPopupBlocked(reason: String) = engine.onPopup(null, null, false, reason)

    override fun onBlockedSubresource(url: String, reason: String) {
        if (engine.isActive) logLine(Step(System.currentTimeMillis(), StepKind.BLOCKED, UrlSafety.redact(url), "sub-recurso bloqueado: $reason"))
    }

    override fun onTabsChanged() = refreshChips()
}
