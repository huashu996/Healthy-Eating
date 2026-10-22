export type NutrientRange = { low: number; high: number } | null | undefined;
export const foodGroups = [
  { key: 'protein', label: '蛋白质', placeholder: '鸡蛋、牛肉、豆腐…' },
  { key: 'fats', label: '油脂', placeholder: '坚果、橄榄油、牛油果…' },
  { key: 'carbs', label: '碳水', placeholder: '米饭、面条、土豆…' },
  { key: 'fiber', label: '膳食纤维', placeholder: '西兰花、苹果、燕麦…' },
] as const;

export function nutrientPoint(value: NutrientRange): number | null {
  if (!value || !Number.isFinite(value.low) || !Number.isFinite(value.high) || value.low < 0 || value.high < value.low) return null;
  return Math.round((value.low + value.high) / 2 * 10) / 10;
}

export function nutrientProgress(value: number | null, target?: number | null) {
  if (value === null || !Number.isFinite(value) || value < 0 || !target || !Number.isFinite(target) || target <= 0) return null;
  return Math.round(value / target * 100);
}

// Display the stored uncertainty without changing the midpoint or daily totals.
export function nutrientRangeLabel(value: NutrientRange): string | null {
  if (nutrientPoint(value) === null || !value || value.low === value.high) return null;
  const format = (amount: number) => amount.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  return `${format(value.low)}–${format(value.high)}`;
}

export function recordedDay(eatenAt: string | null | undefined, timezone = 'Asia/Shanghai'): string | null {
  if (!eatenAt) return null;
  const date = new Date(eatenAt);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat('sv-SE', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

export function nutrientAmountLabel(value: NutrientRange): string {
  const amount = nutrientPoint(value);
  return amount === null || !value ? '待分析' : Math.round((value.low + value.high) / 2).toLocaleString('zh-CN', { useGrouping: false });
}

// Recommendation nutrition is a separate calculated plan, never recorded intake.
export function planAmountLabel(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value).toLocaleString('zh-CN', { useGrouping: false }) : '待核算';
}

export function selectedPlanVariant(plan: any, id?: string | null) {
  const variant = plan?.variants?.find((item: any) => item.id === id);
  return variant ? { ...plan, ...variant, condition_label: variant.condition || variant.label } : plan;
}

export function adviceDayLabel(planDate?: string, today?: string): string {
  if (!planDate || planDate === today) return '今日';
  if (today && Date.parse(planDate + 'T00:00:00Z') - Date.parse(today + 'T00:00:00Z') === 86400000) return '明日';
  return /^\d{4}-\d{2}-\d{2}$/.test(planDate) ? `${Number(planDate.slice(5, 7))}月${Number(planDate.slice(8, 10))}日` : '指定日期';
}

export function remainingPlanIsCurrent(plan: any, today: any): boolean {
  if (plan?.plan_scope !== 'remaining_today') return true;
  const snapshot = plan.original_intake_snapshot;
  if (!today || !snapshot || plan.target_date !== today.date || snapshot.date !== today.date || snapshot.meals_count !== today.meals_count || Boolean(snapshot.finished) !== Boolean(today.finished)) return false;
  return ['kcal', 'protein_g', 'fat_g', 'carbs_g'].every(key => {
    const before = snapshot.totals?.[key], now = today.totals?.[key];
    return !before && !now || before && now && ['low', 'high', 'coverage'].every(field => before[field] === now[field]);
  });
}

export function isConsumedMeal(execution?: string): boolean {
  return !['planned', 'skipped', 'replaced'].includes(execution || 'done');
}

// Match overview's consumed-portion display without altering stored meal nutrition.
export function consumedNutrient(value: NutrientRange, fraction = 1): NutrientRange {
  if (!value || nutrientPoint(value) === null || !Number.isFinite(fraction) || fraction < 0 || fraction > 1) return null;
  return { low: value.low * fraction, high: value.high * fraction };
}

export function likeDraft(data?: any) {
  return { protein: '', fats: '', carbs: '', fiber: '', ...(data?.food_likes || {}), previous: data?.food_likes?.previous ?? (data?.food_likes ? '' : data?.rule || '') };
}

export function likeRule(likes: Record<string, string>) {
  return [...foodGroups.map(group => likes[group.key]?.trim() ? `${group.label}：${likes[group.key].trim()}` : ''), likes.previous?.trim()].filter(Boolean).join('\n');
}
