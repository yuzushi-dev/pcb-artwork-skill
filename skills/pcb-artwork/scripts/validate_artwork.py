#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/"schemas"/"artwork.schema.json").read_text())
def main():
    p=argparse.ArgumentParser(); p.add_argument("artwork",type=Path); a=p.parse_args()
    data=json.loads(a.artwork.read_text())
    errors=sorted(Draft202012Validator(SCHEMA).iter_errors(data),key=lambda e:list(e.path))
    if errors:
        for e in errors: print(f"{'.'.join(str(x) for x in e.path) or '<root>'}: {e.message}")
        return 1
    ids=[x["id"] for x in data["items"]]
    dup=sorted({x for x in ids if ids.count(x)>1})
    if dup: print("duplicate ids: "+", ".join(dup)); return 1
    print(f"valid artwork: {len(ids)} item(s) on {data['layer']}"); return 0
if __name__=="__main__": raise SystemExit(main())
