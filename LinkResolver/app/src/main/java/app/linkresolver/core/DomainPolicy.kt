package app.linkresolver.core

/** Conjunto de domínios confiáveis (domínio registrável) para a sessão. */
class DomainPolicy {
    private val trusted = linkedSetOf<String>()

    val domains: Set<String> get() = trusted

    fun trust(host: String) { trusted.add(registrable(host)) }
    fun isTrusted(host: String): Boolean = registrable(host) in trusted
    fun clear() = trusted.clear()

    companion object {
        private val SECOND_LEVEL = setOf("co", "com", "org", "net", "gov", "edu", "ac", "or", "ne", "go", "gob")

        /** Heurística de eTLD+1 sem lista pública de sufixos (suficiente para o MVP). */
        fun registrable(host: String): String {
            val h = host.lowercase().trimEnd('.')
            if (h.isEmpty() || h.all { it.isDigit() || it == '.' }) return h // IPv4
            val labels = h.split('.')
            if (labels.size <= 2) return h
            val tld = labels.last()
            val sld = labels[labels.size - 2]
            return if (tld.length == 2 && sld in SECOND_LEVEL) labels.takeLast(3).joinToString(".")
            else labels.takeLast(2).joinToString(".")
        }
    }
}
