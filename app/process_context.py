"""Distinguish a normal desktop launch from a restricted test process."""
import sys


def restricted_process():
    if sys.platform!='win32':return False
    import win32api,win32con,win32security
    token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try:
        sid=win32security.GetTokenInformation(token,win32security.TokenIntegrityLevel)[0]
        integrity=int(win32security.ConvertSidToStringSid(sid).split('-')[-1])
        return bool(win32security.IsTokenRestricted(token) or integrity<8192)
    finally:token.Close()


def thread_restricted():
    if sys.platform!='win32':return False
    import win32api,win32con,win32security,pywintypes
    try:token=win32security.OpenThreadToken(win32api.GetCurrentThread(),win32con.TOKEN_QUERY,True)
    except pywintypes.error as exc:
        if exc.winerror==1008:return False
        raise
    try:return bool(win32security.IsTokenRestricted(token))
    finally:token.Close()
