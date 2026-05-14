import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Compose Tailwind class names safely.
 *
 * Combines `clsx` (conditional joining) with `tailwind-merge` (collision
 * resolution), so later utilities reliably override earlier ones.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
