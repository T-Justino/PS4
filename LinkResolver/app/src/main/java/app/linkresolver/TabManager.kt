package app.linkresolver

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.os.Message
import android.view.View
import android.webkit.CookieManager
import android.webkit.JsResult
import android.webkit.SafeBrowsingResponse
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.net.http.SslError
import android.webkit.RenderProcessGoneDetail
import android.webkit.JsPromptResult
import android.widget.FrameLayout
import app.linkresolver.core.DownloadInfo
import app.linkresolver.core.NavDecision
import app.linkresolver.core.UrlSafety
import java.io.ByteArrayInputStream

class BrowserTab(val id: Int, val webView: WebView, val openerId: Int?) {
    var title: String = "Aba $id"
    var closed = false
}

/**
 * Gerencia WebViews (aba principal + popups de origem confiável) com configuração endurecida.
 * Toda decisão de política é delegada a [Callbacks] (motor de navegação).
 */
class TabManager(
    private val context: Context,
    private val container: FrameLayout,
    private val cb: Callbacks,
) {
    interface Callbacks {
        fun onNavigationRequest(tab: BrowserTab, url: String, redirect: Boolean): NavDecision
        fun onPageStarted(tab: BrowserTab, url: String)
        fun onPageFinished(tab: BrowserTab, url: String)
        fun onProgress(tab: BrowserTab, percent: Int)
        fun onDownload(tab: BrowserTab, info: DownloadInfo)
        fun onHttpError(tab: BrowserTab, url: String, code: Int)
        /** Erro na navegação do quadro principal. */
        fun onMainFrameError(tab: BrowserTab, url: String, code: Int, description: String)
        fun onSafeBrowsingHit(tab: BrowserTab, url: String, threat: String)
        /** Decide se um popup (com ou sem gesto do usuário) pode virar aba. */
        fun allowPopup(opener: BrowserTab, userGesture: Boolean): Boolean
        fun onPopupBlocked(reason: String)
        fun onBlockedSubresource(url: String, reason: String)
        fun onTabsChanged()
    }

    companion object {
        const val MAX_TABS = 4
        const val ERROR_SSL = -11
        const val ERROR_RENDER_GONE = -100
    }

    private var nextId = 0
    val all = mutableListOf<BrowserTab>()
    var active: BrowserTab? = null
        private set
    val main: BrowserTab get() = all.first()

    fun openMain(): BrowserTab = create(null).also { select(it) }

    @SuppressLint("SetJavaScriptEnabled")
    private fun create(openerId: Int?): BrowserTab {
        val wv = WebView(context)
        val tab = BrowserTab(nextId++, wv, openerId)
        wv.visibility = View.GONE
        wv.layoutParams = FrameLayout.LayoutParams(-1, -1)
        with(wv.settings) {
            javaScriptEnabled = true            // requisito do MVP
            domStorageEnabled = true
            javaScriptCanOpenWindowsAutomatically = false // window.open sem gesto é bloqueado
            setSupportMultipleWindows(true)     // habilita onCreateWindow
            allowFileAccess = false
            allowContentAccess = false
            @Suppress("DEPRECATION") allowFileAccessFromFileURLs = false
            @Suppress("DEPRECATION") allowUniversalAccessFromFileURLs = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            safeBrowsingEnabled = true          // Safe Browsing ligado
            @Suppress("DEPRECATION") saveFormData = false
            setGeolocationEnabled(false)
            mediaPlaybackRequiresUserGesture = true
        }
        // Cookies de terceiros ficam desligados (padrão mais seguro); cookies próprios persistem na sessão.
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(wv, false)

        wv.webViewClient = Client(tab)
        wv.webChromeClient = Chrome(tab)
        wv.setDownloadListener { url, _, contentDisposition, mimeType, contentLength ->
            cb.onDownload(tab, DownloadInfo(url, mimeType, contentDisposition, contentLength))
        }
        container.addView(wv)
        all += tab
        return tab
    }

    fun select(tab: BrowserTab) {
        for (t in all) t.webView.visibility = if (t === tab) View.VISIBLE else View.GONE
        active = tab
        cb.onTabsChanged()
    }

    fun close(tab: BrowserTab) {
        if (tab.closed || all.size <= 1 || tab === main) return
        tab.closed = true
        val wasActive = active === tab
        all.remove(tab)
        container.removeView(tab.webView)
        // Destruir fora do callback do próprio WebView evita crashes.
        container.post {
            tab.webView.stopLoading()
            tab.webView.webViewClient = WebViewClient()
            tab.webView.destroy()
        }
        if (wasActive) select(all.firstOrNull { it.id == tab.openerId } ?: main) else cb.onTabsChanged()
    }

    fun closePopups() { all.filter { it.openerId != null }.forEach { close(it) } }

    fun onPause() = all.forEach { it.webView.onPause() }
    fun onResume() = all.forEach { it.webView.onResume() }

    fun destroyAll() {
        all.forEach { container.removeView(it.webView); it.webView.destroy() }
        all.clear()
    }

    // ------------------------------------------------------------------ clients

    private inner class Client(val tab: BrowserTab) : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            if (!request.isForMainFrame) return false
            return cb.onNavigationRequest(tab, request.url.toString(), request.isRedirect) != NavDecision.ALLOW
        }

        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
            val url = request.url.toString()
            val v = UrlSafety.checkSubresource(url)
            if (v is UrlSafety.Verdict.Rejected) {
                container.post { cb.onBlockedSubresource(url, v.reason) }
                return WebResourceResponse("text/plain", "utf-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
            }
            return null
        }

        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) = cb.onPageStarted(tab, url)
        override fun onPageFinished(view: WebView, url: String) = cb.onPageFinished(tab, url)

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
            if (request.isForMainFrame) cb.onHttpError(tab, request.url.toString(), errorResponse.statusCode)
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
            if (request.isForMainFrame) cb.onMainFrameError(tab, request.url.toString(), error.errorCode, error.description.toString())
        }

        // Nunca prosseguir diante de erro de certificado.
        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            handler.cancel()
            cb.onMainFrameError(tab, error.url ?: "", ERROR_SSL, "erro SSL (${error.primaryError}) — carregamento cancelado")
        }

        // Safe Browsing: sempre voltar para a segurança, sem relatar a URL.
        override fun onSafeBrowsingHit(view: WebView, request: WebResourceRequest, threatType: Int, callback: SafeBrowsingResponse) {
            callback.backToSafety(false)
            val name = when (threatType) {
                WebViewClient.SAFE_BROWSING_THREAT_MALWARE -> "malware"
                WebViewClient.SAFE_BROWSING_THREAT_PHISHING -> "phishing"
                WebViewClient.SAFE_BROWSING_THREAT_UNWANTED_SOFTWARE -> "software indesejado"
                WebViewClient.SAFE_BROWSING_THREAT_BILLING -> "cobrança abusiva"
                else -> "ameaça"
            }
            cb.onSafeBrowsingHit(tab, request.url.toString(), name)
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            cb.onMainFrameError(tab, "", ERROR_RENDER_GONE, "processo de renderização encerrado")
            if (tab !== main) close(tab)
            return true
        }
    }

    private inner class Chrome(val tab: BrowserTab) : WebChromeClient() {
        override fun onCreateWindow(view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message): Boolean {
            if (all.size >= MAX_TABS) { cb.onPopupBlocked("limite de $MAX_TABS abas"); return false }
            if (!cb.allowPopup(tab, isUserGesture)) return false
            val popup = create(tab.id)
            val transport = resultMsg.obj as WebView.WebViewTransport
            transport.webView = popup.webView
            resultMsg.sendToTarget()
            select(popup)
            return true
        }

        override fun onCloseWindow(window: WebView) {
            all.firstOrNull { it.webView === window }?.let { close(it) }
        }

        override fun onProgressChanged(view: WebView, newProgress: Int) = cb.onProgress(tab, newProgress)

        override fun onReceivedTitle(view: WebView, title: String?) {
            if (!title.isNullOrBlank()) { tab.title = title; cb.onTabsChanged() }
        }

        // Diálogos JS cancelados: evita "alert spam" típico de páginas de anúncios.
        override fun onJsAlert(view: WebView, url: String, message: String, result: JsResult): Boolean { result.cancel(); return true }
        override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean { result.cancel(); return true }
        override fun onJsPrompt(view: WebView, url: String, message: String, defaultValue: String?, result: JsPromptResult): Boolean { result.cancel(); return true }
        override fun onJsBeforeUnload(view: WebView, url: String, message: String, result: JsResult): Boolean { result.confirm(); return true }
        override fun onGeolocationPermissionsShowPrompt(origin: String, callback: android.webkit.GeolocationPermissions.Callback) = callback.invoke(origin, false, false)
        override fun onPermissionRequest(request: android.webkit.PermissionRequest) = request.deny()
    }
}
