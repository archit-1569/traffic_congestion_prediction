const MAP_THEMES = {
    dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};

const map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
    preferCanvas: true,
}).setView([28.6139, 77.2090], 11);

let activeMapTheme = "dark";
let baseTileLayer = L.tileLayer(MAP_THEMES[activeMapTheme], {
    maxZoom: 20,
    subdomains: "abcd",
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
}).addTo(map);

const state = {
    options: null,
    routeMarkers: [],
    hotspotMarkers: [],
    routeLine: null,
    routeHalo: null,
    routeSegments: [],
    heatmapLayers: [],
    quickRouteKey: null,
    tripScope: "city",
    currentPrediction: null,
    selectedRouteName: null,
    heatmapVisible: true,
};

const ROUTING_BASE_URL = "https://router.project-osrm.org/route/v1/driving";

const elements = {
    tabs: document.querySelectorAll(".tab"),
    routePanel: document.getElementById("route-panel"),
    overviewPanel: document.getElementById("overview-panel"),
    routeForm: document.getElementById("route-form"),
    overviewForm: document.getElementById("overview-form"),
    tripScope: document.getElementById("trip_scope"),
    startArea: document.getElementById("start_area"),
    endArea: document.getElementById("end_area"),
    timeOfDay: document.getElementById("time_of_day"),
    dayOfWeek: document.getElementById("day_of_week"),
    weatherCondition: document.getElementById("weather_condition"),
    roadType: document.getElementById("road_type"),
    distanceKm: document.getElementById("distance_km"),
    overviewTime: document.getElementById("overview_time_of_day"),
    overviewDay: document.getElementById("overview_day_of_week"),
    overviewWeather: document.getElementById("overview_weather_condition"),
    routeLoading: document.getElementById("route-loading"),
    routeError: document.getElementById("route-error"),
    overviewLoading: document.getElementById("overview-loading"),
    overviewError: document.getElementById("overview-error"),
    quickRoutes: document.getElementById("quick-routes"),
    tripCount: document.getElementById("trip-count"),
    areaCount: document.getElementById("area-count"),
    toggleAppTheme: document.getElementById("toggle-app-theme"),
    mapTitle: document.getElementById("map-title"),
    toggleHeatmap: document.getElementById("toggle-heatmap"),
    toggleMapTheme: document.getElementById("toggle-map-theme"),
    resetMap: document.getElementById("reset-map"),
    predictButton: document.getElementById("predict-button"),
    resultPrediction: document.getElementById("result-prediction"),
    resultDensityBadge: document.getElementById("result-density-badge"),
    resultSpeed: document.getElementById("result-speed"),
    resultMeterFill: document.getElementById("result-meter-fill"),
    resultSummary: document.getElementById("result-summary"),
    resultTravelTime: document.getElementById("result-travel-time"),
    resultDistance: document.getElementById("result-distance"),
    resultRoadType: document.getElementById("result-road-type"),
    resultConfidence: document.getElementById("result-confidence"),
    resultSuggestion: document.getElementById("result-suggestion"),
    routeOptions: document.getElementById("route-options"),
    overviewCongestion: document.getElementById("overview-congestion"),
    overviewBadge: document.getElementById("overview-badge"),
    overviewSpeed: document.getElementById("overview-speed"),
    overviewMeterFill: document.getElementById("overview-meter-fill"),
    overviewSummary: document.getElementById("overview-summary"),
    overviewDelay: document.getElementById("overview-delay"),
    overviewHotspots: document.getElementById("overview-hotspots"),
};

function setHidden(element, hidden) {
    element.classList.toggle("hidden", hidden);
}

function setButtonLoading(button, loading, idleText) {
    const label = button.querySelector(".button-label");
    const spinner = button.querySelector(".button-spinner");
    if (label) {
        label.textContent = loading ? "Predicting..." : idleText;
    }
    if (spinner) {
        setHidden(spinner, !loading);
    }
    button.disabled = loading;
    button.classList.toggle("is-loading", loading);
}

function setBadge(element, variant, label) {
    element.className = `badge ${variant}`;
    element.textContent = label;
}

