from Tools.Directories import resolveFilename, SCOPE_CONFIG
from os import path


CONFIG_FOLDER = path.join(path.realpath(resolveFilename(SCOPE_CONFIG)), "PlutoTV")
TIMER_FILE = path.join(CONFIG_FOLDER, "Plutotv.timer")
RESUMEPOINTS_FILE = path.join(CONFIG_FOLDER, "resumepoints.pkl")
PLUGIN_FOLDER = path.dirname(path.realpath(__file__))
PLUGIN_ICON = "plutotv.png"
BOUQUET_FILE = "userbouquet.pluto_tv_%s.tv"
BOUQUET_NAME = "Pluto TV (%s)"
NUMBER_OF_LIVETV_BOUQUETS = 5  # maximum number of bouquets
