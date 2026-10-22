// Compare actual instants across time zones. Never use last-modified time.
export type MealTime = { eaten_at?: string | null; received_at?: string | null; created_at?: string | null };
export function mealTime(value: MealTime): number {
  for (const stamp of [value.eaten_at, value.received_at, value.created_at]) {
    if (!stamp || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(stamp)) continue;
    const time = Date.parse(stamp);
    if (Number.isFinite(time)) return time;
  }
  return Infinity;
}
export function compareMealTimes(a: MealTime, b: MealTime): number {
  const first = mealTime(a), second = mealTime(b);
  if (first !== second) return first < second ? -1 : 1;
  const originalA = mealTime({ received_at: a.received_at, created_at: a.created_at });
  const originalB = mealTime({ received_at: b.received_at, created_at: b.created_at });
  return originalA === originalB ? 0 : originalA < originalB ? -1 : 1;
}
