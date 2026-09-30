#!/usr/bin/env python3
import argparse, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lib.validation import load_artwork
def main():
    p=argparse.ArgumentParser(); p.add_argument("artwork",type=Path); a=p.parse_args()
    try:
        data=load_artwork(a.artwork)
    except (ValueError,OSError) as error:
        print(f"invalid artwork: {error}",file=sys.stderr)
        return 1
    ids=[x["id"] for x in data["items"]]
    print(f"valid artwork: {len(ids)} item(s) on {data['layer']}"); return 0
if __name__=="__main__": raise SystemExit(main())
