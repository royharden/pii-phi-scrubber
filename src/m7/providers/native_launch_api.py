"""Lazy Win32 launch calls. Import/validation performs no native operation.

Only new anonymous jobs/pipes/timers/processes and explicitly duplicated token
handles are owned here. No logon, account discovery, privilege adjustment or shell.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import subprocess
import sys

from .contracts import AdapterFault


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", C.c_void_p), ("bInheritHandle", W.BOOL)]


class STARTUPINFO(C.Structure):
    _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR), ("title", W.LPWSTR),
        ("x", W.DWORD), ("y", W.DWORD), ("xsize", W.DWORD), ("ysize", W.DWORD),
        ("xchars", W.DWORD), ("ychars", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
        ("show", W.WORD), ("reserved_size", W.WORD), ("reserved_bytes", C.c_void_p),
        ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]


class STARTUPINFOEX(C.Structure):
    _fields_ = [("startup", STARTUPINFO), ("attributes", C.c_void_p)]


class PROCESS_INFORMATION(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


class BASIC_LIMITS(C.Structure):
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64), ("flags", W.DWORD),
        ("minimum_working_set", C.c_size_t), ("maximum_working_set", C.c_size_t),
        ("active_processes", W.DWORD), ("affinity", C.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]


class IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class EXTENDED_LIMITS(C.Structure):
    _fields_ = [("basic", BASIC_LIMITS), ("io", IO_COUNTERS), ("process_memory", C.c_size_t),
        ("job_memory", C.c_size_t), ("peak_process_memory", C.c_size_t), ("peak_job_memory", C.c_size_t)]


class Win32LaunchApi:
    def __init__(self):
        if sys.platform != "win32":
            raise AdapterFault("unavailable")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.a = C.WinDLL("advapi32", use_last_error=True)
        P, D, B, H, S = C.c_void_p, W.DWORD, W.BOOL, W.HANDLE, C.c_size_t
        def bind(dll, name, args, result):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result
            return function
        self.close_handle = bind(self.k, "CloseHandle", [H], B)
        self.create_job = bind(self.k, "CreateJobObjectW", [P, W.LPCWSTR], H)
        self.set_job = bind(self.k, "SetInformationJobObject", [H, C.c_int, P, D], B)
        self.kill_job = bind(self.k, "TerminateJobObject", [H, W.UINT], B)
        self.create_pipe = bind(self.k, "CreatePipe", [C.POINTER(H), C.POINTER(H), P, D], B)
        self.set_handle = bind(self.k, "SetHandleInformation", [H, D, D], B)
        self.create_file = bind(self.k, "CreateFileW", [W.LPCWSTR, D, D, P, D, D, H], H)
        self.duplicate_token = bind(self.a, "DuplicateTokenEx", [H, D, P, C.c_int, C.c_int, C.POINTER(H)], B)
        self.initialize_attrs = bind(self.k, "InitializeProcThreadAttributeList", [P, D, D, C.POINTER(S)], B)
        self.update_attrs = bind(self.k, "UpdateProcThreadAttribute", [P, D, S, P, S, P, P], B)
        self.delete_attrs = bind(self.k, "DeleteProcThreadAttributeList", [P], None)
        self.create_process = bind(self.a, "CreateProcessAsUserW", [H, W.LPCWSTR, W.LPWSTR, P, P, B, D,
            P, W.LPCWSTR, P, C.POINTER(PROCESS_INFORMATION)], B)
        self.resume_thread = bind(self.k, "ResumeThread", [H], D)
        self.process_times = bind(self.k, "GetProcessTimes", [H, P, P, P, P], B)
        self.wait_one = bind(self.k, "WaitForSingleObject", [H, D], D)
        self.wait_many = bind(self.k, "WaitForMultipleObjects", [D, C.POINTER(H), B, D], D)
        self.create_timer = bind(self.k, "CreateWaitableTimerW", [P, B, W.LPCWSTR], H)
        self.set_timer = bind(self.k, "SetWaitableTimer", [H, C.POINTER(C.c_int64), W.LONG, P, P, B], B)
        self.read_file = bind(self.k, "ReadFile", [H, P, D, C.POINTER(D), P], B)
        self.write_file = bind(self.k, "WriteFile", [H, P, D, C.POINTER(D), P], B)
        self.current_process = bind(self.k, "GetCurrentProcess", [], H)
        self.duplicate_handle = bind(self.k, "DuplicateHandle", [H, H, H, C.POINTER(H), D, B, D], B)

    @staticmethod
    def require(ok):
        if not ok:
            raise AdapterFault("unavailable")  # No FormatMessage/error/path disclosure.

    def close(self, handle: int):
        self.require(self.close_handle(handle))

    def new_job(self) -> int:
        job = self.create_job(None, None)  # New anonymous job; never OpenJobObject.
        self.require(job)
        limits = EXTENDED_LIMITS()
        limits.basic.flags = 0x00002000 | 0x00000008  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS.
        limits.basic.active_processes = 1
        try:
            self.require(self.set_job(job, 9, C.byref(limits), C.sizeof(limits)))
        except BaseException:
            self.close(job)
            raise
        return job

    def pipe(self, *, parent_reads: bool) -> tuple[int, int]:
        sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), None, True)
        read, write = W.HANDLE(), W.HANDLE()
        self.require(self.create_pipe(C.byref(read), C.byref(write), C.byref(sa), 0))
        parent, child = (read.value, write.value) if parent_reads else (write.value, read.value)
        try:
            self.require(self.set_handle(parent, 1, 0))  # Parent end never inherited.
        except BaseException:
            for handle in (parent, child):
                try:
                    self.close(handle)
                except BaseException:
                    pass
            raise
        return parent, child

    def null_output(self) -> int:
        sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), None, True)
        handle = self.create_file("NUL", 0x40000000, 3, C.byref(sa), 3, 0x80, None)
        self.require(handle and handle != C.c_void_p(-1).value)
        return handle

    def primary_token(self, borrowed: int) -> int:
        result = W.HANDLE()
        # Explicit borrowed approved token only; no lookup/logon/adjustment. New
        # duplicate is non-inheritable, primary, and has only launch/query rights.
        self.require(self.duplicate_token(borrowed, 0x0001 | 0x0002 | 0x0008, None, 2, 1, C.byref(result)))
        return result.value

    def suspended(self, token: int, spec, job: int, stdin: int, stdout: int, stderr: int):
        sa_handles = (W.HANDLE * 3)(stdin, stdout, stderr)
        job_list = (W.HANDLE * 1)(job)
        child_policy = W.DWORD(1)  # PROCESS_CREATION_CHILD_PROCESS_RESTRICTED.
        size = C.c_size_t()
        self.initialize_attrs(None, 3, 0, C.byref(size))
        self.require(0 < size.value <= 65536)
        attrs = C.create_string_buffer(size.value)
        self.require(self.initialize_attrs(attrs, 3, 0, C.byref(size)))
        try:
            # Explicit inherit list, job assignment AT CREATION, no descendants.
            for key, value in ((0x00020002, sa_handles), (0x0002000D, job_list), (0x0002000E, child_policy)):
                self.require(self.update_attrs(attrs, 0, key, C.byref(value), C.sizeof(value), None, None))
            startup = STARTUPINFOEX()
            startup.startup.cb = C.sizeof(STARTUPINFOEX)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES.
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdin, stdout, stderr
            startup.attributes = C.cast(attrs, C.c_void_p)
            command = subprocess.list2cmdline(spec.argv)  # Quoting only; never subprocess execution.
            self.require(len(command.encode("utf-16-le")) // 2 < 32767)
            self.require(all("\0" not in key + value for key, value in spec.environment.items()))
            environment = C.create_unicode_buffer("\0".join(
                key + "=" + value for key, value in sorted(spec.environment.items(), key=lambda item: item[0].casefold())) + "\0\0")
            process = PROCESS_INFORMATION()
            flags = 0x00000004 | 0x00000400 | 0x00080000 | 0x08000000
            self.require(self.create_process(token, spec.argv[0], C.create_unicode_buffer(command), None, None,
                True, flags, environment, spec.cwd, C.byref(startup), C.byref(process)))
            return process
        finally:
            self.delete_attrs(attrs)

    def start_identity(self, process: int) -> str:
        values = [C.c_uint64() for _ in range(4)]
        self.require(self.process_times(process, *(C.byref(value) for value in values)))
        return str(values[0].value)  # Actual creation FILETIME, not a guessed nonce.

    def new_timer(self, seconds: float) -> int:
        timer = self.create_timer(None, True, None)  # New unnamed, non-inheritable.
        self.require(timer)
        try:
            self.arm_timer(timer, seconds)
        except BaseException:
            self.close(timer)
            raise
        return timer

    def arm_timer(self, timer: int, seconds: float):
        self.require(0 < seconds <= 21600)
        due = C.c_int64(-max(1, int(seconds * 10000000)))
        self.require(self.set_timer(timer, C.byref(due), 0, None, None, False))

    def wait_process(self, process: int, timeout: float):
        self.require(0 <= timeout <= 21600)
        self.require(self.wait_one(process, min(0xFFFFFFFE, max(0, int(timeout * 1000)))) == 0)

    def wait_lifetime(self, process: int, timer: int) -> int:
        handles = (W.HANDLE * 2)(process, timer)
        result = self.wait_many(2, handles, False, 0xFFFFFFFF)
        self.require(result in (0, 1))
        return result

    def terminate(self, job: int):
        self.require(self.kill_job(job, 1223))  # Exact owned job only.

    def resume(self, thread: int):
        self.require(self.resume_thread(thread) == 1)  # Exactly our initial suspend.

    def read(self, handle: int, limit: int) -> bytes:
        buffer, count = C.create_string_buffer(limit), W.DWORD()
        self.require(self.read_file(handle, buffer, limit, C.byref(count), None))
        return buffer.raw[:count.value]

    def write(self, handle: int, data: bytes) -> int:
        count = W.DWORD()
        self.require(self.write_file(handle, C.create_string_buffer(data), len(data), C.byref(count), None))
        self.require(count.value > 0)
        return count.value

    def copy_handle(self, owned: int, *, access: int = 0) -> int:
        result = W.HANDLE()
        current = self.current_process()  # Pseudo handle is never owned/closed.
        self.require(self.duplicate_handle(current, owned, current, C.byref(result), access,
                                           False, 2 if access == 0 else 0))
        return result.value
