"""Standalone HTML/CSV report from saved multi-seed experiment artifacts."""
import argparse
import csv
import html
from pathlib import Path
import re
import statistics
from .paths import ROOT, OUTPUT, RUNS
from .storage import read_json, write_json


def table(rows):
    if not rows:
        return "<p>No data</p>"
    columns = list(rows[0])
    def cell(value):
        return html.escape(f"{value:.6g}" if isinstance(value,float) else str(value))
    return "<div class='scroll'><table><thead><tr>" + "".join(f"<th>{cell(k)}</th>" for k in columns) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{cell(row.get(k,''))}</td>" for k in columns) + "</tr>" for row in rows) + "</tbody></table></div>"


def build_report(directory):
    directory=Path(directory)
    runs=read_json(directory/"runs.json")
    aggregates=read_json(directory/"aggregates.json")
    network=[]
    for run in runs:
        if not re.fullmatch(r"[0-9a-f]{32}",str(run.get("artifact_id",run["id"]))):
            raise ValueError("Invalid experiment ID in benchmark")
        result=read_json((OUTPUT/"experiments"/run["artifact_id"] if "artifact_id" in run else RUNS/str(run["id"]))/"result.json")
        for item in result["network"]:
            network.append({"id":run["id"],"seed":run["seed"],"profile":run["profile"],
                            "partition":run["partition"],"selection":run["selection"],
                            "model_family":run.get("model_family",result["config"].get("model_family","residual_mlp")),
                            "transport_codec":run.get("transport_codec",result["config"].get("transport_codec","json")),**item})
    groups={}
    for row in network:
        key=tuple(row[k] for k in ("profile","partition","selection","model_family","transport_codec","route_policy","allocation_policy"))
        groups.setdefault(key,[]).append(row)
    network_aggregates=[]
    for key,values in groups.items():
        row=dict(zip(("profile","partition","selection","model_family","transport_codec","route_policy","allocation_policy"),key))
        row["seeds"]=len(values)
        for field in ("delivery_ratio","mean_completion_s","p95_completion_s","throughput_mbps","fairness_jain","wire_mbit"):
            valid=[r[field] for r in values if r[field] is not None]
            row[field+"_mean"]=statistics.mean(valid) if valid else None
            row[field+"_std"]=statistics.stdev(valid) if len(valid)>1 else 0 if valid else None
        row["capacity_violations"]=sum(r["capacity_violations"] for r in values)
        network_aggregates.append(row)
    write_json(directory/"network-aggregates.json",network_aggregates)
    for name,rows in [("network",network),("network-aggregates",network_aggregates)]:
        with (directory/f"{name}.csv").open("w",newline="",encoding="utf-8-sig") as out:
            writer=csv.DictWriter(out,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    content="""<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SAGSIN benchmark</title>
    <style>body{font:15px/1.6 Segoe UI,Arial,sans-serif;max-width:1400px;padding:30px;margin:auto;color:#172c35;background:#f4f6f8}h1,h2{color:#087e78}.scroll{overflow:auto;margin:20px 0;background:white}table{border-collapse:collapse;white-space:nowrap;font-size:12px}td,th{padding:10px;border:1px solid #d9e2e7;text-align:left}th{background:#eaf5f1}p{max-width:950px}</style>
    <h1>FL và tối ưu mạng SAGSIN</h1><p>Báo cáo dữ liệu tổng hợp. Mean/std theo seed; không so sánh trực tiếp với dataset của dự án cũ. Thời gian hoàn tất chỉ tính flow thành công, phải đọc cùng delivery ratio. Không suy ra ưu thế thống kê từ một mức chênh lệch nhỏ.</p>
    <h2>Chất lượng học và chi phí</h2>"""+table(aggregates)+"<h2>Routing và cấp băng thông</h2>"+table(network_aggregates)+"<h2>Từng lần chạy</h2>"+table(runs)+"<p>Minimax tối ưu trên cửa sổ tĩnh và tuyến cố định. Client/traffic synthetic; không có bảo đảm DP hoặc đo RF thực tế. CSV và JSON đầy đủ nằm cùng thư mục báo cáo.</p></html>"
    (directory/"report.html").write_text(content,encoding="utf-8")
    return directory/"report.html"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_directory",type=Path)
    args=parser.parse_args()
    print(build_report(args.benchmark_directory))


if __name__=="__main__":main()
