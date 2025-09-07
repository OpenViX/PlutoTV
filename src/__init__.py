#
#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#
#   PlutoTV is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   PlutoTV is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with PlutoTV.  If not, see <http://www.gnu.org/licenses/>.
#

from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from gettext import bindtextdomain, dgettext, gettext

from urllib.parse import parse_qsl, quote_plus, urlparse

PluginLanguageDomain = "PlutoTV"
PluginLanguagePath = "Extensions/PlutoTV/locale"


def localeInit():
	bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	if (translated := dgettext(PluginLanguageDomain, txt)) != txt:
		return translated
	else:
		return gettext(txt)


localeInit()
language.addCallback(localeInit)


def update_qsd(url, qsd):
	parsed = urlparse(url)
	qsd_out = dict(parse_qsl(parsed.query, keep_blank_values=True)) | {f"{quote_plus(k)}": f"{quote_plus(v)}" for k, v in qsd.items()}
	return parsed._replace(query="&".join([f"{k}={v}" for k, v in qsd_out.items()])).geturl()
