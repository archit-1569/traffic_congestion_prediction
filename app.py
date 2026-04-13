from pathlib import Path

import joblib
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

try:
    from utils import (
        AREA_COORDINATES,
        DAY_TYPE_OPTIONS,
        INTERCITY_COORDINATES,
        ROAD_TYPE_OPTIONS,
        TIME_OF_DAY_OPTIONS,
        WEATHER_OPTIONS,
        build_route_key,
        classify_congestion,
        confidence_from_similar_trips,
        density_to_prediction_label,
        eta_minutes,
        normalize_prediction_payload,
        normalize_scoped_prediction_payload,
        route_points,
        route_points_from_map,
    )
except ModuleNotFoundError:
    from backend.utils import (
        AREA_COORDINATES,
        DAY_TYPE_OPTIONS,
        INTERCITY_COORDINATES,
        ROAD_TYPE_OPTIONS,
        TIME_OF_DAY_OPTIONS,
        WEATHER_OPTIONS,
        build_route_key,
        classify_congestion,
        confidence_from_similar_trips,
        density_to_prediction_label,
        eta_minutes,
        normalize_prediction_payload,
        normalize_scoped_prediction_payload,
        route_points,
        route_points_from_map,
    )


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MODEL_PATH = Path(__file__).resolve().parent / "model.pkl"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)


def load_bundle() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "Model file not found. Run `python train_model.py` before starting the API."
        )
    return joblib.load(MODEL_PATH)


bundle = load_bundle()
speed_model = bundle["speed_model"]
density_model = bundle["density_model"]
route_profiles = bundle["route_profiles"]
dataset = bundle["dataset"]


def build_route_alternatives(
    distance_km: float,
    average_speed_kmph: float,
    prediction: str,
    road_type: str,
) -> dict:
    def route_label(speed: float) -> str:
        return classify_congestion(speed)

    shortest_distance = max(1.0, round(distance_km * 0.91, 2))
    shortest_speed = max(12.0, round(average_speed_kmph * 0.82, 1))
    fastest_distance = round(distance_km * 1.09, 2)
    fastest_speed = round(average_speed_kmph * 1.18, 1)
    balanced_distance = round(distance_km, 2)
    balanced_speed = round(average_speed_kmph, 1)

    routes = [
        {
            "name": "Fastest",
            "distance_km": fastest_distance,
            "eta": eta_minutes(fastest_distance, fastest_speed),
            "traffic_level": route_label(fastest_speed),
            "road_type": "Highway" if road_type != "Inner Road" else road_type,
            "score": fastest_speed / max(fastest_distance, 1),
        },
        {
            "name": "Shortest",
            "distance_km": shortest_distance,
            "eta": eta_minutes(shortest_distance, shortest_speed),
            "traffic_level": route_label(shortest_speed),
            "road_type": "Main Road" if road_type == "Highway" else road_type,
            "score": shortest_speed / max(shortest_distance, 1),
        },
        {
            "name": "Balanced",
            "distance_km": balanced_distance,
            "eta": eta_minutes(balanced_distance, balanced_speed),
            "traffic_level": prediction,
            "road_type": road_type,
            "score": balanced_speed / max(balanced_distance, 1),
        },
    ]

    best_route = min(routes, key=lambda route: (route["eta"], route["distance_km"]))
    for route in routes:
        route["highlighted"] = route["name"] == best_route["name"]
        route.pop("score", None)

    return {
        "routes": routes,
        "best_route": best_route["name"],
    }


def build_intercity_profiles() -> dict:
    weather_factor = {"Clear": 1.0, "Rain": 0.86, "Fog": 0.76, "Heatwave": 0.91}
    time_factor = {"Morning Peak": 0.86, "Afternoon": 1.0, "Evening Peak": 0.83, "Night": 1.08}
    day_factor = {"Weekday": 0.92, "Weekend": 1.03}
    nodes = list(INTERCITY_COORDINATES.keys())
    profiles = {}

    for start in nodes:
        for end in nodes:
            if start == end:
                continue

            base_payload = normalize_scoped_prediction_payload(
                {
                    "start_area": start,
                    "end_area": end,
                    "time_of_day": "Afternoon",
                    "day_of_week": "Weekday",
                    "weather_condition": "Clear",
                },
                {},
                INTERCITY_COORDINATES,
                1.2,
                8.0,
                "Highway",
            )

            distance_km = float(base_payload["distance_km"])
            if distance_km >= 250:
                base_speed = 74.0
                road_type = "Highway"
            elif distance_km >= 140:
                base_speed = 62.0
                road_type = "Highway"
            else:
                base_speed = 49.0
                road_type = "Main Road"

            scenarios = []
            for time_of_day in TIME_OF_DAY_OPTIONS:
                for day_of_week in DAY_TYPE_OPTIONS:
                    for weather in WEATHER_OPTIONS:
                        speed = round(base_speed * weather_factor[weather] * time_factor[time_of_day] * day_factor[day_of_week], 1)
                        prediction = classify_congestion(speed)
                        scenarios.append(
                            {
                                "time_of_day": time_of_day,
                                "day_of_week": day_of_week,
                                "weather_condition": weather,
                                "average_speed_kmph": speed,
                                "prediction": prediction,
                            }
                        )

            profiles[build_route_key(start, end)] = {
                "start_area": start,
                "end_area": end,
                "distance_km": round(distance_km, 2),
                "road_type": road_type,
                "average_speed_kmph": base_speed,
                "prediction": classify_congestion(base_speed),
                "traffic_density_level": classify_congestion(base_speed),
                "travel_time_min": eta_minutes(distance_km, base_speed),
                "confidence": 66,
                "similar_trips": 6,
                "scenarios": scenarios,
            }

    return profiles


