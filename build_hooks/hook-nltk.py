# Replaces PyInstaller's stock hook for nltk (used by build_app.py).
#
# The stock hook copies EVERY folder on nltk.data.path into the exe --
# i.e. everything ever downloaded to ~/nltk_data on the build machine
# (all corpora, every language's tokenizer, old formats), tens of MB the
# app never touches. The app only needs the English tokenizer, which
# build_app.py bundles explicitly, plus nltk's own VERSION file.
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("nltk", includes=["VERSION"])
hiddenimports = []