function populateSelect(selectElement, values, placeholder, allowAll = false) {
    const options = [];
    if (placeholder) {
        options.push(`<option value="">${placeholder}</option>`);
    }
    if (allowAll) {
        options.push('<option value="">All</option>');
    }
    values.forEach((value) => {
        options.push(`<option value="${value}">${value}</option>`);
    });
    selectElement.innerHTML = options.join("");
}

function getScopedAreas() {
    return state.tripScope === "intercity" ? state.options.intercity_areas : state.options.areas;
}

function getScopedCoordinates() {
    return state.tripScope === "intercity"
        ? state.options.intercity_coordinates
        : state.options.area_coordinates;
}

function getScopedQuickRoutes() {
    return state.tripScope === "intercity"
        ? state.options.intercity_routes
        : state.options.quick_routes;
}

function quickRouteKey(route) {
    return `${route.start_area}__${route.end_area}`;
}

function predictionBadgeVariant(prediction) {
    if (prediction === "Low") {
        return "badge-low";
    }
    if (prediction === "Medium") {
        return "badge-medium";
    }
    return "badge-high";
}

function updateMeter(fillElement, value, maxValue) {
    const width = Math.max(8, Math.min(100, (value / maxValue) * 100));
    fillElement.style.width = `${width}%`;
}

function clearRouteLayer() {
    if (state.routeLine) {
        map.removeLayer(state.routeLine);
        state.routeLine = null;
    }
    if (state.routeHalo) {
        map.removeLayer(state.routeHalo);
        state.routeHalo = null;
    }
    state.routeSegments.forEach((segment) => map.removeLayer(segment));
    state.routeSegments = [];
    state.heatmapLayers.forEach((layer) => map.removeLayer(layer));
    state.heatmapLayers = [];
    state.routeMarkers.forEach((marker) => map.removeLayer(marker));
    state.routeMarkers = [];
}

function cloneRouteOption(route) {
    return {
        ...route,
        geometry: route.geometry ? [...route.geometry] : null,
        route_points: route.route_points ? [...route.route_points] : null,
    };
}

function getSegmentColor(prediction, ratio) {
    if (prediction === "High") {
        if (ratio > 0.28 && ratio < 0.82) {
            return "#ff4d4f";
        }
        return "#ff9f1c";
    }

    if (prediction === "Medium") {
        if (ratio > 0.42 && ratio < 0.68) {
            return "#ff7a1a";
        }
        return "#ffd43b";
    }

    if (ratio > 0.48 && ratio < 0.56) {
        return "#9be15d";
    }
    return "#20d98b";
}

function getHeatColor(prediction, ratio) {
    if (prediction === "High") {
        if (ratio > 0.25 && ratio < 0.82) {
            return "#ff3b30";
        }
        return "#ff8c1a";
    }

    if (prediction === "Medium") {
        if (ratio > 0.34 && ratio < 0.74) {
            return "#ffd43b";
        }
        return "#ffb020";
    }

    if (ratio > 0.46 && ratio < 0.58) {
        return "#b8f36b";
    }
    return "#1edc7b";
}

function drawRouteHeatmap(routePoints, prediction) {
    if (!state.heatmapVisible || routePoints.length < 2) {
        return;
    }

    const sampleCount = Math.min(18, Math.max(8, Math.floor(routePoints.length / 6)));
    for (let index = 0; index < sampleCount; index += 1) {
        const ratio = sampleCount === 1 ? 0 : index / (sampleCount - 1);
        const pointIndex = Math.min(
            routePoints.length - 1,
            Math.max(0, Math.round(ratio * (routePoints.length - 1)))
        );
        const [lat, lng] = routePoints[pointIndex];
        const color = getHeatColor(prediction, ratio);
        const outer = L.circle([lat, lng], {
            radius: 150 + ratio * 80,
            stroke: false,
            fillColor: color,
            fillOpacity: prediction === "High" ? 0.18 : prediction === "Medium" ? 0.14 : 0.11,
            interactive: false,
        }).addTo(map);
        const inner = L.circle([lat, lng], {
            radius: 60 + ratio * 26,
            stroke: false,
            fillColor: color,
            fillOpacity: prediction === "High" ? 0.28 : prediction === "Medium" ? 0.22 : 0.18,
            interactive: false,
        }).addTo(map);
        state.heatmapLayers.push(outer, inner);
    }
}

