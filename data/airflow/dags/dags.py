import shlex
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import ShortCircuitOperator

from src.refresh.check_bls import has_new_bls_data

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# name -> (--series-type value for src.main, series CSV)
SERIES = {
    "national": (1, PROJECT_ROOT / "data/inputs/national_series.csv"),
    "state": (2, PROJECT_ROOT / "data/inputs/state_series.csv"),
}

with DAG(
    dag_id="refresh_bls_data",
    default_args={
        "owner": "airflow",
        "depends_on_past": False,
        "start_date": datetime(2024, 6, 1),
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    schedule=timedelta(weeks=1),
    catchup=False,
) as dag:
    for name, (series_type, path) in SERIES.items():
        # Returning False skips run_main, so the DB is only reloaded when every series has new data.
        check_new_data = ShortCircuitOperator(
            task_id=f"check_new_{name}_data",
            python_callable=has_new_bls_data,
            op_kwargs={"path": str(path), "series_type": series_type},
        )
        run_main = BashOperator(
            task_id=f"run_main_{name}",
            bash_command=(
                f"{shlex.quote(sys.executable)} -m src.main"
                f" --path {shlex.quote(str(path))} --series-type {series_type} --latest"
            ),
            cwd=str(PROJECT_ROOT),
        )
        check_new_data >> run_main
