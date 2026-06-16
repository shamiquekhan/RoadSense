"""Interactive map generation for RoadSense scored segments.

Detects both ADB and RoadSense column naming conventions.
Reduces output size by simplifying geometry and thinning Moderate/Low segments.
"""

from __future__ import annotations

import json
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from folium import plugins
from folium.features import GeoJsonPopup, GeoJsonTooltip

from roadsense.config import PRIORITY_THRESHOLDS, PRIORITY_DEFAULT

FIELD_MAP: dict[str, list[str]] = {
    "road_name": ["road_name"],
    "segment_id": ["segment_id"],
    "Posted Limit:": ["SpeedLimit", "posted_limit"],
    "Safe System Limit:": ["safe_system_limit", "safe_system_ref"],
    "85th Pct Speed:": ["F85thPercentileSpeed", "v85"],
    "Limit Gap:": ["limit_gap"],
    "Operating Gap:": ["operating_gap"],
    "Safety Score:": ["speed_safety_score", "SSS"],
    "VRU Risk:": ["vru_risk_score", "B_score"],
    "Priority:": ["priority_class", "risk_tier"],
    "Reliability:": ["reliability_tier"],
    "Region:": ["region"],
    "Fraction Over Limit:": ["PercentOverLimit"],
    "Explanation:": ["score_explanation"],
}

CRITICAL_LABELS = {"Critical — Immediate Review", "Critical"}
HIGH_LABELS = {"High — Priority Review", "High"}