function clearHotspots() {
    state.hotspotMarkers.forEach((marker) => map.removeLayer(marker));
    state.hotspotMarkers = [];
}

function drawBaseAreaMarkers() {
    clearHotspots();
    Object.entries(getScopedCoordinates()).forEach(([name, coords]) => {
        const marker = L.circleMarker([coords.lat, coords.lng], {
            radius: 6,
            weight: 2,
            color: "#ffffff",
            fillColor: "#5d71ff",
            fillOpacity: 0.95,
        }).addTo(map);
        marker.bindTooltip(name, {
            permanent: false,
            sticky: true,
            direction: "top",
            offset: [0, -10],
            className: "area-tooltip",
        });
        marker.bindPopup(`<div class="map-popup"><strong>${name}</strong><br>Delhi area node</div>`);
        state.hotspotMarkers.push(marker);
    });
}

function drawRoute(result, activeRoute = null) {
    clearRouteLayer();
    clearHotspots();
    const routeSource = activeRoute ?? result;
    const fallbackPoints = routeSource.route_points.map((point) => [point.lat, point.lng]);
    const routePoints = routeSource.geometry?.length
        ? routeSource.geometry.map((point) => [point[1], point[0]])
        : routeSource.route_geometry?.length
        ? routeSource.route_geometry.map((point) => [point[1], point[0]])
        : fallbackPoints;
    const routePrediction = routeSource.traffic_level ?? result.prediction;

    state.routeHalo = L.polyline(routePoints, {
        color: "#fff3c6",
        weight: 11,
        opacity: 0.18,
        lineCap: "round",
        lineJoin: "round",
    }).addTo(map);

    for (let index = 0; index < routePoints.length - 1; index += 1) {
        const ratio = index / Math.max(1, routePoints.length - 2);
        const segment = L.polyline([routePoints[index], routePoints[index + 1]], {
            lineCap: "round",
            lineJoin: "round",
            color: getSegmentColor(routePrediction, ratio),
            weight: 5,
            opacity: 0.94,
        }).addTo(map);
        state.routeSegments.push(segment);
    }

    drawRouteHeatmap(routePoints, routePrediction);

    state.routeLine = state.routeSegments[0] ?? null;

    routeSource.route_points.forEach((point, index) => {
        const marker = L.circleMarker([point.lat, point.lng], {
            radius: index === 0 ? 10 : 12,
            weight: 3,
            color: index === 0 ? "#8f8cff" : "#ffb020",
            fillColor: index === 0 ? "#6d6bff" : "#ff9d00",
            fillOpacity: 0.95,
        }).addTo(map);
        marker.bindTooltip(point.name, {
            permanent: false,
            sticky: true,
            direction: "top",
            offset: [0, -12],
            className: "area-tooltip",
        });
        marker.bindPopup(
            `<div class="map-popup"><strong>${point.name}</strong><br>${index === 0 ? "Start area" : "Destination"}</div>`
        );
        state.routeMarkers.push(marker);
    });

    map.fitBounds(routePoints, { padding: [70, 70] });
}

function drawHotspots(hotspots) {
    clearRouteLayer();
    clearHotspots();
    hotspots.forEach((spot) => {
        const radius = Math.max(14, 40 - Math.min(spot.average_speed_kmph, 32));
        const marker = L.circle([spot.lat, spot.lng], {
            radius: radius * 70,
            color: "#ffb020",
            weight: 1,
            fillColor: "#ff9d00",
            fillOpacity: 0.18,
        }).addTo(map);
        marker.bindTooltip(spot.name, {
            permanent: false,
            sticky: true,
            direction: "top",
            offset: [0, -4],
            className: "area-tooltip",
        });
        marker.bindPopup(
            `<div class="map-popup"><strong>${spot.name}</strong><br>${spot.average_speed_kmph} km/h avg<br>${spot.traffic_density_level}</div>`
        );
        state.hotspotMarkers.push(marker);
    });
}

function highlightQuickRoute(activeKey) {
    document.querySelectorAll(".quick-route-card").forEach((card) => {
        card.classList.toggle("active", card.dataset.routeKey === activeKey);
    });
}

