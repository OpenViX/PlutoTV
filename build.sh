#!/bin/sh

#
# To run on windows use MSYS2 or gitbash.
# Some aditional packages may need installing.
# e.g. ar.exe
#

PATTERN="*_all.ipk"
CURRENT=`pwd`
TEMP=$(mktemp -d)

rm -f $CURRENT/$PATTERN # remove old ipk if exists

cp -a $CURRENT/. $TEMP

cd $TEMP

cd po
./updateallpo-multiOS.sh
cd ..

git_revision=`git rev-list HEAD --count`
git_hash=`git rev-parse HEAD`

cd meta

version_orig=`grep Version ./control/control`
# everything before the + sign
version_short=${version_orig%%+*}
version=`echo "$version_short" | cut -d ' ' -f 2`
version_updated="${version}+git${git_revision}+${git_hash:0:8}+${git_hash:0:10}-r0"
version_new="Version: ${version_updated}"
sed -i "s/\b${version_orig}/${version_new}/g" ./control/control

package=$(grep Package ./control/control|cut -d " " -f 2)

mkdir -p usr/lib/enigma2/python/Plugins/Extensions/PlutoTV
cp -ra ../src/. ./usr/lib/enigma2/python/Plugins/Extensions/PlutoTV
tar -cvzf data.tar.gz usr

cd control
tar -cvzf control.tar.gz ./control ./postrm
cd ..
mv ./control/control.tar.gz .

ar -r ../${package}_${version_updated}_all.ipk debian-binary control.tar.gz data.tar.gz

cd $CURRENT

cp $TEMP/$PATTERN $CURRENT

rm -rf $TEMP # clean up
