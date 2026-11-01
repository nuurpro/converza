ARG CORE_IMAGE=converza-api:workspace-upgrade-candidate
FROM ${CORE_IMAGE}
RUN pip install --no-cache-dir psycopg2-binary==2.9.11
COPY core/tests /app/core/tests
COPY core/evals /app/core/evals
COPY core/scripts /app/core/scripts
COPY core/migrations /app/core/migrations
COPY core/compatibility /app/core/compatibility
COPY core/manager /app/core/manager
COPY Sleyz/__init__.py Sleyz/sales_main.py /app/Sleyz/
COPY Sleyz/agents /app/Sleyz/agents
COPY Sleyz/routers /app/Sleyz/routers
COPY Sleyz/db /app/Sleyz/db
COPY Sleyz/personas /app/Sleyz/personas
COPY Vea/services/MoneyPrinterTurbo/app/services/vea.py /app/Vea/services/MoneyPrinterTurbo/app/services/vea.py
COPY scripts/verify_core.py /app/scripts/verify_core.py
COPY scripts/snapshot_renderer_volume.py scripts/verify_renderer_restore.py scripts/check_upgrade_schema.py /app/scripts/
COPY scripts/snapshot_workspace_database.py /app/scripts/
CMD ["python", "/app/scripts/verify_core.py"]
