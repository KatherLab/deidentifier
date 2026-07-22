/**
 * Shared color class maps for pills/badges and soft banners (adapted from
 * llmaixweb's utils/statusStyles.ts). All variants include dark-mode styles.
 */

/**
 * Generic dark-mode-aware color map for semantic pills (status badges, counts,
 * entity type chips, …).
 */
const PILL_COLORS: Record<string, string> = {
  blue: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
  green: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  yellow: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300',
  amber: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
  red: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
  pink: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300',
  purple: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
  teal: 'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300',
  cyan: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300',
  orange: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300',
  gray: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300',
}

const DEFAULT_PILL_COLOR: string = PILL_COLORS.gray ?? ''

export function getPillClass(color: string | null | undefined): string {
  return (color && PILL_COLORS[color]) || DEFAULT_PILL_COLOR
}

/**
 * Soft banner/box variant (bg-*-50 + border-*-200) for status callouts that
 * need more presence than a pill.
 */
const BANNER_COLORS: Record<string, string> = {
  blue: 'bg-blue-50 border border-blue-200 text-blue-700 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-300',
  green:
    'bg-green-50 border border-green-200 text-green-700 dark:bg-green-900/20 dark:border-green-800 dark:text-green-300',
  yellow:
    'bg-yellow-50 border border-yellow-200 text-yellow-700 dark:bg-yellow-900/20 dark:border-yellow-800 dark:text-yellow-300',
  amber:
    'bg-amber-50 border border-amber-200 text-amber-700 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-300',
  red: 'bg-red-50 border border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-300',
  gray: 'bg-slate-50 border border-slate-200 text-slate-700 dark:bg-slate-700/40 dark:border-slate-600 dark:text-slate-300',
}

const DEFAULT_BANNER_COLOR: string = BANNER_COLORS.gray ?? ''

export function getBannerClass(color: string | null | undefined): string {
  return (color && BANNER_COLORS[color]) || DEFAULT_BANNER_COLOR
}

export { PILL_COLORS, DEFAULT_PILL_COLOR, BANNER_COLORS }
