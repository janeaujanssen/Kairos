ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM}

WORKDIR /app

COPY kairos/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kairos/classes.py kairos/converter.py kairos/optimizer.py kairos/api.py kairos/app.py kairos/forecast_simulation.py kairos/visualizations.py kairos/openapi.yaml kairos/supervisord.conf ./

EXPOSE 8000 8501
CMD ["supervisord", "-c", "/app/supervisord.conf"]ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY classes.py converter.py optimizer.py api.py app.py forecast_simulation.py visualizations.py openapi.yaml supervisord.conf ./

EXPOSE 8000 8501
CMD ["supervisord", "-c", "/app/supervisord.conf"]
