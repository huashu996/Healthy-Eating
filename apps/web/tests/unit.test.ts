// All measurements, meals, dates and nutrition values below are synthetic test fixtures.
import { mealVisual } from '../src/mealVisual';
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { adviceDayLabel, consumedNutrient, isConsumedMeal, nutrientAmountLabel, nutrientPoint, nutrientProgress, nutrientRangeLabel, planAmountLabel, recordedDay, remainingPlanIsCurrent, selectedPlanVariant } from '../src/dietDisplay';
import { NutritionRing } from '../src/NutritionRing';
import { DietPage } from '../src/DietPage';

describe('nutrition display keeps the stored estimate intact', () => {
  it('shows the range without changing its midpoint or source', () => {
    const range = Object.freeze({ low: 827, high: 1067 });
    expect(nutrientRangeLabel(range)).toBe('827–1,067');
    expect(nutrientPoint(range)).toBe(947);
    expect(nutrientProgress(nutrientPoint(range), 2400)).toBe(39);
  });
  it('keeps exact values, zero, and missing values distinct', () => {
    expect(nutrientRangeLabel({ low: 20, high: 20 })).toBeNull();
    expect(nutrientPoint({ low: 0, high: 0 })).toBe(0);
    expect(nutrientRangeLabel(null)).toBeNull();
    expect(nutrientPoint(undefined)).toBeNull();
    expect(nutrientProgress(null, 2400)).toBeNull();
  });
  it('rejects invalid ranges and does not invent a reference', () => {
    for (const range of [{ low: -1, high: 2 }, { low: 4, high: 2 }, { low: NaN, high: 2 }]) {
      expect(nutrientRangeLabel(range)).toBeNull();
    }
    expect(nutrientProgress(200, undefined)).toBeNull();
    expect(nutrientRangeLabel({ low: 11.2, high: 16.8 })).toBe('11.2–16.8');
  });
});

