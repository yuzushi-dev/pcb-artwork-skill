from shapely.geometry import LineString, Polygon

def test_polyline_buffer_has_area():
    geom = LineString([(0, 0), (10, 0)]).buffer(0.125, cap_style=2)
    assert geom.area > 0

def test_polygon_difference_removes_keepout():
    artwork = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    keepout = Polygon([(4, 4), (6, 4), (6, 6), (4, 6)])
    result = artwork.difference(keepout)
    assert result.area == 96
