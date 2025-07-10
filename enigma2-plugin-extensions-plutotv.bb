DESCRIPTION = "IPTV VoD player"
MAINTAINER = "OpenViX"
LICENSE = "GPL-3.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"
HOMEPAGE = "https://github.com/OpenViX"

RDEPENDS:${PN} = "${PYTHON_PN}-multiprocessing ${PYTHON_PN}-requests ${PYTHON_PN}-zoneinfo"

# start: for "oe-alliance-core"
# require conf/python/python3-compileall.inc
# inherit gitpkgv allarch gettext setuptools3-openplugins
# end: for "oe-alliance-core"

# start: for "openpli-oe-core"
inherit gitpkgv allarch gettext setuptools3-openplugins python3-compileall
# end: for "openpli-oe-core"

PV = "1.0+git"
PKGV = "1.0+git${GITPKGV}"

SRCREV = "${AUTOREV}"

SRC_URI = "git://github.com/OpenViX/PlutoTV.git;protocol=https;branch=master"

S = "${WORKDIR}/git"
