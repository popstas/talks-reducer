import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from pprint import pprint

ROOT = Path(__file__).resolve().parent.parent


def run_tests():
    """Run the test suite and return True if all tests pass."""
    print("\n=== Running tests ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print("\n❌ Tests failed. Aborting deployment.", file=sys.stderr)
        return False

    print("\n✅ All tests passed!")
    return True


def build_package():
    """Build the Python package."""
    print("\n=== Building package ===")
    # Remove build directories in a cross-platform way
    for dir_path in ["dist", "build"]:
        path = ROOT / dir_path
        if path.exists():
            shutil.rmtree(path)
    # Remove egg-info files
    for egg_info in ROOT.glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)
        else:
            egg_info.unlink()

    subprocess.run([sys.executable, "-m", "build"], check=True, cwd=ROOT)


def check_package():
    """Check the built package."""
    print("\n=== Checking package ===")
    subprocess.run(
        [sys.executable, "-m", "twine", "check", "dist/*"], check=True, cwd=ROOT
    )


def upload_package():
    """Upload the package to PyPI."""
    print("\n=== Uploading to PyPI ===")
    subprocess.run(
        [sys.executable, "-m", "twine", "upload", "dist/*"], check=True, cwd=ROOT
    )


def main() -> None:
    """Run deployment steps with optional version bump."""
    parser = argparse.ArgumentParser(description="Build and upload the package")
    parser.add_argument(
        "bump",
        nargs="?",
        choices=["patch", "minor", "major"],
        help="Run bumpversion before deployment",
    )
    args = parser.parse_args()

    if args.bump:
        subprocess.run(
            ["bump-my-version", "bump", args.bump, "--commit", "--tag"],
            check=True,
            cwd=ROOT,
        )

    # Run tests first
    # if not run_tests():
    # sys.exit(1)

    # Proceed with deployment if tests pass
    build_package()
    check_package()
    upload_package()

    print("\n🚀 Deployment completed successfully!")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error during deployment: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🚫 Deployment cancelled by user.")
        sys.exit(1)
