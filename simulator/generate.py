"""CLI entry point for synthetic UEBA log generation."""

import argparse
from datetime import date, timedelta

from simulator.engine import SimulationEngine


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic UEBA behavioral logs"
    )
    parser.add_argument(
        "--output-dir", default="data/generated",
        help="Output directory for generated CSVs (default: data/generated)"
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="Override start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="Override end date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Generate only N days from start (overrides --end-date)"
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    if args.days is not None:
        from simulator.config import SIM_START
        start = start_date or SIM_START
        end_date = start + timedelta(days=args.days)

    engine = SimulationEngine(output_dir=args.output_dir)
    engine.run(start_date=start_date, end_date=end_date)


if __name__ == "__main__":
    main()
