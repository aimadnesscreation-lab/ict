import { cn } from '../utils/format';

interface SignalBadgeProps {
  type: string;
}

const styles: Record<string, string> = {
  STRONG_BUY: 'bg-emerald-500/10 text-emerald-400',
  BUY: 'bg-emerald-500/5 text-emerald-300',
  NEUTRAL: 'bg-slate-500/10 text-slate-400',
  SELL: 'bg-rose-500/5 text-rose-300',
  STRONG_SELL: 'bg-rose-500/10 text-rose-400',
};

export default function SignalBadge({ type }: SignalBadgeProps) {
  return (
    <span className={cn('px-2 py-0.5 rounded-full text-xs font-bold', styles[type] ?? styles.NEUTRAL)}>
      {type.replace('_', ' ')}
    </span>
  );
}
