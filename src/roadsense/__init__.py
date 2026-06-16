"""RoadSense — AI-powered speed limit alignment analysis for road safety.

A data pipeline that evaluates speed limit appropriateness against Safe System
principles for road networks in Thailand and Maharashtra, India.

Built for the ADB AI for Safer Roads 2026 Innovation Challenge.
"""

from importlib.metadata import version

try:
    __version__ = version("roadsense")
except Exception:
    __version__ = "2.0.0"
