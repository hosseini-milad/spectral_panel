import hashlib
import ipaddress


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except:
        return False


def normalize_ip(value):
    try:
        return int(ipaddress.ip_address(value)) / (2**32)
    except:
        return 0.5


def normalize_text(value):
    try:
        h = hashlib.md5(str(value).encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF
    except:
        return 0.5