from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-silky")
except PackageNotFoundError:
    __version__ = version("django-silk")  # fallback for local dev installs
