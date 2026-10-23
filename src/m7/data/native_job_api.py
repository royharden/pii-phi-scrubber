"""Lazy read-only job/process/handle observations. Borrowed handles never close."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W

from .native_windows_api import NativeUnavailable, Win32ReadOnly


class BASIC_LIMITS(C.Structure):
    _fields_ = [('PerProcessUserTimeLimit', C.c_longlong), ('PerJobUserTimeLimit', C.c_longlong),
        ('LimitFlags', W.DWORD), ('MinimumWorkingSetSize', C.c_size_t), ('MaximumWorkingSetSize', C.c_size_t),
        ('ActiveProcessLimit', W.DWORD), ('Affinity', C.c_size_t), ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class EXTENDED_LIMITS(C.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMITS), ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', C.c_size_t), ('JobMemoryLimit', C.c_size_t),
        ('PeakProcessMemoryUsed', C.c_size_t), ('PeakJobMemoryUsed', C.c_size_t)]


class CPU_RATE(C.Structure):
    _fields_ = [('ControlFlags', W.DWORD), ('CpuRate', W.DWORD)]


class PID_LIST(C.Structure):
    # Explicitly bounded: qualification permits 0 prepared or 1 exact worker.
    _fields_ = [('NumberOfAssignedProcesses', W.DWORD), ('NumberOfProcessIdsInList', W.DWORD),
               ('ProcessIdList', C.c_size_t * 2)]


class Win32ControlReadOnly(Win32ReadOnly):
    def __init__(self):
        super().__init__()
        def bind(name, args, result):
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result
            return fn
        P, D, B, H = C.c_void_p, W.DWORD, W.BOOL, W.HANDLE
        self.query_job = bind('QueryInformationJobObject', [H, C.c_int, P, D, C.POINTER(D)], B)
        self.get_pid = bind('GetProcessId', [H], D)
        self.mitigation = bind('GetProcessMitigationPolicy', [H, C.c_int, P, C.c_size_t], B)
        self.handle_flags = bind('GetHandleInformation', [H, C.POINTER(D)], B)
        self.object_equal = bind('CompareObjectHandles', [H, H], B)
        self.current_process = bind('GetCurrentProcess', [], H)
        self.copy_handle = bind('DuplicateHandle', [H, H, H, C.POINTER(H), D, B, D], B)
        self.file_type = bind('GetFileType', [H], D)

    def flags(self, handle: int) -> int:
        self._handle(handle)
        flags = W.DWORD()
        if not self.handle_flags(handle, C.byref(flags)):
            raise NativeUnavailable('native_borrowed_handle_unavailable')
        return flags.value

    def _handle(self, value: int) -> None:
        maximum = (1 << (C.sizeof(C.c_void_p) * 8)) - 1
        if type(value) is not int or not 0 < value < maximum - 1:
            raise NativeUnavailable('native_handle_identity_invalid')

    def _job(self, handle: int, kind: int, structure):
        self._handle(handle)
        value, returned = structure(), W.DWORD()
        if not self.query_job(handle, kind, C.byref(value), C.sizeof(value), C.byref(returned)):
            raise NativeUnavailable('native_job_query_unavailable')
        if returned.value > C.sizeof(value) or (kind != 3 and returned.value != C.sizeof(value)) or (kind == 3 and returned.value < 8):
            raise NativeUnavailable('native_job_query_incomplete')
        return value

    def job_snapshot(self, job: int) -> dict:
        if self.flags(job) & 1:
            raise NativeUnavailable('native_job_handle_inheritable')
        extended = self._job(job, 9, EXTENDED_LIMITS)
        cpu, ui, pids = self._job(job, 15, CPU_RATE), self._job(job, 4, W.DWORD), self._job(job, 3, PID_LIST)
        if pids.NumberOfAssignedProcesses != pids.NumberOfProcessIdsInList or pids.NumberOfAssignedProcesses > 1:
            raise NativeUnavailable('native_job_membership_incomplete_or_broad')
        basic = extended.BasicLimitInformation
        return {'limit_flags': basic.LimitFlags, 'active_process_limit': basic.ActiveProcessLimit,
            'process_memory_limit': extended.ProcessMemoryLimit, 'job_memory_limit': extended.JobMemoryLimit,
            'process_user_time_100ns': basic.PerProcessUserTimeLimit,
            'cpu_control_flags': cpu.ControlFlags, 'cpu_rate_hundredths': cpu.CpuRate,
            'ui_restrictions': ui.value, 'pids': tuple(pids.ProcessIdList[:pids.NumberOfProcessIdsInList])}

    def exact_job_member(self, process: int, job: int) -> bool:
        self._handle(process)
        self._handle(job)
        result = W.BOOL()
        if not self.in_job(process, job, C.byref(result)):
            raise NativeUnavailable('native_exact_job_query_unavailable')
        return bool(result.value)

    @contextmanager
    def mitigation_process(self, borrowed_process: int, pid: int, start_identity: str):
        self._handle(borrowed_process)
        if type(pid) is not int or not 0 < pid <= 4294967295:
            raise NativeUnavailable('native_process_identity_invalid')
        # QUERY_INFORMATION is required by GetProcessMitigationPolicy. D6's
        # limited-query/DUP_HANDLE lease is never widened or mutated. Request a
        # separate read-only handle to the EXACT approved process, no elevation.
        owned = self.open_process(0x0400, False, pid)
        if not owned:
            raise NativeUnavailable('native_mitigation_query_right_unavailable')
        try:
            if not self.object_equal(owned, borrowed_process) or self.process_identity(owned)[0] != start_identity:
                raise NativeUnavailable('native_mitigation_process_changed')
            yield owned
        finally:
            if not self.close(owned):
                raise NativeUnavailable('native_query_handle_cleanup_unverified')

    def mitigation_snapshot(self, process: int, names: tuple[str, ...], *, pid: int, start_identity: str) -> dict[str, int]:
        # These supported policies have a single DWORD flag union; no DEP layout guess.
        classes = {'strict_handles': 3, 'child_process': 13, 'extension_points': 6, 'image_load': 10}
        result = {}
        with self.mitigation_process(process, pid, start_identity) as query_process:
            for name in names:
                flags = W.DWORD()
                if name not in classes or not self.mitigation(query_process, classes[name], C.byref(flags), C.sizeof(flags)):
                    raise NativeUnavailable('native_mitigation_query_unavailable')
                result[name] = flags.value
        return result

    @contextmanager
    def child_handle_copy(self, process: int, child_handle: int):
        self._handle(process)
        self._handle(child_handle)
        copy = W.HANDLE()
        # SAME_ACCESS only, NEVER CLOSE_SOURCE. New noninheritable local duplicate.
        if not self.copy_handle(process, child_handle, self.current_process(), C.byref(copy), 0, False, 2):
            raise NativeUnavailable('native_child_handle_query_unavailable')
        try:
            yield copy.value
        finally:
            if not self.close(copy):  # Own duplicate only; never a borrowed close.
                raise NativeUnavailable('native_duplicate_cleanup_unverified')

    def compare_child_handle(self, process: int, child: int, expected: int, role: str) -> bool:
        if self.flags(expected) & 1:
            raise NativeUnavailable('native_expected_reference_inheritable')
        with self.child_handle_copy(process, child) as local:
            if self.flags(local) & 1 or not self.object_equal(local, expected):
                return False
            kind = self.file_type(local)
            return kind == 3 if role in ('stdin', 'stdout') else kind in (2, 3)
