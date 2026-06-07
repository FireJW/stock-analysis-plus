---
name: macro-health-overlay
description: 机构市场宏观健康度评分与风险窗口判断技能。用于把真实利率、美元指数、金融条件、流动性、通胀预期、油价、期限溢价和股指确认信号转换为可解释的风险窗口、健康度分数、信心等级和资产筛选建议。适合机构投研、组合复盘、市场晨会和股票池筛选前的宏观环境评估；不用于生成 HTML 页面或替代个股基本面判断。
---

# 机构市场宏观健康度评分与风险窗口判断

## 目标

用结构化信号回答三个问题：

- 当前风险资产窗口是 `favorable`、`tentative`、`mixed` 还是 `adverse`
- 仓位和选股应偏 `risk-on`、`selective`、`defensive` 还是 `neutral`
- 宏观信号是否足够支持继续做股票池筛选，还是应该先降低仓位、等待确认

这个技能只输出评分、判断和解释，不生成 HTML、不做页面设计，也不把宏观分数当作个股买卖结论。

## 输入信号

优先使用带日期的客观数据；没有实时数据时，使用用户给出的信号状态并明确标注覆盖率。

核心触发信号：

- `real_yield`: 10Y real yield，反映估值折现压力
- `dxy`: 美元指数，反映全球流动性和风险偏好压力

确认信号：

- `financial_conditions`: 金融条件是否收紧或放松
- `liquidity`: 准备金、RRP、TGA、SOFR/IORB 等流动性管道
- `equity_confirmation`: SPX、QQQ、VIX 是否确认风险偏好

误判控制信号：

- `breakeven`: 通胀预期是否重新抬头
- `oil`: 油价是否形成通胀冲击
- `term_premium`: 期限溢价是否抬升并压制估值

宏观情景辅助信号：

- `growth`: 增长韧性、改善、转弱或破裂
- `inflation`: 通胀缓和、稳定、粘性或再加速

## 评分模型

用三层 scorecard 避免只看单一宏观指标。

Primary trigger cluster:

- `real_yield`: easing `+1.2`, stable `+0.4`, tightening `-1.2`
- `dxy`: easing `+1.0`, stable `+0.3`, tightening `-1.0`

Confirmation cluster:

- `financial_conditions`: easing `+0.8`, neutral `0`, tightening `-0.8`
- `liquidity`: easing `+0.8`, neutral `0`, draining `-0.8`, stressed `-1.4`
- `equity_confirmation`: confirming `+0.8`, mixed `0`, failing `-0.8`

False-positive controls:

- `breakeven`: easing `+0.2`, stable `0`, reaccelerating `-0.5`
- `oil`: contained `0`, firm `-0.2`, inflationary_spike `-0.6`
- `term_premium`: easing `+0.2`, elevated `-0.2`, rising `-0.5`

判定规则：

- `favorable_risk_window`: total score `>= 2.5`，primary `>= 1.0`，股指确认，且流动性不是 stressed
- `tentative_favorable_risk_window`: total score `>= 1.0` 且 primary `>= 0.5`
- `adverse_risk_window`: primary 明显转负且确认信号恶化，或 total score `<= -1.0`
- `mixed_or_neutral_window`: 其他情况，要求保持选择性和个案驱动

信心等级：

- `high`: 至少 8 个核心信号有读数，且主触发与确认信号不互相冲突
- `medium`: 至少 5 个信号有读数，或高覆盖但主触发与确认信号冲突
- `low`: 覆盖不足、数据过旧，或只有主观判断没有来源

## 工作流

1. 固定 `as_of` 日期，所有结论都必须带数据截止日。
2. 归一化信号状态，不确定时使用 `mixed`、`neutral` 或明确写 `missing`。
3. 计算三层 scorecard，并展示 primary、confirmation、control、total 四个分数。
4. 判断宏观健康标签、风险姿态、窗口状态和增长/通胀情景。
5. 输出股票池筛选指导：偏好的风格、应惩罚的风格、仓位和失效规则。
6. 标注信心等级、数据覆盖率、缺失项和需要更新的数据源。

## 输出格式

默认用中文给出紧凑但可审计的结果：

```markdown
## 一句话判断
截至 YYYY-MM-DD，宏观健康度为 ...

## Scorecard
| Bucket | Score | Meaning |
|---|---:|---|
| Primary trigger | ... | ... |
| Confirmation | ... | ... |
| False-positive controls | ... | ... |
| Total | ... | ... |

## Signal Board
| Signal | State | Evidence | Interpretation |
|---|---|---|---|

## Regime And Guidance
- health_label: ...
- risk_posture: ...
- window_state: ...
- growth_inflation_regime: ...
- confidence: ...
- screening guidance: ...

## Missing Data / Caveats
- ...
```

如果用户需要机器可读结果，同时返回 JSON 字段：

- `macro_health_overlay`
- `scorecard`
- `shortlist_guidance`
- `live_fetch_summary`
- `seed_summary`
- `report_markdown`

## 可选脚本

技能包内的 Python 脚本可用于确定性评分：

```bash
python scripts/macro_health_overlay.py examples/macro-health-overlay-public-mix.request.template.json --output result.json --markdown-output report.md
```

最小请求：

```json
{
  "live_data_provider": "public_macro_mix"
}
```

需要手动填数时，使用：

```json
{
  "as_of": "YYYY-MM-DD",
  "signal_states": {
    "real_yield": "easing",
    "dxy": "stable",
    "financial_conditions": "neutral",
    "liquidity": "draining",
    "equity_confirmation": "mixed"
  },
  "evidence": [
    "写入数据来源、日期和读数"
  ]
}
```

## 约束

- 不生成 HTML、网页、图表页面或前端组件。
- 不因为宏观窗口有利就自动推荐个股；个股仍需基本面、估值、催化剂和交易结构确认。
- 不把缺失数据默认为利好；覆盖不足时降低信心等级。
- 不用“美债收益率下降所以风险资产必涨”这类单链条结论，必须同时检查美元、流动性、金融条件和股指确认。
- 如果实时数据不可用，输出应写明使用的是用户输入、缓存、还是手工数据。
