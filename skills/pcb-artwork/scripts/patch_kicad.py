#!/usr/bin/env python3
import argparse,json
from pathlib import Path
BEGIN="; PCB-ARTWORK-SKILL BEGIN";END="; PCB-ARTWORK-SKILL END"
def poly(points,layer):
    pts=" ".join(f"(xy {x:.6f} {y:.6f})" for x,y in points)
    return f'  (gr_poly (pts {pts}) (stroke (width 0) (type solid)) (fill solid) (layer "{layer}"))'
def block(data):
    out=[]
    for item in data["items"]:
        if item["type"]!="polygon":raise ValueError(f"patcher accepts compiled polygons only: {item['id']} is {item['type']}")
        out.append(poly(item["points"],data["layer"]))
    return "\n".join([BEGIN,*out,END])
def strip(text):
    s=text.find(BEGIN)
    if s<0:return text
    e=text.find(END,s)
    if e<0:raise ValueError("found generated block start without end marker")
    return text[:s]+text[e+len(END):]
def main():
    p=argparse.ArgumentParser();p.add_argument("--board",required=True,type=Path);p.add_argument("--artwork",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    data=json.loads(a.artwork.read_text());board=strip(a.board.read_text());i=board.rfind(")")
    if i<0:raise ValueError("not a KiCad S-expression")
    a.output.write_text(board[:i].rstrip()+"\n"+block(data)+"\n"+board[i:]);print(f"wrote {a.output}");return 0
if __name__=="__main__":raise SystemExit(main())
