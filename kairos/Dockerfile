FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY classes.py converter.py optimizer.py api.py app.py forecast_simulation.py visualizations.py openapi.yaml supervisord.conf ./

EXPOSE 8000 8501
CMD ["supervisord", "-c", "/app/supervisord.conf"]
