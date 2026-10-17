from pathlib import Path
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .statistics import X,Y


def write(run,events,tables,info):
    run=Path(run)
    events.to_parquet(run/'processed/event_dataset.parquet',index=False)
    for name,table in tables.items(): table.to_csv(run/f'tables/{name}.csv',index=False)
    with pd.ExcelWriter(run/'reports/summary.xlsx') as book:
        for name,table in tables.items(): table.to_excel(book,sheet_name=name[:31],index=False)
    valid=events[events.data_quality_status=='VALID']
    for y in Y:
        fig,ax=plt.subplots();ax.scatter(valid[X],valid[y],s=5,alpha=.3)
        ax.set(xlabel='TXF overnight return',ylabel=y,title=info['data_label'])
        fig.savefig(run/f'figures/{y}_scatter.png');plt.close(fig)
    for table_name,x,y in [('conditional_bins','scenario','spot_intraday_return_mean'),
                           ('annual_stability','year','beta'),
                           ('conditional_probability','scenario','spot_intraday_return_mean')]:
        tab=tables[table_name]
        fig,ax=plt.subplots(figsize=(9,5))
        if y in tab: ax.bar(tab[x].astype(str),tab[y])
        ax.set_title(info['data_label']+' / '+table_name);ax.tick_params(axis='x',rotation=45)
        fig.tight_layout();fig.savefig(run/f'figures/{table_name}.png');plt.close(fig)
    exclusions=events.exclusion_reason.value_counts().to_dict()
    ref=tables['trading_reference']
    hold=tables['trading_reference_holdout']
    comparison=tables['close_policy_comparison']
    text=f'''# TXF Overnight → 0050 — Trading Reference v0.1.4

Data: {info['data_label']}; Status: {info['status']}; Research decision: {info['research_decision']}.
Research period: {events.signal_trade_date.min()} to {events.signal_trade_date.max()}.
Candidate: {len(events)}; VALID: {len(valid)}; excluded: {len(events)-len(valid)}.
Exclusions: {exclusions}.

**This is a historical decision-support reference, NOT a trading signal or
profitability backtest.** Percentages in raw CSV are decimal returns, e.g. .01=1%.
Source: Fubon same-contract TXF 1-minute prices, FinLab adjusted 0050 daily
open/close. Predeclared adaptive close uses 13:45/05:00 when valid and
available, otherwise EXACT 13:44/04:59, with contract-expiry exclusions.
These timestamps are research conventions, not independently verified provider
closing semantics. No stale-price fill or cross-contract return.

## Predeclared TXF overnight-return groups

```text
{ref.to_string(index=False)}
```

Groups are fixed before observing outcomes; counts matter. The per-year
table is at tables/trading_reference_by_year.csv.

## Chronological holdout (only after configured history)

Train threshold: {info['config']['initial_train']} earlier observations.
If history is insufficient the following rows are NOT evaluated.
This table describes what happened, not an optimized trade-rule test.

```text
{hold.to_string(index=False)}
```

## Adaptive vs fixed close (descriptive only)

```text
{comparison.to_string(index=False)}
```

## Research diagnostics

H1/H2 remain available in tables/gap_regression.csv and
tables/intraday_regression.csv. Regression HAC, historical-only
quantiles, expanding OOS and prior statistical definitions are preserved.
OOS scores are in tables/out_of_sample_scores.csv.
H2 nonsignificance never proves complete information incorporation.
The 08:45 predictor is NOT part of a pre-05:00 signal.
No profit, slippage, tax, cost, fill, or position-size assumptions have
been validated. Do not use today's observed 0050 gap as a pre-open
predictor. Year-by-year, small-bin, holiday and rollover risks remain.

Git SHA: {info['git_sha']}; raw hashes in raw_manifest/manifest.json.
'''
    for name in ['gap_regression','intraday_regression','out_of_sample_scores']:
        text += '\n\n'+name+'\n\n```text\n'+tables[name].to_string(index=False)+'\n```\n'
    (run/'reports/summary.md').write_text(text,encoding='utf-8')
    (run/'diagnostics/diagnostics.md').write_text('# Diagnostics\n\n'+json.dumps(exclusions,ensure_ascii=False,indent=2)+'\n\nNo silent fill. Contract mismatches excluded.\n',encoding='utf-8')
