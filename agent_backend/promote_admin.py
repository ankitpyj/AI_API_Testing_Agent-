"""
Safe CLI Administration Tool.

Supports:
- Promoting an existing registered user to the 'admin' role
- Demoting an administrator to the 'user' role
- Assigning subscription plan tiers ('internal_demo', 'free', 'pro', 'business')

Ensures no insecure public endpoint exists for administrator or plan privilege escalation.

Usage:
    python agent_backend/promote_admin.py --email <user_email>
    python agent_backend/promote_admin.py --email <user_email> --role user
    python agent_backend/promote_admin.py --email <user_email> --plan pro
    python agent_backend/promote_admin.py --email <user_email> --action demote-admin
    python agent_backend/promote_admin.py --email <user_email> --action assign-plan --plan business
"""

import sys
import os
import argparse
from pathlib import Path

# Add project roots to path
BACKEND_ROOT = Path(__file__).parent.resolve()
REPO_ROOT = BACKEND_ROOT.parent.resolve()
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from database import get_db_connection
    from db_operations import get_user_by_email
    from plans import PLAN_DEFINITIONS
except ImportError:
    from agent_backend.database import get_db_connection
    from agent_backend.db_operations import get_user_by_email
    from agent_backend.plans import PLAN_DEFINITIONS

VALID_ROLES = {"user", "admin"}
VALID_PLANS = set(PLAN_DEFINITIONS.keys())


def promote_user_to_admin(email: str) -> bool:
    """Safely promote an existing user to the 'admin' role."""
    return set_user_role(email, "admin")


def demote_admin_to_user(email: str) -> bool:
    """Safely demote an administrator to the 'user' role."""
    return set_user_role(email, "user")


def set_user_role(email: str, role: str) -> bool:
    """Update role for a user using parameterized SQL."""
    clean_email = email.strip().lower()
    clean_role = role.strip().lower()

    if clean_role not in VALID_ROLES:
        print(f"Error: Invalid role '{clean_role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}")
        return False

    user = get_user_by_email(clean_email)
    if not user:
        print(f"Error: User with email '{clean_email}' not found.")
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET role = %s WHERE id = %s", (clean_role, user["id"]))
        conn.commit()
        print(f"Success: User '{user['full_name']}' ({clean_email}, ID: {user['id']}) updated to role '{clean_role}'.")
        return True
    finally:
        cursor.close()
        conn.close()


def assign_user_plan(email: str, plan_name: str) -> bool:
    """Update subscription plan tier for a user using parameterized SQL."""
    clean_email = email.strip().lower()
    clean_plan = plan_name.strip().lower()

    if clean_plan not in VALID_PLANS:
        print(f"Error: Invalid plan '{clean_plan}'. Must be one of: {', '.join(sorted(VALID_PLANS))}")
        return False

    user = get_user_by_email(clean_email)
    if not user:
        print(f"Error: User with email '{clean_email}' not found.")
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET plan = %s WHERE id = %s", (clean_plan, user["id"]))
        conn.commit()
        print(f"Success: User '{user['full_name']}' ({clean_email}, ID: {user['id']}) plan set to '{clean_plan}'.")
        return True
    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Manage user roles and plans from secure CLI")
    parser.add_argument("--email", required=True, help="Email of the existing user")
    parser.add_argument(
        "--action",
        choices=["promote-admin", "demote-admin", "assign-plan", "update"],
        default=None,
        help="Explicit administrative action"
    )
    parser.add_argument(
        "--role",
        choices=["admin", "user"],
        default=None,
        help="Set user role to 'admin' or 'user'"
    )
    parser.add_argument(
        "--plan",
        choices=sorted(VALID_PLANS),
        default=None,
        help=f"Set user plan ({', '.join(sorted(VALID_PLANS))})"
    )

    args = parser.parse_args()

    # Determine intent
    target_role = args.role
    target_plan = args.plan

    if args.action == "promote-admin":
        target_role = "admin"
    elif args.action == "demote-admin":
        target_role = "user"
    elif args.action == "assign-plan":
        if not target_plan:
            print("Error: --plan must be specified when using --action assign-plan")
            sys.exit(1)

    # Default action if neither role nor plan specified is promote to admin (backward-compatibility)
    if target_role is None and target_plan is None:
        target_role = "admin"

    success = True
    if target_role is not None:
        if not set_user_role(args.email, target_role):
            success = False

    if target_plan is not None:
        if not assign_user_plan(args.email, target_plan):
            success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
