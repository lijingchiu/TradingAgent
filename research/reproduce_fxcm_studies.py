"""Replay immutable pre-final FXCM studies into a separate output directory.

Original receipts and parameters stay intact. Raw source caches must already
match their recorded hashes. This command neither downloads data nor opens
final prices. Full ignored quote traces are deterministically regenerated.
"""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT=Path(__file__).resolve().parents[1]
FAMILIES={"patterns":"fxcm_rsi2","tailguard":"fxcm_rsi2_tailguard",
          "cross-asset":"fxcm_rsi2_cross_asset","fixed-session":"fxcm_fixed_session"}


def reproduce(family: str, output: Path):
    module=importlib.import_module("research."+FAMILIES[family])
    canonical=module.OUT
    output=output.resolve()
    if output==canonical or canonical in output.parents or output in canonical.parents:
        raise ValueError("Reproduction output must be separate from canonical receipts")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Reproduction directory must be empty or absent")
    output.mkdir(parents=True,exist_ok=True)
    scratch=ROOT/".reproductions"
    scratch.mkdir(exist_ok=True)
    # The immutable runners record paths relative to ROOT. Stage inside an
    # ignored directory, then export the replay to the requested destination.
    with tempfile.TemporaryDirectory(prefix="fxcm-replay-",dir=scratch) as temp:
        staging=Path(temp)
        (staging/"preregistration.json").write_bytes((canonical/"preregistration.json").read_bytes())
        module.OUT=staging
        try:
            replay=module.study()
        finally:
            shutil.copytree(staging,output,dirs_exist_ok=True)
            module.OUT=canonical
        for row in replay["candidates"]:
            for phase in ("development","validation"):
                key=phase+"_trade_features_path"
                row[key]=str(output/Path(row[key]).name)
        (output/"selection_report.json").write_text(json.dumps(replay,indent=2)+"\n")
    original=json.loads((canonical/"selection_report.json").read_text())
    reference={r["config"].get("operating_name",r["config"]["name"]):r for r in original["candidates"]}
    same=len(reference)==len(replay["candidates"])
    for row in replay["candidates"]:
        name=row["config"].get("operating_name",row["config"]["name"])
        old=reference[name]
        for field in ("config","development","validation","development_statistics","validation_statistics",
                      "selection_eligible","development_local_quote_trace_sha256","validation_local_quote_trace_sha256"):
            same &= row[field]==old[field]
    same &= replay["selected_config"]==original["selected_config"]
    comparison=dict(family=family,candidate_count=len(replay["candidates"]),
                    numeric_results_and_quote_trace_hashes_identical=bool(same),
                    canonical_receipts_preserved=True,final_outcomes_opened=False)
    (output/"reproduction_comparison.json").write_text(json.dumps(comparison,indent=2)+"\n")
    if not same:
        raise RuntimeError("Reproduction differed; preserve outputs and investigate, do not replace original evidence")
    return comparison


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family",choices=FAMILIES)
    parser.add_argument("--out-dir",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(reproduce(args.family,args.out_dir)))


if __name__=="__main__":main()
