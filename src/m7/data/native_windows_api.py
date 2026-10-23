"""Lazy supported Win32 read-only inspection. Import never loads a Windows DLL."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import sys


class NativeUnavailable(ValueError):
    """Fixed error enums only; never expose Win32 paths/token/ACL exception text."""


class LUID(C.Structure):
    _fields_ = [('LowPart', W.DWORD), ('HighPart', W.LONG)]


class SID_ATTRIBUTES(C.Structure):
    _fields_ = [('Sid', C.c_void_p), ('Attributes', W.DWORD)]


class LUID_ATTRIBUTES(C.Structure):
    _fields_ = [('Luid', LUID), ('Attributes', W.DWORD)]


class TOKEN_STATISTICS(C.Structure):
    _fields_ = [('TokenId', LUID), ('AuthenticationId', LUID), ('ExpirationTime', C.c_longlong),
               ('TokenType', W.DWORD), ('ImpersonationLevel', W.DWORD), ('DynamicCharged', W.DWORD),
               ('DynamicAvailable', W.DWORD), ('GroupCount', W.DWORD), ('PrivilegeCount', W.DWORD), ('ModifiedId', LUID)]


class ACL(C.Structure):
    _fields_ = [('AclRevision', W.BYTE), ('Sbz1', W.BYTE), ('AclSize', W.WORD),
               ('AceCount', W.WORD), ('Sbz2', W.WORD)]


class ACE_HEADER(C.Structure):
    _fields_ = [('AceType', W.BYTE), ('AceFlags', W.BYTE), ('AceSize', W.WORD)]


class GENERIC_MAPPING(C.Structure):
    _fields_ = [('GenericRead', W.DWORD), ('GenericWrite', W.DWORD),
               ('GenericExecute', W.DWORD), ('GenericAll', W.DWORD)]


def luid(value: LUID) -> str:
    return f'{value.HighPart & 0xffffffff:08x}{value.LowPart:08x}'


class Win32ReadOnly:
    def __init__(self):
        if sys.platform != 'win32':
            raise NativeUnavailable('unsupported_native_platform')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.a = C.WinDLL('advapi32', use_last_error=True)
        def bind(dll, name, args, result):
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
            return fn
        P, D, B, H = C.c_void_p, W.DWORD, W.BOOL, W.HANDLE
        self.open_process = bind(self.k, 'OpenProcess', [D, B, D], H)
        self.close = bind(self.k, 'CloseHandle', [H], B)
        self.free = bind(self.k, 'LocalFree', [P], P)
        self.times = bind(self.k, 'GetProcessTimes', [H, P, P, P, P], B)
        self.image = bind(self.k, 'QueryFullProcessImageNameW', [H, D, W.LPWSTR, C.POINTER(D)], B)
        self.exit_code = bind(self.k, 'GetExitCodeProcess', [H, C.POINTER(D)], B)
        self.handles = bind(self.k, 'GetProcessHandleCount', [H, C.POINTER(D)], B)
        self.in_job = bind(self.k, 'IsProcessInJob', [H, H, C.POINTER(B)], B)
        self.open_token = bind(self.a, 'OpenProcessToken', [H, D, C.POINTER(H)], B)
        self.token_info = bind(self.a, 'GetTokenInformation', [H, C.c_int, P, D, C.POINTER(D)], B)
        self.duplicate = bind(self.a, 'DuplicateToken', [H, C.c_int, C.POINTER(H)], B)
        self.sid_string = bind(self.a, 'ConvertSidToStringSidW', [P, C.POINTER(W.LPWSTR)], B)
        self.priv_name = bind(self.a, 'LookupPrivilegeNameW', [W.LPCWSTR, C.POINTER(LUID), W.LPWSTR, C.POINTER(D)], B)
        self.security = bind(self.a, 'GetNamedSecurityInfoW', [W.LPCWSTR, C.c_int, D, P, P, P, P, C.POINTER(P)], D)
        self.valid_sd = bind(self.a, 'IsValidSecurityDescriptor', [P], B)
        self.sd_length = bind(self.a, 'GetSecurityDescriptorLength', [P], D)
        self.sd_control = bind(self.a, 'GetSecurityDescriptorControl', [P, C.POINTER(W.WORD), C.POINTER(D)], B)
        self.relative_sd = bind(self.a, 'MakeSelfRelativeSD', [P, P, C.POINTER(D)], B)
        self.dacl = bind(self.a, 'GetSecurityDescriptorDacl', [P, C.POINTER(B), C.POINTER(P), C.POINTER(B)], B)
        self.sacl = bind(self.a, 'GetSecurityDescriptorSacl', [P, C.POINTER(B), C.POINTER(P), C.POINTER(B)], B)
        self.ace = bind(self.a, 'GetAce', [P, D, C.POINTER(P)], B)
        self.map_generic = bind(self.a, 'MapGenericMask', [C.POINTER(D), C.POINTER(GENERIC_MAPPING)], None)
        self.access = bind(self.a, 'AccessCheck', [P, H, D, C.POINTER(GENERIC_MAPPING), P,
            C.POINTER(D), C.POINTER(D), C.POINTER(B)], B)

    @contextmanager
    def process(self, pid: int):
        if type(pid) is not int or not 0 < pid <= 4294967295:
            raise NativeUnavailable('process_identity_invalid')
        handle = self.open_process(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only.
        if not handle:
            raise NativeUnavailable('process_query_unavailable')
        try:
            yield handle
        finally:
            self.close(handle)

    @contextmanager
    def token(self, process):
        handle = W.HANDLE()
        if not self.open_token(process, 0x0008 | 0x0002, C.byref(handle)):
            raise NativeUnavailable('token_query_unavailable')
        try:
            yield handle
        finally:
            self.close(handle)

    @contextmanager
    def access_token(self, token):
        duplicate = W.HANDLE()
        # SecurityImpersonation=2; duplicate is used ONLY by AccessCheck, never set
        # on a thread, elevated, assigned to a process, or used to launch anything.
        if not self.duplicate(token, 2, C.byref(duplicate)):
            raise NativeUnavailable('accesscheck_token_unavailable')
        try:
            yield duplicate
        finally:
            self.close(duplicate)

    def info(self, token, kind: int):
        size = W.DWORD()
        self.token_info(token, kind, None, 0, C.byref(size))
        if not 0 < size.value <= 1000000:
            raise NativeUnavailable('token_information_unavailable')
        buffer = C.create_string_buffer(size.value)
        if not self.token_info(token, kind, buffer, size, C.byref(size)):
            raise NativeUnavailable('token_information_unavailable')
        return buffer

    def scalar(self, token, kind: int) -> int:
        raw = self.info(token, kind)
        if len(raw) < C.sizeof(W.DWORD):
            raise NativeUnavailable('token_information_malformed')
        return C.cast(raw, C.POINTER(W.DWORD)).contents.value

    def sid(self, pointer) -> str:
        result = W.LPWSTR()
        if not pointer or not self.sid_string(pointer, C.byref(result)):
            raise NativeUnavailable('token_sid_unavailable')
        try:
            return result.value
        finally:
            self.free(C.cast(result, C.c_void_p))

    def groups(self, token, kind: int):
        raw = self.info(token, kind)
        count = C.cast(raw, C.POINTER(W.DWORD)).contents.value
        if count > 4096:
            raise NativeUnavailable('token_groups_malformed')
        class GROUPS(C.Structure):
            _fields_ = [('Count', W.DWORD), ('Groups', SID_ATTRIBUTES * count)]
        if C.sizeof(GROUPS) > len(raw):
            raise NativeUnavailable('token_groups_malformed')
        data = C.cast(raw, C.POINTER(GROUPS)).contents
        return tuple((self.sid(group.Sid), group.Attributes) for group in data.Groups)

    def token_summary(self, token) -> dict:
        user_raw = self.info(token, 1)
        user = self.sid(C.cast(user_raw, C.POINTER(SID_ATTRIBUTES)).contents.Sid)
        stats_raw = self.info(token, 10)
        if len(stats_raw) < C.sizeof(TOKEN_STATISTICS):
            raise NativeUnavailable('token_statistics_malformed')
        stats = C.cast(stats_raw, C.POINTER(TOKEN_STATISTICS)).contents
        raw = self.info(token, 3)
        count = C.cast(raw, C.POINTER(W.DWORD)).contents.value
        if count > 256:
            raise NativeUnavailable('token_privileges_malformed')
        class PRIVILEGES(C.Structure):
            _fields_ = [('Count', W.DWORD), ('Privileges', LUID_ATTRIBUTES * count)]
        if C.sizeof(PRIVILEGES) > len(raw):
            raise NativeUnavailable('token_privileges_malformed')
        privileges = []
        for privilege in C.cast(raw, C.POINTER(PRIVILEGES)).contents.Privileges:
            name, size = C.create_unicode_buffer(256), W.DWORD(256)
            if not self.priv_name(None, C.byref(privilege.Luid), name, C.byref(size)):
                raise NativeUnavailable('token_privilege_unavailable')
            privileges.append(name.value)  # Held, even if disabled; never log names/SIDs.
        return {'sid': user, 'token_id': luid(stats.TokenId), 'modified_id': luid(stats.ModifiedId),
                'primary': stats.TokenType == 1, 'elevated': self.scalar(token, 20),
                'ui_access': self.scalar(token, 26), 'appcontainer': self.scalar(token, 29),
                'integrity_rid': self.integrity(token), 'mandatory_policy': self.scalar(token, 27),
                'restricted': self.scalar(token, 21), 'restricted_sids': self.groups(token, 11),
                'groups': self.groups(token, 2), 'privileges': tuple(privileges)}

    def process_identity(self, process) -> tuple[str, str, int]:
        creation, exit_time, kernel, user = (W.FILETIME() for _ in range(4))
        code, count = W.DWORD(), W.DWORD()
        name, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        if (not self.times(process, C.byref(creation), C.byref(exit_time), C.byref(kernel), C.byref(user))
                or not self.image(process, 0, name, C.byref(size))
                or not self.exit_code(process, C.byref(code)) or code.value != 259
                or not self.handles(process, C.byref(count))):
            raise NativeUnavailable('process_identity_unavailable')
        return str((creation.dwHighDateTime << 32) | creation.dwLowDateTime), name.value, count.value

    @contextmanager
    def descriptor(self, path):
        pointer = C.c_void_p()
        # OWNER|GROUP|DACL|LABEL: no SACL privilege enablement or security mutation.
        if self.security(str(path), 1, 0x17, None, None, None, None, C.byref(pointer)) != 0:
            raise NativeUnavailable('security_descriptor_unavailable')
        try:
            if not self.valid_sd(pointer):
                raise NativeUnavailable('security_descriptor_invalid')
            length = self.sd_length(pointer)
            if not 20 <= length <= 1000000:
                raise NativeUnavailable('security_descriptor_invalid')
            self._supported_acls(pointer)
            control, revision = W.WORD(), W.DWORD()
            if not self.sd_control(pointer, C.byref(control), C.byref(revision)):
                raise NativeUnavailable('security_descriptor_invalid')
            if control.value & 0x8000:
                raw = C.string_at(pointer, length)
            else:
                size = W.DWORD()
                self.relative_sd(pointer, None, C.byref(size))
                if not 20 <= size.value <= 1000000:
                    raise NativeUnavailable('security_descriptor_invalid')
                relative = C.create_string_buffer(size.value)
                if not self.relative_sd(pointer, relative, C.byref(size)):
                    raise NativeUnavailable('security_descriptor_invalid')
                raw = relative.raw[:size.value]
            yield pointer, raw
        finally:
            self.free(pointer)

    def _supported_acls(self, descriptor) -> None:
        for kind in ('dacl', 'sacl'):
            present, defaulted, pointer = W.BOOL(), W.BOOL(), C.c_void_p()
            if not getattr(self, kind)(descriptor, C.byref(present), C.byref(pointer), C.byref(defaulted)):
                raise NativeUnavailable('acl_uninspectable')
            if kind == 'dacl' and (not present.value or not pointer.value):
                raise NativeUnavailable('null_or_missing_dacl')
            if not pointer.value:
                continue
            acl = C.cast(pointer, C.POINTER(ACL)).contents
            for index in range(acl.AceCount):
                ace = C.c_void_p()
                if not self.ace(pointer, index, C.byref(ace)):
                    raise NativeUnavailable('acl_uninspectable')
                header = C.cast(ace, C.POINTER(ACE_HEADER)).contents
                if kind == 'dacl' and header.AceType not in (0, 1):
                    raise NativeUnavailable('conditional_or_unsupported_dacl')
                if kind == 'sacl':
                    if header.AceType != 17 or header.AceSize < 16 or header.AceFlags & 0x8:
                        raise NativeUnavailable('unsupported_mandatory_policy')
                    mask = C.c_uint32.from_address(ace.value + 4).value
                    if mask & ~1:  # Support NO_WRITE_UP only; read/execute-up policy unknown => block.
                        raise NativeUnavailable('unsupported_mandatory_policy')

    def integrity(self, token) -> int:
        raw = self.info(token, 25)
        sid = self.sid(C.cast(raw, C.POINTER(SID_ATTRIBUTES)).contents.Sid)
        if not sid.startswith('S-1-16-'):
            raise NativeUnavailable('token_integrity_unavailable')
        return int(sid.rsplit('-', 1)[1])

    def label(self, descriptor) -> tuple[int, int]:
        present, defaulted, pointer = W.BOOL(), W.BOOL(), C.c_void_p()
        if not self.sacl(descriptor, C.byref(present), C.byref(pointer), C.byref(defaulted)):
            raise NativeUnavailable('mandatory_label_unavailable')
        label = (8192, 1)  # Windows treats unlabeled objects as medium/NO_WRITE_UP.
        if pointer.value:
            acl = C.cast(pointer, C.POINTER(ACL)).contents
            if acl.AceCount > 1:
                raise NativeUnavailable('ambiguous_mandatory_label')
            if acl.AceCount:
                ace = C.c_void_p()
                if not self.ace(pointer, 0, C.byref(ace)):
                    raise NativeUnavailable('mandatory_label_unavailable')
                sid = self.sid(ace.value + 8)
                if not sid.startswith('S-1-16-'):
                    raise NativeUnavailable('mandatory_label_unavailable')
                label = (int(sid.rsplit('-', 1)[1]), C.c_uint32.from_address(ace.value + 4).value)
        return label

    def allows(self, descriptor, token, mask: int) -> bool:
        mapping = GENERIC_MAPPING(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        desired = W.DWORD(mask)
        self.map_generic(C.byref(desired), C.byref(mapping))
        rid, policy = self.label(descriptor)
        if rid > self.integrity(token) and policy & 1 and desired.value & (0x0002 | 0x0004 | 0x0010 | 0x0100 | 0x10000 | 0x40000 | 0x80000):
            return False
        privileges, size, granted, status = C.create_string_buffer(16384), W.DWORD(16384), W.DWORD(), W.BOOL()
        if not self.access(descriptor, token, desired, C.byref(mapping), privileges,
                           C.byref(size), C.byref(granted), C.byref(status)):
            raise NativeUnavailable('native_accesscheck_unavailable')
        return bool(status.value and granted.value & desired.value == desired.value)

    def job_member(self, process) -> bool:
        result = W.BOOL()
        if not self.in_job(process, None, C.byref(result)):
            raise NativeUnavailable('job_membership_unavailable')
        return bool(result.value)  # Exact job/limits still require current host control verification.
