from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable


AREA_COORDINATES = {
    "AIIMS": {"lat": 28.5672, "lng": 77.2100},
    "Chandni Chowk": {"lat": 28.6562, "lng": 77.2303},
    "Civil Lines": {"lat": 28.6766, "lng": 77.2250},
    "Connaught Place": {"lat": 28.6315, "lng": 77.2167},
    "Dwarka": {"lat": 28.5921, "lng": 77.0460},
    "Greater Kailash": {"lat": 28.5484, "lng": 77.2381},
    "Hauz Khas": {"lat": 28.5494, "lng": 77.2001},
    "IGI Airport": {"lat": 28.5562, "lng": 77.1000},
    "Janakpuri": {"lat": 28.6219, "lng": 77.0878},
    "Kalkaji": {"lat": 28.5491, "lng": 77.2588},
    "Karol Bagh": {"lat": 28.6519, "lng": 77.1909},
    "Lajpat Nagar": {"lat": 28.5677, "lng": 77.2435},
    "Mayur Vihar": {"lat": 28.6077, "lng": 77.2942},
    "Model Town": {"lat": 28.7060, "lng": 77.1931},
    "Nehru Place": {"lat": 28.5493, "lng": 77.2513},
    "Noida Sector 18": {"lat": 28.5706, "lng": 77.3240},
    "Okhla": {"lat": 28.5355, "lng": 77.2728},
    "Pitampura": {"lat": 28.7026, "lng": 77.1310},
    "Preet Vihar": {"lat": 28.6415, "lng": 77.2958},
    "Punjabi Bagh": {"lat": 28.6692, "lng": 77.1251},
    "Rajouri Garden": {"lat": 28.6425, "lng": 77.1221},
    "Rohini": {"lat": 28.7041, "lng": 77.1025},
    "Saket": {"lat": 28.5245, "lng": 77.2066},
    "Shahdara": {"lat": 28.6827, "lng": 77.2890},
    "Vasant Kunj": {"lat": 28.5246, "lng": 77.1544},
}

INTERCITY_COORDINATES = {
    "Delhi": {"lat": 28.6139, "lng": 77.2090},
    "Agra": {"lat": 27.1767, "lng": 78.0081},
    "Faridabad": {"lat": 28.4089, "lng": 77.3178},
    "Ghaziabad": {"lat": 28.6692, "lng": 77.4538},
    "Jaipur": {"lat": 26.9124, "lng": 75.7873},
    "Mathura": {"lat": 27.4924, "lng": 77.6737},
    "Meerut": {"lat": 28.9845, "lng": 77.7064},
    "Muzaffarnagar": {"lat": 29.4727, "lng": 77.7085},
}

TIME_OF_DAY_OPTIONS = ["Morning Peak", "Afternoon", "Evening Peak", "Night"]
DAY_TYPE_OPTIONS = ["Weekday", "Weekend"]
WEATHER_OPTIONS = ["Clear", "Rain", "Fog", "Heatwave"]
ROAD_TYPE_OPTIONS = ["Highway", "Main Road", "Inner Road"]
DENSITY_OPTIONS = ["Low", "Medium", "High", "Very High"]


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string value.")
    return " ".join(value.strip().split())


def _normalize_option(value: Any, allowed_values: Iterable[str], field_name: str) -> str:
    normalized = _normalize_text(value).lower()
    options = {option.lower(): option for option in allowed_values}
    if normalized not in options:
        allowed = ", ".join(allowed_values)
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return options[normalized]


def parse_area(value: Any, field_name: str) -> str:
    area = _normalize_option(value, AREA_COORDINATES.keys(), field_name)
    if area not in AREA_COORDINATES:
        raise ValueError(f"{field_name} is not mapped on the Delhi dashboard.")
    return area


def parse_location(value: Any, location_map: Dict[str, Dict[str, float]], field_name: str) -> str:
    location = _normalize_option(value, location_map.keys(), field_name)
    if location not in location_map:
        raise ValueError(f"{field_name} is not available on the map.")
    return location


def parse_positive_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric.") from error

    if number <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return round(number, 2)


def haversine_distance_km(start_area: str, end_area: str) -> float:
    return haversine_distance_from_map(start_area, end_area, AREA_COORDINATES)


def haversine_distance_from_map(
    start_area: str, end_area: str, location_map: Dict[str, Dict[str, float]]
) -> float:
    start = location_map[start_area]
    end = location_map[end_area]

    lat1 = radians(start["lat"])
    lon1 = radians(start["lng"])
    lat2 = radians(end["lat"])
    lon2 = radians(end["lng"])

    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    a = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return round(6371 * c, 2)


def estimate_road_distance_km(start_area: str, end_area: str) -> float:
    base = haversine_distance_km(start_area, end_area)
    if base == 0:
        return 1.0
    return round(base * 1.28 + 1.2, 2)


