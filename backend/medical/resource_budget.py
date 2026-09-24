"""Small dependency-free memory probe for bounded offline jobs."""
import ctypes
import os


class MemoryBudgetError(RuntimeError):
    """The job can be resumed when enough RAM becomes available."""


def memory_status() -> dict:
    if os.name == "nt":
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]

        class ProcessMemory(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        process = ProcessMemory()
        process.cb = ctypes.sizeof(process)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(process), process.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return {"total_mib": round(status.total / 2**20, 1), "available_mib": round(status.available / 2**20, 1),
                "process_working_mib": round(process.working / 2**20, 1), "process_peak_mib": round(process.peak / 2**20, 1)}
    from pathlib import Path
    info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {"total_mib": int(info["MemTotal"].split()[0]) / 1024,
            "available_mib": int(info["MemAvailable"].split()[0]) / 1024}


def require_available(minimum_mib: int) -> dict:
    status = memory_status()
    if status["available_mib"] < minimum_mib:
        raise MemoryBudgetError(f"memory budget: available {status['available_mib']} MiB; requires {minimum_mib} MiB")
    return status
