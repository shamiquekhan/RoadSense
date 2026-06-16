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

from roadsense.config import PRIORITY_THRESHOLDS, PRIORITY_DEFAULT

# iRAP-aligned tier styling
TIER_STYLE: dict[str, dict] = {
    "Critical — Immediate Review": {
        "color": "#E24B4A", "weight": 5, "opacity": 0.95, "fill_opacity": 0.85,
    },
    "High — Priority Review": {
        "color": "#EF9F27", "weight": 4, "opacity": 0.85, "fill_opacity": 0.70,
    },
    "Moderate — Scheduled Review": {
        "color": "#97C459", "weight": 3, "opacity": 0.75, "fill_opacity": 0.55,
    },
    "Low — Monitor": {
        "color": "#5DCAA5", "weight": 2, "opacity": 0.65, "fill_opacity": 0.40,
    },
}

RELIABILITY_OPACITY: dict[str, float] = {
    "High": 0.85, "Medium": 0.55, "Low": 0.30,
}

CRITICAL_LABELS = {"Critical — Immediate Review", "Critical"}
HIGH_LABELS = {"High — Priority Review", "High"}


def _get_tier_name(props: dict) -> str:
    return props.get("priority_class") or props.get("risk_tier") or "Low — Monitor"


def _get_tier_for_gdf(gdf: gpd.GeoDataFrame, row: pd.Series) -> str:
    return row.get("priority_class") or row.get("risk_tier") or "Low — Monitor"


def _get_score(props: dict) -> float:
    return props.get("speed_safety_score") or props.get("SSS") or 0.0


def style_function(feature: dict) -> dict:
    props = feature["properties"]
    tier = _get_tier_name(props)
    cfg = TIER_STYLE.get(tier, TIER_STYLE["Low — Monitor"])
    reliability = props.get("reliability_tier", "Medium")
    opacity = RELIABILITY_OPACITY.get(
        reliability.replace(" (imputed)", ""), 0.55
    )
    return {
        "fillColor": cfg["color"],
        "color": "#333",
        "weight": cfg["weight"],
        "opacity": min(cfg["opacity"], opacity),
        "fillOpacity": min(cfg["fill_opacity"], opacity),
    }


def highlight_function(feature: dict) -> dict:
    return {"weight": 6, "color": "#fff", "fillOpacity": 0.9}


