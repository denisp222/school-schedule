"""Choose a private engine; never install or modify a display driver."""
import ctypes
import os


def cuda_available():
    if os.name!='nt':return False
    try:
        cuda=ctypes.WinDLL('nvcuda.dll')
        version=ctypes.c_int();count=ctypes.c_int()
        if cuda.cuDriverGetVersion(ctypes.byref(version)) or version.value<12040:return False
        if cuda.cuInit(0) or cuda.cuDeviceGetCount(ctypes.byref(count)) or count.value<1:return False
        memory=ctypes.c_size_t()
        cuda.cuDeviceTotalMem_v2.argtypes=[ctypes.POINTER(ctypes.c_size_t),ctypes.c_int]
        return cuda.cuDeviceTotalMem_v2(ctypes.byref(memory),0)==0 and memory.value>=2*1024**3
    except (OSError,AttributeError):return False


def available_engines(resources):
    result=[]
    gpu=resources/'bin-cuda/whisper-cli.exe'
    if gpu.is_file() and cuda_available():result.append((gpu,True))
    for folder in ('bin-blas','bin'):
        path=resources/folder/'whisper-cli.exe'
        if path.is_file():result.append((path,False))
    return result
