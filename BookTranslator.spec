# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['uharfbuzz']
hiddenimports += collect_submodules('google.auth')
hiddenimports += collect_submodules('google.api')
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.genai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['google.cloud', 'google.genai.tests', 'torch', 'torchvision', 'torchaudio', 'tensorflow', 'keras', 'scipy', 'matplotlib', 'sklearn', 'pandas', 'nltk', 'sqlalchemy', 'transformers', 'onnxruntime', 'cv2', 'av', 'librosa', 'soundfile', 'yt_dlp', 'yt_dlp_ejs', 'lightning', 'rich', 'numba', 'pygments', 'jinja2', 'mako', 'grpc', 'translators'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BookTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
