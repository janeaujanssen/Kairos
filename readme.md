# Kairos

Easy, optimized energy scheduling for Home Assistant.

## Architecture Documentation

- **[Backend Architecture](backend_architecture.md)** - Core energy device abstraction, optimizer design, and unified storage model
- **[Home Assistant Integration Architecture](ha_integration_architecture.md)** - Integration between Kairos and Home Assistant

## Run with Docker

Build and run the combined API and Streamlit dashboard from the repository root:

```powershell
docker build -t kairos .
docker run --rm --name kairos -p 8501:8501 -p 8000:8000 kairos
```

Open `http://localhost:8501` for the dashboard or `http://localhost:8000/docs` for the API. The dashboard calls the API inside the same container.

## Install as a Home Assistant add-on

### Install from a public GitHub repository

In Home Assistant, open **Settings > Add-ons > Add-on store**, select the menu in the upper-right corner, and add the public GitHub repository URL. After saving the repository, find **Kairos** in the store, install it, and start it. Open the dashboard from the add-on page. The API is exposed on port `8000` for the Kairos integration; the dashboard is served through Home Assistant ingress.

This repository includes the required root `repository.yaml` and keeps the add-on in the `kairos/` folder.

### Local testing

On a Home Assistant installation with Supervisor, copy or clone the contents of the `kairos/` folder into the host's `/addons/kairos` directory. Refresh the add-on store, install **Kairos** from the local add-ons section, then start it and open its dashboard from the add-on page. The API is exposed on port `8000`; the dashboard is served through Home Assistant ingress.
