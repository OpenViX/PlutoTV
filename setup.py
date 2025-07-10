from setuptools import setup
import setup_translate

pkg = 'Extensions.PlutoTV'
setup(
    name='enigma2-plugin-extensions-plutotv',
    version='1.0',
    author='OpenSPA',
    description='IPTV VoD player,
    package_dir={pkg: 'src'},
    packages=[pkg],
    package_data={pkg: ['*.png', '*.xml', 'locale/*/LC_MESSAGES/*.mo']},
    cmdclass=setup_translate.cmdclass,  # for translation
)
