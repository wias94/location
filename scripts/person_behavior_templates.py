"""
Synthetic Daily Behavior Templates
==================================

30 combinations:
gender: male / female
family: single_no_kids / adult_children / minor_children
occupation: office_worker / freelancer / service_worker / manual_worker / university_student

Each template contains:
- fixed daily skeleton
- time rules
- lunch disturbance
- evening disturbance
- family-related disturbance

This is a deliberately simple first-pass model.
"""

from itertools import product
from pprint import pprint

GENDERS = ["male", "female"]

FAMILIES = [
    "single_no_kids",
    "adult_children",
    "minor_children",
]

OCCUPATIONS = [
    "office_worker",
    "freelancer",
    "service_worker",
    "manual_worker",
    "university_student",
]


# ---------------------------------------------------------------------
# Shared helper definitions
# ---------------------------------------------------------------------

def event(name, probability, time_window=None, destination=None, duration_min=None):
    return {
        "event": name,
        "probability": probability,
        "time_window": time_window,
        "destination": destination,
        "duration_min": duration_min,
    }


# ---------------------------------------------------------------------
# Occupation base formulas
# ---------------------------------------------------------------------

OCCUPATION_RULES = {

    "office_worker": {
        "fixed_skeleton": [
            "HOME",
            "COMMUTE_TO_WORK",
            "WORK",
            "COMMUTE_AFTER_WORK",
            "HOME",
        ],
        "time_rules": {
            "work_start": {"base": "09:00", "jitter_min": 20},
            "work_duration_min": {"base": 540, "jitter_min": 30},
            "commute_departure_rule": "work_start - route_travel_time",
        },
        "midday_events": [
            event(
                "lunch_out",
                0.20,
                ["11:40", "12:40"],
                "RESTAURANT_NEAR_WORK",
                [30, 70],
            ),
            event(
                "stay_at_work_for_lunch",
                0.80,
                ["11:40", "13:10"],
                "WORK",
                [30, 70],
            ),
        ],
        "evening_events": [
            event("go_home", 0.60, ["17:30", "19:30"], "HOME"),
            event("dinner_out", 0.15, ["17:30", "21:30"], "RESTAURANT", [45, 120]),
            event("date", 0.10, ["18:00", "23:30"], "DATE_POI", [90, 240]),
            event("friend_visit", 0.10, ["18:00", "00:00"], "FRIEND_HOME", [90, 240]),
            event("other_activity", 0.05, ["18:00", "23:00"], "OTHER_POI", [45, 180]),
        ],
    },

    "freelancer": {
        "fixed_skeleton": [
            "HOME",
            "OPTIONAL_WORK_LOCATION",
            "OPTIONAL_ACTIVITY",
            "HOME",
        ],
        "time_rules": {
            "work_start": {"base": "10:00", "jitter_min": 90},
            "work_duration_min": {"base": 420, "jitter_min": 120},
            "commute_departure_rule": "optional; depends on selected work location",
        },
        "midday_events": [
            event("lunch_out", 0.35, ["11:30", "14:00"], "RESTAURANT", [30, 90]),
            event("eat_at_home_or_workplace", 0.65, ["11:30", "14:00"], "CURRENT_PLACE", [30, 75]),
        ],
        "evening_events": [
            event("go_home", 0.45, ["17:00", "21:00"], "HOME"),
            event("dinner_out", 0.20, ["17:30", "22:00"], "RESTAURANT", [45, 120]),
            event("date", 0.10, ["18:00", "23:30"], "DATE_POI", [90, 240]),
            event("friend_visit", 0.10, ["18:00", "00:00"], "FRIEND_HOME", [90, 240]),
            event("cafe_or_coworking", 0.10, ["17:00", "22:00"], "CAFE_OR_COWORKING", [60, 180]),
            event("other_activity", 0.05, ["17:00", "23:00"], "OTHER_POI", [45, 180]),
        ],
    },

    "service_worker": {
        "fixed_skeleton": [
            "HOME",
            "COMMUTE_TO_WORK",
            "WORK",
            "COMMUTE_AFTER_WORK",
            "HOME",
        ],
        "time_rules": {
            "shift_start_options": [
                {"base": "07:00", "weight": 0.25},
                {"base": "10:00", "weight": 0.35},
                {"base": "14:00", "weight": 0.40},
            ],
            "shift_start_jitter_min": 30,
            "work_duration_min": {"base": 510, "jitter_min": 60},
            "commute_departure_rule": "shift_start - route_travel_time",
        },
        "midday_events": [
            event("meal_break_near_work", 0.25, ["11:00", "15:00"], "RESTAURANT_NEAR_WORK", [25, 60]),
            event("meal_at_work", 0.75, ["11:00", "15:00"], "WORK", [20, 50]),
        ],
        "evening_events": [
            event("go_home", 0.70, ["15:00", "01:00"], "HOME"),
            event("dinner_out", 0.10, ["17:00", "01:00"], "RESTAURANT", [45, 100]),
            event("friend_visit", 0.08, ["17:00", "01:00"], "FRIEND_HOME", [60, 180]),
            event("date", 0.07, ["17:00", "01:00"], "DATE_POI", [60, 180]),
            event("other_activity", 0.05, ["17:00", "01:00"], "OTHER_POI", [45, 150]),
        ],
    },

    "manual_worker": {
        "fixed_skeleton": [
            "HOME",
            "COMMUTE_TO_WORKSITE",
            "WORKSITE",
            "COMMUTE_AFTER_WORK",
            "HOME",
        ],
        "time_rules": {
            "work_start": {"base": "07:30", "jitter_min": 30},
            "work_duration_min": {"base": 540, "jitter_min": 60},
            "commute_departure_rule": "work_start - route_travel_time",
        },
        "midday_events": [
            event("lunch_near_worksite", 0.20, ["11:30", "13:30"], "RESTAURANT_NEAR_WORK", [25, 60]),
            event("meal_at_worksite", 0.80, ["11:30", "13:30"], "WORKSITE", [25, 50]),
        ],
        "evening_events": [
            event("go_home", 0.72, ["16:00", "20:00"], "HOME"),
            event("dinner_out", 0.10, ["16:00", "21:00"], "RESTAURANT", [45, 100]),
            event("friend_visit", 0.08, ["17:00", "23:00"], "FRIEND_HOME", [60, 180]),
            event("other_activity", 0.05, ["17:00", "22:00"], "OTHER_POI", [45, 120]),
            event("errand", 0.05, ["16:00", "21:00"], "SHOP_OR_SERVICE_POI", [20, 80]),
        ],
    },

    "university_student": {
        "fixed_skeleton": [
            "HOME_OR_DORM",
            "CAMPUS",
            "OPTIONAL_ACTIVITY",
            "HOME_OR_DORM",
        ],
        "time_rules": {
            "first_class": {"base": "09:00", "jitter_min": 60},
            "campus_duration_min": {"base": 420, "jitter_min": 150},
            "commute_departure_rule": "first_class - route_travel_time",
        },
        "midday_events": [
            event("campus_canteen", 0.60, ["11:00", "13:30"], "CAMPUS_CANTEEN", [25, 60]),
            event("restaurant_near_campus", 0.25, ["11:00", "14:00"], "RESTAURANT_NEAR_CAMPUS", [30, 80]),
            event("skip_or_snack", 0.15, ["11:00", "14:00"], "CAMPUS", [10, 30]),
        ],
        "evening_events": [
            event("go_home", 0.40, ["15:00", "22:00"], "HOME_OR_DORM"),
            event("dinner_out", 0.15, ["17:00", "22:30"], "RESTAURANT", [45, 120]),
            event("friend_visit", 0.15, ["17:00", "00:30"], "FRIEND_HOME_OR_DORM", [90, 240]),
            event("date", 0.10, ["17:00", "00:30"], "DATE_POI", [90, 240]),
            event("study", 0.10, ["17:00", "23:00"], "LIBRARY_OR_CAFE", [60, 180]),
            event("other_activity", 0.10, ["17:00", "00:00"], "OTHER_POI", [45, 180]),
        ],
    },
}


