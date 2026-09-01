# -*- coding: utf-8 -*-
import arcpy
import os

# -------------------------
# Minimal helpers (self-contained)
# -------------------------
DEFAULT_SEARCH_TOL = "500 Meters"
DEFAULT_STUDY_AREA = None  # optionally set a default study area layer path/name

# Network cost attribute (your network uses Length in meters)
IMPEDANCE = "Length"

# Fixed census area field (requested)
CENSUS_AREA_FIELD = "Census_Area"

def msg(s: str):
    try:
        arcpy.AddMessage(str(s))
    except Exception:
        pass

def safe_name(name: str) -> str:
    if not name:
        return "Output"
    keep = []
    for ch in name:
        keep.append(ch if (ch.isalnum() or ch == "_") else "_")
    out = "".join(keep)
    if out and out[0].isdigit():
        out = "n_" + out
    return out[:120]

def normalize_out_gdb(val: str) -> str:
    """Return the containing *.gdb even if user picked something inside the gdb."""
    if not val:
        raise arcpy.ExecuteError("Output Geodatabase is required.")
    try:
        d = arcpy.Describe(val)
        cp = getattr(d, "catalogPath", val)
    except Exception:
        cp = val

    p = cp
    while p and (not p.lower().endswith(".gdb")):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent

    if (not p) or (not p.lower().endswith(".gdb")) or (not arcpy.Exists(p)):
        raise arcpy.ExecuteError("Pick an existing file geodatabase (*.gdb) for Output Geodatabase.")
    return p

