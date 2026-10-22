import { useEffect, useRef, useState } from 'react';
import { Camera, Check, ChevronDown, LoaderCircle, RefreshCw, X, Leaf, UserRound, History, Flame, Beef, Droplet, Wheat } from 'lucide-react';
import { api, fmtDate } from './lib';
import { compareMealTimes } from './mealOrder';
import type { Row } from './lib';
import type { PageProps } from './App';
import { IconButton, Link } from './components';
import { HealthProfile } from './HealthProfile';
import { BodyTrend } from './BodyTrend';
import { BodyProgress } from './BodyProgress';
import { NutritionRing } from './NutritionRing';
import { BathroomScaleIcon, BodyFatIcon } from './BodyIcons';
import { ScoreBreakdown } from './ScoreBreakdown';
import { useJobRefresh, usePrivateAnalysis } from './PrivateAnalysis';
import { mealVisual } from './mealVisual';
import { adviceDayLabel, consumedNutrient, isConsumedMeal, nutrientAmountLabel, nutrientRangeLabel, planAmountLabel, recordedDay, remainingPlanIsCurrent, selectedPlanVariant } from './dietDisplay';

function PlanNutrition({ value }: { value: any }) {
  return <>{planAmountLabel(value?.kcal)} kcal · 蛋白质 {planAmountLabel(value?.protein_g)} g · 脂肪 {planAmountLabel(value?.fat_g)} g · 碳水 {planAmountLabel(value?.carbs_g)} g</>;
}