function renderQuickRoutes(routes) {
    elements.quickRoutes.innerHTML = routes
        .map((route) => {
            const speedWidth = Math.max(16, Math.min(100, (route.average_speed_kmph / 70) * 100));
            return `
                <button class="quick-route-card" type="button" data-route-key="${quickRouteKey(route)}">
                    <div class="route-head">
                        <div>
                            <p class="small-label">${route.start_area}</p>
                            <h3>${state.tripScope === "intercity" ? `${route.start_area} to ${route.end_area}` : route.end_area}</h3>
                        </div>
                        <span class="badge ${predictionBadgeVariant(route.prediction)}">${route.prediction}</span>
                    </div>
                    <strong>${route.average_speed_kmph}</strong>
                    <div class="speed-caption">km/h historical average</div>
                    <div class="quick-route-meter"><span style="width:${speedWidth}%"></span></div>
                </button>
            `;
        })
        .join("");

    document.querySelectorAll(".quick-route-card").forEach((card) => {
        card.addEventListener("click", () => {
            const [startArea, endArea] = card.dataset.routeKey.split("__");
            elements.startArea.value = startArea;
            elements.endArea.value = endArea;
            elements.distanceKm.value = "";
            state.quickRouteKey = card.dataset.routeKey;
            highlightQuickRoute(state.quickRouteKey);
            submitRoutePrediction();
        });
    });
}

function updateRouteResult(result) {
    const activeRoute = getActiveRouteOption(result) ?? result;
    elements.resultPrediction.textContent = activeRoute.traffic_level ?? result.prediction;
    setBadge(
        elements.resultDensityBadge,
        predictionBadgeVariant(activeRoute.traffic_level ?? result.prediction),
        activeRoute.traffic_level ?? result.traffic_density_level
    );
    elements.resultSpeed.textContent = result.average_speed_kmph.toFixed(1);
    elements.resultSummary.textContent = activeRoute.stepCount
        ? `${activeRoute.stepCount} map turns loaded. ${result.similar_trips} similar trips matched this corridor under comparable conditions.`
        : `${result.similar_trips} similar trips matched this corridor under comparable conditions.`;
    elements.resultTravelTime.textContent = `${activeRoute.eta ?? result.eta ?? result.travel_time_min} min`;
    elements.resultDistance.textContent = `${Number(activeRoute.distance_km ?? result.distance_km).toFixed(2)} km`;
    elements.resultRoadType.textContent = activeRoute.road_type ?? result.road_type;
    elements.resultConfidence.textContent = `${result.confidence}%`;
    elements.resultSuggestion.textContent = result.suggestion ?? "--";
    updateMeter(elements.resultMeterFill, 75 - result.average_speed_kmph, 75);
    elements.mapTitle.textContent = `${elements.startArea.value} to ${elements.endArea.value}`;
    renderRouteOptions(result.route_options ?? [], state.selectedRouteName ?? result.best_route);
}

function getActiveRouteOption(result) {
    return result.route_options?.find((route) => route.name === state.selectedRouteName) ?? null;
}

function generateShiftedGeometry(baseGeometry, amount) {
    if (!baseGeometry?.length) {
        return null;
    }

    return baseGeometry.map((point, index) => {
        const ratio = index / Math.max(1, baseGeometry.length - 1);
        const arc = Math.sin(ratio * Math.PI);
        return [
            point[0] + amount * arc * 0.18,
            point[1] + amount * arc * 0.12,
        ];
    });
}

