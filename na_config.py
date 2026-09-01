"""na_config.py

Configuration values used by NetworkControlPanel.pyt.

Edit NETWORK_DATASET to point at your Network Dataset.
"""

# Path to the Network Dataset (Road_ND)


# Default search tolerance for AddLocations
DEFAULT_SEARCH_TOL = "500 Meters"

# Travel mode defaults (used by Make*AnalysisLayer tools).
# If your network dataset has travel modes, set this to one of their names.
# If it does not, the toolbox will still load, but solving with travel modes will fail
# until you add travel modes or switch to classic impedance-based tools.
DEFAULT_TRAVEL_MODE = "Driving Time"

# Optional: a polygon feature/layer to use as default study area in the UI.
# Leave as None if you don't want a default.
DEFAULT_STUDY_AREA = None
