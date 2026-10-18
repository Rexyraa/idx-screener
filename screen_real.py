"""CLI for the reusable real-price screening integration."""

import json


def main():
    from idxscreener.screening.real import DATA_DIR, screen_real
    print(json.dumps(screen_real()["summary"], indent=2))
    print(f"Snapshot: {DATA_DIR / 'snapshot.json'}")


if __name__ == "__main__":
    main()