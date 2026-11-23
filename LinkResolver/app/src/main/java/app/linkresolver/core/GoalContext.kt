package app.linkresolver.core

import java.text.Normalizer
import java.util.Locale

/**
 * Objetivo da busca, extraído da página inicial (título, cabeçalho, descrição) e/ou informado pelo usuário
 * (nome e/ou formato do arquivo). Puro Kotlin, sem regras de sites específicos.
 */
data class GoalContext(
    /** Palavras distintivas do conteúdo (sem palavras genéricas, plataformas e formatos). */
    val nameTokens: List<String>,
    /** Extensões desejadas (informadas ou inferidas de forma conservadora). */
    val formats: Set<String>,
    val userSpecified: Boolean,
    /** A própria página é sobre tutorial/guia (então tutoriais não são penalizados). */
    val wantsTutorial: Boolean,
    /** Famílias de mídia aceitas explicitamente (vídeo/áudio/imagem), ex.: "baixar um vídeo MP4". */
    val allowedMedia: Set<MediaFamily>,
    val source: String,
) {
    /** Só aplica relevância quando há informação suficiente (evita punir páginas sem contexto). */
    val informative: Boolean get() = userSpecified || nameTokens.size >= 2 || formats.isNotEmpty()

    fun describe(): String = buildString {
        append(if (userSpecified) "informado pelo usuário" else "inferido da página")
        append(": nome «").append(nameTokens.joinToString(" ").ifEmpty { "—" }).append("»")
        append(", formatos ").append(if (formats.isEmpty()) "não definidos" else formats.sorted().joinToString("/") { ".$it" })
        if (allowedMedia.isNotEmpty()) append(", mídia ").append(allowedMedia.joinToString("/") { it.label })
    }

    companion object {
        private val STOP = setOf(
            "the", "and", "for", "with", "from", "this", "that", "your", "free", "full", "version", "game", "games", "download",
            "downloads", "baixar", "baixe", "gratis", "gratuito", "jogo", "jogos", "para", "com", "uma", "dos", "das", "pelo",
            "por", "como", "mais", "novo", "nova", "latest", "update", "updated", "edition", "pack", "complete", "official", "site",
            "com", "www", "http", "https", "html", "page", "home", "app", "apps", "software", "file", "files", "arquivo", "link", "links",
            "direct", "direto", "online", "torrent", "crack", "mod", "usa", "eur", "jpn", "pt", "br", "english", "portugues",
        )
        private val PLATFORMS = setOf("ps1", "ps2", "ps3", "ps4", "ps5", "psp", "vita", "xbox", "switch", "pc", "android", "ios", "windows", "linux", "mac", "macos", "nintendo", "playstation", "wii", "steam")
        private val FORMAT_WORDS = (DownloadHeuristics.FILE_EXTENSIONS - setOf("001", "part01", "bin", "img", "col", "int", "rom", "ws", "gb", "gg", "vb")) + setOf("rom")
        private val VIDEO_WORDS = setOf("video", "videos", "vídeo", "filme", "movie", "film", "anime", "episodio", "episode", "trailer", "clip", "gameplay")
        private val AUDIO_WORDS = setOf("audio", "musica", "music", "album", "soundtrack", "ost", "podcast")
        private val IMAGE_WORDS = setOf("wallpaper", "wallpapers", "imagem", "image", "foto", "photo", "screenshot", "icon", "icons")
        private val TUTORIAL_WORDS = setOf("tutorial", "guide", "guia", "howto", "faq", "ajuda", "help", "manual", "instructions", "instrucoes", "walkthrough")

        /** Título sem o nome do site ("Jogo X - Site.com" → "Jogo X"). */
        fun cleanTitle(t: String): String =
            t.split(Regex("""\s+[-–—|·»:]\s+""")).firstOrNull { it.isNotBlank() }?.trim() ?: t.trim()

        fun build(title: String, heading: String, description: String, userPref: String?): GoalContext {
            val pref = userPref?.trim().orEmpty()
            val userFormats = mutableSetOf<String>(); val userWords = mutableListOf<String>()
            if (pref.isNotEmpty()) {
                for (raw in pref.split(Regex("""[\s,;]+""")).filter { it.isNotBlank() }) {
                    val w = Text.normalize(raw).trim('.')
                    if ((raw.startsWith(".") || w in FORMAT_WORDS) && w in FORMAT_WORDS) userFormats += w else Text.tokens(raw).forEach { userWords += it }
                }
            }
            val main = cleanTitle(heading.ifBlank { title })
            val titleToks = Text.tokens(cleanTitle(title)) + (if (heading.isNotBlank()) Text.tokens(cleanTitle(heading)) else emptyList())
            val descToks = Text.tokens(description.take(300))
            val allToks = (titleToks + descToks).toSet()
            // formatos: só palavras EXPLÍCITAS no título/cabeçalho/descrição (conservador)
            val inferredFormats = (Text.tokens(title) + Text.tokens(heading) + descToks).filter { it in FORMAT_WORDS }.toMutableSet()
            val media = mutableSetOf<MediaFamily>()
            if (allToks.any { it in VIDEO_WORDS } || inferredFormats.any { it in Relevance.VIDEO }) media += MediaFamily.VIDEO
            if (allToks.any { it in AUDIO_WORDS } || inferredFormats.any { it in Relevance.AUDIO }) media += MediaFamily.AUDIO
            if (allToks.any { it in IMAGE_WORDS } || inferredFormats.any { it in Relevance.IMAGE }) media += MediaFamily.IMAGE
            val nameBase = if (userWords.isNotEmpty()) userWords else Text.tokens(main) + Text.tokens(cleanTitle(title))
            val name = nameBase.filter { it !in STOP && it !in PLATFORMS && it !in FORMAT_WORDS && it !in VIDEO_WORDS && it.length >= 3 && !it.all(Char::isDigit) }.distinct().take(6)
            val formats = if (userFormats.isNotEmpty()) userFormats else inferredFormats
            return GoalContext(
                nameTokens = name, formats = formats, userSpecified = userWords.isNotEmpty() || userFormats.isNotEmpty(),
                wantsTutorial = (titleToks + Text.tokens(heading)).any { it in TUTORIAL_WORDS }, allowedMedia = media,
                source = if (pref.isNotEmpty()) "usuário" else "página",
            )
        }
    }
}