describe('single-value daily dashboard', () => {
  it('matches consumed-portion totals and excludes uneaten plans', () => {
    for (const execution of ['planned', 'skipped', 'replaced']) expect(isConsumedMeal(execution)).toBe(false);
    for (const execution of ['done', 'partial', undefined]) expect(isConsumedMeal(execution)).toBe(true);
    const value = Object.freeze({ low: 300, high: 500 });
    expect(nutrientAmountLabel(consumedNutrient(value, 0.5))).toBe('200');
    expect(nutrientAmountLabel(consumedNutrient(value, 0))).toBe('0');
    expect(nutrientAmountLabel(consumedNutrient(value))).toBe('400');
    expect(consumedNutrient(null, 0.5)).toBeNull();
    expect(consumedNutrient(value, NaN)).toBeNull();
    expect(value).toEqual({ low: 300, high: 500 });
  });
  it('rounds only the displayed midpoint and retains the source range', () => {
    const value = Object.freeze({ low: 34.5, high: 51 });
    expect(nutrientAmountLabel(value)).toBe('43');
    expect(nutrientRangeLabel(value)).toBe('34.5–51');
    expect(nutrientAmountLabel({ low: 947.5, high: 1227.5 })).toBe('1088');
    expect(nutrientAmountLabel({ low: 0.4, high: 0.5 })).toBe('0');
    expect(nutrientAmountLabel(null)).toBe('待分析');
  });
  it('keeps percentages over 100 visible while capping the arc only', () => {
    const html = renderToStaticMarkup(createElement(NutritionRing, { name: '热量', unit: '大卡', value: { low: 110, high: 130 }, target: 100, color: '#ff375f', meals: 1, coverage: 1, finished: false }));
    expect(html).toContain('120%');
    expect(html).toContain('stroke-dasharray="100 100"');
    expect(html).toContain('超过参考目标');
    expect(html).not.toContain('110–130');
    expect(html).not.toContain('估算区间');
  });
  it('does not invent zero intake or divide by a missing target', () => {
    for (const target of [undefined, 0, NaN]) {
      const html = renderToStaticMarkup(createElement(NutritionRing, { name: '热量', unit: '大卡', value: null, target, color: '#ff375f', meals: 0, finished: false }));
      expect(html).not.toContain('NaN');
      expect(html).not.toContain('Infinity');
      expect(html).not.toContain('0%');
      expect(html).toContain('待记录');
      expect(html).toContain('参考目标待完善');
    }
  });
  it('selects meals by the configured local day, not UTC', () => {
    expect(recordedDay('2025-10-11T16:01:00Z')).toBe('2025-10-12');
    expect(recordedDay('2025-10-11T15:59:00Z')).toBe('2025-10-11');
    expect(recordedDay('invalid')).toBeNull();
    expect(recordedDay(undefined)).toBeNull();
  });
  it('renders current profile values and keeps primary sections in order', () => {
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { current_metrics: { 身高: '171', 体重: '68.2', 体脂率: '19.1' }, today: { date: '2025-10-12', totals: {} }, target: { daily: {} }, scores: { days: [] } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    expect(html).toContain('171');
    expect(html).toContain('68.2');
    expect(html).toContain('19.1');
    const order = ['今日饮食</span></h1>', '当前身体资料', '今日营养概览', '今日饮食建议', '今天吃了什么'];
    const positions = order.map(text => html.indexOf(text));
    expect(positions.every(position => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(html).toContain('<details class="diet-data-note">');
    expect(html).toContain('<details class="diet-secondary">');
    expect(html).not.toContain('open=""');
  });
  it('uses the server-assigned diet day without moving legacy or explicitly dated meals', () => {
    const meals = [
      { id: 'new-overnight', diet_date: '2025-10-12', data: { title: '归前饮食日夜宵', eaten_at: '2025-10-13T01:00:00+08:00' } },
      { id: 'explicit-override', diet_date: '2025-10-13', data: { title: '明确归次日餐', diet_date: '2025-10-12', eaten_at: '2025-10-12T20:00:00+08:00' } },
      { id: 'legacy', data: { title: '旧自然日记录', eaten_at: '2025-10-13T01:00:00+08:00' } },
      { id: 'stored-fallback', data: { title: '已存归属日期', diet_date: '2025-10-12', eaten_at: '2025-10-13T02:00:00+08:00' } },
    ];
    const entries = meals.map(({ id, diet_date, data }) => ({ diet_date, meal: { id, data: { ...data, assets: [], execution: 'done', meal_type: '加餐' } }, analysis: null }));
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', totals: {} }, target: { daily: {} }, scores: { days: [] }, entries } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    const todayMeals = html.match(/<section class="today-meals"[\s\S]*?<\/section>/)?.[0] || '';
    expect(todayMeals).toContain('归前饮食日夜宵');
    expect(todayMeals).toContain('已存归属日期');
    expect(todayMeals).not.toContain('明确归次日餐');
    expect(todayMeals).not.toContain('旧自然日记录');
    expect(html).toContain('<time dateTime="2025-10-12">10月12日 · 星期日</time>');
  });
  it('keeps dinner and the optional pre-training meal in the main advice summary', () => {
    const recipes = ['早餐', '午餐', '晚餐', '加餐 / 练前餐'].map(meal_type => ({ meal_type, foods: ['食物示例'] }));
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', totals: {} }, target: { daily: {} }, scores: { days: [] }, daily_plan: { data: { target_date: '2025-10-12', next_meal: { title: '已保存方案', foods: [], recipes, quantification_status: 'verified_estimate', daily_nutrition: { kcal: 2400, protein_g: 165, fat_g: 67, carbs_g: 284 } } } } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    const summary = html.match(/<ul class="advice-glance">([\s\S]*?)<\/ul>/)?.[1] || '';
    expect((summary.match(/<li/g) || []).length).toBe(4);
    expect(summary).toContain('晚餐');
    expect(summary).toContain('加餐 / 练前餐（按需）');
    expect(html).toContain('菜单参考合计');
  });
  it('marks a recorded meal with unknown nutrition visibly instead of rendering zero', () => {
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', meals_count: 1, totals: {} }, target: { daily: {} }, scores: { days: [] }, entries: [{ meal: { id: 'pending-test', data: { title: '测试餐A', eaten_at: '2025-10-12T20:00:00+08:00', execution: 'done', assets: [], meal_type: '加餐' } }, analysis: null }] } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    expect(html).toContain('<dd>待补营养 <span>kcal</span></dd>');
    expect(html).toContain('餐待补营养，圆环暂未计入这些餐次，不代表完整摄入。');
    expect(html).not.toContain('>0<');
  });
  it('retains saved component limitations in the collapsed data explanation', () => {
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', meals_count: 1, totals: {} }, target: { daily: {} }, scores: { days: [] }, entries: [{ meal: { id: 'basis-test', data: { title: '测试食品B', eaten_at: '2025-10-12T20:00:00+08:00', execution: 'done', assets: [], meal_type: '加餐' } }, analysis: { data: { nutrition: { kcal: { low: 180, high: 180 }, basis: '按已确认标签换算。' }, limitations: ['仅粉本身，冲泡液未计入'] } } }] } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    const explanation = html.match(/<details class="diet-data-note">([\s\S]*?)<\/details>/)?.[1] || '';
    expect(explanation).toContain('按已确认标签换算。');
    expect(explanation).toContain('仅粉本身，冲泡液未计入');
    expect(html).toContain('<dd>180 <span>kcal</span></dd>');
  });
  it('formats calculated plan values without inventing missing nutrition', () => {
    expect(planAmountLabel(165.3)).toBe('165');
    expect(planAmountLabel(0)).toBe('0');
    for (const value of [null, undefined, NaN, -1, '165']) expect(planAmountLabel(value)).toBe('待核算');
  });
  it('names the recommendation day relative to the server diet day, including year boundaries', () => {
    expect(adviceDayLabel('2025-10-12', '2025-10-12')).toBe('今日');
    expect(adviceDayLabel('2025-10-13', '2025-10-12')).toBe('明日');
    expect(adviceDayLabel('2026-01-01', '2025-12-31')).toBe('明日');
    expect(adviceDayLabel('2025-10-15', '2025-10-12')).toBe('10月15日');
  });
  it('invalidates remaining advice when its recorded-intake snapshot changes', () => {
    const snapshot = { date: '2025-10-12', meals_count: 1, finished: false, totals: { kcal: { low: 100, high: 200, coverage: 1 } } };
    const plan = { plan_scope: 'remaining_today', target_date: '2025-10-12', original_intake_snapshot: snapshot };
    expect(remainingPlanIsCurrent(plan, snapshot)).toBe(true);
    expect(remainingPlanIsCurrent(plan, { ...snapshot, meals_count: 2 })).toBe(false);
    expect(remainingPlanIsCurrent(plan, { ...snapshot, date: '2025-10-13' })).toBe(false);
    expect(remainingPlanIsCurrent(plan, { ...snapshot, totals: { kcal: { low: 100, high: 200, coverage: 0 } } })).toBe(false);
    expect(remainingPlanIsCurrent(plan, { ...snapshot, totals: { kcal: { low: 150, high: 250, coverage: 1 } } })).toBe(false);
    expect(remainingPlanIsCurrent({ plan_scope: 'remaining_today' }, snapshot)).toBe(false);
  });
  it('labels a valid remaining plan separately and never adds it to actual intake', () => {
    const snapshot = { date: '2025-10-12', meals_count: 1, finished: false, totals: { kcal: { low: 180, high: 180, coverage: 1 } } };
    const plan = { plan_scope: 'remaining_today', target_date: snapshot.date, original_intake_snapshot: snapshot, intake_basis: { date: snapshot.date, as_of: '2025-10-12T20:00:00+08:00', meals_count: 1, nutrient_coverage: { kcal: 1 } }, quantification_status: 'verified_estimate', valid_for_use: true, remaining_nutrition: { kcal: 500, protein_g: 30, fat_g: 15, carbs_g: 61 }, foods: [], recipes: [{ meal_type: '晚餐', foods: ['鱼肉150g（生重）'], nutrition: { kcal: 500, protein_g: 30, fat_g: 15, carbs_g: 61 } }], target_comparison: { targets: { kcal: 2400 }, projected_daily_midpoints: { kcal: 695 } } };
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: snapshot, target: { daily: { kcal: 2400 } }, scores: { days: [] }, daily_plan: { id: 'remaining-test', data: { target_date: snapshot.date, next_meal: plan } } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    expect(html).toContain('今日剩余饮食建议');
    expect(html).toContain('今日剩余建议合计');
    expect(html).not.toContain('菜单参考合计');
    expect(html).toContain('已摄入 180 / 推荐 2400');
    expect(html).not.toContain('已摄入 695 / 推荐 2400');
    expect(html).toContain('已记录＋剩余方案预计 695 / 参考 2400');
    expect(html).toContain('漏记不算零');
  });
  it('switches reference scenarios without changing the saved plan or assuming training', () => {
    const plan = Object.freeze({ active_variant_id: null, training_status: 'unknown', condition_label: '休息日且吃早餐时的参考', daily_nutrition: Object.freeze({ kcal: 2400 }), variants: [Object.freeze({ id: 'training_no_breakfast', label: '训练日 · 不吃早餐', condition: '仅训练且不吃早餐时适用', recipes: [{ meal_type: '练后', foods: ['测试食品B33g'] }], daily_nutrition: { kcal: 2410 } })] });
    expect(selectedPlanVariant(plan, null)).toBe(plan);
    expect(selectedPlanVariant(plan, 'unknown')).toBe(plan);
    const training = selectedPlanVariant(plan, 'training_no_breakfast');
    expect(training.daily_nutrition.kcal).toBe(2410);
    expect(training.condition_label).toBe('仅训练且不吃早餐时适用');
    expect(plan.daily_nutrition.kcal).toBe(2400);
    expect(plan.training_status).toBe('unknown');
    expect(plan.active_variant_id).toBeNull();
  });
  it('shows the backend policy version and keeps proposed rules distinct from active ones', () => {
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', totals: {} }, target: { daily: {} }, scores: { days: [] }, policy: { policy_version: 'policy-test-v7', policy_hash: 'policy-hash', skill_hash: 'skill-hash', rules: [{ id: 'day', title: '已执行规则', description: '测试规则描述', status: 'active' }, { id: 'review', title: '未接入检查', description: '尚待实现', status: 'proposal' }, { id: 'missing', title: '等待数据', description: '当前资料不足', status: 'insufficient_data' }] } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    expect(html).toContain('<details class="calculation-rules">');
    expect(html).toContain('policy-test-v7');
    expect(html).toContain('已执行规则 · 已生效');
    expect(html).toContain('未接入检查 · 待实现');
    expect(html).toContain('等待数据 · 资料不足');
    expect(html).not.toContain('未接入检查 · 已生效');
  });
  it('withdraws unquantified or explicitly disabled plans while preserving recorded intake', () => {
    for (const state of [{}, { quantification_status: 'needs_review' }, { quantification_status: 'verified_estimate', valid_for_use: false }, { quantification_status: 'verified_estimate', plan_scope: 'remaining_today' }]) {
      const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', meals_count: 1, totals: { kcal: { low: 180, high: 180, coverage: 1 } } }, target: { daily: { kcal: 2400 } }, scores: { days: [] }, daily_plan: { data: { target_date: '2025-10-12', next_meal: { title: '旧方案', foods: [], recipes: [{ meal_type: '午餐', foods: ['缺少份量的旧清单'], budget: { kcal: 840 } }], daily_nutrition: { kcal: 2400 }, ...state } } } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
      expect(html).toMatch(/方案核算中|剩余方案需重新核算/);
      expect(html).not.toContain('缺少份量的旧清单');
      expect(html).not.toContain('菜单参考合计');
      expect(html).toContain('已摄入 180 / 推荐 2400');
    }
  });
  it('shows complete planned portions and audited totals without adding them to intake', () => {
    const nutrition = { kcal: 800, protein_g: 55, fat_g: 22, carbs_g: 95 };
    const recipes: any[] = ['早餐', '午餐', '晚餐'].map(meal_type => ({ meal_type, dish_title: '清炖牛肉配米饭', portion_summary: '牛肉150g（生重）· 米饭200g（熟重）· 蔬菜一份，少油', foods: ['熟米饭200g', '牛肉150g（生重）', '蔬菜200g', '食用油10g'], nutrition, budget: { kcal: 9999 }, contributes_to_daily_total: true, items: [{ name: '牛肉', quantity: 150, unit: 'g', weight_basis: '生重', nutrition, source: { title: '测试用已确认标签', product_version: 2 }, assumptions: ['烹调油另计'] }] }));
    recipes.push({ meal_type: '加餐 / 练前餐', foods: ['酸奶150g', '水果100g'], nutrition: { kcal: 150, protein_g: 5, fat_g: 3, carbs_g: 22 }, optional: true, contributes_to_daily_total: false, redistribution_from: '把早餐已列出的酸奶和水果移到此时，不额外增加' });
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', meals_count: 1, totals: { kcal: { low: 180, high: 180, coverage: 1 } } }, target: { daily: { kcal: 2400 } }, scores: { days: [] }, daily_plan: { data: { target_date: '2025-10-12', next_meal: { title: '推荐份量', reference_date: '2025-10-13', reason_summary: '根据近期已记录食物与参考目标搭配。', sources: [{ title: '测试用指南来源', url: 'https://example.com/nutrition' }], foods: [], recipes, daily_nutrition: { kcal: 2400, protein_g: 165, fat_g: 66, carbs_g: 285 }, quantification_status: 'verified_estimate', target_comparison: { targets: { kcal: 2400, protein_g: 165, fat_g: 67, carbs_g: 284 }, actual: { kcal: 2400, protein_g: 165, fat_g: 66, carbs_g: 285 } } } } } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    const summary = html.match(/<ul class="advice-glance">([\s\S]*?)<\/ul>/)?.[1] || '';
    expect(summary).toContain('清炖牛肉配米饭');
    expect((summary.match(/class="plan-meal-card"/g) || []).length).toBe(4);
    expect(summary).toContain('<h3>午餐</h3><p class="plan-dish">清炖牛肉配米饭</p>');
    expect(summary).toContain('牛肉150g（生重）· 米饭200g（熟重）· 蔬菜一份，少油');
    expect(summary).not.toContain('食用油10g');
    expect(html).toContain('食用油10g');
    expect(summary).toContain('把早餐已列出的酸奶和水果移到此时，不额外增加');
    expect(html).toContain('菜单参考合计</strong>');
    expect(html).toContain('已摄入 180 / 推荐 2400');
    expect(html).not.toContain('已摄入 2580 / 推荐 2400');
    expect(html).not.toContain('预算 9999');
    expect(html).toContain('标签版本 2');
    expect(html).toContain('烹调油另计');
    expect(html).toContain('方案与参考目标');
    expect(html).toContain('为什么这样吃');
    expect(html).toContain('根据近期已记录食物与参考目标搭配。');
    expect(html).toContain('测试用指南来源');
    expect(html.indexOf('为什么这样吃')).toBeGreaterThan(html.indexOf('加餐 / 练前餐（按需）'));
    expect(html).toContain('这是整天的参考份量，不是今天剩余要吃的量。');
    expect(html).toContain('方案参考日期：2025-10-13');
    expect(html).toContain('aria-controls="diet-advice-content"'); expect(html).toContain('>明日饮食建议<svg');
    expect(html).toContain('<time dateTime="2025-10-12">10月12日 · 星期日</time>');
  });
});

import { CalendarGrid, HistoryDay, scoreBand, shiftMonth } from '../src/DietHistory';
describe('read-only history calendar', () => {
  it('uses exact score thresholds and keeps unknown scores neutral', () => {
    for (const value of [null, undefined, NaN, Infinity, -1, 101, '90', true]) expect(scoreBand(value)).toBe('neutral');
    for (const value of [85, 90, 100]) expect(scoreBand(value)).toBe('green');
    for (const value of [70, 76, 84, 84.9]) expect(scoreBand(value)).toBe('yellow');
    for (const value of [0, 69, 69.9]) expect(scoreBand(value)).toBe('red');
    expect(shiftMonth('2025-12', 1)).toBe('2026-01');
    expect(shiftMonth('2025-01', -1)).toBe('2024-12');
  });
  it('renders only date text in colored circular buttons and never makes missing a score zero', () => {
    const html = renderToStaticMarkup(createElement(CalendarGrid, { data: { month: '2025-10', first_weekday: 3, today: '2025-10-12', days: [
      { date: '2025-10-01', score: 95, score_status: 'saved', meals: 2 },
      { date: '2025-10-02', score: 76, score_status: 'saved', meals: 2 },
      { date: '2025-10-03', score: 0, score_status: 'saved', meals: 2 },
      { date: '2025-10-04', score: 99, score_status: 'unscored', meals: 2 },
    ] }, navigate: () => {} }));
    expect(html).toContain('history-green'); expect(html).toContain('history-yellow'); expect(html).toContain('history-red'); expect(html).toContain('history-neutral');
    expect(html).not.toContain('>95<'); expect(html).not.toContain('>85<'); expect(html).not.toContain('>0<'); expect(html).not.toContain('>99<');
    expect(html).toContain('2025-10-04，未完整评分');
  });
  it('shows unknown per-meal nutrition and targets without filling zeros or current targets', () => {
    const html = renderToStaticMarkup(createElement(HistoryDay, { data: { date: '2025-10-11', meals: 1, analyzed: 0, finished: false, totals: {}, score_status: 'unscored', state: '待补齐', components: [], entries: [{ id: 'one', meal_type: '午餐', title: '历史实际餐', eaten_at: '2025-10-11T12:00:00+08:00', nutrition: {}, eaten_fraction: 1, limitations: [] }] }, navigate: () => {} }));
    expect(html).toContain('待补营养'); expect(html).toContain('没有该日参考目标存档'); expect(html).toContain('未评分'); expect(html).not.toContain('0 kcal');
  });
});

describe('advance menus are marked as test previews', () => {
  it('shows the publication boundary without changing recorded intake', () => {
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-12', totals: {} }, target: { daily: {} }, scores: { days: [] }, daily_plan: { data: { target_date: '2025-10-12', plan_mode: 'test_preview', next_meal: { reference_date: '2025-10-13', plan_mode: 'test_preview', foods: [] } } } } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    expect(html).toContain(' · 测试预览'); expect(html).toContain('北京时间07:00后由操作者根据最新记录生成');
    expect(html).toContain('当前预览不算已吃或正式发布');
  });
});

import { ScoreBreakdown } from '../src/ScoreBreakdown';
describe('saved quality score explanations', () => {
  it('keeps unknown points as evidence gaps and preserves per-domain reasons', () => {
    const html = renderToStaticMarkup(createElement(ScoreBreakdown, { data: { components: [
      { key: 'energy', name: '能量适配', points: 25, maximum: 25, reason: '落在参考区间内' },
      { key: 'vegetables', name: '蔬菜', points: null, maximum: 10, reason: '没有可靠克数' },
    ], score_readiness: { missing: ['尚未确认全天记完'] }, score_limitations: ['不是医学诊断'] } }));
    expect(html).toContain('能量适配25分'); expect(html).toContain('蔬菜无可评证据'); expect(html).toContain('不当作没吃');
    expect(html).not.toContain('尚未确认全天记完'); expect(html).toContain('不是医学诊断');
    expect(html).not.toContain('undefined'); expect(html).not.toContain('0/10分');
  });
});

 it("manual structured menu without legacy foods does not crash visual lookup", () => { expect(mealVisual({title:"菜单"} as any)).toBeNull(); });

it('compact score rules explain normalization and evidence deductions without inventing missing meals',()=>{
 const html=renderToStaticMarkup(createElement(ScoreBreakdown,{data:{score:84,score_scope:'recorded_normalized',components:[
 {key:'energy',name:'能量',points:25,maximum:25},{key:'protein',name:'蛋白',points:25,maximum:25},{key:'fat',name:'脂肪',points:20,maximum:20},
 {key:'vegetables',name:'蔬菜',points:5,maximum:10,reason:'已可靠识别，份量不明'},{key:'whole',name:'全谷',points:5,maximum:10,reason:'已可靠识别，份量不明'},
 {key:'fruit',name:'水果',points:null,maximum:10},{key:'alcohol',name:'饮酒',points:-5,maximum:0}]}}));
 expect(html).toContain('80 ÷ 90 × 100 ≈ 89');expect(html).toContain('取整为84/100分');expect(html).toContain('已记录饮酒，扣5分');expect(html).toContain('份量未量化');expect(html).toContain('不当作没吃');expect(html).not.toContain('-5/0');
});

describe('private dashboard shares the phone visual hierarchy', () => {
  const props = {data:{'diet/overview':{current_metrics:{身高:172,体重:69.4,体脂率:21.2},today:{date:'2025-10-13',totals:{}},scores:{days:[]}}},edit:()=>{},remove:()=>{},run:async()=>{},navigate:()=>{},notify:()=>{},refresh:()=>{}};
  it('uses two header rows, body trends, pastel rings and history beside meals', () => {
    const html=renderToStaticMarkup(createElement(DietPage,props));
    expect(html).toContain('class="header-meta"');expect(html).toContain('class="dashboard-heading"');
    expect(html).toContain('今日饮食</span>');expect(html).toContain('目标待设置');expect(html).not.toContain('减脂模式');expect(html).toContain('07:00 饮食日分界');expect(html).not.toContain('每日7:00更新');
    expect(html).toContain('#F9B086');expect(html).toContain('#8DB5F0');expect(html).toContain('#D1B48A');expect(html).toContain('#8ABEA8');
    expect((html.match(/aria-label="查看体重趋势"/g)||[]).length).toBe(1);
    expect((html.match(/aria-label="查看体脂率趋势"/g)||[]).length).toBe(1);
    expect(html.indexOf('历史记录</button>')).toBeGreaterThan(html.indexOf('今天吃了什么'));
    expect(html).toContain('记录、建议与历史');expect(html).toContain('上传餐食照片');
  });
  it('keeps the two disclosures independent and binds refreshing to the request', () => {
    const html=renderToStaticMarkup(createElement(DietPage,{...props,refreshing:true}));
    expect(html).toContain('aria-controls="diet-advice-content"');expect(html).toContain('aria-controls="today-meals-content"');
    expect(html).toContain('refresh-button is-refreshing');expect(html).toContain('disabled="" aria-label="刷新今日摄入"');
  });
});

import { compareMealTimes, mealTime } from '../src/mealOrder';
describe('chronological actual meal display', () => {
  it('sorts mixed timezones, late entries and corrections without changing source', () => {
    const entries = Object.freeze([
      Object.freeze({ title: '晚餐', eaten_at: '2025-10-13T18:38:52+08:00', updated_at: '2025-10-13T23:59:00+08:00' }),
      Object.freeze({ title: '夜宵', eaten_at: '2025-10-13T15:14:19Z' }),
      Object.freeze({ title: '早餐', eaten_at: '2025-10-13T10:30:24+08:00', created_at: '2025-10-13T23:50:00+08:00' }),
      Object.freeze({ title: '午餐', eaten_at: '2025-10-13T04:39:51Z' }),
      Object.freeze({ title: '拿铁', eaten_at: '2025-10-13T07:52:09Z' }),
      Object.freeze({ title: '加餐', eaten_at: '2025-10-13T17:51:00+08:00' }),
    ]);
    expect([...entries].sort(compareMealTimes).map(e => e.title)).toEqual(['早餐', '午餐', '拿铁', '加餐', '晚餐', '夜宵']);
    expect(entries[0].title).toBe('晚餐');
    const rows = entries.map((data, i) => ({meal:{id:`meal-${i}`,created_at:'created_at' in data ? data.created_at : undefined,data:{...data,diet_date:'2025-10-13',meal_type:data.title,assets:[],execution:'done'}},analysis:null}));
    const html = renderToStaticMarkup(createElement(DietPage, { data: { 'diet/overview': { today: { date: '2025-10-13', totals: {} }, target: { daily: {} }, scores: { days: [] }, entries: rows } }, edit: () => {}, remove: () => {}, run: async () => {}, navigate: () => {}, notify: () => {}, refresh: () => {} }));
    const todayMeals=html.match(/<section class="today-meals"[\s\S]*?<\/section>/)?.[0] || '';
    expect([...todayMeals.matchAll(/<h3>(.*?)<\/h3>/g)].map(m=>m[1]).slice(0,6)).toEqual(['早餐', '午餐', '拿铁', '加餐', '晚餐', '夜宵']);
  });
  it('falls back only to original receipt or creation and keeps stable ties', () => {
    expect(mealTime({ eaten_at: 'bad', received_at: '2025-10-13T10:00:00Z' })).toBe(Date.parse('2025-10-13T10:00:00Z'));
    expect(mealTime({ created_at: '2025-10-13T10:00:00Z' })).toBe(Date.parse('2025-10-13T10:00:00Z'));
    expect(mealTime({ eaten_at: '2025-10-13T10:00:00' })).toBe(Infinity);
    expect(compareMealTimes({}, {})).toBe(0);
    expect(compareMealTimes({eaten_at:'2025-10-13T10:00:00Z'},{eaten_at:'2025-10-13T18:00:00+08:00'})).toBe(0);
    expect(compareMealTimes({eaten_at:'2025-10-14T01:00:00+08:00'},{eaten_at:'2025-10-13T23:00:00+08:00'})).toBe(1);
  });
});

import { ScoreSummary } from '../src/ScoreSummary';
describe('versioned score arithmetic', () => {
  const parts=[{key:'energy',name:'热量目标',points:25,maximum:25},{key:'protein',name:'蛋白质目标',points:20,maximum:20},{key:'fat',name:'脂肪目标',points:15,maximum:15},{key:'carbs',name:'碳水目标',points:0,maximum:10},{key:'vegetables',name:'蔬菜',points:10,maximum:10},{key:'fruit',name:'水果',points:10,maximum:10},{key:'wholegrain',name:'全谷',points:10,maximum:10}];
  it('explains stored 79 cap instead of pretending 90 rounds to 79', () => {
    const html=renderToStaticMarkup(createElement(ScoreSummary,{data:{score:79,components:parts,score_limitations:['明显偏离目标，最高限制为79']}}));
    expect(html).toContain('按明显偏离目标规则封顶为');
    expect(html).not.toContain('取整为');
    expect(html).toContain('碳水目标10分');
  });
  it('keeps legacy dynamic weights and ordinary rounding without inventing a cap', () => {
    const legacy=[{key:'energy',name:'能量适配',points:25,maximum:25,reason:'85%–115%满分'},{key:'protein',name:'蛋白适量',points:25,maximum:25},{key:'fat',name:'脂肪供能',points:20,maximum:20},{key:'vegetables',name:'蔬菜',points:10,maximum:10},{key:'fruit',name:'水果',points:10,maximum:10},{key:'wholegrain',name:'全谷',points:0,maximum:10},{key:'alcohol',name:'酒精',points:-5.3,maximum:0}];
    const html=renderToStaticMarkup(createElement(ScoreSummary,{data:{score:85,components:legacy}}));
    expect(html).toContain('蛋白适量25分');expect(html).toContain('脂肪供能20分');
    expect(html).not.toContain('碳水目标');expect(html).not.toContain('封顶为');expect(html).toContain('取整为');
  });
  it('explains an estimated 79 cap from zero macro points without changing the saved-score rule', () => {
    const estimated = renderToStaticMarkup(createElement(ScoreSummary, { data: { score: null, score_status: 'estimated', estimated_score: 79, estimated_components: parts } }));
    expect(estimated).toContain('估算项目合计90，按明显偏离目标规则封顶为79/100分');
    expect(estimated).not.toContain('取整为79');
    const saved = renderToStaticMarkup(createElement(ScoreSummary, { data: { score: 79, score_status: 'saved', components: parts } }));
    expect(saved).not.toContain('封顶为');
    expect(saved).toContain('取整为79/100分');
    const unrelatedZero = parts.map(part => part.key === 'carbs' ? { ...part, key: 'wholegrain' } : part);
    const other = renderToStaticMarkup(createElement(ScoreSummary, { data: { score: null, score_status: 'estimated', estimated_score: 79, estimated_components: unrelatedZero } }));
    expect(other).not.toContain('封顶为');
  });
});

import { estimatedScoreValue, scoreEstimateNotice } from '../src/scoreDisplay';
describe('explicit historical score estimates', () => {
  const estimateParts = [
    { key: 'energy', name: '热量目标', points: 0, maximum: 25 },
    { key: 'protein', name: '蛋白质目标', points: 20, maximum: 20 },
    { key: 'fat', name: '脂肪目标', points: 3, maximum: 15 },
    { key: 'carbs', name: '碳水目标', points: 5, maximum: 10 },
    { key: 'vegetables', name: '蔬菜', points: 10, maximum: 10 },
    { key: 'fruit', name: '水果', points: 10, maximum: 10 },
    { key: 'wholegrain', name: '全谷', points: 10, maximum: 10 },
    { key: 'alcohol', name: '酒精', points: -30, maximum: 0, reason: '已记录饮酒，扣30分；每3g扣1分，最多30分' },
  ];
  const estimate = {
    date: '2025-10-14', meals: 3, totals: {}, entries: [], state: '待复核',
    score: null, score_status: 'estimated', score_scope: 'unavailable', score_maximum: null,
    estimated_score: 28, estimated_components: estimateParts,
    components: [{ key: 'legacy', name: '不可混用的正式项目', points: 100, maximum: 100 }],
    estimate_notice: '按营养区间中点估算，不代表精确摄入；区间跨评分档位，正式评分仍待复核。',
  };
  const calendar = (day: any) => renderToStaticMarkup(createElement(CalendarGrid, { data: { month: '2025-10', first_weekday: 3, today: '2025-10-15', days: [day] }, navigate: () => {} }));
  const dayMarkup = (day: any) => renderToStaticMarkup(createElement(HistoryDay, { data: day, navigate: () => {} }));

  it('shows 28 as red with an explicit accessible estimate label', () => {
    const html = calendar(estimate);
    expect(html).toContain('class="history-day history-red history-estimated"');
    expect(html).toContain('aria-label="2025-10-14，估算28分，待正式复核，3餐"');
    expect(html).toContain('<time dateTime="2025-10-14">14</time>');
    expect(html).not.toContain('>28<');
    expect(html).not.toContain('绿色');
  });

  it('keeps a compact estimate label without the removed verbose notice', () => {
    const html = dayMarkup(estimate);
    expect(html).toContain('class="history-score history-red history-estimated"');
    expect(html).toContain('28 / 100 分 · 估算');
    expect(html).not.toContain('aria-label="估算评分说明"');
    expect(html).not.toContain(estimate.estimate_notice);
    expect(html).toContain('估算，待正式复核');
    expect(html).not.toContain('已验证');
    expect(html).not.toContain('不可混用的正式项目');
    expect(html).not.toContain('未评分</span>');
  });

  it('uses only estimated components and alcohol in the existing two sections', () => {
    const frozen = Object.freeze({ ...estimate, estimated_components: estimateParts.map(part => Object.freeze({ ...part })) });
    const before = JSON.stringify(frozen);
    for (const element of [createElement(ScoreSummary, { data: frozen }), createElement(ScoreBreakdown, { data: frozen })]) {
      const html = renderToStaticMarkup(element);
      expect((html.match(/<h3>/g) || []).length).toBe(2);
      expect(html).toContain('2. 分数怎么算');
      expect(html).toContain('1. 我为什么扣分');
      expect(html.indexOf('1. 我为什么扣分')).toBeLessThan(html.indexOf('2. 分数怎么算'));
      expect(html).toContain('估算项目合计58，再扣30分，估算取整为28/100分');
      expect(html).toContain('已记录饮酒，扣30分');
      expect(html).toContain('每3g扣1分，最多30分');
      expect(html).toContain('少量饮酒也非无风险');
      expect(html).not.toContain(estimate.estimate_notice);
      expect(html).not.toContain('-30/0');
      expect(html).not.toContain('不可混用的正式项目');
      expect(html).not.toContain('已评项目合计');
    }
    expect(frozen.score).toBeNull();
    expect(JSON.stringify(frozen)).toBe(before);
  });

  it('keeps invalid, pending, future, and mismatched estimate states neutral', () => {
    const invalid = [
      ...[null, undefined, NaN, Infinity, -1, 101, '28'].map(estimated_score => ({ estimated_score })),
      { pending_changes: true }, { is_future: true }, { score_status: 'pending' },
      { score_status: 'unscored' }, { score_status: 'saved' }, { score: 28 }, { score_maximum: 80 },
    ];
    for (const override of invalid) {
      const data = { ...estimate, ...override };
      const month = calendar(data), day = dayMarkup(data);
      expect(month).toContain('class="history-day history-neutral"');
      expect(month).not.toContain('估算28分');
      expect(month).not.toContain('history-estimated');
      expect(day).toContain('class="history-score history-neutral">未评分');
      expect(day).not.toContain('28 / 100 分 · 估算');
      expect(day).not.toContain('取整为28/100分');
      expect(day).not.toContain('NaN');
      expect(day).not.toContain('Infinity');
    }
    expect(calendar({ ...estimate, is_future: true })).toContain('未到日期');
    expect(calendar({ ...estimate, is_future: true })).toContain('disabled=""');
    expect(dayMarkup({ ...estimate, pending_changes: true })).toContain('等待重新结算');
  });

  it('preserves valid saved and unscored views and ignores stray estimate fields', () => {
    const saved = { ...estimate, score: 93, score_status: 'saved', score_scope: 'full_day', score_maximum: 100, components: [{ key: 'energy', name: '热量目标', points: 93, maximum: 100 }] };
    const month = calendar(saved), day = dayMarkup(saved);
    expect(month).toContain('class="history-day history-green"');
    expect(month).toContain('绿色，85分及以上');
    expect(day).toContain('class="history-score history-green">93 / 100 分');
    expect(day).toContain('已评项目合计93，取整为93/100分');
    expect(day).not.toContain('history-estimated');
    expect(day).not.toContain(estimate.estimate_notice);
    const unscored = dayMarkup({ ...saved, score: null, score_status: 'unscored', components: [] });
    expect(unscored).toContain('class="history-score history-neutral">未评分');
    expect(unscored).toContain('尚未生成有效评分');
    expect(unscored).not.toContain('28/100分');
    expect(unscored).not.toContain('93/100分');
    for (const override of [{ pending_changes: true }, { is_future: true }, { score: NaN }, { score: 101 }]) {
      expect(calendar({ ...saved, ...override })).toContain('class="history-day history-neutral"');
      expect(dayMarkup({ ...saved, ...override })).toContain('class="history-score history-neutral">未评分');
    }
  });

  it('retains a real zero estimate and supplies a cautious fallback notice', () => {
    expect(estimatedScoreValue({ ...estimate, estimated_score: 0 })).toBe(0);
    expect(calendar({ ...estimate, estimated_score: 0 })).toContain('估算0分');
    expect(dayMarkup({ ...estimate, estimated_score: 0 })).toContain('0 / 100 分 · 估算');
    const notice = scoreEstimateNotice({ estimate_notice: ' ' });
    expect(notice).toContain('中点');
    expect(notice).toContain('不代表精确摄入');
    expect(notice).toContain('区间跨评分档位');
    expect(notice).toContain('正式评分仍待复核');
    expect(dayMarkup({ ...estimate, estimate_notice: undefined })).not.toContain(notice);
  });
});
