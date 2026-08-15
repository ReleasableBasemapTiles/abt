import json
import sqlite3
from datetime import datetime, timezone

datetime_format = "%Y-%m-%dT%H:%M:%S.%fZ"
production_date = datetime.now(timezone.utc).strftime(datetime_format)

metadata = {
    "name": "Releasable Basemap Tiles (RBT)",
    "version": "2.0.0",
    "production_date": production_date,
    "description": "",
    "attribution": (
        "<a href='https://www.agc.army.mil'>Army Geospatial Center</a> "
        "<a href='https://www.openstreetmap.org/copyright'>© OpenStreetMap contributors</a> "
        "<a href='https://fieldmaps.io'>FieldMaps</a> "
        "<a href='https://www.naturalearthdata.com'>Natural Earth</a> "
        "<a href='https://overturemaps.org'>Overture Maps Foundation</a> "
        "<a href='https://www.usgs.gov'>USGS</a> "
        "<a href='https://www.nga.mil'>National Geospatial-Intelligence Agency</a> "
        "<a href='https://ourairports.com'>OurAirports</a>"
    ),
    "tags": ["Army", "Basemap", "Tiles", "Vector", "Schema", "Geospatial",
             "OpenStreetMap", "FieldMaps", "Natural Earth", "USGS",
             "Overture Maps", "NGA", "OurAirports"],
    "source": "https://www.agc.army.mil/",
    "license": [
        {
            "name": "OpenStreetMap",
            "license": "ODbL 1.0",
            "url": "https://www.openstreetmap.org/copyright"
        },
        {
            "name": "FieldMaps",
            "license": "ODbL 1.0",
            "url": "https://fieldmaps.io/data/"
        },
        {
            "name": "Overture Maps Foundation",
            "license": "ODbL 1.0",
            "url": "https://overturemaps.org/resources/license/"
        },
        {
            "name": "Natural Earth",
            "license": "Public Domain",
            "url": "https://www.naturalearthdata.com/about/terms-of-use/"
        },
        {
            "name": "OurAirports",
            "license": "Public Domain",
            "url": "https://ourairports.com/about.html"
        }
    ],
    "creators": {
        "creators:name": "Team SACI",
        "creators:websites": "https://www.strategicaci.com/ & https://www.twelvelabs.io/ & https://www.axismaps.com/"
    },
    "format": "pbf",
    "bounds": [-179.99999999999997, -60.0, 179.99999999999997, 83.0],
    "center": [-77.0365, 38.8977, 10],
    "type": "baselayer",
}
