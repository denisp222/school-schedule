"""Download official Windows build prerequisites, without any school assets."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

import httpx

ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'build/vendor'


def fetch(client,url,path,sha512=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and (not sha512 or hashlib.sha512(path.read_bytes()).hexdigest()==sha512):return
    temporary=path.with_suffix(path.suffix+'.part')
    with client.stream('GET',url) as response:
        response.raise_for_status()
        with temporary.open('wb') as stream:
            for chunk in response.iter_bytes(1024*1024):stream.write(chunk)
    if sha512 and hashlib.sha512(temporary.read_bytes()).hexdigest()!=sha512:
        temporary.unlink();raise ValueError('Official package checksum mismatch.')
    temporary.replace(path)


def extract(archive,target):
    target=target.resolve()
    with ZipFile(archive) as package:
        for row in package.infolist():
            if not (target/row.filename).resolve().is_relative_to(target):raise ValueError('Unsafe archive entry')
        package.extractall(target)


def main():
    VENDOR.mkdir(parents=True,exist_ok=True)
    (VENDOR/'temp').mkdir(exist_ok=True)
    with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(120,connect=15),trust_env=False) as client:
        view_version='1.0.3856.49'
        view_url=f'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{view_version}/microsoft.web.webview2.{view_version}.nupkg'
        view=VENDOR/'webview2.nupkg'
        # NuGet catalog packageHash, pinned together with the exact package version.
        view_hash='ddbf23b637f0da274ddc10aeafdd26f05575cb985697c55adcad087c0adc0b34000f7e5df0b153b4cdf7c137808a75bf0d907f2469e82e0e2f6d7db6a117d4fb'
        fetch(client,view_url,view,view_hash)
        destination=ROOT/'assets/webview';destination.mkdir(parents=True,exist_ok=True)
        with ZipFile(view) as package:
            for source,name in [('lib_manual/netcoreapp3.0/Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Core.dll'),
                                ('lib_manual/netcoreapp3.0/Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.WinForms.dll'),
                                ('build/native/x64/WebView2Loader.dll','WebView2Loader.dll'),('LICENSE.txt','LICENSE.txt')]:
                (destination/name).write_bytes(package.read(source))
        compiler=VENDOR/'innosetup-7.1.1-x64.exe'
        fetch(client,'https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe',compiler)
        # Validate downloaded executables with Windows Authenticode before running them.
        bootstrap=VENDOR/'MicrosoftEdgeWebView2Setup.exe'
        fetch(client,'https://go.microsoft.com/fwlink/p/?LinkId=2124703',bootstrap)
        for path,publisher in [(compiler,'Pyrsys B.V.'),(bootstrap,'Microsoft Corporation')]:
            command="$env:PSModulePath=$env:SystemRoot+'\\System32\\WindowsPowerShell\\v1.0\\Modules'; $ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath '"+str(path).replace("'","''")+"'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*"+publisher+"*') { throw 'Invalid official installer signature' }"
            subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],check=True)
        inno=VENDOR/'inno-portable'
        if not (inno/'ISCC.exe').exists():
            subprocess.run([str(compiler),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                            '/CURRENTUSER','/DIR='+str(inno)],check=True)
        metadata=client.get('https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json')
        metadata.raise_for_status()
        release=next(r for r in metadata.json()['releases'] if r['release-version']=='10.0.14')
        runtime=VENDOR/'dotnet-10.0.14'
        for kind,prefix in [('runtime','dotnet-runtime-'),('windowsdesktop','windowsdesktop-runtime-')]:
            row=next(p for p in release[kind]['files'] if p.get('rid')=='win-x64' and p['name'].startswith(prefix) and p['name'].endswith('.zip'))
            archive=VENDOR/(kind+'-10.0.14-win-x64.zip')
            fetch(client,row['url'],archive,row['hash']);extract(archive,runtime)
        (VENDOR/'distribution.json').write_text(json.dumps({'dotnetVersion':'10.0.14',
            'dotnetRoot':str(runtime),'compiler':str(compiler),'webviewBootstrap':str(bootstrap)}),encoding='utf-8')
    print('Public build prerequisites ready; no school files required.')


if __name__=='__main__':main()
