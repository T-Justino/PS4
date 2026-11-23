package app.linkresolver.core

import java.net.IDN

/**
 * Validação e higienização de URLs. Sem dependências de Android (testável na JVM).
 *
 * Limitação conhecida: não resolve DNS; um nome público que aponte para IP interno
 * (DNS rebinding) não é detectado aqui. Mitigação parcial: bloqueio de domínios
 * "curinga de IP" (nip.io etc.), esquemas perigosos e HTTP puro.
 */
object UrlSafety {

    sealed class Verdict {
        object Ok : Verdict()
        data class Rejected(val reason: String) : Verdict()
    }

    data class Parsed(
        val scheme: String,
        val host: String,
        val port: Int?,
        val path: String,
        val query: String?,
        val fragment: String?,
        val hasUserInfo: Boolean,
    )

    const val MAX_URL_LENGTH = 4096

    val DANGEROUS_SCHEMES = setOf(
        "javascript", "data", "file", "content", "intent", "market", "blob",
        "ftp", "ws", "wss", "vbscript", "chrome", "view-source", "android-app", "sms", "tel", "mailto",
    )

    private val URL_RE = Regex("""^([a-zA-Z][a-zA-Z0-9+.\-]*):(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?$""")

    private val BLOCKED_SUFFIXES = listOf(
        "localhost", "local", "localdomain", "internal", "intranet", "lan", "home", "corp",
        "home.arpa", "nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "traefik.me",
    )

    fun parse(raw: String): Parsed? {
        val s = raw.trim()
        if (s.isEmpty() || s.length > MAX_URL_LENGTH) return null
        if (s.any { it.code < 0x20 || it.code == 0x7f }) return null
        val m = URL_RE.matchEntire(s) ?: return null
        val scheme = m.groupValues[1].lowercase()
        val authority = m.groups[2]?.value
        var host = ""
        var port: Int? = null
        var userInfo = false
        if (authority != null) {
            var hostPort = authority
            val at = authority.lastIndexOf('@')
            if (at >= 0) {
                userInfo = true
                hostPort = authority.substring(at + 1)
            }
            if (hostPort.startsWith("[")) {
                val end = hostPort.indexOf(']')
                if (end < 0) return null
                host = hostPort.substring(0, end + 1)
                val rest = hostPort.substring(end + 1)
                if (rest.startsWith(":")) port = rest.substring(1).toIntOrNull() ?: return null
            } else {
                val colon = hostPort.lastIndexOf(':')
                if (colon >= 0) {
                    host = hostPort.substring(0, colon)
                    val p = hostPort.substring(colon + 1)
                    if (p.isNotEmpty()) port = p.toIntOrNull() ?: return null
                } else host = hostPort
            }
            host = host.lowercase().trimEnd('.')
            if (host.any { it.code > 127 }) {
                host = try { IDN.toASCII(host).lowercase() } catch (e: Exception) { return null }
            }
        }
        return Parsed(
            scheme, host, port, m.groupValues[3],
            m.groups[4]?.value, m.groups[5]?.value, userInfo,
        )
    }

    /** Verificação completa para navegação de nível superior. */
    fun check(raw: String, allowHttp: Boolean = false): Verdict {
        val p = parse(raw) ?: return Verdict.Rejected("URL inválida ou longa demais")
        if (p.scheme in DANGEROUS_SCHEMES) return Verdict.Rejected("esquema perigoso bloqueado: ${p.scheme}")
        if (p.scheme != "https" && !(allowHttp && p.scheme == "http")) {
            return Verdict.Rejected("somente HTTPS é permitido (esquema: ${p.scheme})")
        }
        if (p.hasUserInfo) return Verdict.Rejected("URL com usuário/senha embutidos")
        if (p.host.isEmpty()) return Verdict.Rejected("URL sem host")
        p.port?.let { if (it !in 1..65535) return Verdict.Rejected("porta inválida") }
        return checkHost(p.host)
    }

    /** Verificação leve (sem exigir HTTPS) para sub-recursos: só impede acesso a rede interna. */
    fun checkSubresource(raw: String): Verdict {
        val p = parse(raw) ?: return Verdict.Rejected("URL inválida")
        if (p.scheme != "http" && p.scheme != "https") return Verdict.Ok
        if (p.host.isEmpty()) return Verdict.Rejected("sem host")
        return checkHost(p.host)
    }

    fun checkHost(host: String): Verdict {
        if (host.startsWith("[")) return Verdict.Rejected("literais IPv6 não são suportados")
        if (host.contains(':')) return Verdict.Rejected("host inválido")
        val lastLabel = host.substringAfterLast('.')
        if (NUMERIC_LABEL.matches(lastLabel)) {
            val ip = parseIpv4(host) ?: return Verdict.Rejected("endereço IP inválido")
            return if (isPrivateIpv4(ip)) Verdict.Rejected("endereço IP local/interno bloqueado")
            else Verdict.Ok
        }
        if (!host.contains('.')) return Verdict.Rejected("host sem domínio (rede interna)")
        for (s in BLOCKED_SUFFIXES) {
            if (host == s || host.endsWith(".$s")) return Verdict.Rejected("domínio local/interno bloqueado: .$s")
        }
        if (!HOST_RE.matches(host)) return Verdict.Rejected("host com caracteres inválidos")
        return Verdict.Ok
    }