function attachRouteVariants(result, routedRoutes) {
    const baseGeometry = routedRoutes?.[0]?.geometry ?? null;
    const defaultPoints = result.route_points;
    const routeMap = new Map((result.route_options ?? []).map((route) => [route.name, cloneRouteOption(route)]));

    const fastest = routeMap.get("Fastest");
    const shortest = routeMap.get("Shortest");
    const balanced = routeMap.get("Balanced");

    if (fastest) {
        const fastRoute = routedRoutes?.reduce((best, route) => (route.durationMin < best.durationMin ? route : best), routedRoutes[0]);
        fastest.geometry = fastRoute?.geometry ?? baseGeometry;
        fastest.stepCount = fastRoute?.stepCount ?? 0;
        fastest.route_points = defaultPoints;
    }

    if (shortest) {
        const shortRoute = routedRoutes?.reduce((best, route) => (route.distanceKm < best.distanceKm ? route : best), routedRoutes[0]);
        shortest.geometry = shortRoute?.geometry ?? generateShiftedGeometry(baseGeometry, 0.035);
        shortest.stepCount = shortRoute?.stepCount ?? 0;
        shortest.route_points = defaultPoints;
    }

    if (balanced) {
        const balancedRoute = routedRoutes?.[Math.min(1, (routedRoutes?.length ?? 1) - 1)] ?? routedRoutes?.[0];
        balanced.geometry = balancedRoute?.geometry ?? generateShiftedGeometry(baseGeometry, -0.025);
        balanced.stepCount = balancedRoute?.stepCount ?? 0;
        balanced.route_points = defaultPoints;
    }

    result.route_options = Array.from(routeMap.values());
}

function selectRouteOption(routeName) {
    if (!state.currentPrediction) {
        return;
    }
    state.selectedRouteName = routeName;
    updateRouteResult(state.currentPrediction);
    drawRoute(state.currentPrediction, getActiveRouteOption(state.currentPrediction));
}

function renderRouteOptions(routeOptions, bestRoute) {
    if (!routeOptions.length) {
        elements.routeOptions.innerHTML = "<p class=\"support-text\">No alternate routes available.</p>";
        return;
    }

    elements.routeOptions.innerHTML = routeOptions
        .map((route) => `
            <button type="button" class="route-option ${route.highlighted || route.name === bestRoute ? "best" : ""} ${route.name === state.selectedRouteName ? "active" : ""}" data-route-name="${route.name}">
                <div class="route-option-head">
                    <strong>${route.name}</strong>
                    <span class="badge ${predictionBadgeVariant(route.traffic_level)}">
                        ${route.highlighted || route.name === bestRoute ? "Best Route" : route.traffic_level}
                    </span>
                </div>
                <div class="route-option-metrics">
                    <span>${route.distance_km.toFixed(2)} km</span>
                    <span>${route.eta} min</span>
                    <span>${route.traffic_level}</span>
                </div>
            </button>
        `)
        .join("");

    elements.routeOptions.querySelectorAll(".route-option").forEach((button) => {
        button.addEventListener("click", () => {
            selectRouteOption(button.dataset.routeName);
        });
    });
}

function updateOverviewResult(result) {
    elements.overviewCongestion.textContent = `${result.congestion_index}%`;
    elements.overviewSpeed.textContent = result.average_speed_kmph.toFixed(1);
    elements.overviewDelay.textContent = `${result.average_delay_min} min`;
    elements.overviewHotspots.textContent = result.hotspots.length;
    updateMeter(elements.overviewMeterFill, result.congestion_index, 100);

    let label = "Free Flow";
    let variant = "badge-low";
    if (result.congestion_index >= 50) {
        label = "Heavy";
        variant = "badge-high";
    } else if (result.congestion_index >= 28) {
        label = "Moderate";
        variant = "badge-medium";
    }
    setBadge(elements.overviewBadge, variant, label);
    elements.overviewSummary.textContent =
        `Filtered Delhi view shows ${result.average_speed_kmph.toFixed(1)} km/h average movement with ${result.hotspots.length} hotspot corridors.`;
    elements.mapTitle.textContent = "Delhi Traffic Hotspots";
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || "Request failed.");
    }
    return data;
}

function applyMapTheme(themeName) {
    if (!MAP_THEMES[themeName] || themeName === activeMapTheme) {
        return;
    }

    map.removeLayer(baseTileLayer);
    activeMapTheme = themeName;
    baseTileLayer = L.tileLayer(MAP_THEMES[activeMapTheme], {
        maxZoom: 20,
        subdomains: "abcd",
        attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    }).addTo(map);

    elements.toggleMapTheme.textContent = activeMapTheme === "dark" ? "Light Map" : "Dark Map";
}

function applyAppTheme(themeName) {
    document.body.dataset.theme = themeName;
    elements.toggleAppTheme.textContent = themeName === "dark" ? "Light UI" : "Dark UI";
}

