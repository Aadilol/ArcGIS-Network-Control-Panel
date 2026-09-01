# Service Area Tool Documentation
---
# Inputs

| Parameter                              | Type                      | Required    | What It Does                                                                                                                   | Notes                                       |
|----------------------------------------|---------------------------|-------------|-------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| Network Dataset (from Map)             | Dropdown (GPString)       | Yes         | Selects the network dataset layer already added to the active map (e.g., Road\_ND).                                          | Must be added to map before running tool.   |
| Facilities (Points)                    | Feature Layer (Point)     | Yes         | Defines origin locations for service area calculation.                                                                         | Examples: bus stops, banks, clinics.        |
| Cutoff Type                            | Dropdown                  | Yes         | Determines whether service areas are calculated by time or distance.                                                         | Options: Time (minutes), Distance (meters). |
| Travel Profile (approx)                | Dropdown                  | Conditional | Applies speed conversion for time-based cutoffs.                                                                               | Enabled only when Cutoff Type = Time.       |
| Cutoffs                                | String (; separated)      | Yes         | Defines service area break values.                                                                                             | Example: 5;10;15.                           |
| Output Geodatabase                     | Workspace (.gdb)          | Yes         | Location where all outputs are written.                                                                                        | Required.                                   |
| Output Service Area Polygons Name      | String                    | No          | Name of exported service area polygon feature class.                                                                           | Default: ServiceAreaPolygons.               |
| Census Polygons (optional)             | Feature Layer (Polygon)   | No          | Provides demographic data for accessibility weighting.                                                                         | Required for demographic analysis.          |
| Census ID Field                        | String                    | Conditional | Unique identifier used for grouping (e.g., DGUID).                                                                             | Used in summary & pivot.                    |
| Census Variable to Weight (optional)   | Dropdown (numeric fields) | Conditional | Selects demographic variable to proportionally weight (e.g., population, income).                                            | Enables weighted analysis.                  |
| Output Intersect Feature Class Name    | String                    | No          | Name of service area × census intersection output.                                                                             | Default: MixedLayer.                        |

---

# Outputs

| Output Name               | Type                      | Created When                | Contains                                                                                                                       |
|--------------------------|---------------------------|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| ServiceAreaPolygons      | Polygon Feature Class     | Always                      | Service area geometry with ToBreak field identifying rings.                                                                    |
| MixedLayer               | Polygon Feature Class     | If Census Provided          | Intersection of service areas and census polygons. Includes INT\_A\_M2, Intersect\_Area, and weighted field (if selected).   |
| RingByCensusSummary      | Table                     | If Census Variable Selected | Grouped by DGUID and ToBreak. Contains SUM\_Weighted\_\<Variable>.                                                             |
| MixedLayer\_pivot        | Table                     | If Census Variable Selected | Pivot table with rows = DGUID, columns = service area breaks, values = summed weighted variable. Nulls replaced with 0.      |


# 1. Core Workflow

The tool performs four stages automatically:

1. Network Service Area generation
2. Census polygon intersection
3. Weighted demographic calculation
4. Summary + Pivot table generation

---

# 2. Inputs

## Required

### Network Dataset (from Map)
- User selects a network dataset layer already added to the map.

### Facilities (Points)
- Locations to analyze accessibility from

### Cutoff Type
- Time (minutes, approx)
- Distance (meters)

### Cutoffs
- Example: 5;10;15

### Output Geodatabase

## Optional

### Census Variable to Weight
- (e.g., Total_Popu, Low_Incom, etc.)

---

# 3. What the Tool Does

## Service Area Creation

Creates service area polygons around facilities using:

- Selected network dataset
- Selected travel profile
- Selected cutoffs

## Census Intersection (if census provided)

Intersects service areas with census polygons.

Creates:

### MixedLayer

Adds:

- `INT_A_M2` → intersection area
- `Intersect_Area` → `INT_A_M2 / Census_Area`

## Weighted Demographic Calculation

If a census variable is selected:

Calculates:

```text
Weighted_<Variable> = <Variable> × Intersect_Area
```

This estimates how much of that demographic lies within each ring.

## Summary Statistics

Groups by:

- DGUID
- ToBreak (ring distance/time)

Computes:

```text
SUM_Weighted_<Variable>
```

Output:

```text
RingByCensusSummary
```