def ensure_area_field(poly_fc: str, area_field=CENSUS_AREA_FIELD):
    """Adds/updates a geodesic area field in m^2 (always named Census_Area)."""
    existing = [f.name.upper() for f in arcpy.ListFields(poly_fc)]
    if area_field.upper() not in existing:
        arcpy.management.AddField(poly_fc, area_field, "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(
        poly_fc, [[area_field, "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
    )

def project_to_network_sr(in_fc: str, out_gdb: str, out_name: str, network_dataset: str) -> str:
    """Copy or project features to the network dataset spatial reference."""
    out_fc = os.path.join(out_gdb, safe_name(out_name))
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    sr_net = arcpy.Describe(network_dataset).spatialReference
    sr_in = arcpy.Describe(in_fc).spatialReference
    if sr_in and sr_net and getattr(sr_in, "factoryCode", None) == getattr(sr_net, "factoryCode", None):
        arcpy.management.CopyFeatures(in_fc, out_fc)
    else:
        arcpy.management.Project(in_fc, out_fc, sr_net)
    return out_fc

def filter_points_inside(points_fc: str, polygon_fc: str, out_gdb: str, out_name: str) -> str:
    out_fc = os.path.join(out_gdb, safe_name(out_name))
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    lyr = "pts_lyr_tmp"
    arcpy.management.MakeFeatureLayer(points_fc, lyr)
    arcpy.management.SelectLayerByLocation(lyr, "INTERSECT", polygon_fc)
    arcpy.management.CopyFeatures(lyr, out_fc)
    arcpy.management.Delete(lyr)
    return out_fc

def list_numeric_fields(fc: str):
    numeric_types = ("Integer", "SmallInteger", "Double", "Single")
    return [f.name for f in arcpy.ListFields(fc) if f.type in numeric_types]

# -------------------------
# Toolbox
# -------------------------
class Toolbox(object):
    def __init__(self):
        self.label = "Network Analysis Control Panel"
        self.alias = "na_control_panel"
        self.tools = [ServiceAreaTool, JoinCustomStatTool]

# -------------------------
# Tool 1: Service Area + MixedLayer + Stats + Pivot
# -------------------------
class ServiceAreaTool(object):
    def __init__(self):
        self.label = "Service Area Tool"
        self.description = "Run a Service Area and optionally compute weighted census overlay, stats, and pivot."
        self.canRunInBackground = False
        self._nd_sources = {}

    def getParameterInfo(self):
        # Network dataset from CURRENT map (dropdown)
        p_nd = arcpy.Parameter(
            displayName="Network Dataset (from Map)",
            name="network_dataset",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_nd.filter.type = "ValueList"
        p_nd.filter.list = []

        # Facilities
        p_fac = arcpy.Parameter(
            displayName="Facilities (Points)",
            name="facilities",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        # Cutoff configuration
        p_cutoff_type = arcpy.Parameter(
            displayName="Cutoff Type",
            name="cutoff_type",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_cutoff_type.filter.type = "ValueList"
        p_cutoff_type.filter.list = ["Time (minutes, approx)", "Distance (meters)"]
        p_cutoff_type.value = "Time (minutes, approx)"

        p_profile = arcpy.Parameter(
            displayName="Travel Profile (approx)",
            name="travel_profile",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_profile.filter.type = "ValueList"
        p_profile.filter.list = ["Driving (approx)", "Walking (approx)"]
        p_profile.value = "Driving (approx)"

        p_breaks = arcpy.Parameter(
            displayName="Cutoffs (use ';' separator) — minutes or meters",
            name="breaks",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_breaks.value = "5;10;15"

        # Output
        p_outgdb = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="out_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        p_out_sa = arcpy.Parameter(
            displayName="Output Service Area Polygons Name",
            name="out_sa",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_out_sa.value = "ServiceAreaPolygons"

        # Optional census overlay
        p_census = arcpy.Parameter(
            displayName="Census Polygons (optional)",
            name="census_polys",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )

        p_census_id_field = arcpy.Parameter(
            displayName="Census ID Field",
            name="census_id_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_census_id_field.value = "DGUID"

        p_census_value_field = arcpy.Parameter(
            displayName="Census Variable to Weight (optional)",
            name="census_value_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_census_value_field.filter.type = "ValueList"
        p_census_value_field.filter.list = []
        p_census_value_field.value = ""

        p_mixed_name = arcpy.Parameter(
            displayName="Output Intersect Feature Class Name",
            name="mixed_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_mixed_name.value = "MixedLayer"

        # NEW: names for stats + pivot outputs (so pivot is part of output)
        p_stats_name = arcpy.Parameter(
            displayName="Ring-by-Census Summary Table Name",
            name="stats_table_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_stats_name.value = "RingByCensusSummary"

        p_pivot_name = arcpy.Parameter(
            displayName="Pivot Output Table Name",
            name="pivot_table_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_pivot_name.value = "MixedLayer_pivot"

        return [
            p_nd,
            p_fac,
            p_cutoff_type, p_profile, p_breaks,
            p_outgdb, p_out_sa,
            p_census, p_census_id_field, p_census_value_field,
            p_mixed_name, p_stats_name, p_pivot_name
        ]

    def updateParameters(self, params):
        idx = {p.name: i for i, p in enumerate(params)}

        # enable/disable profile depending on cutoff type
        cutoff_type = params[idx["cutoff_type"]].valueAsText or "Time (minutes, approx)"
        params[idx["travel_profile"]].enabled = cutoff_type.startswith("Time")

        # Populate network dataset dropdown from CURRENT map
        nd_items = []
        nd_sources = {}
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            m = aprx.activeMap
            if m:
                for lyr in m.listLayers():
                    if getattr(lyr, "isGroupLayer", False):
                        continue
                    if not lyr.supports("DATASOURCE"):
                        continue
                    try:
                        ds = lyr.dataSource
                        d = arcpy.Describe(ds)
                        dt = (getattr(d, "dataType", "") or "").lower()
                        if dt in ("networkdataset", "networkdatasetlayer"):
                            key = getattr(lyr, "longName", None) or lyr.name
                            nd_items.append(key)
                            nd_sources[key] = ds
                    except Exception:
                        pass
        except Exception:
            pass

        nd_items = sorted(set(nd_items))
        self._nd_sources = nd_sources

        params[idx["network_dataset"]].filter.type = "ValueList"
        params[idx["network_dataset"]].filter.list = nd_items
        cur = params[idx["network_dataset"]].valueAsText
        if (not cur) or (cur not in nd_items):
            params[idx["network_dataset"]].value = nd_items[0] if nd_items else ""

        # Census: enable/disable related params
        census_fc = params[idx["census_polys"]].valueAsText
        has_census = bool(census_fc)

        for nm in ("census_id_field", "census_value_field", "mixed_name", "stats_table_name", "pivot_table_name"):
            params[idx[nm]].enabled = has_census

        # Populate census variable dropdown from numeric fields (exclude Census_Area)
        if has_census:
            try:
                fields = list_numeric_fields(census_fc)
                fields = [f for f in fields if f.lower() != CENSUS_AREA_FIELD.lower()]
                fields = sorted(fields)
                params[idx["census_value_field"]].filter.list = fields
                curv = params[idx["census_value_field"]].valueAsText
                if (not curv) or (curv not in fields):
                    preferred = ["Total_Popu", "Low_Incom", "Total_Hous", "Total_Fami", "Total_Families"]
                    pick = next((f for f in preferred if f in fields), None)
                    params[idx["census_value_field"]].value = pick if pick else (fields[0] if fields else "")
            except Exception:
                params[idx["census_value_field"]].filter.list = []
        else:
            params[idx["census_value_field"]].filter.list = []
            params[idx["census_value_field"]].value = ""

        return

    def execute(self, params, messages):
        idx = {p.name: i for i, p in enumerate(params)}

        nd_key = params[idx["network_dataset"]].valueAsText
        if not nd_key:
            raise arcpy.ExecuteError(
                "No Network Dataset found in the current map. "
                "Add the network dataset (e.g., Road_ND) to the map first."
            )
        network_dataset = self._nd_sources.get(nd_key, nd_key)
        if not arcpy.Exists(network_dataset):
            raise arcpy.ExecuteError(f"Selected Network Dataset does not exist: {network_dataset}")

        facilities = params[idx["facilities"]].valueAsText
        cutoff_type = params[idx["cutoff_type"]].valueAsText or "Time (minutes, approx)"
        profile = params[idx["travel_profile"]].valueAsText or "Driving (approx)"
        breaks_str = params[idx["breaks"]].valueAsText or "5;10;15"

        out_gdb = normalize_out_gdb(params[idx["out_gdb"]].valueAsText)
        out_sa_name = safe_name(params[idx["out_sa"]].valueAsText or "ServiceAreaPolygons")

        census_fc = params[idx["census_polys"]].valueAsText
        census_id_field = (params[idx["census_id_field"]].valueAsText or "DGUID").strip()
        census_value_field = (params[idx["census_value_field"]].valueAsText or "").strip()
        mixed_name = safe_name(params[idx["mixed_name"]].valueAsText or "MixedLayer")
        stats_table_name = safe_name(params[idx["stats_table_name"]].valueAsText or "RingByCensusSummary")
        pivot_table_name = safe_name(params[idx["pivot_table_name"]].valueAsText or "MixedLayer_pivot")

        msg(f"Network dataset: {network_dataset}")
        msg(f"Impedance: {IMPEDANCE} (meters)")
        msg(f"Census area field (fixed): {CENSUS_AREA_FIELD}")

        # Parse breaks -> meters
        vals = [float(v.strip()) for v in breaks_str.split(";") if v.strip()]
        if not vals:
            raise arcpy.ExecuteError("Provide cutoffs like 5;10;15 or 500;1000;1500")

        if cutoff_type.startswith("Time"):
            speed_kmh = 40.0 if profile.startswith("Driving") else 5.0
            km_per_min = speed_kmh / 60.0
            meters = [int(round(m * km_per_min * 1000.0)) for m in vals]
        else:
            meters = [int(round(m)) for m in vals]

        meters = sorted(set([m for m in meters if m > 0]))
        break_vals = " ".join(map(str, meters))
        msg(f"Breaks used (meters): {break_vals}")

        # Prepare facilities in output gdb and network SR
        fac_clean = project_to_network_sr(facilities, out_gdb, "Facilities_clean", network_dataset)

        # Create Service Area layer
        msg("Creating Service Area layer...")
        sa_layer = arcpy.na.MakeServiceAreaLayer(
            network_dataset,
            "SA_Layer",
            IMPEDANCE,
            "TRAVEL_FROM",
            break_vals,
            "DETAILED_POLYS",
            "MERGE",
            "RINGS",
            "NO_LINES"
        ).getOutput(0)

        arcpy.na.AddLocations(sa_layer, "Facilities", fac_clean, search_tolerance=DEFAULT_SEARCH_TOL, append="CLEAR")
        msg("Solving Service Area...")
        arcpy.na.Solve(sa_layer)

        # Export polygons
        classes = arcpy.na.GetNAClassNames(sa_layer)
        polys_sub = classes.get("SAPolygons") or classes.get("Polygons")
        out_sa_fc = os.path.join(out_gdb, out_sa_name)
        if arcpy.Exists(out_sa_fc):
            arcpy.management.Delete(out_sa_fc)
        msg(f"Exporting Service Area polygons -> {out_sa_fc}")
        arcpy.management.CopyFeatures(f"{sa_layer}\\{polys_sub}", out_sa_fc)

        # Optional census intersect + weighting + stats + pivot
        if census_fc:
            msg("Preparing census polygons (project to network SR if needed)...")
            census_clean = project_to_network_sr(census_fc, out_gdb, "Census_clean", network_dataset)

            # Ensure Census_Area exists/filled (m²)
            ensure_area_field(census_clean, CENSUS_AREA_FIELD)

            # Intersect
            mixed_fc = os.path.join(out_gdb, mixed_name)
            if arcpy.Exists(mixed_fc):
                arcpy.management.Delete(mixed_fc)
            msg(f"Intersecting Service Area polygons with Census -> {mixed_fc}")
            arcpy.analysis.Intersect([out_sa_fc, census_clean], mixed_fc, "ALL")

            # Intersection area + fraction
            int_area_field = "INT_A_M2"
            if int_area_field.upper() not in [f.name.upper() for f in arcpy.ListFields(mixed_fc)]:
                arcpy.management.AddField(mixed_fc, int_area_field, "DOUBLE")
            arcpy.management.CalculateGeometryAttributes(
                mixed_fc, [[int_area_field, "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
            )

            frac_field = "Intersect_Area"
            if frac_field.upper() not in [f.name.upper() for f in arcpy.ListFields(mixed_fc)]:
                arcpy.management.AddField(mixed_fc, frac_field, "DOUBLE")
            arcpy.management.CalculateField(
                mixed_fc,
                frac_field,
                f"0 if (!{CENSUS_AREA_FIELD}! in (None, 0)) else (!{int_area_field}! / !{CENSUS_AREA_FIELD}!)",
                "PYTHON3"
            )

            if census_value_field:
                weighted_field = safe_name(f"Weighted_{census_value_field}")
                if weighted_field.upper() not in [f.name.upper() for f in arcpy.ListFields(mixed_fc)]:
                    arcpy.management.AddField(mixed_fc, weighted_field, "DOUBLE")
                arcpy.management.CalculateField(
                    mixed_fc,
                    weighted_field,
                    f"0 if (!{census_value_field}! is None) else (!{census_value_field}! * !{frac_field}!)",
                    "PYTHON3"
                )
                msg(f"Computed {weighted_field} on MixedLayer.")

                # Step 1: SummaryStatistics (SUM by DGUID + ToBreak)
                ring_field = "ToBreak"
                stats_table = os.path.join(out_gdb, stats_table_name)
                if arcpy.Exists(stats_table):
                    arcpy.management.Delete(stats_table)
                arcpy.analysis.Statistics(
                    mixed_fc, stats_table, [[weighted_field, "SUM"]],
                    case_field=f"{census_id_field};{ring_field}"
                )

                # Optional alias for ToBreak in stats table
                try:
                    arcpy.management.AlterField(stats_table, ring_field, new_field_alias="Distance:")
                except Exception:
                    pass

                # Step 2: PivotTable (this is now explicitly part of the outputs)
                pivot_table = os.path.join(out_gdb, pivot_table_name)
                if arcpy.Exists(pivot_table):
                    arcpy.management.Delete(pivot_table)

                arcpy.management.PivotTable(
                    stats_table,                 # Input Table (RingByCensusSummary)
                    census_id_field,             # Input Fields (DGUID)
                    ring_field,                  # Pivot Field (ToBreak)
                    f"SUM_{weighted_field}",     # Value Field (SUM_Weighted_*)
                    pivot_table                  # Output Table
                )

                # Step 3: Null -> 0 in pivot numeric fields
                for f in arcpy.ListFields(pivot_table):
                    if f.name.upper() == census_id_field.upper():
                        continue
                    if f.type not in ("Integer", "SmallInteger", "Double", "Single"):
                        continue
                    arcpy.management.CalculateField(
                        pivot_table,
                        f.name,
                        f"0 if (!{f.name}! is None) else !{f.name}!",
                        "PYTHON3"
                    )

                msg(f"Created summary table -> {stats_table}")
                msg(f"Created pivot table -> {pivot_table}")
            else:
                msg("No Census Variable selected; skipping weighted/stat/pivot steps.")
        else:
            msg("No census polygons provided; skipping census overlay.")

        msg("Done.")

# -------------------------
# Tool 2: Join pivot + custom combined statistic
# -------------------------
class JoinCustomStatTool(object):
    def __init__(self):
        self.label = "Join + Custom Statistic"
        self.description = "Join a pivot table back to census polygons (DGUID) and compute combined percent."
        self.canRunInBackground = False

    def getParameterInfo(self):
        p_census = arcpy.Parameter(
            displayName="Census Polygons (Master)",
            name="cs_census",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        p_pivot = arcpy.Parameter(
            displayName="Pivot Table (e.g., MixedLayer_pivot)",
            name="cs_pivot",
            datatype="GPTableView",
            parameterType="Required",
            direction="Input"
        )

        p_break_fields = arcpy.Parameter(
            displayName="Break Columns to Sum (multi-select)",
            name="cs_break_fields",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        p_break_fields.filter.type = "ValueList"
        p_break_fields.filter.list = []

        p_denom = arcpy.Parameter(
            displayName="Denominator Census Field (e.g., Total_Popu)",
            name="cs_denom_field",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        p_denom.filter.type = "ValueList"
        p_denom.filter.list = []

        p_out_field = arcpy.Parameter(
            displayName="Output Field Name (e.g., Pct_0_10)",
            name="cs_out_field",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        p_out_field.value = "Pct_0_10"

        p_out_fc = arcpy.Parameter(
            displayName="Output Census Feature Class Name",
            name="cs_out_fc",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        p_out_fc.value = "Census_Joined"

        p_outgdb = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="cs_out_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )

        return [p_census, p_pivot, p_break_fields, p_denom, p_out_field, p_out_fc, p_outgdb]

    def updateParameters(self, params):
        idx = {p.name: i for i, p in enumerate(params)}

        pivot = params[idx["cs_pivot"]].valueAsText
        if pivot:
            numeric = []
            for f in arcpy.ListFields(pivot):
                if f.name.upper() == "DGUID":
                    continue
                if f.type in ("Integer", "SmallInteger", "Double", "Single"):
                    numeric.append(f.name)
            params[idx["cs_break_fields"]].filter.list = numeric

        census = params[idx["cs_census"]].valueAsText
        if census:
            num = [f.name for f in arcpy.ListFields(census) if f.type in ("Integer", "SmallInteger", "Double", "Single")]
            params[idx["cs_denom_field"]].filter.list = num
            if not params[idx["cs_denom_field"]].valueAsText and num:
                for cand in ("Total_Popu", "Total_Pop", "POP", "Population"):
                    if cand in num:
                        params[idx["cs_denom_field"]].value = cand
                        break
        return

    def execute(self, params, messages):
        idx = {p.name: i for i, p in enumerate(params)}

        census = params[idx["cs_census"]].valueAsText
        pivot = params[idx["cs_pivot"]].valueAsText
        break_fields = params[idx["cs_break_fields"]].valueAsText
        denom_field = params[idx["cs_denom_field"]].valueAsText
        out_field = params[idx["cs_out_field"]].valueAsText
        out_fc_name = params[idx["cs_out_fc"]].valueAsText
        out_gdb = normalize_out_gdb(params[idx["cs_out_gdb"]].valueAsText)

        if not break_fields:
            raise arcpy.ExecuteError("Choose at least one break column to sum.")
        break_list = [b.strip() for b in break_fields.split(";") if b.strip()]

        out_census_fc = os.path.join(out_gdb, safe_name(out_fc_name))
        if arcpy.Exists(out_census_fc):
            arcpy.management.Delete(out_census_fc)
        msg(f"Copying census -> {out_census_fc}")
        arcpy.management.CopyFeatures(census, out_census_fc)

        msg("Joining pivot table to census copy (JoinField on DGUID)...")
        arcpy.management.JoinField(out_census_fc, "DGUID", pivot, "DGUID")

        existing = {f.name.upper() for f in arcpy.ListFields(out_census_fc)}
        if out_field.upper() not in existing:
            arcpy.management.AddField(out_census_fc, out_field, "DOUBLE")

        sum_expr = " + ".join([f"(!{b}! if !{b}! is not None else 0)" for b in break_list])
        expr = (
            f"0 if (!{denom_field}! in (None, 0)) else "
            f"(100.0 * ({sum_expr}) / !{denom_field}!)"
        )

        msg(f"Calculating {out_field} = 100 * sum(selected breaks) / {denom_field}")
        arcpy.management.CalculateField(out_census_fc, out_field, expr, "PYTHON3")

        msg(f"Done -> {out_census_fc}")