function applyHeatmapVisibility(visible) {
    state.heatmapVisible = visible;
    elements.toggleHeatmap.textContent = visible ? "Hide Heatmap" : "Show Heatmap";
    if (state.currentPrediction) {
        drawRoute(state.currentPrediction, getActiveRouteOption(state.currentPrediction));
    }
}

async function fetchRoutedGeometry(routePoints) {
    const coordinates = routePoints
        .map((point) => `${point.lng},${point.lat}`)
        .join(";");
    const url = `${ROUTING_BASE_URL}/${coordinates}?overview=full&geometries=geojson&steps=true&alternatives=true`;

    const response = await fetch(url);
    if (!response.ok) {
        throw new Error("Routing service unavailable.");
    }

    const data = await response.json();
    if (data.code !== "Ok" || !data.routes?.length) {
        throw new Error("No routed path available.");
    }

    return data.routes.map((route) => ({
        geometry: route.geometry.coordinates,
        distanceKm: Number((route.distance / 1000).toFixed(2)),
        durationMin: Math.max(1, Math.round(route.duration / 60)),
        stepCount: route.legs?.reduce((total, leg) => total + (leg.steps?.length || 0), 0) || 0,
    }));
}

async function submitRoutePrediction() {
    setHidden(elements.routeError, true);
    setHidden(elements.routeLoading, false);
    setButtonLoading(elements.predictButton, true, "Predict Route");
    const payload = {
        trip_scope: state.tripScope,
        start_area: elements.startArea.value,
        end_area: elements.endArea.value,
        time_of_day: elements.timeOfDay.value,
        day_of_week: elements.dayOfWeek.value,
        weather_condition: elements.weatherCondition.value,
        road_type: elements.roadType.value,
        distance_km: elements.distanceKm.value,
    };

    try {
        const result = await fetchJson("/predict", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        try {
            const routedRoutes = await fetchRoutedGeometry(result.route_points);
            const primaryRoute = routedRoutes[0];
            result.route_geometry = primaryRoute.geometry;
            result.routed_distance_km = primaryRoute.distanceKm;
            result.routed_duration_min = primaryRoute.durationMin;
            result.step_count = primaryRoute.stepCount;
            attachRouteVariants(result, routedRoutes);
        } catch (_routingError) {
            result.route_geometry = null;
            attachRouteVariants(result, []);
        }
        state.currentPrediction = result;
        state.selectedRouteName = result.best_route ?? result.route_options?.[0]?.name ?? null;
        updateRouteResult(result);
        drawRoute(result, getActiveRouteOption(result));
        if (!elements.distanceKm.value) {
            elements.distanceKm.value = result.distance_km.toFixed(2);
        }
        state.quickRouteKey = `${payload.start_area}__${payload.end_area}`;
        highlightQuickRoute(state.quickRouteKey);
    } catch (error) {
        elements.routeError.textContent = error.message;
        setHidden(elements.routeError, false);
    } finally {
        setHidden(elements.routeLoading, true);
        setButtonLoading(elements.predictButton, false, "Predict Route");
    }
}

async function syncRouteProfile() {
    if (!elements.startArea.value || !elements.endArea.value || elements.startArea.value === elements.endArea.value) {
        elements.distanceKm.value = "";
        elements.roadType.value = "";
        return;
    }

    try {
        const result = await fetchJson("/api/route-profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                trip_scope: state.tripScope,
                start_area: elements.startArea.value,
                end_area: elements.endArea.value,
                time_of_day: elements.timeOfDay.value || "Morning Peak",
                day_of_week: elements.dayOfWeek.value || "Weekday",
                weather_condition: elements.weatherCondition.value || "Clear",
            }),
        });
        elements.distanceKm.value = Number(result.distance_km).toFixed(2);
        elements.roadType.value = result.road_type;
    } catch (_error) {
        elements.distanceKm.value = "";
        elements.roadType.value = "";
    }
}

