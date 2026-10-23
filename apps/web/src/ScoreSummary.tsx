import { estimatedScoreValue, validScore } from './scoreDisplay';
import type { ScoreDisplayData } from './scoreDisplay';

type Part = { key: string; name: string; points: number | null; maximum: number; reason?: string };
type ScoreSummaryData = ScoreDisplayData & { components?: Part[]; estimated_components?: Part[]; score_limitations?: string[]; score_version?: string };
const show = (value: number) => Number(value.toFixed(1)).toString();

export function ScoreSummary({ data = {} }: { data?: ScoreSummaryData }) {
  const estimate = estimatedScoreValue(data), estimated = estimate !== null;
  const continuous = data.score_version === 'diet-quality-v8-continuous-tolerance';
  // Explicit estimate data never becomes a saved score or falls back to formal components.
  const score = estimated ? estimate : (!data.score_status || data.score_status === 'saved') && !data.pending_changes && !data.is_future && validScore(data.score) ? data.score : null;
  const parts = estimated ? data.estimated_components || [] : data.score_status === 'estimated' ? [] : data.components || [];
  const assessed = parts.filter(p => typeof p.points === 'number' && p.maximum > 0);
  const risks = parts.filter(p => typeof p.points === 'number' && p.maximum === 0 && p.points < 0);
  const raw = assessed.reduce((a, p) => a + (p.points || 0), 0), max = assessed.reduce((a, p) => a + p.maximum, 0), deduction = risks.reduce((a, p) => a - (p.points || 0), 0);
  const alcohol = parts.find(p => p.key === 'alcohol');
  const capped = !continuous && score === 79 && Math.round(raw - deduction) > 79 && (data.score_limitations?.some(note => note.includes('79')) || estimated && parts.some(p => ['energy', 'protein', 'fat', 'carbs'].includes(p.key) && p.points === 0));
  const normalized = data.score_scope === 'recorded_normalized', points = parts.filter(p => typeof p.points === 'number' && p.points < p.maximum);
  const unknown = parts.filter(p => p.points === null).map(p => p.name);
  const why = (p: Part) => p.key === 'alcohol' ? (p.reason?.split('；')[0] || `已记录饮酒，扣${show(Math.abs(p.points || 0))}分。`) : p.maximum === 10 && p.points === 5 && p.reason?.includes('识别') ? `${p.name}：已识别吃过，但份量未量化，按规则计5/10分，扣5分。` : `${p.name}：${show(p.points || 0)}/${p.maximum}分，扣${show(p.maximum - (p.points || 0))}分。${p.reason?.split('；')[0]?.slice(0, 90) || ''}`;
  return <div className="score-concise"><h3>1. 我为什么扣分</h3><ul>{points.length ? points.map(p => <li key={p.key}>{why(p)}</li>) : <li>{score === null ? '尚未生成有效评分。' : `${estimated ? '估算' : '已评'}项目没有扣分。`}</li>}</ul>
    <h3>2. 分数怎么算</h3><ul>
    <li>{parts.length ? parts.filter(p => p.maximum > 0).map(p => `${p.name}${p.maximum}分`).join('、') + '。' : '当日暂无可用的评分明细。'}</li>
    {continuous && <li>热量、蛋白质、脂肪、碳水：上下偏差5%内满分，之后线性扣分，偏差40%及以上为0分。</li>}
    {continuous && <li>蔬菜、水果、全谷杂豆仍参考300、200、50克；少多少比例就扣该项多少比例，吃够或超过满分，没吃0分。</li>}
    {score !== null && max > 0 && <li>{normalized ? `${show(raw)} ÷ ${max} × 100 ≈ ${Math.round(raw / max * 100)}` : `${estimated ? '估算' : '已评'}项目合计${show(raw)}`}{deduction > 0 ? `，再扣${show(deduction)}分` : ''}{capped ? '，按明显偏离目标规则封顶为' : estimated ? '，估算取整为' : '，取整为'}{score}/100分。</li>}
    {continuous && <li>固定100分，不归一、不另设79分封顶；计算保留原精度，展示至1位小数。未称重本身不扣分。</li>}
    {unknown.length > 0 && <li>{unknown.join('、')}无可评证据，不当作没吃；{normalized ? '从分母剔除。' : '保留未评。'}</li>}
    {alcohol?.reason?.includes('每3g') && <li>酒精：毫升×酒精度÷100×0.789换算克数；每3g扣1分，最多30分。</li>}
    <li>软件饮食参考分，不是医学诊断。{alcohol?.reason?.includes('每3g') ? '少量饮酒也非无风险，扣分封顶不等于风险封顶。' : ''}</li></ul></div>;
}
