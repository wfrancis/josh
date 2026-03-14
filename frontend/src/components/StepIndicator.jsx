import { Check } from 'lucide-react'

const STEPS = [
  { key: 'info', label: 'Job Info & Materials' },
  { key: 'pricing', label: 'Quotes & Pricing' },
  { key: 'bid', label: 'Review & Generate' },
]

export default function StepIndicator({ current, onStepClick, completedSteps = [] }) {
  return (
    <div className="flex items-center gap-0">
      {STEPS.map((step, i) => {
        const isActive = current === step.key
        const isComplete = completedSteps.includes(step.key)
        return (
          <div key={step.key} className="flex items-center">
            {i > 0 && (
              <div className={`w-4 sm:w-12 h-px ${isComplete ? 'bg-si-bright/40' : 'bg-white/[0.06]'}`} />
            )}
            <button
              onClick={() => onStepClick(step.key)}
              className={`flex items-center gap-1.5 sm:gap-2.5 px-2 sm:px-4 py-2 rounded-xl text-sm font-medium transition-all
                ${isActive
                  ? 'bg-si-bright/10 text-si-bright'
                  : isComplete
                    ? 'text-si-bright/70 hover:bg-white/[0.04]'
                    : 'text-gray-600 hover:text-gray-400 hover:bg-white/[0.03]'
                }`}
            >
              <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all
                ${isActive
                  ? 'bg-si-bright text-white shadow-[0_0_12px_rgba(17,109,255,0.4)]'
                  : isComplete
                    ? 'bg-si-bright/15 text-si-bright'
                    : 'bg-white/[0.06] text-gray-500'
                }`}
              >
                {isComplete && !isActive ? <Check className="w-4 h-4" /> : i + 1}
              </span>
              <span className="hidden sm:inline">{step.label}</span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

export { STEPS }
