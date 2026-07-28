import os

__all__ = ["__version__", "build_revision"]

__version__ = "0.2.0"
build_revision = os.getenv("APP_BUILD_REVISION", "unknown")
