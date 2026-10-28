FROM python:3.12-slim AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
RUN /opt/venv/bin/python -m pip install --upgrade "pip>=26.2.2,<27"
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1     DJANGO_SETTINGS_MODULE=payroll_project.settings.production DJANGO_LOAD_DOTENV=False
RUN groupadd --gid 10001 hros && useradd --uid 10001 --gid hros --create-home hros
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=hros:hros . /app
RUN DJANGO_SETTINGS_MODULE=payroll_project.settings.test python manage.py collectstatic --noinput
RUN /usr/local/bin/python -m pip uninstall -y pip && /opt/venv/bin/python -m pip uninstall -y pip
USER 10001:10001
EXPOSE 8000
CMD ["python", "scripts/start_server.py"]
