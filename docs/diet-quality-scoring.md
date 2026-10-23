# 饮食评分 v8 / Diet scoring v8

版本 / Version: `diet-quality-v8-continuous-tolerance`  
生效饮食日期 / Effective diet date: **2026-10-23**, Asia/Shanghai（07:00 分界 / 07:00 boundary）

规则实现见 `apps/api/app/diet_scoring.py`，版本配置见 `apps/api/app/diet_policy.json`。本文说明软件计算，不是营养处方、医学风险换算或临床验证的健康指数。

The implementation is in `apps/api/app/diet_scoring.py`; version configuration is in `apps/api/app/diet_policy.json`. This document describes software calculations, not a nutrition prescription, medical-risk conversion, or clinically validated health index.

## 1. 七项固定 100 分 / Seven fixed components totaling 100

| 项目 / Component | 满分 / Maximum | 参考 / Reference |
| --- | ---: | --- |
| 热量 / Energy | 25 | 当日目标 / Target for that diet day |
| 蛋白质 / Protein | 20 | 当日目标 / Target for that diet day |
| 脂肪 / Fat | 15 | 当日目标 / Target for that diet day |
| 碳水 / Carbohydrates | 15 | 当日目标 / Target for that diet day |
| 蔬菜 / Vegetables | 10 | 300g 生可食重 / raw edible weight |
| 水果 / Fruit | 10 | 200g 可食重 / edible weight |
| 全谷杂豆 / Whole grains and mixed beans | 5 | 50g 原料干重 / dry ingredient weight |

个人目标必须来自该日适用的有效资料，不能拿本文算例作为默认目标。食物组参考克数保持不变；干重、生可食重与熟重不能直接混用。

Personal targets must come from valid information applicable to that diet day; examples here are not default targets. Food-group reference amounts are unchanged. Do not interchange dry, raw-edible, and cooked weights without a justified conversion.

## 2. 四项营养：容差内满分，之后连续扣分 / Macro and energy tolerance

令 `I` 为摄入、`T` 为正数目标、`W` 为该项满分；`d = abs(I / T - 1)`。

Let `I` be intake, `T` a positive target, and `W` the component maximum; `d = abs(I / T - 1)`.

- `d <= 0.05`：满分 / full points.
- `0.05 < d < 0.40`：线性递减 / linear decrease: `W * (0.40 - d) / 0.35`.
- `d >= 0.40`：该项零分 / zero component points.

等价统一公式 / Equivalent formula:

`points = W * max(0, min(1, (0.40 - abs(I / T - 1)) / 0.35))`

因此摄入为目标的 95%–105%（含边界）时满分；60% 或 140% 及其外侧为零。多吃和少吃按相对偏差对称计算，不奖励不足摄入。

Intake at 95%–105% of target, inclusive, earns full points; at or outside 60% and 140% it earns zero. Above- and below-target deviations are symmetric; underconsumption is not rewarded.

**仅用于验算的比例例子 / Ratio examples for checking the calculation:**

- 目标的 100% 或 105% / 100% or 105% of target → `W`.
- 目标的 120% / 120% of target → `W * 4/7`（热量项约 14.286 分 / approximately 14.286 energy points）.
- 目标的 60% 或 140% / 60% or 140% of target → `0`.

## 3. 食物组：按比例计分，吃够封顶 / Proportional food-group points

`points = W * max(0, min(1, intake_g / reference_g))`

少多少比例就扣该项多少比例，达到或超过参考值获得该项满分，不再另扣超量分。例如，明确记录的 150g 生可食蔬菜为 5/10 分；100g 水果为 5/10 分；25g 干重全谷杂豆为 2.5/5 分。这些只是计算例子，不是推荐个人餐单。

Points reflect the fraction of the reference amount achieved. Reaching or exceeding the reference earns full points, with no separate excess penalty. For example, documented 150g raw-edible vegetables earns 5/10, 100g fruit earns 5/10, and 25g dry whole grains/mixed beans earns 2.5/5. These illustrate calculations, not a recommended personal menu.

“明确没吃”可得该项零分，但“没有记录”或“份量未知”不自动等于零摄入。原证据要求、估算范围与缺失状态仍须保留。

Confirmed nonconsumption can yield zero component points; absent records or unknown quantities are not automatically zero intake. Preserve existing evidence requirements, estimate ranges, and missing-data states.

## 4. 酒精与总分 / Alcohol and total

酒精扣分规则不变 / Alcohol deduction is unchanged:

`pure_alcohol_g = volume_ml * ABV_percent / 100 * 0.789`

`deduction = round(min(30, pure_alcohol_g / 3), 1)`

`total = max(0, sum(seven_component_points) - deduction)`

保留各项计算精度，不先逐项四舍五入后再求和；显示数值可以舍入，最终总分按实现取整数。酒精扣分保留原一位小数规则。比如 6g 纯酒精扣 2 分，90g 扣 30 分；扣分封顶不表示健康风险封顶，也不表示存在无风险饮酒量。餐食能量已包括酒精时不重复加热量。

Retain component precision rather than rounding each component before summing; display values may be rounded and the final total is rounded to an integer by the implementation. The alcohol deduction retains its one-decimal rule. For example, 6g pure alcohol deducts 2 points and 90g deducts 30 points. The deduction cap is not a cap on health risk and implies no risk-free alcohol intake. Do not add alcohol energy again when it is already included in meal energy.

v8 不剔除任何评分维度，不把缺失项目重新归一化，也没有额外的 79 分封顶。资料不足或适用性审核未通过时仍可能不给总分，不能为填满页面而生成 0 分。展示颜色仍为 ≥85 绿、≥70 黄、其余红；这些不是医学安全线。

v8 drops no scoring dimension, does not renormalize missing components, and has no additional 79-point cap. Insufficient evidence or failed applicability checks may still prevent a total score; do not invent zero to fill the page. Display colors remain green at ≥85, yellow at ≥70, and red below 70; these are not medical safety thresholds.

## 5. 版本与历史 / Versioning and history

自 2026-10-23 饮食日起使用 v8，时间归属仍按 Asia/Shanghai 07:00。既有 v6/v7 历史评分、权重、解释和版本化估算保持原样，不因软件升级自动重算。旧版本的规则（包括适用的旧封顶）不能偷偷替换成 v8 的规则。

v8 applies from the 2026-10-23 diet day, retaining the Asia/Shanghai 07:00 boundary. Existing v6/v7 scores, weights, explanations, and versioned estimates remain unchanged rather than being recalculated on upgrade. Historical rules, including applicable legacy caps, must not silently become v8 rules.

本仓库不附带任何个人历史回写授权。另行提出的历史更正须按明确范围处理，并保留版本和审计。未记录日不是禁食日；原有证据完整性、适用性核验与非医疗限制始终有效。

This repository includes no authorization to rewrite anyone's personal history. A separately requested historical correction needs an explicit scope and retained version/audit evidence. An unrecorded day is not a fasting day; evidence completeness, applicability checks, and nonmedical limitations remain in force.
