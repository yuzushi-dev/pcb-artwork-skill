#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path

def count(pattern, text): return len(re.findall(pattern, text))

def main():
    p=argparse.ArgumentParser(); p.add_argument("board",type=Path); a=p.parse_args()
    t=a.board.read_text(errors="replace")
    print(json.dumps({"file":a.board.name,"footprints":count(r"\(footprint\s",t),"segments":count(r"\(segment\s",t),"vias":count(r"\(via\s",t),"zones":count(r"\(zone\s",t),"gr_poly":count(r"\(gr_poly\s",t),"front_silkscreen_objects":count(r'\(layer "F\.SilkS"\)',t),"back_silkscreen_objects":count(r'\(layer "B\.SilkS"\)',t)},indent=2))
    return 0
if __name__=="__main__": raise SystemExit(main())