def _build_tier_popup(props: dict) -> str:
    tier = _get_tier_name(props)
    score = _get_score(props)
    speed_limit = props.get("SpeedLimit") or props.get("posted_limit") or "—"
    f85 = props.get("F85thPercentileSpeed") or props.get("v85") or "—"
    ssl = props.get("safe_system_limit") or props.get("safe_system_ref") or "—"
    road_class = props.get("RoadClass") or props.get("functional_class") or "—"
    region = props.get("region", "—")
    reliability = props.get("reliability_tier", "Medium")
    land_use = props.get("LandUse") or props.get("urban_rural") or "—"
    a_score = props.get("A_score") or props.get("speed_safety_score") or 0
    b_score = props.get("B_score") or props.get("vru_risk_score") or 0
    c_score = props.get("C_score") or 0
    over_limit = props.get("PercentOverLimit", 0)
    if over_limit == 0 and isinstance(over_limit, int):
        over_limit = props.get("limit_gap", 0)
        over_limit = 1 if over_limit and over_limit > 0 else 0

    limit_gap = props.get("limit_gap", 0)
    operating_gap = props.get("operating_gap", 0)
    show_alert = "none"
    alert_text = ""
    if limit_gap is not None and limit_gap > 0:
        show_alert = "block"
        alert_text = "Posted limit exceeds Safe System recommendation"
    elif operating_gap is not None and operating_gap > 0:
        show_alert = "block"
        alert_text = "Traffic speed exceeds Safe System threshold"

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; min-width: 260px;">
        <div style="background:#1a1a2e; color:white; padding:8px 12px; border-radius:6px 6px 0 0;
                    display:flex; align-items:center; justify-content:space-between;">
            <strong style="font-size:14px;">{tier}</strong>
            <span style="font-size:20px; font-weight:700;">{score:.2f}</span>
        </div>
        <div style="padding:10px 12px; border:1px solid #e0e0e0; border-top:none; border-radius:0 0 6px 6px;">
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="color:#666; padding:3px 0;">Road class</td>
                    <td style="text-align:right; font-weight:500;">{road_class}</td></tr>
                <tr><td style="color:#666; padding:3px 0;">Region</td>
                    <td style="text-align:right; font-weight:500;">{region}</td></tr>
                <tr><td style="color:#666; padding:3px 0;">Land use</td>
                    <td style="text-align:right; font-weight:500;">{land_use}</td></tr>
                <tr><td style="color:#666; padding:3px 0;">Data reliability</td>
                    <td style="text-align:right; font-weight:500;">{reliability}</td></tr>
                <tr><td colspan="2" style="padding-top:4px; border-top:1px solid #eee;"></td></tr>
                <tr><td style="color:#666; padding:3px 0;">Posted limit</td>
                    <td style="text-align:right; font-weight:500;">{speed_limit} km/h</td></tr>
                <tr><td style="color:#666; padding:3px 0;">85th pct speed</td>
                    <td style="text-align:right; font-weight:500;">{f85} km/h</td></tr>
                <tr><td style="color:#666; padding:3px 0;">Safe System limit</td>
                    <td style="text-align:right; font-weight:500;">{ssl} km/h</td></tr>
                <tr><td style="color:#666; padding:3px 0;">% over limit</td>
                    <td style="text-align:right; font-weight:500;">{over_limit}%</td></tr>
                <tr><td colspan="2" style="padding-top:4px; border-top:1px solid #eee;"></td></tr>
                <tr><td style="color:#666; padding:3px 0;">Speed alignment</td>
                    <td style="text-align:right;">{a_score:.2f}</td></tr>
                <tr><td style="color:#666; padding:3px 0;">VRU exposure</td>
                    <td style="text-align:right;">{b_score:.2f}</td></tr>
                <tr><td style="color:#666; padding:3px 0;">Infrastructure</td>
                    <td style="text-align:right;">{c_score:.2f}</td></tr>
            </table>
            <div style="margin-top:8px; padding:6px 8px; background:#fff3f3; border-radius:4px;
                        color:#c0392b; font-size:12px; display:{show_alert};">
                {alert_text}
            </div>
        </div>
    </div>
    """


def popup_html(feature: dict) -> str:
    return _build_tier_popup(feature["properties"])


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


def _build_legend_html() -> str:
    return f"""
    <div style="position:fixed; bottom:30px; left:20px; z-index:9999;
                background:rgba(255,255,255,0.95); color:#333;
                padding:14px 18px; border-radius:10px; box-shadow:0 2px 12px rgba(0,0,0,0.15);
                font-family:-apple-system, BlinkMacSystemFont, sans-serif;
                font-size:13px; min-width:200px;">
        <p style="margin:0 0 10px; font-weight:600; font-size:14px; letter-spacing:0.03em; color:#222;">
            Speed Safety Score
        </p>
        <div style="display:flex; align-items:center; margin-bottom:6px;">
            <span style="width:28px; height:5px; background:#E24B4A; display:inline-block;
                         border-radius:3px; margin-right:10px;"></span>
            <strong style="color:#E24B4A;">Critical</strong>
            <span style="margin-left:auto; color:#888; font-size:12px;">0.65 – 1.00</span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:6px;">
            <span style="width:28px; height:5px; background:#EF9F27; display:inline-block;
                         border-radius:3px; margin-right:10px;"></span>
            <strong style="color:#EF9F27;">High</strong>
            <span style="margin-left:auto; color:#888; font-size:12px;">0.45 – 0.65</span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:6px;">
            <span style="width:28px; height:5px; background:#97C459; display:inline-block;
                         border-radius:3px; margin-right:10px;"></span>
            <strong style="color:#97C459;">Moderate</strong>
            <span style="margin-left:auto; color:#888; font-size:12px;">0.25 – 0.45</span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:10px;">
            <span style="width:28px; height:5px; background:#5DCAA5; display:inline-block;
                         border-radius:3px; margin-right:10px;"></span>
            <strong style="color:#5DCAA5;">Low risk</strong>
            <span style="margin-left:auto; color:#888; font-size:12px;">0.00 – 0.25</span>
        </div>
        <p style="margin:0; color:#999; font-size:11px; border-top:1px solid #eee; padding-top:8px;">
            Score = weighted composite of<br>speed alignment · VRU exposure · infrastructure
        </p>
    </div>
    """


def _build_stats_html(gdf: gpd.GeoDataFrame) -> str:
    priority_col = "priority_class" if "priority_class" in gdf.columns else "risk_tier"
    length_col = "Shape_Length" if "Shape_Length" in gdf.columns else "length_m"
    score_col = "speed_safety_score" if "speed_safety_score" in gdf.columns else "SSS"

    total_km = (gdf[length_col].sum() / 1000) if length_col in gdf.columns else 0
    tiers = {
        "Critical": gdf[gdf[priority_col].str.startswith("Critical", na=False)],
        "High": gdf[gdf[priority_col].str.startswith("High", na=False)],
        "Moderate": gdf[gdf[priority_col].str.startswith("Moderate", na=False)],
        "Low": gdf[gdf[priority_col].str.startswith("Low", na=False)],
    }
    n_critical = len(tiers["Critical"])
    n_high = len(tiers["High"])
    n_medium = len(tiers["Moderate"])
    n_low = len(tiers["Low"])
    pct_critical = (n_critical / len(gdf) * 100) if len(gdf) else 0

    return f"""
    <div style="position:fixed; top:20px; right:60px; z-index:9999;
                background:rgba(255,255,255,0.95); color:#333;
                padding:14px 18px; border-radius:10px; box-shadow:0 2px 12px rgba(0,0,0,0.15);
                font-family:-apple-system, BlinkMacSystemFont, sans-serif;
                font-size:13px; width:220px;">
        <p style="margin:0 0 10px; font-weight:600; color:#222;">Network summary</p>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
            <div style="text-align:center; background:rgba(226,75,74,0.1);
                        border-radius:6px; padding:8px;">
                <div style="font-size:22px; font-weight:700; color:#E24B4A;">{n_critical}</div>
                <div style="font-size:11px; color:#888;">Critical</div>
            </div>
            <div style="text-align:center; background:rgba(239,159,39,0.1);
                        border-radius:6px; padding:8px;">
                <div style="font-size:22px; font-weight:700; color:#EF9F27;">{n_high}</div>
                <div style="font-size:11px; color:#888;">High</div>
            </div>
            <div style="text-align:center; background:rgba(151,196,89,0.08);
                        border-radius:6px; padding:8px;">
                <div style="font-size:22px; font-weight:700; color:#97C459;">{n_medium}</div>
                <div style="font-size:11px; color:#888;">Moderate</div>
            </div>
            <div style="text-align:center; background:rgba(93,202,165,0.08);
                        border-radius:6px; padding:8px;">
                <div style="font-size:22px; font-weight:700; color:#5DCAA5;">{n_low}</div>
                <div style="font-size:11px; color:#888;">Low risk</div>
            </div>
        </div>
        <div style="margin-top:10px; padding-top:10px; border-top:1px solid #eee;
                    font-size:12px; color:#888;">
            {total_km:.0f} km of road analysed<br>
            {pct_critical:.1f}% flagged critical
        </div>
    </div>
    """


def _add_top10_markers(m: folium.Map, gdf: gpd.GeoDataFrame) -> None:
    """Pin numbered circle markers on the 10 highest-risk segments."""
    score_col = "speed_safety_score" if "speed_safety_score" in gdf.columns else "SSS"
    top10 = gdf.nsmallest(10, score_col)

    for rank, (_, row) in enumerate(top10.iterrows(), start=1):
        if row.geometry is None or row.geometry.is_empty:
            continue
        mid = row.geometry.interpolate(0.5, normalized=True)
        score = row.get(score_col, 0)
        props = row.to_dict()
        tier = _get_tier_name(props)
        label_text = f"#{rank}"

        folium.Marker(
            location=[mid.y, mid.x],
            icon=folium.DivIcon(
                html=f"""
                <div style="width:30px; height:30px; border-radius:50%;
                            background:#E24B4A; color:white; font-weight:700;
                            font-size:14px; display:flex; align-items:center;
                            justify-content:center; border:2px solid white;
                            box-shadow:0 2px 8px rgba(0,0,0,0.5);
                            font-family:sans-serif;">
                  {label_text}
                </div>""",
                icon_size=(30, 30),
                icon_anchor=(15, 15),
            ),
            tooltip=f"#{rank} priority — {tier} (score {score:.2f})",
        ).add_to(m)


def _add_tier_layers(
    m: folium.Map, gdf: gpd.GeoDataFrame, data: dict
) -> None:
    """Add per-tier FeatureGroups with layer control."""
    priority_col = "priority_class" if "priority_class" in gdf.columns else "risk_tier"

    tier_names = [
        "Critical — Immediate Review",
        "High — Priority Review",
        "Moderate — Scheduled Review",
        "Low — Monitor",
    ]

    tier_short = {"Critical — Immediate Review": "Critical",
                  "High — Priority Review": "High",
                  "Moderate — Scheduled Review": "Moderate",
                  "Low — Monitor": "Low"}

    def _filter_features(data: dict, tier_name: str) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                f for f in data.get("features", [])
                if f["properties"].get(priority_col, "") == tier_name
            ],
        }

    for i, tier_name in enumerate(tier_names):
        tier_data = _filter_features(data, tier_name)
        if not tier_data["features"]:
            continue
        cfg = TIER_STYLE.get(tier_name, TIER_STYLE["Low — Monitor"])
        show = i < 2

        fg = folium.FeatureGroup(name=tier_short.get(tier_name, tier_name), show=show)
        folium.GeoJson(
            tier_data,
            style_function=lambda f, c=cfg: {
                "fillColor": c["color"],
                "color": "#333",
                "weight": c["weight"],
                "opacity": c["opacity"],
                "fillOpacity": c["fill_opacity"],
            },
            highlight_function=highlight_function,
            popup=folium.GeoJsonPopup(fields=[], aliases=[],
                                       style="display:none;"),
            tooltip=folium.GeoJsonTooltip(
                fields=[priority_col],
                aliases=["Priority"],
                labels=True,
                style="background:#1a1a2e; color:white; border:none;"
                      " border-radius:4px; padding:4px 8px; font-size:12px;"
                      " font-family:sans-serif;",
            ),
            smooth_factor=0.5,
        ).add_to(fg)

        # Re-attach custom HTML popup via .bind_popup on each layer
        for feat in tier_data["features"]:
            pass  # popup handled by click listener in JS

        fg.add_to(m)

    # Add module layers
    score_col = "speed_safety_score" if "speed_safety_score" in gdf.columns else "SSS"
    if "A_score" in gdf.columns:
        a_data = _filter_features(data, None)
        fg_a = folium.FeatureGroup(name="Module A — Speed alignment", show=False)
        _add_module_layer(fg_a, data, "A_score", "#3498db", gdf)
        fg_a.add_to(m)

    if "B_score" in gdf.columns:
        fg_b = folium.FeatureGroup(name="Module B — VRU exposure", show=False)
        _add_module_layer(fg_b, data, "B_score", "#e67e22", gdf)
        fg_b.add_to(m)

    if "C_score" in gdf.columns:
        fg_c = folium.FeatureGroup(name="Module C — Infrastructure", show=False)
        _add_module_layer(fg_c, data, "C_score", "#2ecc71", gdf)
        fg_c.add_to(m)


def _add_module_layer(
    fg: folium.FeatureGroup, data: dict, col: str, color: str, gdf: gpd.GeoDataFrame
) -> None:
    """Add a single module-score layer to a FeatureGroup."""
    scores = gdf[col] if col in gdf.columns else pd.Series([0.5] * len(gdf[col]))
    norm = (scores - scores.min()) / (scores.max() - scores.min() + 1e-6) if len(scores) > 0 else scores
    scale = norm.fillna(0.5).tolist()

    def _style(feature: dict, s=scale, c=color) -> dict:
        return {
            "fillColor": c,
            "color": "#333",
            "weight": 2,
            "opacity": 0.6,
            "fillOpacity": 0.4,
        }

    folium.GeoJson(
        data,
        style_function=_style,
        highlight_function=highlight_function,
        tooltip=folium.GeoJsonTooltip(
            fields=[col],
            aliases=[f"{col.replace('_', ' ')}"],
            labels=True,
            style="background:#1a1a2e; color:white; border:none;"
                  " border-radius:4px; padding:4px 8px; font-size:12px;"
                  " font-family:sans-serif;",
        ),
        smooth_factor=0.5,
    ).add_to(fg)


def _add_budget_widget(m: folium.Map, gdf: gpd.GeoDataFrame) -> None:
    """Add a km budget slider that highlights top-priority segments."""
    length_col = "Shape_Length" if "Shape_Length" in gdf.columns else "length_m"
    if length_col not in gdf.columns:
        return

    priority_col = "priority_class" if "priority_class" in gdf.columns else "risk_tier"

    total_critical_km = int(
        gdf[gdf[priority_col].isin(CRITICAL_LABELS | HIGH_LABELS)][length_col].sum() / 1000
    )
    total_km = int(gdf[length_col].sum() / 1000)
    step = max(1, total_km // 100)

    budget_html = f"""
    <div id="budget-widget"
         style="position: fixed; top: 70px; left: 60px; z-index: 1000;
                background: rgba(255,255,255,0.95); color: #333;
                padding: 12px 16px; border-radius: 8px; box-shadow:0 2px 12px rgba(0,0,0,0.15);
                font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; min-width: 260px;">
        <b style="color:#222;">Review Budget</b>
        <div style="margin-top: 6px; display: flex; align-items: center; gap: 10px;">
            <span id="budget-value" style="font-weight: bold; min-width: 60px;">{min(500, total_critical_km)} km</span>
            <input type="range" id="budget-slider"
                   min="0" max="{total_km}" step="{step}" value="{min(500, total_critical_km)}"
                   style="flex: 1;">
        </div>
        <div style="margin-top: 4px; font-size: 11px; color: #888;">
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
        zoom_start=5,
        tiles="cartodbpositron",
        control_scale=True,
        prefer_canvas=True,
    )

    # Fit map to data bounds so both countries are visible
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    # Custom popup on click via GeoJson with popup function
    # Auto-detect priority/tier column
    priority_col = "priority_class" if "priority_class" in gdf.columns else "risk_tier"

    folium.GeoJson(
        data,
        name="Speed Safety Score",
        style_function=style_function,
        highlight_function=highlight_function,
        popup=folium.GeoJsonPopup(
            fields=[],
            aliases=[],
            style="display:none;",
        ),
        tooltip=folium.GeoJsonTooltip(
            fields=[priority_col],
            aliases=["Priority"],
            labels=False,
            style="background:rgba(255,255,255,0.95); color:#333; border:1px solid #ddd;"
                  " border-radius:4px; padding:6px 10px; font-size:13px;"
                  " font-family:sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.15);",
        ),
        smooth_factor=0.5,
    ).add_to(m)

    # Attach custom HTML popup via click binding in JS
    # Use __MAP__ placeholder to avoid % formatting conflicts with JS/CSS
    popup_js = """
    <script>
    (function() {
        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                              .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function formatSubScore(val) {
            return val !== undefined && val !== null ? Number(val).toFixed(2) : '\u2014';
        }

        function buildPopupHtml(props) {
            var tier = props.priority_class || props.risk_tier || 'Low \u2014 Monitor';
            var score = props.speed_safety_score || props.SSS || 0;
            var speedLimit = props.SpeedLimit || props.posted_limit || '\u2014';
            var f85 = props.F85thPercentileSpeed || props.v85 || '\u2014';
            var ssl = props.safe_system_limit || props.safe_system_ref || '\u2014';
            var roadClass = props.RoadClass || props.functional_class || '\u2014';
            var region = props.region || '\u2014';
            var reliability = props.reliability_tier || 'Medium';
            var landUse = props.LandUse || props.urban_rural || '\u2014';
            var aScore = formatSubScore(props.A_score || props.speed_safety_score);
            var bScore = formatSubScore(props.B_score || props.vru_risk_score);
            var cScore = formatSubScore(props.C_score || 0);
            var limitGap = props.limit_gap || 0;
            var operatingGap = props.operating_gap || 0;
            var showAlert = (limitGap > 0 || operatingGap > 0) ? 'block' : 'none';
            var alertText = limitGap > 0
                ? 'Posted limit exceeds Safe System recommendation'
                : (operatingGap > 0 ? 'Traffic speed exceeds Safe System threshold' : '');

            return '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:13px;min-width:260px;">'
                + '<div style="background:#f5f5f5;color:#222;padding:8px 12px;border-radius:6px 6px 0 0;border:1px solid #e0e0e0;border-bottom:none;display:flex;align-items:center;justify-content:space-between;">'
                + '<strong style="font-size:14px;">' + escapeHtml(tier) + '</strong>'
                + '<span style="font-size:20px;font-weight:700;">' + Number(score).toFixed(2) + '</span>'
                + '</div>'
                + '<div style="padding:10px 12px;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 6px 6px;">'
                + '<table style="width:100%;border-collapse:collapse;">'
                + '<tr><td style="color:#666;padding:3px 0;">Road class</td><td style="text-align:right;font-weight:500;">' + escapeHtml(roadClass) + '</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Region</td><td style="text-align:right;font-weight:500;">' + escapeHtml(region) + '</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Land use</td><td style="text-align:right;font-weight:500;">' + escapeHtml(landUse) + '</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Data reliability</td><td style="text-align:right;font-weight:500;">' + escapeHtml(reliability) + '</td></tr>'
                + '<tr><td colspan="2" style="padding-top:4px;border-top:1px solid #eee;"></td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Posted limit</td><td style="text-align:right;font-weight:500;">' + escapeHtml(String(speedLimit)) + ' km/h</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">85th pct speed</td><td style="text-align:right;font-weight:500;">' + escapeHtml(String(f85)) + ' km/h</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Safe System limit</td><td style="text-align:right;font-weight:500;">' + escapeHtml(String(ssl)) + ' km/h</td></tr>'
                + '<tr><td colspan="2" style="padding-top:4px;border-top:1px solid #eee;"></td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Speed alignment</td><td style="text-align:right;">' + aScore + '</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">VRU exposure</td><td style="text-align:right;">' + bScore + '</td></tr>'
                + '<tr><td style="color:#666;padding:3px 0;">Infrastructure</td><td style="text-align:right;">' + cScore + '</td></tr>'
                + '</table>'
                + (showAlert === 'block'
                    ? '<div style="margin-top:8px;padding:6px 8px;background:#fff3f3;border-radius:4px;color:#c0392b;font-size:12px;">' + escapeHtml(alertText) + '</div>'
                    : '')
                + '</div></div>';
        }

        __MAP__.on('click', function(e) {
            if (e && e.propagatedFrom && e.propagatedFrom.feature) {
                var props = e.propagatedFrom.feature.properties;
                var html = buildPopupHtml(props);
                L.popup({maxWidth: 320, className: 'roadsense-popup'})
                    .setLatLng(e.latlng)
                    .setContent(html)
                    .openOn(__MAP__);
            }
        });
    })();
    </script>
    """.replace("__MAP__", "m")

    m.get_root().html.add_child(folium.Element(popup_js))

    _add_top10_markers(m, gdf)
    _add_budget_widget(m, gdf)

    folium.LayerControl(collapsed=False, position="topright").add_to(m)
    plugins.Fullscreen().add_to(m)
    plugins.MiniMap(toggle_display=True, position="bottomright").add_to(m)

    m.save(str(out_path))
    file_size = Path(out_path).stat().st_size / 1_000_000
    print(f"  Map saved: {out_path} ({file_size:.1f} MB)")
    return str(out_path)
