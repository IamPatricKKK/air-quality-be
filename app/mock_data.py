providers = [
    {
        "id": "pr-1",
        "code": "waqi",
        "name": "WAQI",
        "category": "air_quality",
        "baseUrl": "https://api.waqi.info",
        "authType": "token",
        "rateLimitPerMinute": 60,
        "timeoutSeconds": 30,
        "isActive": True,
        "lastFetchedAt": "2026-04-11T01:00:00Z",
        "lastRunAt": "2026-04-11T01:00:00Z",
        "lastRunStatus": "success",
    },
    {
        "id": "pr-2",
        "code": "openaq",
        "name": "OpenAQ",
        "category": "air_quality",
        "baseUrl": "https://api.openaq.org/v3",
        "authType": "api_key",
        "rateLimitPerMinute": 60,
        "timeoutSeconds": 30,
        "isActive": True,
        "lastFetchedAt": "2026-04-11T00:55:00Z",
        "lastRunAt": "2026-04-11T00:55:00Z",
        "lastRunStatus": "success",
    },
]

endpoints = [
    {
        "id": "ep-1",
        "providerCode": "waqi",
        "code": "waqi_current",
        "name": "WAQI Current AQI",
        "kind": "air_quality",
        "httpMethod": "GET",
        "path": "/feed/@{station}",
        "scheduleExpression": "*/30 * * * *",
        "parserKey": "waqi.current.v1",
        "isActive": True,
        "updatedAt": "2026-04-11T01:00:00Z",
    },
    {
        "id": "ep-2",
        "providerCode": "openaq",
        "code": "openaq_latest",
        "name": "OpenAQ Latest",
        "kind": "air_quality",
        "httpMethod": "GET",
        "path": "/locations/{locationId}/latest",
        "scheduleExpression": "*/30 * * * *",
        "parserKey": "openaq.latest.v1",
        "isActive": True,
        "updatedAt": "2026-04-11T00:55:00Z",
    },
]

source_bindings = [
    {
        "id": "sb-1",
        "stationId": "st-2",
        "stationName": "Hà Nội - Hoàn Kiếm",
        "providerCode": "openaq",
        "endpointCode": "openaq_latest",
        "externalObjectId": "openaq-hn-hk",
        "priority": 10,
        "isEnabled": True,
        "validFrom": "2026-04-01T00:00:00Z",
        "validTo": None,
        "updatedAt": "2026-04-11T00:55:00Z",
    },
    {
        "id": "sb-2",
        "stationId": "st-1",
        "stationName": "TP.HCM - Quận 1",
        "providerCode": "waqi",
        "endpointCode": "waqi_current",
        "externalObjectId": "waqi-hcm-q1",
        "priority": 10,
        "isEnabled": True,
        "validFrom": "2026-04-01T00:00:00Z",
        "validTo": None,
        "updatedAt": "2026-04-11T01:00:00Z",
    },
]

pipeline_runs = [
    {
        "id": "run-1",
        "pipelineCode": "fetch_air_quality",
        "status": "success",
        "triggerType": "scheduled",
        "startedAt": "2026-04-11T01:00:00Z",
        "finishedAt": "2026-04-11T01:02:10Z",
        "endpointCode": "waqi_current",
        "requestCount": 8,
        "payloadCount": 8,
        "normalizeCount": 8,
        "analysisCount": 1,
        "predictionCount": 0,
    },
    {
        "id": "run-2",
        "pipelineCode": "predict_aqi_48h",
        "status": "running",
        "triggerType": "manual",
        "startedAt": "2026-04-11T01:05:00Z",
        "endpointCode": "forecast",
        "requestCount": 0,
        "payloadCount": 0,
        "normalizeCount": 0,
        "analysisCount": 1,
        "predictionCount": 24,
    },
]

model_versions = [
    {
        "id": "mv-1",
        "modelCode": "aqi-xgb-global",
        "version": "2026.04.11-01",
        "target": "aqi",
        "isProduction": True,
        "mae": 9.8,
        "updatedAt": "2026-04-11T00:50:00Z",
    }
]

predictions = [
    {
        "id": "pd-1",
        "stationName": "Hà Nội - Hoàn Kiếm",
        "target": "AQI",
        "predictedFor": "2026-04-11T06:00:00Z",
        "predictedValue": 178,
        "modelVersion": "2026.04.11-01",
    }
]

lineage = [
    {
        "stationId": "st-2",
        "stationCode": "HN-HK",
        "stationName": "Hà Nội - Hoàn Kiếm",
        "providerCode": "openaq",
        "endpointCode": "openaq_latest",
        "observedAt": "2026-04-11T01:00:00Z",
        "fetchedAt": "2026-04-11T01:01:12Z",
        "aqi": 178,
        "pipelineRunId": "run-1",
        "rawPayloadId": "raw-1",
        "normalizeRunId": "norm-1",
        "analysisRunId": "analysis-1",
        "analysisType": "trend",
        "analysisStatus": "success",
        "predictionRunId": "pred-run-1",
        "predictionCount": 24,
        "lastPredictedFor": "2026-04-11T06:00:00Z",
        "lastPredictedValue": 178,
    },
    {
        "stationId": "st-1",
        "stationCode": "HCM-Q1",
        "stationName": "TP.HCM - Quận 1",
        "providerCode": "waqi",
        "endpointCode": "waqi_current",
        "observedAt": "2026-04-11T01:00:00Z",
        "fetchedAt": "2026-04-11T01:02:10Z",
        "aqi": 126,
        "pipelineRunId": "run-1",
        "rawPayloadId": "raw-2",
        "normalizeRunId": "norm-2",
        "analysisRunId": "analysis-2",
        "analysisType": "daily_summary",
        "analysisStatus": "success",
        "predictionRunId": "pred-run-2",
        "predictionCount": 24,
        "lastPredictedFor": "2026-04-11T06:00:00Z",
        "lastPredictedValue": 126,
    },
]


def _patch_item(items: list[dict], item_id: str, payload: dict):
    for item in items:
        if item["id"] == item_id:
            item.update({key: value for key, value in payload.items() if value is not None})
            return item
    return None


def patch_provider(provider_id: str, payload: dict):
    return _patch_item(providers, provider_id, payload)


def patch_endpoint(endpoint_id: str, payload: dict):
    return _patch_item(endpoints, endpoint_id, payload)


def patch_source_binding(binding_id: str, payload: dict):
    return _patch_item(source_bindings, binding_id, payload)