enum class MediaFamily(val label: String) { VIDEO("vídeo"), AUDIO("áudio"), IMAGE("imagem") }

object Text {
    fun normalize(s: String): String =
        Normalizer.normalize(s, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "").lowercase(Locale.ROOT)

    fun tokens(s: String): List<String> = normalize(s).split(Regex("[^a-z0-9]+")).filter { it.length >= 2 }

    /** Texto sem separadores, para achar palavras coladas em nomes de arquivo ("guidedownloadgame"). */
    fun squash(s: String): String = normalize(s).replace(Regex("[^a-z0-9]+"), "")
}

enum class Verdict { COMPATIBLE, UNKNOWN, MISMATCH }
data class Compat(val verdict: Verdict, val reason: String)
data class FileFacts(val url: String, val name: String?, val mime: String?, val linkText: String)

/** Relevância contextual (separada da pontuação técnica) e compatibilidade de arquivos com o objetivo. */
object Relevance {
    val VIDEO = setOf("mp4", "mkv", "avi", "mov", "webm", "wmv", "flv", "m4v", "mpg", "mpeg")
    val AUDIO = setOf("mp3", "flac", "wav", "ogg", "m4a", "aac")
    val IMAGE = setOf("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg")
    val ARCHIVE = setOf("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst")
    val INSTALLER = setOf("pkg", "exe", "msi", "apk", "aab", "dmg", "deb", "rpm", "appimage", "iso", "img", "bin", "jar", "nsp", "xci", "wad", "cia", "chd", "cso", "pbp")
    private val TUTORIAL_SQUASHED = listOf("tutorial", "guide", "guia", "howto", "faq", "ajuda", "helpme", "manual", "instruction", "walkthrough", "trailer", "preview", "demo")
    private val TUTORIAL_TOKENS = setOf("help", "how", "faq", "guide", "guia", "tutorial", "ajuda")

    fun mediaOf(ext: String?): MediaFamily? = when (ext) {
        null -> null
        in VIDEO -> MediaFamily.VIDEO; in AUDIO -> MediaFamily.AUDIO; in IMAGE -> MediaFamily.IMAGE
        else -> null
    }

    fun isTutorialLike(s: String): Boolean {
        val sq = Text.squash(s)
        return TUTORIAL_SQUASHED.any { sq.contains(it) } || Text.tokens(s).any { it in TUTORIAL_TOKENS }
    }

    private fun lastSegment(url: String): String =
        UrlSafety.parse(url)?.path?.trimEnd('/')?.substringAfterLast('/')?.let { UrlSafety.decode(it) }.orEmpty()

    private fun nameOf(url: String): String =
        UrlSafety.parse(url)?.path?.substringAfterLast('/')?.let { UrlSafety.decode(it) }.orEmpty()

    private fun formatOk(goal: GoalContext, ext: String): Boolean =
        ext in goal.formats ||
            (ext in ARCHIVE && goal.formats.any { it in INSTALLER || it in DownloadHeuristics.FILE_EXTENSIONS && it !in VIDEO && it !in AUDIO && it !in IMAGE }) ||
            (goal.formats.contains("rom") && (ext in ARCHIVE || ext in DownloadHeuristics.FILE_EXTENSIONS && mediaOf(ext) == null))

