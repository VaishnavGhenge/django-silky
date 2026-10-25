from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-silky")
except PackageNotFoundError:
    try:
        __version__ = version("django-silk")  # fallback for local dev installs
    except PackageNotFoundError:
        __version__ = "unknown"