intercity_profiles = build_intercity_profiles()


def build_route_response(normalized_input: dict) -> dict:
    input_frame = pd.DataFrame([normalized_input])

    route_key = build_route_key(normalized_input["start_area"], normalized_input["end_area"])
    profile = route_profiles.get(route_key, {})

    predicted_speed = round(float(speed_model.predict(input_frame)[0]), 1)
    predicted_density = str(density_model.predict(input_frame)[0])

    similar_rows = dataset[
        (dataset["start_area"] == normalized_input["start_area"])
        & (dataset["end_area"] == normalized_input["end_area"])
        & (dataset["time_of_day"] == normalized_input["time_of_day"])
        & (dataset["day_of_week"] == normalized_input["day_of_week"])
        & (dataset["weather_condition"] == normalized_input["weather_condition"])
    ]
    similar_trips = int(len(similar_rows))

    if similar_trips:
        predicted_speed = round(float(similar_rows["average_speed_kmph"].mean()), 1)
        predicted_density = str(similar_rows["traffic_density_level"].mode().iat[0])

    prediction = density_to_prediction_label(predicted_density)
    if prediction == "Low":
        prediction = classify_congestion(predicted_speed)

    distance_km = round(float(normalized_input["distance_km"]), 2)
    travel_time_min = eta_minutes(distance_km, predicted_speed)
    confidence = confidence_from_similar_trips(similar_trips or int(profile.get("similar_trips", 1)))
    suggestion = (
        "Leave earlier"
        if prediction == "High"
        else "Expect delay"
        if prediction == "Medium"
        else "Good to go"
    )
    alternatives = build_route_alternatives(distance_km, predicted_speed, prediction, normalized_input["road_type"])

    return {
        "prediction": prediction,
        "eta": travel_time_min,
        "suggestion": suggestion,
        "traffic_density_level": predicted_density,
        "average_speed_kmph": predicted_speed,
        "distance_km": distance_km,
        "travel_time_min": travel_time_min,
        "road_type": normalized_input["road_type"],
        "confidence": confidence,
        "similar_trips": similar_trips,
        "route_points": route_points(normalized_input["start_area"], normalized_input["end_area"]),
        "historical_average_speed_kmph": profile.get("average_speed_kmph"),
        "route_options": alternatives["routes"],
        "best_route": alternatives["best_route"],
    }


def build_intercity_response(normalized_input: dict) -> dict:
    route_key = build_route_key(normalized_input["start_area"], normalized_input["end_area"])
    profile = intercity_profiles.get(route_key, {})
    scenario = next(
        (
            item
            for item in profile.get("scenarios", [])
            if item["time_of_day"] == normalized_input["time_of_day"]
            and item["day_of_week"] == normalized_input["day_of_week"]
            and item["weather_condition"] == normalized_input["weather_condition"]
        ),
        None,
    )

    average_speed = float(scenario["average_speed_kmph"] if scenario else profile.get("average_speed_kmph", 48))
    prediction = str(scenario["prediction"] if scenario else profile.get("prediction", "Medium"))
    distance_km = round(float(normalized_input["distance_km"]), 2)
    eta = eta_minutes(distance_km, average_speed)
    suggestion = (
        "Leave earlier"
        if prediction == "High"
        else "Expect delay"
        if prediction == "Medium"
        else "Good to go"
    )
    alternatives = build_route_alternatives(distance_km, average_speed, prediction, normalized_input["road_type"])

    return {
        "prediction": prediction,
        "eta": eta,
        "suggestion": suggestion,
        "traffic_density_level": prediction,
        "average_speed_kmph": round(average_speed, 1),
        "distance_km": distance_km,
        "travel_time_min": eta,
        "road_type": normalized_input["road_type"],
        "confidence": int(profile.get("confidence", 66)),
        "similar_trips": int(profile.get("similar_trips", 6)),
        "route_points": route_points_from_map(
            normalized_input["start_area"],
            normalized_input["end_area"],
            INTERCITY_COORDINATES,
        ),
        "historical_average_speed_kmph": profile.get("average_speed_kmph"),
        "route_options": alternatives["routes"],
        "best_route": alternatives["best_route"],
    }