def _resolve_fields(gdf: gpd.GeoDataFrame, field_map: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    cols = set(gdf.columns)
    tooltip_fields: list[str] = []
    popup_fields: list[str] = []
    for display_name, candidates in field_map.items():
        found = next((c for c in candidates if c in cols), None)
        if found:
            tooltip_fields.append(found)
            popup_fields.append(found)
    return tooltip_fields, popup_fields


def _get_colour(priority_class: str) -> str:
    for _, label, colour in PRIORITY_THRESHOLDS:
        if label == priority_class:
            return colour
    return PRIORITY_DEFAULT[1]


RELIABILITY_OPACITY: dict[str, float] = {
    "High": 0.85,
    "Medium": 0.55,
    "Low": 0.30,
}


def style_function(feature: dict) -> dict:
    props = feature["properties"]
    priority = props.get("priority_class") or props.get("risk_tier") or ""
    colour = _get_colour(priority)
    reliability = props.get("reliability_tier", "Medium")
    opacity = RELIABILITY_OPACITY.get(reliability, 0.55)
    return {
        "fillColor": colour,
        "color": "#333",
        "weight": 1.5,
        "opacity": opacity,
        "fillOpacity": opacity,
    }


def highlight_function(feature: dict) -> dict:
    return {"weight": 3, "color": "#000", "fillOpacity": 0.8}


def _build_tooltip_aliases(tooltip_fields: list[str]) -> list[str]:
    rev: dict[str, str] = {}
    for display, candidates in FIELD_MAP.items():
        for c in candidates:
            rev[c] = display
    return [rev.get(f, f) for f in tooltip_fields]


def prepare_for_web(
    gdf: gpd.GeoDataFrame,
    max_segments: int = 3500,
    simplify_tolerance: float = 0.001,
) -> gpd.GeoDataFrame:
    """Reduce file size for hosted map without losing Critical/High segments.

    - Keeps all Critical and High priority segments (never dropped).
    - For Moderate/Low, keeps the top `max_segments` by traffic percentile.
    - Simplifies geometry to ~11m resolution.
    """
    priority_col = "priority_class" if "priority_class" in gdf.columns else "risk_tier"
    pct_col = "RankedPercentile" if "RankedPercentile" in gdf.columns else "PercentOverLimit"
    score_col = "speed_safety_score" if "speed_safety_score" in gdf.columns else "SSS"

    if priority_col not in gdf.columns:
        raise KeyError(f"Neither priority_class nor risk_tier found in columns: {list(gdf.columns)}")

    crit_high = gdf[gdf[priority_col].isin(CRITICAL_LABELS | HIGH_LABELS)].copy()
    other = gdf[~gdf.index.isin(crit_high.index)].copy()

    if pct_col not in other.columns:
        other[pct_col] = other[score_col] * 100

    crit_high_keep = min(len(crit_high), max(2000, max_segments // 2))
    if len(crit_high) > crit_high_keep:
        score_col_local = "speed_safety_score" if "speed_safety_score" in crit_high.columns else "SSS"
        crit_high = crit_high.nlargest(crit_high_keep, score_col_local)

    keep_n = max(0, max_segments - len(crit_high))
    if keep_n > 0 and len(other) > keep_n:
        other = other.nlargest(keep_n, pct_col)

    web = pd.concat([crit_high, other], ignore_index=True)
    web = web.to_crs("EPSG:4326")
    web["geometry"] = web.geometry.simplify(tolerance=simplify_tolerance, preserve_topology=True)

    # Cumulative km for budget-constraint slider
    length_col = "Shape_Length" if "Shape_Length" in web.columns else "length_m"
    if length_col in web.columns:
        sorted_idx = web[score_col].fillna(0).sort_values(ascending=False).index
        web = web.loc[sorted_idx]
        web["budget_cumul_km"] = (web[length_col] / 1000).cumsum().round(2)
    else:
        web["budget_cumul_km"] = 0.0

    web = web.reset_index(drop=True)

    print(f"  Map data: {len(web)} segments ({len(crit_high)} Critical/High kept, "
          f"{len(other)} Moderate/Low sampled), geometry simplified")
    return web


def _add_budget_widget(m: folium.Map, gdf: gpd.GeoDataFrame) -> None:
    """Add a km budget slider that highlights top-priority segments."""
    length_col = "Shape_Length" if "Shape_Length" in gdf.columns else "length_m"
    if length_col not in gdf.columns:
        return

    total_critical_km = int(
        gdf[gdf["priority_class"].isin(CRITICAL_LABELS | HIGH_LABELS)][length_col].sum() / 1000
    )
    total_km = int(gdf[length_col].sum() / 1000)
    step = max(1, total_km // 100)

    budget_html = f"""
    <div id="budget-widget"
         style="position: fixed; top: 20px; left: 60px; z-index: 1000;
                background: white; padding: 12px 16px; border-radius: 6px;
                box-shadow: 0 0 10px rgba(0,0,0,0.25);
                font-family: sans-serif; font-size: 13px; min-width: 260px;">
        <b>Review Budget</b>
        <div style="margin-top: 6px; display: flex; align-items: center; gap: 10px;">
            <span id="budget-value" style="font-weight: bold; min-width: 60px;">{min(500, total_critical_km)} km</span>
            <input type="range" id="budget-slider"
                   min="0" max="{total_km}" step="{step}" value="{min(500, total_critical_km)}"
                   style="flex: 1;">
        </div>
        <div style="margin-top: 4px; font-size: 11px; color: #666;">
            Critical/High: <span id="critical-km">{total_critical_km}</span> km total
            &middot; <span id="budget-segments">0</span> segments highlighted
        </div>
    </div>
    <script>
    (function() {{
        var budgetSlider = document.getElementById('budget-slider');
        var budgetValue = document.getElementById('budget-value');
        var budgetSegments = document.getElementById('budget-segments');

        function findLayers(map) {{
            var layers = [];
            map.eachLayer(function(l) {{
                if (l.feature && l.feature.properties) {{
                    layers.push(l);
                }}
            }});
            return layers;
        }}

        function updateBudget(km) {{
            budgetValue.textContent = km + ' km';
            var layers = findLayers(m);
            var count = 0;
            layers.forEach(function(l) {{
                var cumul = l.feature && l.feature.properties && l.feature.properties.budget_cumul_km;
                if (cumul !== undefined && cumul <= km) {{
                    l.setStyle({{opacity: 0.9, fillOpacity: 0.85, weight: 2.5}});
                    count++;
                }} else {{
                    l.setStyle({{opacity: 0.15, fillOpacity: 0.10, weight: 0.5}});
                }}
            }});
            budgetSegments.textContent = count;
        }}

        if (budgetSlider) {{
            budgetSlider.addEventListener('input', function() {{
                updateBudget(parseInt(this.value));
            }});
            setTimeout(function() {{ updateBudget(parseInt(budgetSlider.value)); }}, 500);
        }}
    }})();
    </script>
    """
    m.get_root().html.add_child(folium.Element(budget_html))


def create_interactive_map(
    geojson_path: str | Path,
    out_path: str | Path = "speed_safety_map.html",
) -> str:
    """Create a Folium map from scored GeoJSON.

    Auto-detects column naming convention. Simplifies geometry and thins
    Moderate/Low segments to keep the HTML file under ~5 MB for fast web loading.
    Returns the path to the saved HTML.
    """
    print("  Loading GeoJSON...")
    gdf = gpd.read_file(geojson_path)
    gdf = prepare_for_web(gdf)
    data = json.loads(gdf.to_json())

    bounds = gdf.total_bounds
    center = ((bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2)

    m = folium.Map(
        location=center,
        zoom_start=6,
        tiles="cartodbpositron",
        control_scale=True,
    )

    tooltip_fields, popup_fields = _resolve_fields(gdf, FIELD_MAP)
    tooltip_aliases = _build_tooltip_aliases(tooltip_fields)

    tooltip = GeoJsonTooltip(
        fields=tooltip_fields,
        aliases=tooltip_aliases,
        localize=True,
        sticky=False,
        labels=True,
        style="""
            background-color: #F0EFEF; border: 1px solid black;
            border-radius: 3px; box-shadow: 3px; font-size: 12px;
        """,
    )

    popup = GeoJsonPopup(
        fields=popup_fields,
        aliases=tooltip_aliases,
        localize=True,
        labels=True,
        style="width: 350px; font-size: 12px;",
        show=True,
    )

    folium.GeoJson(
        data,
        name="Speed Safety Score",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
        popup=popup,
        smooth_factor=0.5,
    ).add_to(m)

    folium.LayerControl().add_to(m)

    legend = """
    <div style="position: fixed; bottom: 20px; right: 20px; z-index: 1000;
                background: white; padding: 12px; border-radius: 5px;
                box-shadow: 0 0 10px rgba(0,0,0,0.3); font-family: sans-serif;">
        <b>Priority</b><br>
    """
    for _, label, colour in PRIORITY_THRESHOLDS:
        legend += (
            f'<span style="background:{colour}; width:12px; height:12px; '
            f'display:inline-block; margin-right:5px;"></span> {label}<br>'
        )
    legend += (
        f'<span style="background:{PRIORITY_DEFAULT[1]}; width:12px; height:12px; '
        f'display:inline-block; margin-right:5px;"></span> {PRIORITY_DEFAULT[0]}<br>'
    )
    legend += (
        '<hr><div style="font-size:11px; color:#666;">'
        'Opacity = data reliability<br>'
        '<span style="opacity:0.85;">▬</span> High &nbsp;'
        '<span style="opacity:0.55;">▬</span> Medium &nbsp;'
        '<span style="opacity:0.30;">▬</span> Low<br>'
        'ADB AI for Safer Roads 2026<br>RoadSense</div></div>'
    )
    m.get_root().html.add_child(folium.Element(legend))

    plugins.Fullscreen().add_to(m)
    plugins.MiniMap(toggle_display=True).add_to(m)

    _add_budget_widget(m, gdf)

    m.save(str(out_path))
    file_size = Path(out_path).stat().st_size / 1_000_000
    print(f"  Map saved: {out_path} ({file_size:.1f} MB)")
    return str(out_path)
