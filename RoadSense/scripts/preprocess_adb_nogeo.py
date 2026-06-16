"""Lightweight ADB preprocessing that reads GeoJSON without geopandas.

This extracts feature properties, computes derived metrics (speed excess, logs,
risk indices) and saves a CSV. It avoids geopandas so it can run in restricted
environments.
"""
from pathlib import Path
import json
import argparse
import pandas as pd
import numpy as np
import joblib
from sklearn.preprocessing import StandardScaler, MinMaxScaler


def load_geojson(path: Path, region: str) -> pd.DataFrame:
    with open(path, 'r', encoding='utf-8') as f:
        gj = json.load(f)
    props = [feat.get('properties', {}) for feat in gj.get('features', [])]
    df = pd.DataFrame(props)
    df['region'] = region
    print(f"Loaded {len(df)} features from {path}")
    return df


def clean(df: pd.DataFrame, min_sample: int = 500) -> pd.DataFrame:
    df = df.copy()
    drop_cols = [
        'RoadLength', 'Percent_', 'ForAnalysis', 'SpeedLimitFloor',
        'NO_OF_Result_Segments', 'ProvinceID', 'PercentileBand'
    ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True, errors='ignore')

    if 'AnalysisStatus' in df.columns:
        df = df[df['AnalysisStatus'] == 'Valid']

    if 'SampleSize_avg' in df.columns:
        df = df[df['SampleSize_avg'].fillna(0) >= min_sample]

    if 'LandUse' in df.columns:
        df['LandUse'] = df['LandUse'].fillna('RURAL').astype(str).str.upper().str.strip()
    if 'RoadClass' in df.columns:
        df['RoadClass'] = df['RoadClass'].fillna('unknown').astype(str).str.lower().str.strip()

    if 'SpeedLimit' in df.columns and 'RoadClass' in df.columns:
        defaults = {'motorway':110,'trunk':90,'primary':80,'secondary':60}
        mask = df['SpeedLimit'].isnull() | (df['SpeedLimit'] == 0)
        df.loc[mask, 'SpeedLimit'] = df.loc[mask, 'RoadClass'].map(defaults)

    required = [c for c in ['MedianSpeed','F85thPercentileSpeed','PercentOverLimit'] if c in df.columns]
    if required:
        df = df.dropna(subset=required)

    if 'PercentOverLimit' in df.columns:
        df['PercentOverLimit'] = df['PercentOverLimit'].clip(0,1)

    return df.reset_index(drop=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if 'F85thPercentileSpeed' in df.columns and 'SpeedLimit' in df.columns:
        df['speed_excess_85'] = df['F85thPercentileSpeed'] - df['SpeedLimit']
    if 'MedianSpeed' in df.columns and 'SpeedLimit' in df.columns:
        df['speed_excess_median'] = df['MedianSpeed'] - df['SpeedLimit']
    if 'WeightedSample' in df.columns:
        df['log_weighted_sample'] = np.log1p(df['WeightedSample'])
    if 'SampleSize_avg' in df.columns:
        df['log_sample_size'] = np.log1p(df['SampleSize_avg'])

    if all(c in df.columns for c in ['PercentOverLimit','speed_excess_85','SpeedLimit']):
        df['speed_risk_index'] = df['PercentOverLimit'] * np.maximum(df['speed_excess_85'],0) / df['SpeedLimit'].replace(0,np.nan)
    if 'RankedPercentile' in df.columns and 'speed_risk_index' in df.columns:
        df['exposure_risk'] = df['RankedPercentile'] / 100 * df['speed_risk_index']
    if 'LandUse' in df.columns:
        df['urban_flag'] = (df['LandUse']=='URBAN').astype(int)
        if 'exposure_risk' in df.columns:
            df['urban_weighted_risk'] = df['exposure_risk'] * (1 + 0.5 * df['urban_flag'])

    df['is_speed_problem'] = 0
    if all(c in df.columns for c in ['PercentOverLimit','speed_excess_85']):
        df['is_speed_problem'] = ((df['PercentOverLimit']>0.5) | (df['speed_excess_85']>20)).astype(int)

    return df


def encode_and_normalise(df: pd.DataFrame, fit: bool = True):
    df = df.copy()
    for c in ['RoadClass','LandUse']:
        if c in df.columns:
            d = pd.get_dummies(df[c], prefix=c)
            df = pd.concat([df.drop(columns=[c]), d], axis=1)

    standard_cols = [c for c in ['MedianSpeed','F85thPercentileSpeed','speed_excess_85','speed_excess_median','log_weighted_sample','log_sample_size'] if c in df.columns]
    minmax_cols = [c for c in ['SpeedLimit','Shape_Length'] if c in df.columns]

    scalers = {}
    if standard_cols:
        ss = StandardScaler()
        df[standard_cols] = ss.fit_transform(df[standard_cols]) if fit else ss.transform(df[standard_cols])
        scalers['standard'] = ss
    if minmax_cols:
        mm = MinMaxScaler()
        df[minmax_cols] = mm.fit_transform(df[minmax_cols]) if fit else mm.transform(df[minmax_cols])
        scalers['minmax'] = mm

    return df, scalers


def run_pipeline(thailand_path: Path, maharashtra_path: Path, output: Path, min_sample: int = 500):
    dfs = []
    if thailand_path and thailand_path.exists():
        dfs.append(load_geojson(thailand_path, 'Thailand'))
    if maharashtra_path and maharashtra_path.exists():
        dfs.append(load_geojson(maharashtra_path, 'Maharashtra'))
    if not dfs:
        raise FileNotFoundError('No input files found')

    common = set(dfs[0].columns)
    for d in dfs[1:]:
        common &= set(d.columns)
    common = list(common)
    df = pd.concat([d[common] for d in dfs], ignore_index=True)
    print(f'Combined rows: {len(df)}')

    df = clean(df, min_sample=min_sample)
    print(f'After cleaning: {len(df)}')

    df = engineer_features(df)
    df, scalers = encode_and_normalise(df, fit=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    csv_out = str(output).replace('.gpkg','.csv')
    df.to_csv(csv_out, index=False)
    print(f'Saved CSV to {csv_out}')

    for k,s in scalers.items():
        joblib.dump(s, output.parent / f'{k}_scaler.pkl')
    print('Saved scalers')
    return df


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--thailand', type=Path, default=Path('data/ADB_Innovation_Thailand.geojson'))
    p.add_argument('--maharashtra', type=Path, default=Path('data/ADB_Innovation_Maharashtra.geojson'))
    p.add_argument('--output', type=Path, default=Path('RoadSense/outputs/processed_road_safety.gpkg'))
    p.add_argument('--min-sample', type=int, default=500)
    args = p.parse_args()
    run_pipeline(args.thailand, args.maharashtra, args.output, min_sample=args.min_sample)
