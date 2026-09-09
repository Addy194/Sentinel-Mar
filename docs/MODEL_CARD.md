# Model Card: sar_spill_pixel_v1

**Status:** Prototype / demo integration artifact

This artifact is based on synthetic SAR-like data and is **not a field-validated operational oil-spill detector**. Replace it with a model trained and evaluated on representative Sentinel-1 oil-spill and look-alike data before deployment.

Inputs: Sentinel-1 VV and VH. Output: pixel-level candidate probability. All detections require analyst review.

Known look-alikes include low-wind sea, ship wakes, coastal dark areas, biogenic films, and rain-related effects.
