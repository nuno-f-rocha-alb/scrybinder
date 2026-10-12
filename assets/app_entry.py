"""Entry point of the packaged app (PyInstaller does not accept relative imports in the main script)."""
from scrybinder.app import main

if __name__ == "__main__":
    main()
