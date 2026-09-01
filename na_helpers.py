"""na_helpers.py

Helper functions used by NetworkControlPanel.pyt.

This module is intentionally lightweight and avoids dependencies.
It assumes it is imported inside ArcGIS Pro's Python environment.
"""

from __future__ import annotations

import os
import re
import arcpy

from na_config import NETWORK_DATASET


# ----------------------------
# Messaging / licensing
# ----------------------------

def msg(text: str) -> None:
    arcpy.AddMessage(str(text))


def warn(text: str) -> None:
    arcpy.AddWarning(str(text))


def require_network_analyst() -> None:
    """Checks out the Network Analyst extension or raises."""
    status = arcpy.CheckExtension("network")
    if status != "Available":
        raise arcpy.ExecuteError("Network Analyst extension is not available.")
    arcpy.CheckOutExtension("network")


# ----------------------------
# Data validation / naming
# ----------------------------

def safe_name(name: str, max_len: int = 80) -> str:
    """Returns a geodatabase-safe feature class/table name."""
    if not name:
        return "Output"
    s = str(name).strip()
    # Replace spaces with underscore and strip invalid chars
    s = s.replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_]+", "", s)
    s = s.strip("_")
    if not s:
        s = "Output"
    return s[:max_len]


def assert_points(fc_or_layer: str, label: str = "Input") -> None:
    """Raise if the input is not point geometry."""
    shp = (arcpy.Describe(fc_or_layer).shapeType or "").upper()
    if shp != "POINT":
        raise arcpy.ExecuteError(f"{label} must be POINT geometry (got {shp}).")


# ----------------------------
# Spatial reference helpers
# ----------------------------

def network_sr(network_dataset):
    return arcpy.Describe(network_dataset).spatialReference


def copy_and_project_to_network(in_fc, network_dataset, out_gdb, out_name):
    sr_net = network_sr(network_dataset)
    """Copy features into out_gdb and project to network SR if needed.

    Signature matches how your .pyt calls it:
        copy_and_project_to_network(in_points, NETWORK_DATASET, out_gdb, "name")
    """
    out_fc = os.path.join(out_gdb, out_name)
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    sr_net = network_sr(network_dataset)
    sr_in = arcpy.Describe(in_fc).spatialReference

    # If spatial references are missing, just copy.
    if not sr_in or not sr_net or getattr(sr_in, "factoryCode", 0) == 0 or getattr(sr_net, "factoryCode", 0) == 0:
        arcpy.management.CopyFeatures(in_fc, out_fc)
        return out_fc

    if sr_in.factoryCode == sr_net.factoryCode:
        arcpy.management.CopyFeatures(in_fc, out_fc)
    else:
        # Project can fail if output exists or is locked; we already delete.
        arcpy.management.Project(in_fc, out_fc, sr_net)

    return out_fc


# ----------------------------
# Study area filtering
# ----------------------------

def filter_points_inside(points_fc: str,
                         polygon_fc: str,
                         out_gdb: str,
                         out_name: str) -> tuple[str, int, int]:
    """Filter points to those intersecting polygon_fc.

    Returns: (out_points_fc, total_count, inside_count)
    """
    out_fc = os.path.join(out_gdb, out_name)
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    total = int(arcpy.management.GetCount(points_fc)[0])

    lyr = "_tmp_pts_lyr"
    if arcpy.Exists(lyr):
        try:
            arcpy.management.Delete(lyr)
        except Exception:
            pass

    arcpy.management.MakeFeatureLayer(points_fc, lyr)
    arcpy.management.SelectLayerByLocation(lyr, "INTERSECT", polygon_fc)
    inside = int(arcpy.management.GetCount(lyr)[0])

    arcpy.management.CopyFeatures(lyr, out_fc)

    try:
        arcpy.management.Delete(lyr)
    except Exception:
        pass

    return out_fc, total, inside
