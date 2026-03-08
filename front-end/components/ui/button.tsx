import * as React from 'react'
import { cn } from '@/lib/utils'

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: 'default' | 'icon' | 'lg'
}

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  default: 'h-10 px-4 py-2',
  icon: 'h-10 w-10',
  lg: 'h-11 px-6 py-3',
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, size = 'default', type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-md text-sm font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        'disabled:pointer-events-none disabled:opacity-50',
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  ),
)

Button.displayName = 'Button'
