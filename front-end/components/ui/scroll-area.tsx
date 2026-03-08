import * as React from 'react'
import { cn } from '@/lib/utils'

type ScrollAreaProps = React.HTMLAttributes<HTMLDivElement>

export const ScrollArea = React.forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('overflow-y-auto', className)} {...props} />
  ),
)

ScrollArea.displayName = 'ScrollArea'