def estimate_road_distance_from_map(
    start_area: str, end_area: str, location_map: Dict[str, Dict[str, float]], multiplier: float, bias: float
) -> float:
    base = haversine_distance_from_map(start_area, end_area, location_map)
    if base == 0:
        return round(max(1.0, bias), 2)
    return round(base * multiplier + bias, 2)


def normalize_prediction_payload(payload: Dict[str, Any], route_profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    start_area = parse_area(payload.get("start_area"), "start_area")
    end_area = parse_area(payload.get("end_area"), "end_area")
    if start_area == end_area:
        raise ValueError("start_area and end_area must be different.")

    route_key = build_route_key(start_area, end_area)
    profile = route_profiles.get(route_key, {})

    time_of_day = _normalize_option(payload.get("time_of_day"), TIME_OF_DAY_OPTIONS, "time_of_day")
    day_of_week = _normalize_option(payload.get("day_of_week"), DAY_TYPE_OPTIONS, "day_of_week")
    weather_condition = _normalize_option(
        payload.get("weather_condition"), WEATHER_OPTIONS, "weather_condition"
    )

    road_type = payload.get("road_type", profile.get("road_type", "Main Road"))
    road_type = _normalize_option(road_type, ROAD_TYPE_OPTIONS, "road_type")

    distance_value = payload.get("distance_km")
    if distance_value in (None, ""):
        distance_km = float(profile.get("distance_km", estimate_road_distance_km(start_area, end_area)))
    else:
        distance_km = parse_positive_float(distance_value, "distance_km")

    return {
        "start_area": start_area,
        "end_area": end_area,
        "distance_km": distance_km,
        "time_of_day": time_of_day,
        "day_of_week": day_of_week,
        "weather_condition": weather_condition,
        "road_type": road_type,
    }


def normalize_scoped_prediction_payload(
    payload: Dict[str, Any],
    route_profiles: Dict[str, Dict[str, Any]],
    location_map: Dict[str, Dict[str, float]],
    default_distance_multiplier: float,
    default_distance_bias: float,
    default_road_type: str,
) -> Dict[str, Any]:
    start_area = parse_location(payload.get("start_area"), location_map, "start_area")
    end_area = parse_location(payload.get("end_area"), location_map, "end_area")
    if start_area == end_area:
        raise ValueError("start_area and end_area must be different.")

    route_key = build_route_key(start_area, end_area)
    profile = route_profiles.get(route_key, {})

    time_of_day = _normalize_option(payload.get("time_of_day"), TIME_OF_DAY_OPTIONS, "time_of_day")
    day_of_week = _normalize_option(payload.get("day_of_week"), DAY_TYPE_OPTIONS, "day_of_week")
    weather_condition = _normalize_option(
        payload.get("weather_condition"), WEATHER_OPTIONS, "weather_condition"
    )

    road_type = payload.get("road_type", profile.get("road_type", default_road_type))
    road_type = _normalize_option(road_type, ROAD_TYPE_OPTIONS, "road_type")

    distance_value = payload.get("distance_km")
    if distance_value in (None, ""):
        distance_km = float(
            profile.get(
                "distance_km",
                estimate_road_distance_from_map(
                    start_area,
                    end_area,
                    location_map,
                    default_distance_multiplier,
                    default_distance_bias,
                ),
            )
        )
    else:
        distance_km = parse_positive_float(distance_value, "distance_km")

    return {
        "start_area": start_area,
        "end_area": end_area,
        "distance_km": distance_km,
        "time_of_day": time_of_day,
        "day_of_week": day_of_week,
        "weather_condition": weather_condition,
        "road_type": road_type,
    }


def build_route_key(start_area: str, end_area: str) -> str:
    return f"{start_area}__{end_area}"


def classify_congestion(speed_kmph: float) -> str:
    if speed_kmph >= 42:
        return "Low"
    if speed_kmph >= 24:
        return "Medium"
    return "High"


def density_to_prediction_label(density_level: str) -> str:
    normalized = density_level.strip().lower()
    if normalized in {"high", "very high"}:
        return "High"
    if normalized == "medium":
        return "Medium"
    return "Low"


def eta_minutes(distance_km: float, speed_kmph: float) -> int:
    if speed_kmph <= 0:
        return 0
    return max(1, round((distance_km / speed_kmph) * 60))


def confidence_from_similar_trips(similar_trips: int) -> int:
    return max(58, min(96, 58 + similar_trips * 4))


def route_points(start_area: str, end_area: str) -> list[dict[str, float]]:
    return route_points_from_map(start_area, end_area, AREA_COORDINATES)


def route_points_from_map(
    start_area: str, end_area: str, location_map: Dict[str, Dict[str, float]]
) -> list[dict[str, float]]:
    start = location_map[start_area]
    end = location_map[end_area]
    return [
        {"name": start_area, "lat": start["lat"], "lng": start["lng"]},
        {"name": end_area, "lat": end["lat"], "lng": end["lng"]},
    ]