    private val NUMERIC_LABEL = Regex("""^(0[xX][0-9a-fA-F]*|[0-9]+)$""")
    private val HOST_RE = Regex("""^[a-z0-9]([a-z0-9\-_]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-_]{0,61}[a-z0-9])?)*$""")

    /** Interpreta IPv4 em formas decimal, octal, hex e abreviadas (como navegadores). */
    fun parseIpv4(host: String): IntArray? {
        val parts = host.split('.')
        if (parts.isEmpty() || parts.size > 4 || parts.any { it.isEmpty() }) return null
        val nums = LongArray(parts.size)
        for ((i, p) in parts.withIndex()) {
            nums[i] = when {
                p.startsWith("0x") || p.startsWith("0X") -> p.substring(2).ifEmpty { "0" }.toLongOrNull(16)
                p.length > 1 && p.startsWith("0") -> p.substring(1).toLongOrNull(8)
                else -> p.toLongOrNull(10)
            } ?: return null
        }
        for (i in 0 until nums.size - 1) if (nums[i] > 255) return null
        val last = nums.last()
        val maxLast = 1L shl (8 * (5 - nums.size))
        if (last >= maxLast || last < 0) return null
        var value = last
        for (i in 0 until nums.size - 1) value += nums[i] shl (8 * (3 - i))
        return intArrayOf(
            ((value shr 24) and 255).toInt(), ((value shr 16) and 255).toInt(),
            ((value shr 8) and 255).toInt(), (value and 255).toInt(),
        )
    }

    fun isPrivateIpv4(ip: IntArray): Boolean {
        val (a, b, c) = Triple(ip[0], ip[1], ip[2])
        return when {
            a == 0 || a == 10 || a == 127 -> true
            a == 169 && b == 254 -> true
            a == 172 && b in 16..31 -> true
            a == 192 && b == 168 -> true
            a == 100 && b in 64..127 -> true
            a == 192 && b == 0 && c in 0..2 -> true
            a == 198 && (b == 18 || b == 19) -> true
            a == 198 && b == 51 && c == 100 -> true
            a == 203 && b == 0 && c == 113 -> true
            a >= 224 -> true
            else -> false
        }
    }

    // ---------- higienização para logs/exibição ----------

    private val SENSITIVE_KEY = Regex(
        """(?i)^(.*(token|secret|passw|pwd|auth|session|sess|cookie|credential|signature|jwt|bearer|apikey|api[_\-]?key|access[_\-]?key).*|sig|sid|key|code|ticket|hash|hmac|x-amz-.*|x-goog-.*|policy|expires?|st|e|h)$"""
    )

    private val SENSITIVE_ONLY = Regex(
        """(?i)^(.*(token|secret|passw|pwd|auth|session|cookie|credential|signature|jwt|bearer|apikey|api[_\-]?key|access[_\-]?key).*|sig|sid|key|code|ticket|hmac|x-amz-(signature|credential|security-token)|x-goog-(signature|credential)|policy)$"""
    )

    /** Remove credenciais, fragmento e mascara valores de parâmetros sensíveis. */
    fun redact(raw: String): String {
        val p = parse(raw) ?: return raw.take(80).replace(Regex("""[?#].*"""), "")
        val sb = StringBuilder()
        sb.append(p.scheme).append(':')
        if (p.host.isNotEmpty() || raw.contains("://")) {
            sb.append("//").append(p.host)
            p.port?.let { sb.append(':').append(it) }
        }
        sb.append(p.path)
        if (!p.query.isNullOrEmpty()) {
            sb.append('?').append(
                p.query.split('&').joinToString("&") { kv ->
                    val k = kv.substringBefore('=')
                    if (kv.contains('=') && SENSITIVE_KEY.matches(decode(k))) "$k=***" else kv
                }
            )
        }
        if (!p.fragment.isNullOrEmpty()) sb.append("#…")
        return sb.toString()
    }

    fun hasSensitiveParams(raw: String): Boolean {
        val p = parse(raw) ?: return false
        if (p.hasUserInfo) return true
        if (p.fragment?.contains('=') == true) return true
        return p.query?.split('&')?.any { kv ->
            kv.contains('=') && SENSITIVE_ONLY.matches(decode(kv.substringBefore('=')))
        } ?: false
    }

    /** Chave para detecção de loops: sem fragmento, query ordenada, sem barra final. */
    fun loopKey(raw: String): String {
        val p = parse(raw) ?: return raw
        val q = p.query?.split('&')?.filter { it.isNotEmpty() }?.sorted()?.joinToString("&")
        return buildString {
            append(p.scheme).append("://").append(p.host)
            p.port?.let { append(':').append(it) }
            append(p.path.trimEnd('/').ifEmpty { "/" })
            if (!q.isNullOrEmpty()) append('?').append(q)
        }
    }

    fun host(raw: String): String? = parse(raw)?.host?.takeIf { it.isNotEmpty() }

    fun decode(s: String): String = try {
        java.net.URLDecoder.decode(s.replace("+", "%2B"), "UTF-8")
    } catch (e: Exception) { s }
}
