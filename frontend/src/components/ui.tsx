/* Small component kit in the shadcn/ui pattern (Radix primitives + CVA + Tailwind), written in-repo. */
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/format'

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
