DESCRIPTION = "PlutoTV plugin for enigma2"
MAINTAINER = "OpenViX"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://src/LICENSE;md5=c644709e9dad24bd9bf90ac96687ed2f"
HOMEPAGE = "https://github.com/OpenViX"

RDEPENDS:${PN} = "${PYTHON_PN}-requests"

# start: for "oe-alliance-core"
require conf/python/python3-compileall.inc
inherit gitpkgv allarch gettext setuptools3-openplugins
# end: for "oe-alliance-core"

# start: for "openpli-oe-core"
# inherit gitpkgv allarch gettext setuptools3-openplugins python3-compileall
# end: for "openpli-oe-core"

PV = "1.0+git"
PKGV = "1.0+git${GITPKGV}"

SRCREV = "${AUTOREV}"

SRC_URI = "git://github.com/OpenViX/PlutoTV.git;protocol=https;branch=master"

S = "${UNPACKDIR}/git"
