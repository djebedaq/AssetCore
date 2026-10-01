"""Windows Job Object: bound worker memory and kill its children on cleanup."""

import ctypes
from ctypes import wintypes


def attach(process) -> object:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class Basic(ctypes.Structure):
        _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
            ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t), ("MaxWorkingSet", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperations", "WriteOperations", "OtherOperations",
                                                      "ReadTransfer", "WriteTransfer", "OtherTransfer")]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Counters", Counters), ("ProcessMemory", ctypes.c_size_t),
            ("JobMemory", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]

    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.Basic.Flags = 0x100 | 0x2000  # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    limits.ProcessMemory = 1024**3
    if (not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle)))):
        if job:
            kernel.CloseHandle(job)
        process.kill()
        process.wait()
        raise RuntimeError("catalog_ingest_resource_limit")

    class Lease:
        def close(self):
            kernel.CloseHandle(job)

    return Lease()
