"""Make runtime importable so `unittest discover -s tests -t .` recurses into it.

Without this the directory is a namespace package and discovery skips it
silently, so its tests never run under the full-suite command even though the
run still reports success.
"""
