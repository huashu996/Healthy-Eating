import { useEffect, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { api, fmtDate } from './lib';
import { nutrientAmountLabel, nutrientRangeLabel } from './dietDisplay';
import { IconButton } from './components';
import { ScoreBreakdown } from './ScoreBreakdown';
import { estimatedScoreValue, validScore } from './scoreDisplay';

const nutrients = [['kcal', '热量', 'kcal'], ['protein_g', '蛋白质', 'g'], ['fat_g', '脂肪', 'g'], ['carbs_g', '碳水', 'g']];
export function scoreBand(value: unknown): string {
  return validScore(value) ? value >= 85 ? 'green' : value >= 70 ? 'yellow' : 'red' : 'neutral';
}
export function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split('-').map(Number);
  const date = new Date(Date.UTC(year, number - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}
export function CalendarGrid({ data, navigate }: { data: any; navigate: (path: string) => void }) {
  const bandLabels: Record<string, string> = { green: '绿色，85分及以上', yellow: '黄色，70至不足85分', red: '红色，不足70分', neutral: '未完整评分' };
  return <div className="history-calendar" aria-label={`${data.month}饮食日历`}>
    {['一', '二', '三', '四', '五', '六', '日'].map(day => <span className="history-weekday" key={day} aria-label={'星期' + day}>{day}</span>)}
    {Array.from({ length: data.first_weekday }, (_, index) => <span key={'blank' + index} aria-hidden="true"/>)}
    {data.days.map((day: any) => {
      const estimated = estimatedScoreValue(day);
      const band = estimated !== null ? scoreBand(estimated) : day.score_status === 'saved' && !day.pending_changes && !day.is_future && day.score_scope !== 'recorded_partial' && (day.score_maximum ?? 100) === 100 ? scoreBand(day.score) : 'neutral';
      const label = day.is_future ? '未到日期' : estimated !== null ? `估算${estimated}分，待正式复核` : bandLabels[band];
      return <button key={day.date} className={`history-day history-${band}${estimated !== null ? ' history-estimated' : ''}`} aria-current={day.date === data.today ? 'date' : undefined} aria-label={`${day.date}，${label}，${day.meals}餐`} disabled={day.is_future} onClick={() => navigate(`/diet/history/${day.date}`)}><time dateTime={day.date}>{Number(day.date.slice(8))}</time></button>;
    })}
  </div>;
}
function Amounts({ totals, meals }: { totals: any; meals?: number }) {
  return <dl className="history-amounts">{nutrients.map(([key, label, unit]) => <div key={key}><dt>{label}</dt><dd>{totals?.[key] ? <>{nutrientAmountLabel(totals[key])} {unit}</> : '待补营养'}</dd>{meals !== undefined && <p>{totals?.[key]?.coverage || 0}/{meals}餐有数值</p>}</div>)}</dl>;
}
export function HistoryDay({ data, navigate }: { data: any; navigate: (path: string) => void }) {
  const estimated = estimatedScoreValue(data);
  const saved = data.score_status === 'saved' && !data.pending_changes && !data.is_future && validScore(data.score);
  const band = estimated !== null ? scoreBand(estimated) : saved && data.score_scope !== 'recorded_partial' && (data.score_maximum ?? 100) === 100 ? scoreBand(data.score) : 'neutral';
  return <>
    <button className="text-button history-back" onClick={() => navigate(`/diet/history?month=${data.date.slice(0,7)}`)}><ArrowLeft size={18}/>返回日历</button>
    <section className="history-day-card" aria-label="所选日期记录">
      <div className="history-heading"><h1>{Number(data.date.slice(5,7))}月{Number(data.date.slice(8))}日的记录</h1><span className={`history-score history-${band}${estimated !== null ? ' history-estimated' : ''}`}>{estimated !== null ? `${estimated} / 100 分 · 估算` : saved ? `${data.score} / ${data.score_maximum ?? 100} 分` : '未评分'}</span></div>
      <p className="history-status">{estimated !== null ? '估算，待正式复核' : data.state} · {data.meals} 餐{data.pending_changes?' · 等待重新结算':''}</p>
      <section className="history-total" aria-label="当日实际摄入合计"><Amounts totals={data.totals}/></section>
      <details className="history-basis"><summary>评分细则</summary><ScoreBreakdown data={data}/></details>
      <section className="history-meals" aria-label="当日实际餐食"><h2>这天吃了什么</h2>{data.entries.length ? data.entries.map((meal: any) => <article key={meal.id}>
        <p>{meal.meal_type} · {fmtDate(meal.eaten_at)}</p><h3>{meal.title}</h3><Amounts totals={meal.nutrition}/>
        <details><summary>份量与营养来源</summary>{meal.eaten_fraction !== 1 && <p>按已吃份量{Math.round(meal.eaten_fraction * 100)}%计入。</p>}<p>{meal.basis || '尚无当前餐食版本的营养分析。'}</p>{meal.notes && <p>{meal.notes}</p>}{meal.limitations.map((note: string, index: number) => <p key={index}>{note}</p>)}{nutrients.map(([key, label, unit]) => nutrientRangeLabel(meal.nutrition[key]) && <p key={key}>{label}已计入估算范围：{nutrientRangeLabel(meal.nutrition[key])} {unit}</p>)}</details>
      </article>) : <p>这一天没有已保存的实际饮食记录。</p>}</section>
      <details className="history-basis"><summary>存档资料</summary><p>{data.notice}</p><p>存档规则：{data.score_version}</p>{data.score_source?.settled_at&&<p>结算时间：{fmtDate(data.score_source.settled_at)}</p>}{data.target?<dl className="history-amounts">{nutrients.map(([key,label,unit])=><div key={key}><dt>{label}目标</dt><dd>{data.target[key]??'未存档'} {unit}</dd></div>)}</dl>:<p>没有该日参考目标存档</p>}</details>
    </section>
  </>;
}

export function DietHistory({ path, today, navigate }: { path: string; today: string; navigate: (path: string) => void }) {
  const url = new URL(path, 'http://localhost');
  const selectedDay = /^\/diet\/history\/(\d{4}-\d{2}-\d{2})$/.exec(url.pathname)?.[1];
  const month = selectedDay?.slice(0, 7) || url.searchParams.get('month') || today.slice(0, 7);
  const [result, setResult] = useState<{ key: string; data?: any; error?: string } | null>(null);
  const [revision, refresh] = useState(0);
  const key = selectedDay ? `diet/history/${selectedDay}` : `diet/history?month=${encodeURIComponent(month)}`;
  useEffect(() => {
    let active = true;
    api(key).then(data => { if (active) setResult({ key, data }); }).catch(error => { if (active) setResult({ key, error: error.message }); });
    return () => { active = false; };
  }, [key, revision]);
  const data = result?.key === key ? result.data : null;
  const error = result?.key === key ? result.error : '';
  return <div className="diet-history">
    <nav className="history-top-actions"><button className="text-button history-back" onClick={() => navigate('/diet/health')}><ArrowLeft size={18}/>返回今日面板</button></nav>
    <div className={!selectedDay?'history-calendar-card':''}>
    {!selectedDay && <div className="history-month-nav"><IconButton label="上个月" onClick={() => navigate(`/diet/history?month=${shiftMonth(month, -1)}`)}><ChevronLeft size={20}/></IconButton><h2 aria-live="polite">{month.replace('-', '年')}月</h2><IconButton label="下个月" onClick={() => navigate(`/diet/history?month=${shiftMonth(month, 1)}`)}><ChevronRight size={20}/></IconButton></div>}
    {error ? <div role="alert"><p>{error}</p><button className="text-button" onClick={() => refresh(value => value + 1)}>重试</button></div> : !data ? <p role="status">正在读取历史记录…</p> : selectedDay ? <HistoryDay data={data} navigate={navigate}/> : <><CalendarGrid data={data} navigate={navigate}/><div className="history-legend" aria-label="日历颜色说明"><span><i className="history-green"/>85分及以上</span><span><i className="history-yellow"/>70–84分</span><span><i className="history-red"/>低于70分</span><span><i className="history-estimated"/>估算（待复核）</span><span><i className="history-neutral"/>未评分</span></div><p className="history-status">点日期查看记录</p></>}
    </div>
  </div>;
}
