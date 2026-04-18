import { BookOpen } from 'lucide-react'
import { api } from '../api'

const EXAMPLE_RULES = [
  'For mosaic tile and backsplash, use white thinset',
  'Tub/shower Schluter uses Jolly J 100 AE at $9.78/stick',
  'Only add LFT thinset for tiles 16x30 or larger',
  'Sound mat is excluded from LVT unless specified',
]

export default function BusinessRulesTab() {
  return (
    <div className="space-y-6">
      <div className="glass-card p-8">
        {/* Header */}
        <div className="flex items-start gap-4 mb-6">
          <div className="w-11 h-11 rounded-xl bg-blue-500/10 flex items-center justify-center flex-shrink-0">
            <BookOpen className="w-5 h-5 text-blue-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-white">Business Rules</h2>
            <p className="text-sm text-gray-500 mt-1">
              Define rules that control how the AI pipeline handles materials, pricing, and descriptions.
            </p>
          </div>
          <span className="text-[10px] font-bold px-2.5 py-1 rounded-full bg-gray-500/15 text-gray-500 uppercase tracking-wider">
            Coming Soon
          </span>
        </div>

        {/* Empty state explanation */}
        <div className="text-center py-6 mb-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
          <BookOpen className="w-8 h-8 text-gray-600 mx-auto mb-3 opacity-40" />
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Business rules will let you create instructions like "Default Schluter to AE finish" or
            "Use white thinset for backsplash". Rules are enforced automatically every time the pipeline runs.
          </p>
        </div>

        {/* Example rules */}
        <div>
          <span className="text-xs font-bold text-gray-500 uppercase tracking-[0.12em] mb-3 block">
            Example Rules
          </span>
          <div className="space-y-2">
            {EXAMPLE_RULES.map((rule, i) => (
              <div
                key={i}
                className="flex items-center gap-3 px-4 py-3 bg-white/[0.02] border border-white/[0.04] rounded-xl border-l-2 border-l-blue-500/40 opacity-60"
              >
                <p className="flex-1 text-sm text-gray-400">{rule}</p>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-gray-500/10 text-gray-600 whitespace-nowrap">
                  Coming soon
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