export function DietPage(p: PageProps) {
  const [trend,setTrend]=useState<'weight'|'body_fat'|null>(null);
  const [adviceOpen, setAdviceOpen] = useState(false), [mealsOpen, setMealsOpen] = useState(false);
  const overview = p.data['diet/overview'] || {};
  const entries: { meal: Row; analysis: any; diet_date?: string }[] = overview.entries || [];
  const nutrition = overview.today?.totals || {}, target = overview.target?.daily || {};
  const savedPlan = overview.daily_plan?.data.next_meal, scores = overview.scores?.days || [];
  const [variantChoice, setVariantChoice] = useState<{ reportId: string; id: string } | null>(null);
  const variantId = variantChoice && variantChoice.reportId === overview.daily_plan?.id ? variantChoice.id : savedPlan?.active_variant_id || '';
  const next = selectedPlanVariant(savedPlan, variantId);
  const isRemainingPlan = next?.plan_scope === 'remaining_today';
  const isTestPreview = savedPlan?.plan_mode === 'test_preview' || overview.daily_plan?.data.plan_mode === 'test_preview';
  const adviceDate = (isRemainingPlan ? next.target_date : next?.reference_date) || overview.daily_plan?.data.target_date;
  const proposedNutrition = isRemainingPlan ? next.remaining_nutrition : next?.daily_nutrition;
  const remainingCurrent = remainingPlanIsCurrent(next, overview.today);
  const hasQuantifiedPlan = savedPlan?.valid_for_use !== false && savedPlan?.quantification_status === 'verified_estimate' && next?.valid_for_use !== false && next?.quantification_status === 'verified_estimate' && (!next.plan_scope || next.plan_scope === 'full_day_reference' || isRemainingPlan) && remainingCurrent && proposedNutrition && next.recipes?.length > 0;
  const planSources = next?.sources || overview.daily_plan?.data.sources || overview.guidance || [];
  const visual = mealVisual(next);
  const today = overview.today?.date, body = overview.body_progress;
  const currentMetrics = overview.current_metrics || {};
  const todayEntries = entries.filter(({ meal, diet_date }) => isConsumedMeal(meal.data.execution) && (diet_date || meal.data.diet_date || recordedDay(meal.data.eaten_at, overview.timezone || 'Asia/Shanghai')) === today).sort((a, b) => compareMealTimes({ ...a.meal.data, created_at: a.meal.created_at }, { ...b.meal.data, created_at: b.meal.created_at }));
  const pendingNutritionCount = todayEntries.filter(({ analysis }) => !analysis?.data.nutrition?.kcal).length;
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notes, setNotes] = useState('');
  const [chosen, setChosen] = useState<File | null>(null), [preview, setPreview] = useState(''), [mealType, setMealType] = useState('午餐');
  const [selectedDay, setSelectedDay] = useState<string | null>(null), [exercise, setExercise] = useState('');
  const file = useRef<HTMLInputElement>(null), dayDialog = useRef<HTMLDialogElement>(null);
  const activeJobs = (overview.jobs || []).filter((j: any) => j.operation === 'analyze_meal' && ['queued', 'running'].includes(j.status));
  const selected = scores.find((d: any) => d.date === selectedDay);
  useJobRefresh(overview.jobs || [], p.refresh);
  useEffect(() => {
    if (!overview.update_schedule?.enabled || !overview.update_schedule?.next_at) return;
    const delay = Math.max(0, Date.parse(overview.update_schedule.next_at) - Date.now()) + 5000;
    const timer = setTimeout(p.refresh, Math.min(delay, 2147483647));
    return () => clearTimeout(timer);
  }, [overview.update_schedule?.enabled, overview.update_schedule?.next_at, p.refresh]);
  const analysis = usePrivateAnalysis(p.refresh);
  useEffect(() => { if (!chosen) { setPreview(''); return; } const url = URL.createObjectURL(chosen); setPreview(url); return () => URL.revokeObjectURL(url); }, [chosen]);
  useEffect(() => { if (selectedDay) dayDialog.current?.showModal(); }, [selectedDay]);
  async function prepare(meal: Row) {
    await analysis.prepare('diet', 'analyze_meal', { meal_id: meal.id, context_refs: [{ id: meal.id, version: meal.version }] }, '识别这一餐的食物和营养');
  }
  function choose(value?: File) {
    if (!value) return; setError('');
    if (value.size > 12 * 1024 * 1024) { setError('单张照片请小于 12 MB'); return; }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(value.type)) { setError('请选择 JPG、PNG 或 WebP 照片'); return; }
    setChosen(value); const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone: overview.timezone || 'Asia/Shanghai' }).format(new Date()));
    setMealType(hour < 10 ? '早餐' : hour < 15 ? '午餐' : hour < 21 ? '晚餐' : '加餐');
  }
  async function upload() {
    if (!chosen) return; setBusy(true); setError('');
    try {
      const form = new FormData(); form.append('file', chosen); form.append('module', 'diet');
      const asset = await api('assets', 'POST', form);
      const meal = await api('diet/meals', 'POST', { data: { title: mealType + '照片', meal_type: mealType, eaten_at: new Date().toISOString(), assets: [asset.id], notes: notes.trim() } });
      setChosen(null); setNotes(''); p.refresh(); await prepare(meal);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); if (file.current) file.current.value = ''; }
  }
  async function finishDay() {
    setBusy(true); setError('');
    try {
      const row = selected?.log;
      await api('diet/days' + (row ? '/' + row.id : ''), row ? 'PATCH' : 'POST', { version: row?.version, data: { date: selectedDay, exercise, finished: true } });
      p.refresh(); p.notify('已保存。结算需手动运行命令，本程序无内置调度。'); setSelectedDay(null);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="diet-simple">
    <header className="dashboard-header">
      <div className="header-meta"><time dateTime={today}>{today ? `${Number(today.slice(5,7))}月${Number(today.slice(8))}日 · ${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'long'}).format(new Date(`${today}T12:00:00+08:00`))}` : '日期待载入'}</time><span className="mode-status"><Leaf aria-hidden="true"/>{overview.target?.goal?.direction || currentMetrics['目标'] || '目标待设置'}</span></div>
      <div className="dashboard-heading"><h1 className="today-title"><span>今日饮食</span></h1>
        <dl className="body-summary" aria-label="当前身体资料">{([['身高','cm',UserRound],['体重','kg',BathroomScaleIcon],['体脂率','%',BodyFatIcon]] as const).map(([key,unit,Icon])=><div key={key}><Icon aria-hidden="true"/><div><dt>{key==='体脂率'?'体脂':key}</dt><dd>{currentMetrics[key]!=null&&String(currentMetrics[key]).trim()!==''?`${currentMetrics[key]}${unit}`:'待完善'}</dd></div>{key!=='身高'&&<button className="body-metric-trigger" aria-label={`查看${key}趋势`} onClick={()=>setTrend(key==='体重'?'weight':'body_fat')}/>}</div>)}</dl>
        <button className={`refresh-button ${p.refreshing?'is-refreshing':''}`} disabled={p.refreshing} aria-label="刷新今日摄入" onClick={p.refresh}><RefreshCw aria-hidden="true"/></button>
      </div>
    </header>
    {trend&&<BodyTrend kind={trend} points={overview.body_measurements?.[trend]||[]} onClose={()=>setTrend(null)}/>}
    <section className="nutrition-rings" aria-label="今日营养概览">
      {[['kcal', '热量', 'kcal', '#F9B086'], ['protein_g', '蛋白质', 'g', '#8DB5F0'], ['fat_g', '脂肪', 'g', '#D1B48A'], ['carbs_g', '碳水', 'g', '#8ABEA8']].map(([key, name, unit, color]) => <NutritionRing key={key} name={name} unit={unit} color={color} value={nutrition[key]} target={target[key]} coverage={nutrition[key]?.coverage} labels={overview.today?.label_counts?.[key]} meals={overview.today?.meals_count || 0} finished={overview.today?.finished || false}/>)}
    </section>
    {!overview.target?.daily && <p className="target-pending" role="status">{overview.target?.note}</p>}
      <section className="next-meal-card daily-advice" aria-label="饮食建议"><div className="advice-heading"><h2><button className="section-toggle" aria-expanded={adviceOpen} aria-controls="diet-advice-content" onClick={() => setAdviceOpen(value => !value)}>{adviceDayLabel(adviceDate, today)}{isRemainingPlan ? '剩余饮食建议' : '饮食建议'}{isTestPreview ? ' · 测试预览' : ''}<ChevronDown aria-hidden="true"/></button></h2>{!isRemainingPlan && <small>（07:00 饮食日分界）</small>}</div>
        <div id="diet-advice-content" hidden={!adviceOpen}>{isTestPreview && <p className="plan-preview-notice">提前测试预览。正式菜单需在目标日北京时间07:00后由操作者根据最新记录生成，当前预览不算已吃或正式发布。</p>}
        {!hasQuantifiedPlan && adviceDate && adviceDate !== today && <p>方案参考日期：{adviceDate}</p>}
        {hasQuantifiedPlan ? <>
          <p className="plan-scope sr-only">{isRemainingPlan ? `今日剩余方案 · ${adviceDate}。仅根据已记录摄入核算；漏记不算零，不代表当天已经记全。` : `全天参考方案 · ${adviceDate}。这是整天的参考份量，不是今天剩余要吃的量。`}</p>
          {isRemainingPlan && next.intake_basis?.as_of && <p>摄入快照：{next.intake_basis.as_of}</p>}
          {!isRemainingPlan && savedPlan.variants?.length > 0 && <label className="field plan-scenario"><span>参考情境（仅切换建议）</span><select value={variantId || ''} onChange={e => setVariantChoice({ reportId: overview.daily_plan.id, id: e.target.value })}><option value="">选择参考情境</option>{savedPlan.variants.map((variant: any) => <option key={variant.id} value={variant.id}>{variant.label}</option>)}</select></label>}
          {next.condition_label && <p className="plan-condition">{next.condition_label}</p>}

          {next.recipes?.length > 0 ? <ul className="advice-glance">{next.recipes.map((recipe: any) => <li key={recipe.meal_type} className="plan-meal-card"><h3>{recipe.meal_type}{recipe.display_condition ? `（${recipe.display_condition}）` : recipe.optional || recipe.meal_type === '加餐 / 练前餐' ? '（按需）' : ''}</h3><p className="plan-dish">{recipe.dish_title || (recipe.foods || []).join(' · ')}</p>{recipe.nutrition && <dl className="plan-macro-row">{[['kcal','热量','kcal'],['protein_g','蛋白质','g'],['fat_g','脂肪','g'],['carbs_g','碳水','g']].map(([key,label,unit])=><div key={key}><dt>{label}</dt><dd>{planAmountLabel(recipe.nutrition[key])} <span>{unit}</span></dd></div>)}</dl>}<details><summary>完整食材与做法</summary><p>{recipe.portion_summary || (recipe.foods || []).join(' · ')}</p><p>{recipe.preparation}</p>{recipe.items?.map((item:any,index:number)=><p key={index}>{item.name} {item.quantity}{item.unit} · {item.weight_basis}</p>)}</details>{recipe.redistribution_from && <p className="plan-redistribution">{recipe.redistribution_from}</p>}</li>)}</ul> : <p className="advice-glance">{next.title}</p>}
          {(next.reason_summary || next.reason) && <section className="plan-reason" aria-label="为什么这样吃"><h3>为什么这样吃</h3><p>{next.reason_summary || next.reason}</p><details><summary>指南与依据</summary>{next.reason_summary && next.reason && <p>{next.reason}</p>}{planSources.map((source: any, index: number) => <p key={source.url || index}>{source.url ? <Link href={source.url}>{source.title}</Link> : source.title}{source.summary && `：${source.summary}`}</p>)}</details></section>}
          {proposedNutrition && <div className="plan-total" aria-label={isRemainingPlan ? '今日剩余建议合计' : '菜单参考合计'}><p><strong>{isRemainingPlan ? '今日剩余建议合计' : '菜单参考合计'}</strong></p><p><PlanNutrition value={proposedNutrition}/></p>{next.total_note && <p>{next.total_note}</p>}{next.caveat && <p className="menu-note">{next.caveat}</p>}</div>}
          <details className="advice-full"><summary>查看完整建议</summary><p>方案参考日期：{adviceDate}</p>
          {next.scope_notice && <p>{next.scope_notice}</p>}{next.quantification_note && <p>{next.quantification_note}</p>}
          {proposedNutrition && <p>上述为推荐份量的营养估算，不是今日实际摄入；不计入顶部已记录摄入圆环。条件餐次与份量调整按方案注明的情境使用。</p>}
          {isRemainingPlan && <><p>{next.intake_basis?.notice}</p><p>记录快照：{next.intake_basis?.meals_count ?? next.original_intake_snapshot?.meals_count} 餐；热量/蛋白质/脂肪/碳水覆盖 {['kcal', 'protein_g', 'fat_g', 'carbs_g'].map(key => next.intake_basis?.nutrient_coverage?.[key] ?? '未知').join(' / ')}。</p>{next.limitations?.map((text: string, index: number) => <p key={index}>{text}</p>)}</>}
          {!next.daily_nutrition && next.recipes?.some((recipe: any) => recipe.meal_type === '加餐 / 练前餐') && <p>若今天训练，可结合训练安排；不训练无需额外加餐。</p>}
          {visual && <figure className="meal-inspiration"><img src={visual.src} alt={visual.alt}/><figcaption>{visual.caption}</figcaption></figure>}
          {next.today_summary && <p className="today-food-summary">{next.today_summary}</p>}<h4>{next.title}</h4><div className="food-tags">{(next.foods || []).map((food: string) => <span key={food}>{food}</span>)}</div><p>{next.reason}</p>
          {!next.daily_nutrition && next.recipes?.length > 0 && <p className="note">以下是示例搭配，不是已吃记录；所列数值为每餐预算，不是菜品核算营养。</p>}{next.recipes?.length > 0 && <div className="daily-recipes">{next.recipes.map((recipe: any) => <article key={recipe.meal_type}><h4>{recipe.meal_type}</h4><p>{(recipe.foods || []).join(' · ')}</p>{recipe.nutrition ? <p>份量估算：<PlanNutrition value={recipe.nutrition}/></p> : recipe.budget?.kcal != null && <p>预算 {recipe.budget.kcal} 大卡 · 蛋白质 {recipe.budget.protein_g} g · 脂肪 {recipe.budget.fat_g} g · 碳水 {recipe.budget.carbs_g} g</p>}{recipe.redistribution_from && <p>{recipe.redistribution_from}</p>}<p>{recipe.preparation}</p>{recipe.items?.length > 0 && <details className="recipe-calculation"><summary>食物份量与来源</summary>{recipe.items.map((item: any, index: number) => <section key={index}><h4>{item.name} {item.quantity}{item.unit} · {item.weight_basis}</h4><p><PlanNutrition value={item.nutrition}/></p>{item.source?.title && <p>{item.source.url ? <Link href={item.source.url}>{item.source.title}</Link> : item.source.title}{item.source.product_version != null && ` · 标签版本 ${item.source.product_version}`}</p>}{item.assumptions?.map((text: string, i: number) => <p key={i}>{text}</p>)}</section>)}</details>}</article>)}</div>}
          {next.target_comparison && <details className="plan-target-comparison"><summary>方案与参考目标</summary>{[['kcal', '热量', 'kcal'], ['protein_g', '蛋白质', 'g'], ['fat_g', '脂肪', 'g'], ['carbs_g', '碳水', 'g']].map(([key, name, unit]) => <p key={key}>{name}：{isRemainingPlan ? '已记录＋剩余方案预计' : '方案'} {planAmountLabel((isRemainingPlan ? next.target_comparison.projected_daily_midpoints : next.target_comparison.actual)?.[key])} / 参考 {planAmountLabel(next.target_comparison.targets?.[key])} {unit}</p>)}</details>}
          {next.additions?.length > 0 && <ul className="nutrition-additions">{next.additions.map((item: string) => <li key={item}>{item}</li>)}</ul>}
          <details><summary>建议依据</summary>{overview.guidance?.map((source: any) => <p key={source.url}><Link href={source.url}>{source.title}</Link>：{source.summary}</p>)}</details>
        </details></> : next ? <div className="plan-pending" role="status"><p><strong>{!remainingCurrent ? '剩余方案需重新核算' : '方案核算中'}</strong></p><p>{!remainingCurrent ? '饮食日或已记录摄入已有变化，旧份量暂不作为进食依据。' : next.reason || '原方案缺少可核对的份量，暂不作为进食依据。已记录摄入保持不变。'}</p></div> : <div className="gentle-empty"><p>尚无已保存建议。饮食日以07:00分界；结算、建议和目标复核需由操作者运行相应命令，本程序不会自动执行。</p></div>}
        </div>
      </section>
    {overview.target_review?.enabled && <details className="target-review"><summary>每日目标 · 每15天复核</summary><p>下次复核：{overview.target_review.next_review_at?.slice(0, 10)} 北京时间07:00{overview.target_review.due ? '（待复核）' : ''}</p><p>根据两周实际摄入、体重均值趋势和近期体脂资料判断；资料不足保持原目标，不随单日体重变化调量。</p>{overview.target_review.last_review && <p>上次：{overview.target_review.last_review.review_date} · {overview.target_review.last_review.decision === 'hold' ? '保留目标' : '调整目标'}。{overview.target_review.last_review.reason}（置信度：{overview.target_review.last_review.confidence === 'high' ? '高' : overview.target_review.last_review.confidence === 'moderate' ? '中' : '低'}）</p>}</details>}
    <section className="today-meals" aria-label="今天吃了什么"><div className="section-head"><h2><button className="section-toggle" aria-expanded={mealsOpen} aria-controls="today-meals-content" onClick={() => setMealsOpen(value => !value)}>今天吃了什么<ChevronDown aria-hidden="true"/></button></h2><button className="text-button history-entry" onClick={() => p.navigate('/diet/history')}><History aria-hidden="true"/>历史记录</button></div><div id="today-meals-content" hidden={!mealsOpen}>
      {todayEntries.length ? <div className="today-meal-list">{todayEntries.map(({ meal, analysis }) => <article className="today-meal" key={meal.id}>
        {meal.data.assets?.[0] && <img src={'/api/v1/assets/' + meal.data.assets[0]} alt={analysis?.data.meal_title || meal.data.title}/>}
        <div><small>{meal.data.meal_type} · {new Intl.DateTimeFormat('zh-CN', { timeZone: overview.timezone || 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(meal.data.eaten_at))}</small><h3>{analysis?.data.meal_title || meal.data.title}</h3>
          <dl className="plan-macro-row meal-macro-row">{([['kcal','热量','kcal',Flame],['protein_g','蛋白质','g',Beef],['fat_g','脂肪','g',Droplet],['carbs_g','碳水','g',Wheat]] as const).map(([key,label,unit,Icon])=><div key={key}><dt><Icon aria-hidden="true"/><span className="sr-only">{label}</span></dt><dd>{analysis?.data.nutrition?.[key]?nutrientAmountLabel(consumedNutrient(analysis.data.nutrition[key],meal.data.eaten_fraction)):'待补营养'} <span>{unit}</span></dd></div>)}</dl>

        </div></article>)}</div> : <p className="gentle-empty">今天还没有餐食记录。</p>}
    <details className="diet-data-note"><summary>数据说明</summary>
      <p>{today} · 北京时间</p><p className="diet-coverage">已记录 {overview.today?.meals_count || 0} 餐 · {overview.today?.finished ? '已确认当天记完' : '尚未确认全天记完'}<span>营养数值与目标均为参考；未记录的不计作零。</span></p>
      {pendingNutritionCount > 0 && <p>{pendingNutritionCount} 餐待补营养，圆环暂未计入这些餐次，不代表完整摄入。</p>}
      <h3>已记录摄入的估算详情</h3><p>主面板显示已记录摄入的估算中点并统一四舍五入为整数；底层原始范围不变。目标采用用户设定值或当前资料计算的参考值，不是医生核定的摄入量。</p>
      <dl className="nutrition-range-details">{[['kcal', '热量', '大卡'], ['protein_g', '蛋白质', 'g'], ['fat_g', '脂肪', 'g'], ['carbs_g', '碳水', 'g']].map(([key, name, unit]) => <div key={key}><dt>{name}</dt><dd>{nutrientRangeLabel(nutrition[key]) || nutrientAmountLabel(nutrition[key])}{nutrition[key] && ` ${unit}`}</dd></div>)}</dl>
      {todayEntries.some(({ analysis }) => analysis?.data.nutrition?.basis || analysis?.data.limitations?.length) && <div className="meal-estimate-details"><h3>各餐估算依据</h3>{todayEntries.map(({ meal, analysis }) => analysis && (analysis.data.nutrition?.basis || analysis.data.limitations?.length) ? <section key={meal.id}><h4>{analysis.data.meal_title || meal.data.title}</h4>{analysis.data.nutrition?.basis && <p>{analysis.data.nutrition.basis}</p>}{analysis.data.limitations?.length > 0 && <ul>{analysis.data.limitations.map((limitation: string, index: number) => <li key={index}>{limitation}</li>)}</ul>}</section> : null)}</div>}
      <p>{overview.target?.note}</p>
      {overview.target?.goal?.direction && <p>目标：{overview.target.goal.direction} · {overview.target.goal.description}</p>}
      {overview.target?.activity?.description && <p>活动安排：{overview.target.activity.description}</p>}
      {overview.target?.steps?.length > 0 && <div className="target-calculation"><table><thead><tr><th>项目</th><th>计算</th><th>结果</th></tr></thead><tbody>{overview.target.steps.map((step: any) => <tr key={step.label}><th scope="row">{step.label}</th><td>{step.formula}</td><td>{step.value} {step.unit}</td></tr>)}</tbody></table></div>}
      {overview.target?.activity?.assumptions?.map((text: string) => <p key={text}>{text}</p>)}
      {overview.target?.activity?.items?.map((item: any) => <p key={item.description}>{item.name}：{item.assumption}{item.compendium_code && `（活动代码 ${item.compendium_code}）`}</p>)}
      <p>{overview.target?.activity_basis}</p><p>{overview.target?.method}</p>
      <p>标签数值优先；无标签时显示估算值。仅统计已记录、已分析餐次，漏记不计作零。旧区间记录取中间值显示。</p>
      {overview.target?.source_details?.map((source: any) => <Link key={source.url} href={source.url}>{source.title}</Link>)}
    </details></div></section>
    <details className="diet-secondary"><summary>记录、建议与历史</summary>
      <div className="diet-profile-actions"><BodyProgress {...p}/><HealthProfile {...p}/></div>
      <details className="calculation-rules"><summary>计算与建议规则</summary>{overview.policy ? <><p>版本：{overview.policy.policy_version}</p>{overview.policy.rules?.map((rule: any) => <article key={rule.id}><h3>{rule.title} · {rule.status === 'active' ? '已生效' : rule.status === 'insufficient_data' ? '资料不足' : rule.status === 'proposal' ? '待实现' : '待核实'}</h3><p>{rule.description}</p>{rule.implementation === 'software_and_manual_agent' && <p>执行方式：本地软件校验与操作者提交。</p>}</article>)}<details><summary>版本校验信息</summary><p>策略 SHA-256：{overview.policy.policy_hash}</p><p>工作流程 SHA-256：{overview.policy.skill_hash}</p></details></> : <p>当前服务尚未返回规则状态。</p>}</details>
    <div className="diet-focus-grid">
      <section className="photo-composer"><h3>记录这一餐</h3>
        <button className={`meal-dropzone ${chosen ? 'has-photo' : ''}`} onClick={() => file.current?.click()} disabled={busy} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) choose(e.dataTransfer.files[0]); }}>
          {preview ? <><img src={preview} alt="待保存的餐食照片"/><span>更换照片</span></> : <><Camera size={32} strokeWidth={1.3}/><strong>上传餐食照片</strong></>}
        </button><input className="sr-only" ref={file} type="file" accept="image/jpeg,image/png,image/webp" aria-label="餐食照片" onChange={e => choose(e.target.files?.[0])}/>
        <label className="field meal-notes"><span>补充说明（可选）</span><textarea rows={2} maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)} placeholder="例如：另外还吃了250克熟米饭，照片里没拍到"/></label>
        {chosen && <div className="meal-submit-row"><select aria-label="餐次" value={mealType} onChange={e => setMealType(e.target.value)}>{['早餐', '午餐', '晚餐', '练前餐', '练后餐', '加餐'].map(t => <option key={t}>{t}</option>)}</select><button className="button" disabled={busy} onClick={upload}>{busy ? <LoaderCircle className="spin" size={16}/> : <Check size={16}/>}保存并分析</button><IconButton label="取消选择照片" onClick={() => { if (!busy) setChosen(null); }}><X size={18}/></IconButton></div>}
        {activeJobs.length > 0 && <p role="status"><LoaderCircle className="spin" size={16}/>正在识别餐食…</p>}
      </section>

    </div>
    {error && !selectedDay && <p className="error" role="alert">{error}</p>}
    <section className="weekly-simple"><div className="row between"><h3>这一周，吃得怎么样</h3><button className="text-button" onClick={() => { setSelectedDay(today); setExercise(overview.today?.log?.data.exercise || ''); setError(''); }}>今天记完了</button></div>
      <div className="week-score-strip">{scores.map((day: any, index: number) => <button key={day.date} disabled={day.date > today} className={day.score !== null ? 'scored' : ''} aria-label={`周${['一', '二', '三', '四', '五', '六', '日'][index]} ${day.score === null ? day.state : day.score + '/' + (day.score_maximum ?? 100) + '分 ' + day.state}`} onClick={() => { setSelectedDay(day.date); setExercise(day.exercise); setError(''); }}><span>周{['一', '二', '三', '四', '五', '六', '日'][index]}</span><strong>{day.score ?? '—'}</strong><span>{day.date > today ? '未到' : day.state}</span></button>)}</div>
      <details className="score-explanation"><summary>评分依据与本周记录</summary><p>{overview.scores?.method}</p><p>评分规则版本：{overview.scores?.version}。以07:00为饮食日分界，手动运行结算命令时按已记录证据结算，不要求手动确认全天；完整历史存档按当时规则保留，失效记录不冒充有效评分。</p><p>参考量结合个人资料与每周运动安排；缺少基础营养、体重依据或核心食物结构证据时不出总分，保留已知分项与缺项说明。结算需由操作者触发；白天记录不会立即改分。</p>{overview.scores?.activity && <p>每周安排：{overview.scores.activity}</p>}<div className="week-meals">{overview.week?.meals?.map((m: any) => <div key={m.meal_id}><span>{m.day.slice(5)} · {m.meal_type}</span><strong>{m.title}</strong><small>{m.foods?.length ? m.foods.map((f: any) => f.name).join('、') : '待分析'}</small></div>)}</div></details>
    </section>
    {body?.review && <section className="body-progress-summary"><h3>身体变化</h3><p>{body.review.summary}</p><details><summary>这次调整与测量记录</summary>{body.review.suggestions.map((s: string) => <p key={s}>{s}</p>)}<div className="body-history">{body.checkins.map((r: Row) => <div key={r.id}><span>{r.data.measured_on}</span><strong>{r.data.weight_kg} kg{r.data.body_fat_pct != null ? ` · ${r.data.body_fat_pct}%` : ''}</strong><button className="text-button danger-text" onClick={() => p.remove('diet/checkins', r)}>删除</button></div>)}</div></details></section>}
    {entries.length > 0 && <details className="meal-history"><summary>餐食记录 · {entries.length}</summary><div className="meal-photo-grid">{entries.map(({ meal, analysis }) => { const job = (overview.jobs || []).find((j: any) => j.input?.meal_id === meal.id); return <article key={meal.id} className="meal-record">{meal.data.assets[0] && <img src={'/api/v1/assets/' + meal.data.assets[0]} alt={analysis?.data.meal_title || meal.data.title}/>}<div><small>{fmtDate(meal.data.eaten_at)}</small><h3>{analysis?.data.meal_title || meal.data.title}</h3>{meal.data.notes && <p>{meal.data.notes}</p>}{analysis ? <details><summary>识别详情</summary><p>{analysis.data.summary}</p><p>{analysis.data.nutrition?.basis}</p>{analysis.data.nutrition?.label_values?.map((label: any) => <p key={label.nutrient}>{label.evidence}{label.quantity_evidence && `；${label.quantity_evidence}`}</p>)}</details> : <p>{job?.status === 'failed' ? '分析未完成，可重试。' : '照片已保存，尚未分析。'}</p>}<div className="row"><button className="text-button" disabled={busy || ['queued', 'running'].includes(job?.status)} onClick={async () => { setBusy(true); try { await prepare(meal); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>{analysis ? '重新分析' : '分析'}</button><button className="text-button" onClick={() => p.edit({ title: '补充这餐', path: 'diet/meals', row: meal, initial: meal.data, fields: [{ key: 'title', label: '这餐吃了什么' }, { key: 'notes', label: '补充或修正', type: 'textarea' }, { key: 'eaten_at', label: '吃饭时间', type: 'datetime-local' }] })}>修改</button><button className="text-button danger-text" onClick={() => p.remove('diet/meals', meal)}>删除</button></div></div></article>; })}</div></details>}
    </details>
    {selectedDay && <dialog className="dialog" ref={dayDialog} aria-label="每日饮食评分" onCancel={() => setSelectedDay(null)}><div className="dialog-head"><h2>{selectedDay} · {selected?.score == null ? selected?.state || '待结算' : `${selected.score} / ${selected.score_maximum ?? 100}`}</h2><IconButton label="关闭每日评分" onClick={() => setSelectedDay(null)}><X size={20}/></IconButton></div><div className="form-body"><p>已记录 {selected?.meals || 0} 餐，已分析 {selected?.analyzed || 0} 餐。</p><ScoreBreakdown data={selected}/><label className="field"><span>当天的运动（可选）</span><textarea rows={2} value={exercise} onChange={e => setExercise(e.target.value)} maxLength={2000} placeholder="例如：力量训练60分钟，其他时间以坐着为主"/></label><details><summary>评分说明</summary><p>{selected?.score_method ? '存档评分规则' : '当前规则（不回填历史）'}：{selected?.score_method || overview.scores?.method}</p><p>运动补充保存在本机，运行结算时留作回顾；每日参考按个人资料中的每周训练安排计算，不凭一句描述直接增加热量。</p></details>{error && <p className="error" role="alert">{error}</p>}</div><div className="dialog-foot"><button className="button" disabled={busy || !selected?.meals} onClick={finishDay}>{busy && <LoaderCircle className="spin" size={16}/>}确认当天已记完</button></div></dialog>}
    {analysis.consent}
  </div>;
}
