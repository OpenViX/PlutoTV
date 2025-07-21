from Tools.Directories import resolveFilename, SCOPE_CONFIG
from os import listdir, path


def getDataFolder():
	files = listdir("/media/")
	folder = None
	if "hdd" in files:
		folder = "/media/hdd/PlutoTV"
	elif "usb" in files:
		folder = "/media/usb/PlutoTV"
	else:
		for mp in ("hdd", "usb", "sd", "mmc"):  # to control the order
			for filename in files:
				if filename.startswith(mp):
					folder = path.join("/media/", filename, "PlutoTV")
					break
			if folder:
				break

	if not folder:
		folder = "/tmp/PlutoTV"

	return folder


CONFIG_FOLDER = path.join(path.realpath(resolveFilename(SCOPE_CONFIG)), "PlutoTV")
TIMER_FILE = path.join(CONFIG_FOLDER, "Plutotv.timer")
RESUMEPOINTS_FILE = path.join(CONFIG_FOLDER, "resumepoints.pkl")
PLUGIN_FOLDER = path.dirname(path.realpath(__file__))
DATA_FOLDER = getDataFolder()
BOUQUET_FILE = "userbouquet.pluto_tv.tv"
BOUQUET_NAME = "Pluto TV"
