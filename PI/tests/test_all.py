"""The obsolete hardware sweep was retired; unittest discovery is non-actuating."""
if __name__ == "__main__":
    raise SystemExit(
        "Use python -m unittest discover -s tests for non-actuating checks. "
        "For real hardware checks follow PI/README.md; old Camera imports and "
        "microsecond servo sweeps no longer match this robot."
    )
