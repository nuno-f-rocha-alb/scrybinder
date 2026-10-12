# -*- mode: python ; coding: utf-8 -*-
# Build from the repository root:  pyinstaller packaging/scrybinder.spec --noconfirm
# Optional folders next to this file are bundled when present: tesseract/ (Windows), hf/ (DINOv2 weights, HF cache layout).
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = os.path.dirname(SPECPATH)
datas = [(os.path.join(ROOT, 'ui', 'dist'), 'ui/dist'), (os.path.join(ROOT, 'assets', 'scrybinder.ico'), 'assets')]
for name in ('tesseract', 'hf'):
    if os.path.isdir(os.path.join(SPECPATH, name)):
        datas.append((os.path.join(SPECPATH, name), name))

hiddenimports = ['transformers.models.dinov2.modeling_dinov2', 'transformers.models.dinov2.configuration_dinov2']
hiddenimports += collect_submodules('transformers.models.dinov2')
# transformers checks its dependencies through importlib.metadata: without the .dist-info folders it reports modules as unavailable
for pkg in ('transformers', 'torch', 'tokenizers', 'huggingface_hub', 'safetensors', 'numpy', 'packaging', 'filelock', 'requests', 'tqdm', 'regex', 'pyyaml'):
    try:
        datas += copy_metadata(pkg)
    except Exception:  # noqa: BLE001 — optional package not installed
        pass
hiddenimports += collect_submodules('webview')
hiddenimports += collect_submodules('uvicorn')

a = Analysis(
    [os.path.join(ROOT, 'assets', 'app_entry.py')],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['torchvision'],  # transformers would import it, but its native ops do not load in the bundle and DINOv2 does not need it
)
# PyTorch ships its own test binaries and headers: ~100 MB nobody needs
_junk = ('torch/test/', 'torch/bin/test_', 'torch/include/')
a.datas = [d for d in a.datas if not d[0].replace(os.sep, '/').startswith(_junk)]
a.binaries = [b for b in a.binaries if not b[0].replace(os.sep, '/').startswith(_junk)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Scrybinder',
    console=False,
    icon=[os.path.join(ROOT, 'assets', 'scrybinder.ico')] if sys.platform == 'win32' else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Scrybinder')