# ---------------------------------------------------------------------
# Family modifiers
# These modify occupation formulas without creating a second complex model.
# ---------------------------------------------------------------------

FAMILY_RULES = {

    "single_no_kids": {
        "fixed_events": [],
        "evening_probability_multiplier": {
            "go_home": 1.00,
            "dinner_out": 1.00,
            "date": 1.00,
            "friend_visit": 1.00,
            "other_activity": 1.00,
            "cafe_or_coworking": 1.00,
            "study": 1.00,
            "errand": 1.00,
        },
        "extra_events": [
            event("visit_parent", 0.06, ["18:00", "22:30"], "PARENT_HOME", [60, 180]),
        ],
    },

    "adult_children": {
        "fixed_events": [],
        "evening_probability_multiplier": {
            "go_home": 1.15,
            "dinner_out": 0.90,
            "date": 0.60,
            "friend_visit": 0.90,
            "other_activity": 0.90,
            "cafe_or_coworking": 0.90,
            "study": 1.00,
            "errand": 1.15,
        },
        "extra_events": [
            event("visit_adult_child", 0.08, ["18:00", "22:30"], "ADULT_CHILD_HOME", [60, 180]),
            event("visit_parent", 0.03, ["18:00", "22:30"], "PARENT_HOME", [60, 150]),
        ],
    },

    "minor_children": {
        "fixed_events": [
            {
                "event": "child_pickup_or_dropoff",
                "probability": 0.65,
                "time_windows": [
                    ["07:00", "09:00"],
                    ["15:30", "18:30"],
                ],
                "destination": "SCHOOL_OR_CHILDCARE",
            }
        ],
        "evening_probability_multiplier": {
            "go_home": 1.55,
            "dinner_out": 0.60,
            "date": 0.25,
            "friend_visit": 0.45,
            "other_activity": 0.45,
            "cafe_or_coworking": 0.50,
            "study": 0.70,
            "errand": 1.20,
        },
        "extra_events": [
            event("family_dinner_out", 0.08, ["17:30", "20:30"], "FAMILY_RESTAURANT", [45, 100]),
            event("child_activity", 0.12, ["16:00", "20:30"], "CHILD_ACTIVITY_POI", [45, 120]),
            event("visit_parent", 0.04, ["17:30", "22:00"], "PARENT_HOME", [60, 150]),
        ],
    },
}