@app.post("/api/route-profile")
def route_profile():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON payload."}), 400

    try:
        start_area = payload.get("start_area")
        end_area = payload.get("end_area")
        trip_scope = payload.get("trip_scope", "city")
        base_payload = {
            "start_area": start_area,
            "end_area": end_area,
            "time_of_day": payload.get("time_of_day", TIME_OF_DAY_OPTIONS[0]),
            "day_of_week": payload.get("day_of_week", DAY_TYPE_OPTIONS[0]),
            "weather_condition": payload.get("weather_condition", WEATHER_OPTIONS[0]),
        }
        if trip_scope == "intercity":
            normalized_input = normalize_scoped_prediction_payload(
                base_payload,
                intercity_profiles,
                INTERCITY_COORDINATES,
                1.2,
                8.0,
                "Highway",
            )
            route_key = build_route_key(normalized_input["start_area"], normalized_input["end_area"])
            profile = intercity_profiles.get(route_key, {})
        else:
            normalized_input = normalize_prediction_payload(base_payload, route_profiles)
            route_key = build_route_key(normalized_input["start_area"], normalized_input["end_area"])
            profile = route_profiles.get(route_key, {})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(
        {
            "distance_km": normalized_input["distance_km"],
            "road_type": normalized_input["road_type"],
            "historical_profile_found": bool(profile),
        }
    )


def build_overview_response(payload: dict | None) -> dict:
    filtered = dataset.copy()
    if payload:
        for field in ("time_of_day", "day_of_week", "weather_condition"):
            value = payload.get(field)
            if value:
                filtered = filtered[filtered[field] == value]

    if filtered.empty:
        filtered = dataset

    average_speed = round(float(filtered["average_speed_kmph"].mean()), 1)
    congestion_share = round(float((filtered["traffic_density_level"].isin(["High", "Very High"])).mean() * 100), 1)
    average_delay = round(float((filtered["distance_km"] / filtered["average_speed_kmph"] * 60).mean()), 1)

    hotspots = []
    area_summary = (
        filtered.groupby("start_area", as_index=False)
        .agg(
            average_speed_kmph=("average_speed_kmph", "mean"),
            traffic_density_level=("traffic_density_level", lambda values: values.mode().iat[0]),
            trips=("Trip_ID", "count"),
        )
        .sort_values(["average_speed_kmph", "trips"], ascending=[True, False])
    )

    for row in area_summary.head(15).to_dict("records"):
        hotspots.append(
            {
                "name": row["start_area"],
                "average_speed_kmph": round(float(row["average_speed_kmph"]), 1),
                "traffic_density_level": str(row["traffic_density_level"]),
                "trips": int(row["trips"]),
                **AREA_COORDINATES[row["start_area"]],
            }
        )

    return {
        "average_speed_kmph": average_speed,
        "congestion_index": congestion_share,
        "average_delay_min": average_delay,
        "hotspots": hotspots,
        "quick_routes": bundle["quick_routes"],
        "hourly_trend": bundle["city_summary"]["hourly_trend"],
    }


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:filename>")
def frontend_assets(filename: str):
    file_path = FRONTEND_DIR / filename
    if file_path.exists() and file_path.is_file():
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"error": "Resource not found."}), 404


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"})


@app.get("/api/options")
def options():
    return jsonify(
        {
            "areas": bundle["areas"],
            "intercity_areas": list(INTERCITY_COORDINATES.keys()),
            "area_coordinates": AREA_COORDINATES,
            "intercity_coordinates": INTERCITY_COORDINATES,
            "time_of_day_options": TIME_OF_DAY_OPTIONS,
            "day_of_week_options": DAY_TYPE_OPTIONS,
            "weather_condition_options": WEATHER_OPTIONS,
            "road_type_options": ROAD_TYPE_OPTIONS,
            "quick_routes": bundle["quick_routes"],
            "intercity_routes": list(intercity_profiles.values())[:8],
            "city_summary": build_overview_response({}),
            "trip_count": int(len(dataset)),
        }
    )


@app.post("/api/overview")
def overview():
    payload = request.get_json(silent=True) or {}
    try:
        response = build_overview_response(payload)
    except Exception as error:
        return jsonify({"error": f"Overview failed: {error}"}), 500
    return jsonify(response)


@app.post("/predict")
def predict():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON payload."}), 400

    try:
        trip_scope = payload.get("trip_scope", "city")
        if trip_scope == "intercity":
            normalized_input = normalize_scoped_prediction_payload(
                payload,
                intercity_profiles,
                INTERCITY_COORDINATES,
                1.2,
                8.0,
                "Highway",
            )
            response = build_intercity_response(normalized_input)
        else:
            normalized_input = normalize_prediction_payload(payload, route_profiles)
            response = build_route_response(normalized_input)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Prediction failed: {error}"}), 500

    return jsonify(response)


if __name__ == "__main__":
    app.run(debug=True)