async function submitOverview() {
    setHidden(elements.overviewError, true);
    setHidden(elements.overviewLoading, false);
    const payload = {
        time_of_day: elements.overviewTime.value,
        day_of_week: elements.overviewDay.value,
        weather_condition: elements.overviewWeather.value,
    };

    try {
        const result = await fetchJson("/api/overview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        updateOverviewResult(result);
        drawHotspots(result.hotspots);
        renderQuickRoutes(result.quick_routes);
    } catch (error) {
        elements.overviewError.textContent = error.message;
        setHidden(elements.overviewError, false);
    } finally {
        setHidden(elements.overviewLoading, true);
    }
}

function setTab(tabName) {
    elements.tabs.forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.tab === tabName);
    });
    elements.routePanel.classList.toggle("active", tabName === "route");
    elements.overviewPanel.classList.toggle("active", tabName === "overview");
    if (tabName === "overview") {
        submitOverview();
    } else {
        drawBaseAreaMarkers();
        elements.mapTitle.textContent = "Delhi Traffic Network";
    }
}

function applyTripScope(scope) {
    state.tripScope = scope;
    elements.areaCount.textContent = String(getScopedAreas().length);
    populateSelect(
        elements.startArea,
        getScopedAreas(),
        scope === "intercity" ? "Select origin city" : "Select origin"
    );
    populateSelect(
        elements.endArea,
        getScopedAreas(),
        scope === "intercity" ? "Select destination city" : "Select destination"
    );

    if (scope === "intercity") {
        elements.startArea.value = "Delhi";
        elements.endArea.value = "Jaipur";
        elements.weatherCondition.value = "Clear";
        elements.timeOfDay.value = "Afternoon";
        elements.dayOfWeek.value = "Weekday";
        elements.mapTitle.textContent = "Intercity Commute Network";
    } else {
        elements.startArea.value = "Connaught Place";
        elements.endArea.value = "IGI Airport";
        elements.weatherCondition.value = "Rain";
        elements.timeOfDay.value = "Afternoon";
        elements.dayOfWeek.value = "Weekday";
        elements.mapTitle.textContent = "Delhi Traffic Network";
    }

    renderQuickRoutes(getScopedQuickRoutes());
    drawBaseAreaMarkers();
    syncRouteProfile();
}

async function loadOptions() {
    state.options = await fetchJson("/api/options");
    elements.tripCount.textContent = String(state.options.trip_count ?? 4000);
    elements.areaCount.textContent = String(state.options.areas.length);

    populateSelect(elements.timeOfDay, state.options.time_of_day_options, "Select time");
    populateSelect(elements.dayOfWeek, state.options.day_of_week_options, "Select day");
    populateSelect(elements.weatherCondition, state.options.weather_condition_options, "Select weather");

    populateSelect(elements.overviewTime, state.options.time_of_day_options, "", true);
    populateSelect(elements.overviewDay, state.options.day_of_week_options, "", true);
    populateSelect(elements.overviewWeather, state.options.weather_condition_options, "", true);

    updateOverviewResult(state.options.city_summary);
    applyTripScope("city");
}

elements.routeForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitRoutePrediction();
});

elements.overviewForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitOverview();
});

elements.tabs.forEach((tab) => {
    tab.addEventListener("click", () => setTab(tab.dataset.tab));
});

elements.tripScope.addEventListener("change", () => {
    applyTripScope(elements.tripScope.value);
});

[elements.startArea, elements.endArea, elements.timeOfDay, elements.dayOfWeek, elements.weatherCondition].forEach((element) => {
    element.addEventListener("change", () => {
        syncRouteProfile();
    });
});

elements.resetMap.addEventListener("click", () => {
    clearRouteLayer();
    drawBaseAreaMarkers();
    map.setView([28.6139, 77.2090], 11);
    elements.mapTitle.textContent = "Delhi Traffic Network";
});

elements.toggleMapTheme.addEventListener("click", () => {
    applyMapTheme(activeMapTheme === "dark" ? "light" : "dark");
});

elements.toggleAppTheme.addEventListener("click", () => {
    applyAppTheme(document.body.dataset.theme === "light" ? "dark" : "light");
});

elements.toggleHeatmap.addEventListener("click", () => {
    applyHeatmapVisibility(!state.heatmapVisible);
});

loadOptions()
    .then(() => submitRoutePrediction())
    .catch((error) => {
        elements.routeError.textContent = error.message;
        setHidden(elements.routeError, false);
    });

applyAppTheme("dark");
applyHeatmapVisibility(true);
