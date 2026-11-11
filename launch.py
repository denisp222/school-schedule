import sys
import site
from pathlib import Path

# The desktop shortcut uses the installed, signed Python executable. Keep the
# project's dependencies without executing the development-folder redirector.
if not getattr(sys,'frozen',False):
    candidates=[Path(__file__).resolve().parent/'.venv'/'Lib'/'site-packages',
                Path(sys.executable).resolve().parent.parent/'Lib'/'site-packages',
                *map(Path,site.getsitepackages())]
    for packages in dict.fromkeys(candidates):
        if packages.is_dir():site.addsitedir(str(packages))

from desktop import run

if __name__ == '__main__':
    import sys
    if len(sys.argv)==2 and sys.argv[1]=='--check-webview':
        from app.distribution import webview_available
        sys.exit(0 if webview_available() else 2)
    elif len(sys.argv)==4 and sys.argv[1]=='--solver-worker':
        from app.solver_process import worker
        worker(sys.argv[2],sys.argv[3])
    else:
        run()
