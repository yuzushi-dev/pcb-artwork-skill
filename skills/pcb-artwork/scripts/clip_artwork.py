#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from shapely.geometry import LineString, Polygon, box

def item_geometry(item):
    if item["type"]=="polygon": return Polygon(item["points"])
    if item["type"]=="polyline": return LineString(item["points"]).buffer(item["width_mm"]/2,cap_style=2,join_style=2)
    if item["type"]=="rect":
        x1,y1,x2,y2=item["region"]; return box(min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2))
    raise ValueError(f'{item["type"]} must be expanded before clipping')

def polygons(g):
    if g.is_empty:return []
    if g.geom_type=="Polygon":return [g]
    if g.geom_type=="MultiPolygon":return list(g.geoms)
    return []

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--board",required=True,type=Path);p.add_argument("--artwork",required=True,type=Path);p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(); data=json.loads(a.artwork.read_text()); a.board.read_text(errors="replace")
    clearance=float(data.get("clearance_mm",0.16)); out=[]
    for item in data["items"]:
        if item["type"]=="hatching":out.append(item);continue
        ps=polygons(item_geometry(item))
        for i,poly in enumerate(ps):
            out.append({"id":item["id"] if i==0 else f'{item["id"]}-{i+1}',"type":"polygon","points":[[round(x,6),round(y,6)] for x,y in list(poly.exterior.coords)[:-1]]})
    result=dict(data);result["items"]=out;result["meta"]={"source_board":a.board.name,"clearance_mm":clearance,"keepout_parser":"not-yet-implemented"}
    a.output.write_text(json.dumps(result,indent=2)+"\n");print(f"wrote {len(out)} item(s) to {a.output}");return 0
if __name__=="__main__":raise SystemExit(main())
