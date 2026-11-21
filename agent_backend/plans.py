"""
SaaS Plan Definitions, Quotas, and Operational Platform Configuration.

Defines:
- Platform operational mode ('internal' vs 'public')
- Plan tiers ('internal_demo', 'free', 'pro', 'business')
- Quota limits (max_projects, monthly_test_runs, monthly_test_cases, monthly_ai_operations)
- Feature entitlements (rule_based_testing, ai_generation, ai_analysis, advanced_analytics)

Operational Modes:
- PLATFORM_MODE=internal:
  - Default development/internal testing mode.
  - New user registrations default to 'internal_demo' plan (generous capacity, full AI features).
  - Quota enforcement disabled by default (ENFORCE_USAGE_LIMITS=false).
- PLATFORM_MODE=public:
  - Production SaaS mode.
  - New user registrations default to 'free' plan (starter capacity, rule-based testing only).
  - Quota enforcement must be explicitly enabled via ENFORCE_USAGE_LIMITS=true.
"""

import os
from typing import Dict, Any


def get_platform_mode() -> str:
    """Return configured platform mode: 'internal' (default) or 'public'."""
    return os.getenv("PLATFORM_MODE", "internal").strip().lower()


def is_quota_enforcement_enabled() -> bool:
    """Return whether usage limits and quotas should be enforced at runtime."""
    return os.getenv("ENFORCE_USAGE_LIMITS", "false").strip().lower() in ("true", "1", "yes")


def get_default_registration_plan() -> str:
    """
    Determine default plan for new user registrations:
    - If explicit DEFAULT_PLAN environment variable is set, respect it.
    - If PLATFORM_MODE == 'public': defaults to 'free'.
    - Otherwise (internal / demo mode): defaults to 'internal_demo'.
    Existing user records in database are never overwritten.
    """
    explicit = os.getenv("DEFAULT_PLAN")
    if explicit and explicit.strip():
        return explicit.strip().lower()
    return "free" if get_platform_mode() == "public" else "internal_demo"


# For backwards-compatibility with direct attribute imports
PLATFORM_MODE = get_platform_mode()
ENFORCE_USAGE_LIMITS = is_quota_enforcement_enabled()
DEFAULT_PLAN = get_default_registration_plan()


PLAN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "internal_demo": {
        "name": "Internal / Demo",
        "description": "Internal platform mode with full feature access and generous development allowances.",
        "max_projects": 100,
        "monthly_test_runs": 10000,
        "monthly_test_cases": 100000,
        "monthly_ai_operations": 5000,
        "features": [
            "unlimited_projects",
            "full_analytics",
            "rule_based_testing",
            "ai_generation",
            "ai_analysis",
            "bug_reporting"
        ]
    },
    "free": {
        "name": "Free Tier",
        "description": "Starter plan for individual developers testing small APIs.",
        "max_projects": 3,
        "monthly_test_runs": 50,
        "monthly_test_cases": 500,
        "monthly_ai_operations": 0,
        "features": [
            "basic_analytics",
            "rule_based_testing",
            "bug_reporting"
        ]
    },
    "pro": {
        "name": "Pro Developer",
        "description": "Expanded capacity for agile teams and growing APIs.",
        "max_projects": 20,
        "monthly_test_runs": 500,
        "monthly_test_cases": 10000,
        "monthly_ai_operations": 500,
        "features": [
            "advanced_analytics",
            "rule_based_testing",
            "ai_generation",
            "ai_analysis",
            "bug_reporting"
        ]
    },
    "business": {
        "name": "Business / Enterprise",
        "description": "High-throughput automated testing for production engineering teams.",
        "max_projects": 100,
        "monthly_test_runs": 2500,
        "monthly_test_cases": 50000,
        "monthly_ai_operations": 2500,
        "features": [
            "advanced_analytics",
            "rule_based_testing",
            "ai_generation",
            "ai_analysis",
            "bug_reporting",
            "team_collaboration"
        ]
    }
}


def get_plan_config(plan_name: str) -> Dict[str, Any]:
    """
    Retrieve configuration for a plan tier.
    Falls back to 'internal_demo' if the plan name is unrecognized.
    """
    key = (plan_name or get_default_registration_plan()).strip().lower()
    return PLAN_DEFINITIONS.get(key, PLAN_DEFINITIONS["internal_demo"])


def is_feature_allowed(plan_name: str, feature_key: str) -> bool:
    """
    Check if a specific feature entitlement is enabled for a user's plan.
    """
    cfg = get_plan_config(plan_name)
    return feature_key in cfg.get("features", [])
