"""Shared predeclared research summaries for full runs and statistics-only resume.

Never adjusts event prices, signal times, sampling or statistical parameters.
"""
import pandas as pd
from .conditional_analysis import conditional
from .robustness import analyze
from .statistics import regression, oos, oos_scores, X, Y
from .trading_reference import trading_reference


def build_tables(valid, cfg):
    if valid.empty:
        raise ValueError('No valid events; research blocked')
    prob, bins = conditional(valid, cfg)
    annual, robust = analyze(valid, cfg)
    predictions = oos(valid, cfg)
    tables = {
        'descriptive_statistics': valid[[X, *Y, 'spot_total_return']].describe().reset_index(),
        'gap_regression': pd.DataFrame([regression(valid, Y[0], cfg)]),
        'intraday_regression': pd.DataFrame([regression(valid, Y[1], cfg)]),
        'conditional_probability': prob,
        'conditional_bins': bins,
        'annual_stability': annual,
        'out_of_sample_results': predictions,
        'out_of_sample_scores': oos_scores(predictions),
        'robustness_summary': robust,
    }
    tables.update(trading_reference(valid, cfg))
    return tables
