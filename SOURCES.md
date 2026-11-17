# Data sources

Each bay record carries `borough` and `source`. Raw files live in `data/raw/` and `scripts/build.py` turns
them into `data/bays.sqlite` (rebuilt in the Docker build).

Attribution, shown in the tool description and at `GET /`:

> Contains public sector information licensed under the Open Government Licence v3.0
> (London Borough of Camden; City of London Corporation).

## Used

| Borough | Dataset | Licence | File | Bays |
| --- | --- | --- | --- | --- |
| Camden | "Parking Bays" (`7hiv-3r9k`) on Open Data Camden, rows with `restriction_type = dockless bike hire`: <https://opendata.camden.gov.uk/Transport/Parking-Bays/7hiv-3r9k> | UK Open Government Licence v3 (stated in the portal metadata) | `data/raw/camden.json` | 203 |
| City of London | COMPASS "Driving and Cycling" map service, layers 8 (E-Scooter and Cycle Hire), 29 (Dockless Bike Bays), 21 (Scooters and Cycle Hire Parking Places): <https://www.mapping.cityoflondon.gov.uk/arcgis/rest/services/COMPASS_Driving_and_Cycling/MapServer>. Catalogued on data.gov.uk as "Dockless Bike Bays" and "Parking Places (Scooters & Cycle Hire)": <https://www.data.gov.uk/dataset/dockless-bike-bays> | Open Government Licence v3 (data.gov.uk listing). The CKAN mirror shows "no licence provided"; the data.gov.uk listing is the publisher's statement | `data/raw/city_layer{8,29,21}.geojson` | 106 after merging the three layers (bays within 15 m treated as one; layer 8's suspended bay dropped) |

Fetched 17 Nov 2026. Refresh commands:

```bash
curl -s "https://opendata.camden.gov.uk/resource/7hiv-3r9k.json?restriction_type=dockless%20bike%20hire&\$limit=5000" -o data/raw/camden.json
B=https://www.mapping.cityoflondon.gov.uk/arcgis/rest/services/COMPASS_Driving_and_Cycling/MapServer
for L in 8 29 21; do curl -s "$B/$L/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson" -o data/raw/city_layer$L.geojson; done
python3 -I scripts/build.py
```

Location names come from each dataset's street field (`road_name`, `STREET_NAM`, `LOCATION`, `STREET_NAME`). Every
bay had one; the fallback (name of the nearest named bay, "near X") is in the build script but unused today. City
bays are polygons; the point used is the mean of the polygon's vertices.

## Looked at, not used

- **lime-parking.vercel.app** (`/data/bays.<hash>.json`, 3,552 bays, 15 boroughs). The site states no licence and no
  source for its bay data (only map credits: OpenFreeMap, OpenMapTiles, OpenStreetMap). Ids look like operator
  zone codes (`brent.C1`). Not used: reuse is not clearly permitted.
- **Hackney**: GeoServer layers `transport:lime_dockless_location` (374 active bays) and `_all` at
  <https://map2.hackney.gov.uk/geoserver/ows>. No licence in the service metadata; the only explicit terms found for
  Hackney GeoServer data on data.gov.uk forbid storing, reproducing or merging it. Not used until Hackney confirms OGL.
- **Islington, Westminster, Southwark, Lambeth, Tower Hamlets**: no published dockless bay dataset found on their
  portals, data.gov.uk, the London Datastore or ArcGIS Hub (quick search, 17 Nov 2026).
- **Kensington & Chelsea** "Parking Bay Locations" (OGL) and **Southwark** "Parking bays" (OGL, 2018): general parking
  datasets; not checked for a dockless bay type in this pass.