# ---------------------------------------------------------------------
# Gender modifier
# Keep this intentionally minimal.
# Gender does not change the fixed work skeleton in v1.
# ---------------------------------------------------------------------

GENDER_RULES = {
    "male": {
        "time_shift_min": 0,
        "probability_modifiers": {},
    },
    "female": {
        "time_shift_min": 0,
        "probability_modifiers": {},
    },
}


def normalize_events(events):
    """Normalize event probabilities to sum to 1.0."""
    total = sum(e["probability"] for e in events)
    if total <= 0:
        return events

    normalized = []
    for e in events:
        e2 = dict(e)
        e2["probability"] = round(e["probability"] / total, 4)
        normalized.append(e2)
    return normalized


def apply_family_modifier(base_events, family):
    rules = FAMILY_RULES[family]
    multipliers = rules.get("evening_probability_multiplier", {})

    modified = []
    for e in base_events:
        e2 = dict(e)
        m = multipliers.get(e2["event"], 1.0)
        e2["probability"] *= m
        modified.append(e2)

    modified.extend(rules.get("extra_events", []))
    return normalize_events(modified)


def build_template(gender, family, occupation):
    base = OCCUPATION_RULES[occupation]

    return {
        "template_id": f"{gender}__{occupation}__{family}",
        "tags": {
            "gender": gender,
            "occupation": occupation,
            "family": family,
        },

        # The formula is intentionally explicit and readable.
        "formula": f"{gender} + {occupation} + {family}",

        "fixed_skeleton": list(base["fixed_skeleton"]),
        "time_rules": dict(base["time_rules"]),

        "family_fixed_events": FAMILY_RULES[family].get("fixed_events", []),

        "midday_events": list(base["midday_events"]),

        "evening_events": apply_family_modifier(
            base["evening_events"],
            family,
        ),

        "global_disturbance": {
            "departure_time_jitter_min": 10,
            "route_speed_jitter_pct": 8,
            "activity_duration_jitter_pct": 10,
            "gps_noise_meters": [3, 12],
        },
    }


# ---------------------------------------------------------------------
# Generate all 30 formulas
# ---------------------------------------------------------------------

PERSON_TEMPLATES = {}

for gender, family, occupation in product(
    GENDERS,
    FAMILIES,
    OCCUPATIONS,
):
    template = build_template(gender, family, occupation)
    PERSON_TEMPLATES[template["template_id"]] = template


# ---------------------------------------------------------------------
# Human-readable list of all formulas
# ---------------------------------------------------------------------

ALL_FORMULAS = [
    # Male
    "male + office_worker + single_no_kids",
    "male + freelancer + single_no_kids",
    "male + service_worker + single_no_kids",
    "male + manual_worker + single_no_kids",
    "male + university_student + single_no_kids",

    "male + office_worker + adult_children",
    "male + freelancer + adult_children",
    "male + service_worker + adult_children",
    "male + manual_worker + adult_children",
    "male + university_student + adult_children",

    "male + office_worker + minor_children",
    "male + freelancer + minor_children",
    "male + service_worker + minor_children",
    "male + manual_worker + minor_children",
    "male + university_student + minor_children",

    # Female
    "female + office_worker + single_no_kids",
    "female + freelancer + single_no_kids",
    "female + service_worker + single_no_kids",
    "female + manual_worker + single_no_kids",
    "female + university_student + single_no_kids",

    "female + office_worker + adult_children",
    "female + freelancer + adult_children",
    "female + service_worker + adult_children",
    "female + manual_worker + adult_children",
    "female + university_student + adult_children",

    "female + office_worker + minor_children",
    "female + freelancer + minor_children",
    "female + service_worker + minor_children",
    "female + manual_worker + minor_children",
    "female + university_student + minor_children",
]


if __name__ == "__main__":
    print(f"Total templates: {len(PERSON_TEMPLATES)}")
    print()

    for formula in ALL_FORMULAS:
        print(formula)

    print("\nExample template:\n")
    pprint(
        PERSON_TEMPLATES[
            "male__office_worker__single_no_kids"
        ],
        sort_dicts=False,
    )