    /** Aplica a relevância: devolve cópia com `score = técnica + contexto`, mantendo as duas partes separadas. */
    fun apply(c: ScoredCandidate, goal: GoalContext?): ScoredCandidate {
        if (goal == null || !goal.informative || c.url == null) return c
        val reasons = mutableListOf<String>(); var rel = 0; var bonus = 0
        val url = c.url!!
        // só o TEXTO do link e o último trecho da URL (nome do arquivo/slug): diretórios comuns a todos os links (dono/repo) não contam
        val hay = c.raw.text + " " + lastSegment(url)
        val sq = Text.squash(hay)
        val matched = goal.nameTokens.count { it.length >= 3 && sq.contains(it) }
        if (matched > 0) {
            val b = 20 + (30.0 * matched / goal.nameTokens.size).toInt(); rel += b; bonus += b; reasons += "corresponde ao nome do conteúdo ($matched/${goal.nameTokens.size})"
        }
        val fileName = nameOf(url)
        val ext = DownloadHeuristics.extensionOf(url) ?: DownloadHeuristics.extensionOf(c.raw.text)
        if (ext != null && ext in DownloadHeuristics.FILE_EXTENSIONS) {
            val media = mediaOf(ext)
            if (formatOk(goal, ext)) { rel += 25; bonus += 25; reasons += "formato desejado (.$ext)" }
            else if (media != null && media !in goal.allowedMedia) {
                rel -= if (goal.formats.isNotEmpty()) 35 else 25; reasons += "mídia (.$ext) que não é o objetivo"
            } else if (goal.formats.isNotEmpty() && media == null) { rel -= 20; reasons += "formato diferente do desejado (.$ext)" }
        }
        if (!goal.wantsTutorial && matched < maxOf(1, goal.nameTokens.size * 2 / 3) && isTutorialLike("${c.raw.text} $fileName")) {
            rel -= 40; reasons += "tutorial/guia/ajuda/vídeo explicativo (não corresponde ao objetivo)"
        }
        // Bônus só para quem já tem sinal técnico de download/etapa: um link de navegação comum não vira candidato só por citar o nome
        if (c.technical < 20 && bonus > 0) { rel -= bonus; reasons.removeAll { it.startsWith("corresponde") || it.startsWith("formato desejado") } }
        if (rel == 0) return c
        return c.copy(score = c.technical + rel, relevance = rel, relevanceReasons = reasons)
    }

    /** O arquivo confirmado por HTTP corresponde ao que se procurava? */
    fun compat(goal: GoalContext?, f: FileFacts): Compat {
        if (goal == null || !goal.informative) return Compat(Verdict.UNKNOWN, "sem contexto suficiente")
        val name = f.name ?: nameOf(f.url)
        val ext = DownloadHeuristics.extensionOf(name) ?: DownloadHeuristics.extensionOf(f.url)
            ?: f.mime?.substringAfter('/')?.substringBefore(';')?.takeIf { it in VIDEO || it in AUDIO || it in IMAGE }
        val sq = Text.squash("$name ${f.linkText}")
        val matched = goal.nameTokens.count { it.length >= 3 && sq.contains(it) }
        val media = mediaOf(ext) ?: when {
            f.mime?.startsWith("video/") == true -> MediaFamily.VIDEO
            f.mime?.startsWith("audio/") == true -> MediaFamily.AUDIO
            f.mime?.startsWith("image/") == true -> MediaFamily.IMAGE
            else -> null
        }
        if (!goal.wantsTutorial && matched < maxOf(1, goal.nameTokens.size * 2 / 3) && isTutorialLike("$name ${f.linkText}")) {
            return Compat(Verdict.MISMATCH, "o arquivo parece tutorial/guia/vídeo explicativo (${name.ifEmpty { f.url.substringAfterLast('/') }})")
        }
        if (media != null && media !in goal.allowedMedia) {
            return Compat(Verdict.MISMATCH, "mídia ${media.label} (.${ext ?: f.mime}) não corresponde ao objetivo")
        }
        if (ext != null && goal.formats.isNotEmpty() && !formatOk(goal, ext)) {
            return Compat(Verdict.MISMATCH, "formato .$ext diferente do desejado (${goal.formats.sorted().joinToString("/") { ".$it" }})")
        }
        if (matched > 0) return Compat(Verdict.COMPATIBLE, "o nome corresponde ao conteúdo ($matched/${goal.nameTokens.size})")
        // nome com palavras distintivas e nenhuma coincide ⇒ conteúdo diferente; nome opaco ⇒ não dá para saber
        val distinctive = Text.tokens(name.substringBeforeLast('.')).filter { it.length >= 4 && !it.all(Char::isDigit) && Regex("[a-z]{4,}").containsMatchIn(it) }
        // só quando o USUÁRIO disse o que quer: o título de uma página não obriga o arquivo a ter o mesmo nome
        if (goal.userSpecified && goal.nameTokens.isNotEmpty() && distinctive.isNotEmpty() && ext != null && ext in DownloadHeuristics.FILE_EXTENSIONS) {
            return Compat(Verdict.MISMATCH, "o nome do arquivo (${distinctive.take(3).joinToString(" ")}) não corresponde ao conteúdo «${goal.nameTokens.joinToString(" ")}»")
        }
        return Compat(Verdict.UNKNOWN, "nome sem informação suficiente")
    }
}
