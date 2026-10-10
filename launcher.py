"""Double-click launch: use the isolated runtime and leave the service in background."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:18765'


def health():
    try:
        with urllib.request.urlopen(URL+'/api/v1/health',timeout=1) as r:
            return json.load(r)
    except Exception:
        return None


def main():
    if '--serve' in sys.argv:
        os.chdir(ROOT)
        os.environ['AW_DATA_DIR']=str(ROOT/'data')
        (ROOT/'logs').mkdir(exist_ok=True)
        (ROOT/'logs'/'service.pid').write_text(str(os.getpid()),encoding='ascii')
        import uvicorn
        uvicorn.run('backend.app:app',host='127.0.0.1',port=18765,access_log=False)
        return
    existing=health()
    if existing:
        if Path(existing.get('data_dir','')).resolve() != (ROOT/'data').resolve():
            raise RuntimeError('端口被另一个数据目录的工作台占用，请停止另一个工作台后重试')
        webbrowser.open(URL)
        return
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    python=ROOT/'.venv'/'Scripts'/'python.exe'
    if not python.exists():
        raise RuntimeError('请先运行安装依赖.ps1')
    with (logs/'service.log').open('a',encoding='utf-8') as log:
        proc=subprocess.Popen([str(python),str(ROOT/'launcher.py'),'--serve'],cwd=ROOT,stdout=log,stderr=log,
                              creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
    for _ in range(80):
        if health():
            webbrowser.open(URL)
            return
        if proc.poll() is not None: break
        time.sleep(.25)
    raise RuntimeError('服务启动失败，请查看 logs/service.log')


if __name__=='__main__':
    main()
