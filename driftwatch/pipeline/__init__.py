"""Part 1 data pipeline: pure pandas transforms (transform.py) and the Postgres warehouse
(warehouse.py). The Airflow DAG in airflow/dags/ only wires these together, so every step can be
tested without Airflow running."""
