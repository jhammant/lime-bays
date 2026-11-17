from app import bays


def test_spoken_distance_rounding():
    # Arrange / Act / Assert
    assert bays.spoken_distance(3) == "10 metres"
    assert bays.spoken_distance(84) == "80 metres"
    assert bays.spoken_distance(196) == "200 metres"
    assert bays.spoken_distance(212) == "200 metres"
    assert bays.spoken_distance(238) == "250 metres"
    assert bays.spoken_distance(990) == "1 kilometre"
    assert bays.spoken_distance(1440) == "1.4 kilometres"


def test_compass_points():
    assert bays.compass(bays.bearing_deg(51.5, -0.1, 51.51, -0.1)) == "north"
    assert bays.compass(bays.bearing_deg(51.5, -0.1, 51.5, -0.08)) == "east"
    assert bays.compass(bays.bearing_deg(51.5, -0.1, 51.49, -0.115)) == "south-west"


def test_st_pancras_returns_three_bays_without_coordinates_in_speech():
    r = bays.nearest(51.5308, -0.1238)
    assert r["status"] == "ok" and len(r["bays"]) == 3
    assert len(r["spoken"].splitlines()) == 3
    assert "51." not in r["spoken"] and "camden-" not in r["spoken"]
    assert [b["distance_m"] for b in r["bays"]] == sorted(b["distance_m"] for b in r["bays"])


def test_outside_london_and_no_coverage():
    assert bays.nearest(52.9225, -1.4746)["status"] == "outside_london"
    assert bays.nearest(51.4613, -0.3037)["status"] == "none_nearby"
