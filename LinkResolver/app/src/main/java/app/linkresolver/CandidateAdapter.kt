package app.linkresolver

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import app.linkresolver.core.ScoredCandidate
import app.linkresolver.core.UrlSafety
import app.linkresolver.databinding.ItemCandidateBinding

class CandidateAdapter(
    private val onAction: (ScoredCandidate) -> Unit,
    private val onCopy: (ScoredCandidate) -> Unit,
) :
    RecyclerView.Adapter<CandidateAdapter.VH>() {

    private var items: List<ScoredCandidate> = emptyList()
    private var statuses: List<String> = emptyList()

    fun submit(list: List<ScoredCandidate>) {
        items = list
        statuses = emptyList()
        notifyDataSetChanged()
    }

    /** Status por candidato (mesma ordem de [submit]) após a análise terminar. */
    fun setStatuses(s: List<String>) {
        statuses = s
        notifyDataSetChanged()
    }

    class VH(val b: ItemCandidateBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(ItemCandidateBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: VH, position: Int) {
        val c = items[position]
        val badge = when {
            c.ad -> "ANÚNCIO"
            !c.safe -> "INSEGURO"
            c.trusted -> "confiável"
            else -> "domínio novo"
        }
        h.b.candTitle.text = "[${c.score}] ${c.raw.text.ifBlank { "(sem texto)" }}  · ${c.linkClass.label} · $badge"
        h.b.candUrl.text = c.url?.let { UrlSafety.redact(it) } ?: "(sem URL — botão de script, ${c.raw.tag})"
        val status = statuses.getOrNull(position) ?: "não verificado"
        h.b.candReasons.text = "Status: $status\n" + c.reasons.joinToString(" • ").ifEmpty { "sem sinais" }
        h.b.candCopy.isEnabled = c.url != null && c.safe && !c.ad
        h.b.candCopy.setOnClickListener { onCopy(c) }
        val actionable = !c.ad && (c.url == null || c.safe) && (c.url != null || c.raw.elementId != null)
        h.b.candAction.isEnabled = actionable
        h.b.candAction.setText(if (c.url != null) R.string.btn_follow else R.string.btn_click)
        h.b.candAction.setOnClickListener { onAction(c) }
    }
}
