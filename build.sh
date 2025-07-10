#!/bin/sh
find . -name '*_all.ipk' -delete # remove old ipks from previous use of this script

cd po
./updateallpo-multiOS.sh
cd ..

cd meta

printf -v date '%(%Y%m%d%H%M%S)T' -1 # creates $date
version=$(grep Version ./control/control|cut -d " " -f 2)
package=$(grep Package ./control/control|cut -d " " -f 2)

mkdir -p usr/lib/enigma2/python/Plugins/Extensions/PlutoTV
cp -ra ../src/. ./usr/lib/enigma2/python/Plugins/Extensions/PlutoTV
tar -cvzf data.tar.gz usr

cd control
tar -cvzf control.tar.gz ./control
cd ..
mv ./control/control.tar.gz .

ar -r ../${package}_${version}-r${date}_all.ipk debian-binary control.tar.gz data.tar.gz

rm -fr control.tar.gz data.tar.gz usr
cd ..

rm -rf ./src/locale # clean up after po update

git stash # clean up any changes to the repo
