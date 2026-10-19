"""Exec the fixed converter command within the same supervised process group."""
import os
import resource
import sys

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (40, 41))
    resource.setrlimit(resource.RLIMIT_FSIZE, (40 * 1024**2, 40 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execv(sys.argv[1], sys.argv[1:])
