"""Paired multi-seed experiments with architecture and lossless-codec ablations."""
import argparse
import csv
from datetime import datetime, timezone
from itertools import product
import statistics
from .config import ExperimentConfig
from .paths import ROOT, OUTPUT, RUNS
from .offline import centralized
from .storage import read_json,write_json

GROUP_FIELDS=("profile","partition","selection","model_family","transport_codec")


def summarize(directory,records):
    groups={}
    for row in records:
        groups.setdefault(tuple(row[key] for key in GROUP_FIELDS),[]).append(row)
    aggregates=[]
    for key,rows in groups.items():
        item=dict(zip(GROUP_FIELDS,key));item["seeds"]=len(rows)
        for metric in ("fl_mae_ms","persistence_mae_ms","linear_trend_mae_ms","local_mae_ms",
                       "centralized_mae_ms","fl_json_bytes","training_json_bytes","savings_inclusive_fraction"):
            values=[r[metric] for r in rows]
            item[metric+"_mean"]=statistics.mean(values)
            item[metric+"_std"]=statistics.stdev(values) if len(values)>1 else 0
        aggregates.append(item)
    write_json(directory/"runs.json",records);write_json(directory/"aggregates.json",aggregates)
    for name,rows in (("runs",records),("aggregates",aggregates)):
        with (directory/f"{name}.csv").open("w",newline="",encoding="utf-8-sig") as output:
            writer=csv.DictWriter(output,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    pairs=[];cases={}
    for row in records:
        cases.setdefault((row["seed"],row["profile"],row["partition"],row["selection"]),{})[
            (row["model_family"],row["transport_codec"])]=row
    for key,arms in cases.items():
        legacy=arms.get(("residual_mlp","json"));packed=arms.get(("residual_mlp","packed"));trend=arms.get(("trend","packed"))
        if legacy and packed and trend:
            a=read_json(OUTPUT/"experiments"/legacy.get("artifact_id",str(legacy["id"]))/"result.json")
            b=read_json(OUTPUT/"experiments"/packed.get("artifact_id",str(packed["id"]))/"result.json")
            c=read_json(OUTPUT/"experiments"/trend.get("artifact_id",str(trend["id"]))/"result.json")
            fingerprints=lambda result:{k:v["dataset_sha256"] for k,v in result["clients"].items()}
            if not fingerprints(a)==fingerprints(b)==fingerprints(c):
                raise AssertionError("Ablations do not share the same client data")
            if abs(legacy["fl_mae_ms"]-packed["fl_mae_ms"])>1e-8:
                raise AssertionError("Lossless codec changed model quality")
            pairs.append({"seed":key[0],"profile":key[1],"partition":key[2],"selection":key[3],
                "same_data":True,"codec_quality_unchanged":True,
                "codec_body_reduction_fraction":1-packed["fl_json_bytes"]/legacy["fl_json_bytes"],
                "trend_mae_reduction_fraction":1-trend["fl_mae_ms"]/legacy["fl_mae_ms"],
                "inclusive_body_reduction_fraction":1-trend["fl_json_bytes"]/legacy["fl_json_bytes"],
                "legacy_run":legacy["id"],"packed_run":packed["id"],"trend_run":trend["id"]})
    write_json(directory/"paired-upgrades.json",pairs)
    from .report import build_report
    return build_report(directory)


def main():
    from .benchmark import main as run
    run()

if __name__=='__main__':main()
