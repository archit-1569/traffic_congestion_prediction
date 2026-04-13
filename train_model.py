from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from backend.utils import (
    AREA_COORDINATES,
    ROAD_TYPE_OPTIONS,
    WEATHER_OPTIONS,
    build_route_key,
    classify_congestion,
    confidence_from_similar_trips,
    density_to_prediction_label,
    eta_minutes,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_PATH = PROJECT_ROOT / "data" / "delhi_traffic_features.csv"
OUTPUT_MODEL_PATH = PROJECT_ROOT / "backend" / "model.pkl"
FEATURE_COLUMNS = [
    "start_area",
    "end_area",
    "distance_km",
    "time_of_day",
    "day_of_week",
    "weather_condition",
    "road_type",
]


def load_dataset() -> pd.DataFrame:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATASET_PATH}. Copy delhi_traffic_features.csv into the data folder."
        )

    dataset = pd.read_csv(DATASET_PATH)
    dataset = dataset.dropna().copy()
    dataset["distance_km"] = dataset["distance_km"].astype(float)
    dataset["average_speed_kmph"] = dataset["average_speed_kmph"].astype(float)
    dataset = dataset[
        dataset["start_area"].isin(AREA_COORDINATES)
        & dataset["end_area"].isin(AREA_COORDINATES)
        & dataset["weather_condition"].isin(WEATHER_OPTIONS)
        & dataset["road_type"].isin(ROAD_TYPE_OPTIONS)
    ].copy()
    dataset["prediction_label"] = dataset["traffic_density_level"].map(density_to_prediction_label)
    return dataset


def build_preprocessor() -> ColumnTransformer:
    categorical_features = [
        "start_area",
        "end_area",
        "time_of_day",
        "day_of_week",
        "weather_condition",
        "road_type",
    ]
    numeric_features = ["distance_km"]

    return ColumnTransformer(
        transformers=[
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical_features),
            ("numeric", "passthrough", numeric_features),
        ]
    )


def build_speed_model() -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=320,
                    max_depth=18,
                    min_samples_split=3,
                    random_state=42,
                ),
            ),
        ]
    )


def build_density_model() -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=320,
                    max_depth=18,
                    min_samples_split=3,
                    random_state=42,
                ),
            ),
        ]
    )


def build_route_profiles(dataset: pd.DataFrame) -> dict[str, dict]:
    grouped = (
        dataset.groupby(["start_area", "end_area"], as_index=False)
        .agg(
            distance_km=("distance_km", "median"),
            road_type=("road_type", lambda values: values.mode().iat[0]),
            average_speed_kmph=("average_speed_kmph", "mean"),
            traffic_density_level=("traffic_density_level", lambda values: values.mode().iat[0]),
            trip_count=("Trip_ID", "count"),
        )
        .sort_values("trip_count", ascending=False)
    )

    profiles = {}
    for row in grouped.to_dict("records"):
        key = build_route_key(row["start_area"], row["end_area"])
        avg_speed = round(float(row["average_speed_kmph"]), 1)
        distance_km = round(float(row["distance_km"]), 2)
        similar_trips = int(row["trip_count"])
        density_level = str(row["traffic_density_level"])
        profiles[key] = {
            "start_area": row["start_area"],
            "end_area": row["end_area"],
            "distance_km": distance_km,
            "road_type": row["road_type"],
            "average_speed_kmph": avg_speed,
            "traffic_density_level": density_level,
            "prediction": density_to_prediction_label(density_level),
            "travel_time_min": eta_minutes(distance_km, avg_speed),
            "confidence": confidence_from_similar_trips(similar_trips),
            "similar_trips": similar_trips,
        }

    return profiles


def build_city_summary(dataset: pd.DataFrame) -> dict:
    average_speed = round(float(dataset["average_speed_kmph"].mean()), 1)
    congestion_ratio = round(
        float((dataset["prediction_label"] == "High").mean() * 100),
        1,
    )
    avg_delay_min = round(float((dataset["distance_km"] / dataset["average_speed_kmph"] * 60).mean()), 1)

    hotspots = []
    start_area_summary = (
        dataset.groupby("start_area", as_index=False)
        .agg(
            average_speed_kmph=("average_speed_kmph", "mean"),
            trips=("Trip_ID", "count"),
            dominant_density=("traffic_density_level", lambda values: values.mode().iat[0]),
        )
        .sort_values(["average_speed_kmph", "trips"], ascending=[True, False])
    )

    for row in start_area_summary.head(12).to_dict("records"):
        hotspots.append(
            {
                "name": row["start_area"],
                "average_speed_kmph": round(float(row["average_speed_kmph"]), 1),
                "traffic_density_level": str(row["dominant_density"]),
                "trips": int(row["trips"]),
                **AREA_COORDINATES[row["start_area"]],
            }
        )

    hourly_trend = []
    for time_of_day, group in dataset.groupby("time_of_day"):
        hourly_trend.append(
            {
                "time_of_day": time_of_day,
                "average_speed_kmph": round(float(group["average_speed_kmph"].mean()), 1),
                "high_congestion_share": round(float((group["prediction_label"] == "High").mean() * 100), 1),
            }
        )

    return {
        "average_speed_kmph": average_speed,
        "congestion_index": congestion_ratio,
        "average_travel_time_min": avg_delay_min,
        "hotspots": hotspots,
        "hourly_trend": hourly_trend,
    }


def build_quick_routes(route_profiles: dict[str, dict]) -> list[dict]:
    candidates = sorted(
        route_profiles.values(),
        key=lambda route: (route["similar_trips"], route["average_speed_kmph"]),
        reverse=True,
    )
    return candidates[:6]


def main() -> None:
    dataset = load_dataset()

    X_train, X_test, y_train_speed, y_test_speed = train_test_split(
        dataset[FEATURE_COLUMNS],
        dataset["average_speed_kmph"],
        test_size=0.2,
        random_state=42,
    )
    y_train_density = dataset.loc[X_train.index, "traffic_density_level"]
    y_test_density = dataset.loc[X_test.index, "traffic_density_level"]

    speed_model = build_speed_model()
    speed_model.fit(X_train, y_train_speed)

    density_model = build_density_model()
    density_model.fit(X_train, y_train_density)

    speed_score = speed_model.score(X_test, y_test_speed)
    density_score = density_model.score(X_test, y_test_density)

    route_profiles = build_route_profiles(dataset)
    city_summary = build_city_summary(dataset)
    quick_routes = build_quick_routes(route_profiles)

    bundle = {
        "speed_model": speed_model,
        "density_model": density_model,
        "route_profiles": route_profiles,
        "city_summary": city_summary,
        "quick_routes": quick_routes,
        "areas": sorted(AREA_COORDINATES.keys()),
        "feature_columns": FEATURE_COLUMNS,
        "dataset": dataset,
    }

    OUTPUT_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, OUTPUT_MODEL_PATH)

    print(f"Model bundle saved to {OUTPUT_MODEL_PATH}")
    print(f"Speed model R^2: {speed_score:.3f}")
    print(f"Density model accuracy: {density_score:.3f}")
    print(f"Loaded {len(dataset)} Delhi trips and {len(route_profiles)} route profiles.")


if __name__ == "__main__":
    main()
