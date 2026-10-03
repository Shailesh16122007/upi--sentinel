/* Small component kit in the shadcn/ui pattern (Radix primitives + CVA + Tailwind), written in-repo. */
import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from 'react'
import { cn, STATUS_TONE } from '@/lib/format'

const button = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[var(--radius-sm)] text-[13px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-white hover:bg-accent-ink',
        secondary: 'border border-rule bg-surface text-ink hover:bg-tint',
        ghost: 'text-ink-2 hover:bg-tint',
        danger: 'border border-contra/40 bg-surface text-contra hover:bg-contra-tint',
      },
      size: { sm: 'h-7 px-2.5', md: 'h-8 px-3', lg: 'h-10 px-4 text-[14px]' },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>>(
  ({ className, variant, size, ...p }, ref) => <button ref={ref} className={cn(button({ variant, size }), className)} {...p} />,
)
Button.displayName = 'Button'

const badge = cva('inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-1.5 py-px text-[11.5px] font-medium leading-5', {
  variants: {
    tone: {
      neutral: 'bg-tint text-ink-2',
      accent: 'bg-accent-tint text-accent-ink',
      ok: 'bg-ok-tint text-ok',
      warn: 'bg-missing-tint text-missing',
      bad: 'bg-contra-tint text-contra',
      outline: 'border border-rule text-muted',
    },
  },
  defaultVariants: { tone: 'neutral' },
})
export const Badge = ({ className, tone, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) =>
  <span className={cn(badge({ tone }), className)} {...p} />

export const Panel = ({ className, ...p }: HTMLAttributes<HTMLDivElement>) =>
  <div className={cn('rounded-[var(--radius-md)] border border-rule bg-surface', className)} {...p} />

export const PanelHead = ({ title, aside, sub }: { title: ReactNode; aside?: ReactNode; sub?: ReactNode }) => (
  <div className="flex items-start justify-between gap-3 border-b border-rule-2 px-4 py-2.5">
    <div>
      <h3 className="text-[13.5px] font-semibold text-ink">{title}</h3>
      {sub && <p className="mt-0.5 text-[12.5px] text-muted">{sub}</p>}
    </div>
    {aside}
  </div>
)

export const Tabs = TabsPrimitive.Root
export const TabsList = ({ className, ...p }: TabsPrimitive.TabsListProps) =>
  <TabsPrimitive.List className={cn('flex gap-0 overflow-x-auto border-b border-rule', className)} {...p} />
export const TabsTrigger = ({ className, ...p }: TabsPrimitive.TabsTriggerProps) => (
  <TabsPrimitive.Trigger
    className={cn('-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-[13px] text-muted hover:text-ink data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-ink', className)}
    {...p}
  />
)
export const TabsContent = TabsPrimitive.Content

export const ErrorNote = ({ children, action }: { children: ReactNode; action?: ReactNode }) => (
  <div role="alert" className="flex items-start justify-between gap-3 rounded-[var(--radius-sm)] border border-contra/30 bg-contra-tint px-3 py-2 text-[13px] text-contra">
    <span>{children}</span>{action}
  </div>
)

export const Empty = ({ children }: { children: ReactNode }) =>
  <p className="px-4 py-6 text-[13px] text-muted">{children}</p>

export const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) => (
  <label className="block">
    <span className="text-[13px] font-medium text-ink">{label}</span>
    {hint && <span className="ml-1.5 text-[12.5px] text-muted">{hint}</span>}
    <div className="mt-1.5">{children}</div>
  </label>
)

export const inputCls = 'w-full rounded-[var(--radius-sm)] border border-rule bg-surface px-2.5 py-1.5 text-[14px] text-ink placeholder:text-faint focus:border-accent focus:outline-none'

/* ------------------------------------------------------------------ V2 additions */

export const StatusBadge = ({ status, label, className }: { status: string; label: string; className?: string }) =>
  <Badge tone={STATUS_TONE[status] ?? 'neutral'} className={className}>{label}</Badge>

export const SyntheticBadge = () => <Badge tone="bad" title="Synthetic demonstration data — not a real dispute">DEMO · synthetic</Badge>

export function Stat({ label, value, hint, onClick, tone }: { label: string; value: ReactNode; hint?: ReactNode; onClick?: () => void; tone?: 'warn' | 'ok' | 'bad' }) {
  const Comp = onClick ? 'button' : 'div'
  return (
    <Comp onClick={onClick} className={cn('flex flex-col items-start rounded-[var(--radius-md)] border border-rule bg-surface px-4 py-3 text-left',
      onClick && 'hover:border-accent/50 hover:bg-tint/40')}>
      <span className="text-[12.5px] text-muted">{label}</span>
      <span className={cn('tabular mt-0.5 text-[24px] font-semibold leading-tight',
        tone === 'warn' && 'text-missing', tone === 'ok' && 'text-ok', tone === 'bad' && 'text-contra')}>{value}</span>
      {hint && <span className="mt-0.5 text-[12px] text-faint">{hint}</span>}
    </Comp>
  )
}

export const PageHead = ({ title, sub, aside }: { title: ReactNode; sub?: ReactNode; aside?: ReactNode }) => (
  <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-ink">{title}</h1>
      {sub && <p className="mt-0.5 text-[13.5px] text-muted">{sub}</p>}
    </div>
    {aside}
  </div>
)

export const selectCls = 'h-8 rounded-[var(--radius-sm)] border border-rule bg-surface px-2 text-[13px] text-ink focus:border-accent focus:outline-none'

export function Dialog({ open, onOpenChange, title, children, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode; wide?: boolean }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/25" />
        <DialogPrimitive.Content className={cn('fixed left-1/2 top-[12vh] z-50 max-h-[80vh] w-[calc(100%-32px)] -translate-x-1/2 overflow-y-auto rounded-[var(--radius-md)] border border-rule bg-surface shadow-[0_12px_40px_rgba(19,35,63,0.18)]',
          wide ? 'max-w-[720px]' : 'max-w-[520px]')}>
          <div className="flex items-center justify-between border-b border-rule-2 px-5 py-3">
            <DialogPrimitive.Title className="text-[15px] font-semibold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close className="text-[13px] text-muted hover:text-ink" aria-label="Close">Close</DialogPrimitive.Close>
          </div>
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
          <div className="px-5 py-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export const FieldStateBadge = ({ state, label }: { state: string; label: string }) => {
  const tone = ({ CONFIRMED: 'ok', SINGLE_SOURCE: 'neutral', NEEDS_REVIEW: 'warn', APPROXIMATE: 'warn', PARTIAL: 'warn',
    CONFLICT: 'bad', NOT_FOUND: 'outline' } as const)[state] ?? 'neutral'
  return <Badge tone={tone}>{label}</Badge>
}
