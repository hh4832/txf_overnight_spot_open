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
    text=f'''# TXF Overnight → 0050 Open v0.1.3

{info['data_label']}

研究狀態：{info['status']}。{info['live_data_validation']}。
研究判定：{info['research_decision']}。框架交付不代表完成真實研究。

研究問題：H1 夜盤資訊是否傳至開盤跳空；H2 開盤後是否仍有增量資訊；H3 僅描述。
方法：同契約報酬、調整價格、HAC({info['config']['hac_lags']})、歷史 expanding bins、逐日 expanding OOS。
資料日期：{events.signal_trade_date.min()} 至 {events.signal_trade_date.max()}。
樣本流程：{len(events)} → 有效 {len(valid)}；排除 {len(events)-len(valid)}。
排除原因：{exclusions}。

H1：請見 gap_regression.csv（係數、CI、相關性、R²）及 out_of_sample_scores.csv。
H2：請見 intraday_regression.csv。EQUIVALENCE_NOT_TESTED；未事前指定經濟等效界值。
p > 0.05 不證明一次反映完；開盤後平均報酬不必為零。
控制模型請見 robustness_summary.csv，0500 與 0845 模型分開。
年度／波動／假期／極端事件／公司行動敏感度詳見 tables。

反對者觀點：日盤收盤差 15 分鐘、週末新消息、契約換月、分鐘棒缺漏、樣本依賴，均可能影響解讀。
條件分組 CI 是描述性 IID t/Wilson 區間，不具序列相關調整；正式推論以 HAC 模型為主。
0050 單一現存 ETF 存在標的選擇限制，不能外推全市場；不宣稱交易獲利，未模擬滑價、成本或可成交性。
事後開盤 gap 分組不作為開盤前可用訊號。未驗證的重大事件控制不執行。

目前建議：修改後再測（完成真實資料驗證後再判讀）。不得因單一 p-value 判定成功。
Git SHA：{info['git_sha']}；執行紀錄與套件版本見 run_info.json。
'''
    for name in ['gap_regression','intraday_regression','out_of_sample_scores']:
        text += '\n\n'+name+'\n\n```text\n'+tables[name].to_string(index=False)+'\n```\n'
    (run/'reports/summary.md').write_text(text,encoding='utf-8')
    (run/'diagnostics/diagnostics.md').write_text('# Diagnostics\n\n'+json.dumps(exclusions,ensure_ascii=False,indent=2)+'\n\nNo silent fill. Contract mismatches excluded.\n',encoding='utf-8')
