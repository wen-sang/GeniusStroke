from __future__ import annotations

from dao.market_gap_fill_dao import market_gap_fill_dao


def run_history_discovery_until_complete(
    service,
    target_date: str,
    until_complete: bool,
) -> dict:
    rounds = []
    while True:
        result = service.run(target_date)
        counts = market_gap_fill_dao.get_governance_counts()
        task_counts = counts["tasks"]
        discovery_counts = counts["tickflow_assets"]
        pending = int(task_counts.get("PENDING", 0))
        failed = int(task_counts.get("FAILED", 0))
        running = int(task_counts.get("RUNNING", 0))
        skipped = int(task_counts.get("SKIPPED", 0))
        discovery_pending = int(discovery_counts.get("PENDING", 0))
        discovery_failed = int(discovery_counts.get("FAILED", 0))
        progress = (
            int(result["tasks"].get("filled", 0))
            + int(result["tasks"].get("confirmed", 0))
        )
        round_summary = {
            "round": len(rounds) + 1,
            "status": result["status"],
            "tasks": result["tasks"],
            "history_discovery": result["history_discovery"],
            "remaining": {
                "task_pending": pending,
                "task_failed": failed,
                "task_running": running,
                "task_skipped": skipped,
                "tickflow_pending_assets": discovery_pending,
                "tickflow_failed_assets": discovery_failed,
            },
            "progress": progress,
        }
        rounds.append(round_summary)
        complete = (
            pending == 0
            and failed == 0
            and running == 0
            and skipped == 0
            and discovery_pending == 0
            and discovery_failed == 0
        )
        if complete:
            return {"status": "COMPLETED", "exit_code": 0, "rounds": rounds}
        if not until_complete:
            return {
                "status": "INCOMPLETE",
                "exit_code": 1,
                "rounds": rounds,
            }
        if progress == 0:
            return {
                "status": "NO_PROGRESS",
                "exit_code": 1,
                "rounds": rounds,
            }
