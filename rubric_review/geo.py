"""Project-area coverage check for HEC-RAS models, with a map figure. Runs where the model files are readable.

Needs the optional packages ``geopandas``, ``h5py`` and ``matplotlib`` (``conda install geopandas h5py matplotlib``).
The HDF paths read here follow HEC-RAS 6.x geometry files; if a model stores geometry elsewhere the check reports
what it found instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GeoResult:
    status: str | None
    comment: str
    figure: str | None = None


class LocalGeo:
    def __init__(self, area_shapefile: str | Path, out_dir: str | Path, min_coverage: float = 0.95):
        self.area_shapefile = Path(area_shapefile)
        self.out_dir = Path(out_dir)
        self.min_coverage = min_coverage

    def check_ras(self, project: dict, plan: dict) -> GeoResult:
        import geopandas as gpd
        import h5py
        import numpy as np
        from shapely.geometry import MultiPoint, Polygon
        from shapely.ops import unary_union

        hdf_path = Path(project["dir"]) / f"{project['base']}.{plan['geomFile']}.hdf"
        if not hdf_path.exists():
            return GeoResult(None, f"Geometry HDF not found ({hdf_path.name}); cannot compute model footprint.")

        lines, points, shapes, crs_wkt, found = [], [], [], None, []
        with h5py.File(hdf_path, "r") as hdf:
            raw = hdf.attrs.get("Projection")
            if raw is not None:
                crs_wkt = raw.decode() if isinstance(raw, bytes) else str(raw)
            geometry = hdf.get("Geometry")
            if geometry is None:
                return GeoResult(None, f"{hdf_path.name} has no Geometry group; top-level groups: {list(hdf.keys())}")
            areas = geometry.get("2D Flow Areas")
            if areas is not None:
                for name, grp in areas.items():
                    if isinstance(grp, h5py.Group) and "Perimeter" in grp:
                        shapes.append(Polygon(np.asarray(grp["Perimeter"])[:, :2]))
                        found.append(f"2D area '{name}'")
            for label, key in (("cross sections", "Cross Sections"), ("river centerlines", "River Centerlines")):
                grp = geometry.get(key)
                if grp is not None and "Polyline Points" in grp:
                    pts = np.asarray(grp["Polyline Points"])[:, :2]
                    points.append(pts)
                    lines.append(pts)
                    found.append(label)
            if not (shapes or points):
                return GeoResult(None, f"No readable model extent in {hdf_path.name}; Geometry contains: {list(geometry.keys())}")

        footprint_parts = list(shapes)
        if points:
            footprint_parts.append(MultiPoint(np.vstack(points)).convex_hull)
        footprint = unary_union([p for p in footprint_parts if p.area > 0])

        area = gpd.read_file(self.area_shapefile)
        note = ""
        if crs_wkt:
            area = area.to_crs(crs_wkt) if area.crs else area
        else:
            note = " Model CRS not found in HDF; assumed same CRS as the shapefile."
        area_geom = unary_union(area.geometry)
        coverage = area_geom.intersection(footprint).area / area_geom.area if area_geom.area else 0.0

        figure = self._figure(project["base"], plan["title"], area_geom, footprint, lines)
        status = "Y" if coverage >= self.min_coverage else "N"
        comment = (f"{coverage:.0%} of the project area ({self.area_shapefile.name}) lies inside the model footprint "
                   f"[{', '.join(found)}]; threshold {self.min_coverage:.0%}.{note}")
        return GeoResult(status, comment, str(figure))

    def _figure(self, base: str, plan_title: str, area_geom, footprint, lines) -> Path:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 7))
        for geom, kw in ((footprint, {"fc": "#cfe2f3", "ec": "#1f5f99", "label": "Model footprint"}),
                         (area_geom, {"fc": "none", "ec": "#c0392b", "lw": 2, "label": "Project area (Grant Agreement)"})):
            for part in getattr(geom, "geoms", [geom]):
                if part.geom_type == "Polygon":
                    ax.fill(*part.exterior.xy, **kw)
                    kw = {k: v for k, v in kw.items() if k != "label"}
        for pts in lines:
            ax.plot(pts[:, 0], pts[:, 1], color="#555", lw=0.4)
        ax.set_aspect("equal")
        ax.set_title(f"{base} — {plan_title}")
        ax.legend(loc="best")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"area-{re.sub(r'[^A-Za-z0-9]+', '_', base + '_' + plan_title)}.png"
        fig.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return path
