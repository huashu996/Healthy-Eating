export type ScoreDisplayData = {
  score?: number | null;
  score_status?: string;
  score_scope?: string;
  score_maximum?: number | null;
  estimated_score?: number | null;
  estimate_notice?: string;
  pending_changes?: boolean;
  is_future?: boolean;
};

export function validScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100;
}

export function estimatedScoreValue(data: ScoreDisplayData): number | null {
  return data.score_status === 'estimated' && data.score == null && !data.pending_changes && !data.is_future && (data.score_maximum ?? 100) === 100 && validScore(data.estimated_score) ? data.estimated_score : null;
}

export function scoreEstimateNotice(data: ScoreDisplayData): string {
  return data.estimate_notice?.trim() || '按营养区间中点估算，不代表精确摄入；区间跨评分档位，分数可能变化，正式评分仍待复核。';
}
