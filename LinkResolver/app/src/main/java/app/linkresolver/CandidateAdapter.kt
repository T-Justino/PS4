package app.linkresolver

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import app.linkresolver.core.ScoredCandidate
import app.linkresolver.core.UrlSafety
import app.linkresolver.databinding.ItemCandidateBinding

class CandidateAdapter(private val onAction: (ScoredCandidate) -> Unit) :
    RecyclerView.Adapter<CandidateAdapter.VH>() {

    private var items: List<ScoredCandidate> = emptyList()

    fun submit(list: List<ScoredCandidate>) {
        items = list
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
        h.b.candTitle.text = "[${c.score}] ${c.raw.text.ifBlank { "(sem texto)" }}  · $badge"
        h.b.candUrl.text = c.url?.let { UrlSafety.redact(it) } ?: "(sem URL — botão de script, ${c.raw.tag})"
        h.b.candReasons.text = c.reasons.joinToString(" • ").ifEmpty { "sem sinais" }
        val actionable = !c.ad && (c.url == null || c.safe) && (c.url != null || c.raw.elementId != null)
        h.b.candAction.isEnabled = actionable
        h.b.candAction.setText(if (c.url != null) R.string.btn_follow else R.string.btn_click)
        h.b.candAction.setOnClickListener { onAction(c) }
    }
}
