# Роли сервисного аккаунта для terraform
# iam.serviceAccounts.admin - для создания сервисных аккаунтов
# container-registry.admin - для создания реестра и назначения прав
# vpc.publicAdmin - для создания VPC-сети и подсети
# vpc.privateAdmin - для создания VPC-сети и подсети
# vpc.user
# vpc.securityGroups.admin - для создания security group
# compute.admin - для создания группы ВМ
# k8s.admin - для создания кластера k8s

# ============================================================================
# Сервисный аккаунт для Cloud Functions
# ============================================================================

resource "yandex_iam_service_account" "weather_sa" {
  name        = "weather-functions-sa"
  description = "Service account for weather forecast functions"
  folder_id   = var.folder_id
}

# Роли для сервисного аккаунта
resource "yandex_resourcemanager_folder_iam_member" "weather_sa_invoker" {
  folder_id = var.folder_id
  role      = "serverless.functions.invoker"
  member    = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "weather_sa_editor" {
  folder_id = var.folder_id
  role      = "editor"
  member    = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "weather_sa_db_admin" {
  folder_id = var.folder_id
  role      = "mdb.admin"
  member    = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
}

# ============================================================================
# Managed PostgreSQL для хранения статистики
# ============================================================================

resource "yandex_vpc_network" "weather_network" {
  name        = "weather-network"
  description = "Network for weather forecast application"
  folder_id   = var.folder_id
}

resource "yandex_vpc_subnet" "weather_subnet" {
  name           = "weather-subnet"
  zone           = var.zone
  network_id     = yandex_vpc_network.weather_network.id
  v4_cidr_blocks = ["10.1.0.0/24"]
  folder_id      = var.folder_id
}

resource "yandex_mdb_postgresql_cluster" "weather_db" {
  name        = "weather-db"
  environment = "PRODUCTION"
  network_id  = yandex_vpc_network.weather_network.id
  folder_id   = var.folder_id

  config {
    version = "14"
    resources {
      resource_preset_id = "s2.micro"
      disk_type_id       = "network-ssd"
      disk_size          = 10
    }
  }

  host {
    zone             = var.zone
    subnet_id        = yandex_vpc_subnet.weather_subnet.id
    assign_public_ip = false
  }
}

resource "yandex_mdb_postgresql_user" "weather_user" {
  cluster_id = yandex_mdb_postgresql_cluster.weather_db.id
  name       = "weather_user"
  password   = "WeatherPass123!"
}

resource "yandex_mdb_postgresql_database" "weather_stats" {
  cluster_id = yandex_mdb_postgresql_cluster.weather_db.id
  name       = "weather_stats"
  owner      = yandex_mdb_postgresql_user.weather_user.name
}

# ============================================================================
# Object Storage для статической страницы
# ============================================================================

resource "yandex_iam_service_account" "storage_sa" {
  name        = "weather-storage-sa"
  description = "Service account for Object Storage operations"
  folder_id   = var.folder_id
}

resource "yandex_resourcemanager_folder_iam_member" "storage_sa_admin" {
  folder_id = var.folder_id
  role      = "storage.admin"
  member    = "serviceAccount:${yandex_iam_service_account.storage_sa.id}"
}

resource "yandex_iam_service_account_static_access_key" "storage_key" {
  service_account_id = yandex_iam_service_account.storage_sa.id
  description        = "Static access key for weather app storage"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "yandex_storage_bucket" "weather_static" {
  access_key = yandex_iam_service_account_static_access_key.storage_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.storage_key.secret_key
  bucket     = "weather-app-static-${random_id.bucket_suffix.hex}"
  folder_id  = var.folder_id

  website {
    index_document = "index.html"
    error_document = "error.html"
  }

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# Простая HTML страница с автоопределением геолокации
resource "yandex_storage_object" "index_html" {
  access_key   = yandex_iam_service_account_static_access_key.storage_key.access_key
  secret_key   = yandex_iam_service_account_static_access_key.storage_key.secret_key
  bucket       = yandex_storage_bucket.weather_static.id
  key          = "index.html"
  content_type = "text/html; charset=utf-8"

  content = templatefile("${path.module}/static/index.html", {
    api_gateway_url = "https://${yandex_api_gateway.weather_api.id}.apigw.yandexcloud.net"
  })
}

# ============================================================================
# Cloud Functions
# ============================================================================

# Function 2: Weather Forecast (создаем первой)
resource "yandex_function" "weather_forecast" {
  name               = "weather-forecast"
  description        = "Function to get weather forecast from external API"
  user_hash          = "weather-forecast-v1"
  runtime            = "python39"
  entrypoint         = "index.handler"
  memory             = "128"
  execution_timeout  = "30"
  service_account_id = yandex_iam_service_account.weather_sa.id
  folder_id          = var.folder_id

  environment = {
    WEATHER_API_KEY = var.weather_api_key
  }

  content {
    zip_filename = "weather_forecast.zip"
  }
}

# Function 1: Weather Context
resource "yandex_function" "weather_context" {
  name               = "weather-context"
  description        = "Function to save user statistics and call weather forecast"
  user_hash          = "weather-context-v1"
  runtime            = "python39"
  entrypoint         = "index.handler"
  memory             = "128"
  execution_timeout  = "30"
  service_account_id = yandex_iam_service_account.weather_sa.id
  folder_id          = var.folder_id

  environment = {
    DB_HOST              = yandex_mdb_postgresql_cluster.weather_db.host[0].fqdn
    DB_NAME              = "weather_stats"
    DB_USER              = "weather_user"
    DB_PASSWORD          = "WeatherPass123!"
    DB_PORT              = "6432"
    FORECAST_FUNCTION_ID = yandex_function.weather_forecast.id
  }

  content {
    zip_filename = "weather_context.zip"
  }

  depends_on = [yandex_function.weather_forecast]
}

# ============================================================================
# API Gateway
# ============================================================================

resource "yandex_api_gateway" "weather_api" {
  name        = "weather-api"
  description = "API Gateway for weather forecast application"
  folder_id   = var.folder_id

  spec = <<-EOT
openapi: 3.0.0
info:
  title: Weather Forecast API
  version: 1.0.0
  description: Simple weather forecast service with geolocation

paths:
  /:
    get:
      summary: Main weather forecast page with auto geolocation
      responses:
        '200':
          description: HTML page that automatically gets user location and shows weather
          content:
            text/html:
              schema:
                type: string
      x-yc-apigateway-integration:
        type: object_storage
        bucket: ${yandex_storage_bucket.weather_static.id}
        object: index.html
        service_account_id: ${yandex_iam_service_account.storage_sa.id}

  /weather:
    get:
      summary: Get weather forecast for coordinates
      parameters:
        - name: lat
          in: query
          required: true
          schema:
            type: number
          description: Latitude
        - name: lon
          in: query
          required: true
          schema:
            type: number
          description: Longitude
        - name: days
          in: query
          required: false
          schema:
            type: integer
            default: 5
            minimum: 1
            maximum: 7
          description: Number of forecast days
        - name: user_id
          in: query
          required: false
          schema:
            type: string
          description: User identifier
      responses:
        '200':
          description: Weather forecast data
          content:
            application/json:
              schema:
                type: object
                properties:
                  location:
                    type: string
                  country:
                    type: string
                  forecast_days:
                    type: integer
                  forecast:
                    type: array
                    items:
                      type: object
        '400':
          description: Bad request
        '500':
          description: Internal server error
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id: ${yandex_function.weather_context.id}
        service_account_id: ${yandex_iam_service_account.weather_sa.id}

  /health:
    get:
      summary: Health check
      responses:
        '200':
          description: Service status
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  timestamp:
                    type: string
      x-yc-apigateway-integration:
        type: dummy
        content:
          '*': '{"status": "healthy", "timestamp": "2025-09-16T12:00:00Z"}'
        http_code: 200
        http_headers:
          'Content-Type': 'application/json'
          'Access-Control-Allow-Origin': '*'

x-yc-apigateway-cors:
  origin: '*'
  methods: 'GET,POST,OPTIONS'
  headers: 'Content-Type'
  credentials: false
EOT
}

# ============================================================================
# Security Group для PostgreSQL
# ============================================================================

resource "yandex_vpc_security_group" "weather_db_sg" {
  name        = "weather-db-security-group"
  description = "Security group for Weather PostgreSQL cluster"
  network_id  = yandex_vpc_network.weather_network.id
  folder_id   = var.folder_id

  ingress {
    description    = "PostgreSQL from functions"
    port           = 6432
    protocol       = "TCP"
    v4_cidr_blocks = ["10.1.0.0/24"]
  }

  egress {
    description    = "All outbound traffic"
    port           = -1
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "weather_app_url" {
  description = "URL of the weather application"
  value       = "https://${yandex_api_gateway.weather_api.id}.apigw.yandexcloud.net"
}

output "api_gateway_id" {
  description = "ID of the API Gateway"
  value       = yandex_api_gateway.weather_api.id
}

output "weather_context_function_id" {
  description = "ID of the weather context function"
  value       = yandex_function.weather_context.id
}

output "weather_forecast_function_id" {
  description = "ID of the weather forecast function"
  value       = yandex_function.weather_forecast.id
}

output "database_host" {
  description = "PostgreSQL database host"
  value       = yandex_mdb_postgresql_cluster.weather_db.host[0].fqdn
  sensitive   = true
}

output "storage_bucket_name" {
  description = "Name of the storage bucket"
  value       = yandex_storage_bucket.weather_static.id
}

output "test_commands" {
  description = "Commands to test the application"
  value = {
    web_app      = "Open: https://${yandex_api_gateway.weather_api.id}.apigw.yandexcloud.net"
    health_check = "curl https://${yandex_api_gateway.weather_api.id}.apigw.yandexcloud.net/health"
    api_test     = "curl 'https://${yandex_api_gateway.weather_api.id}.apigw.yandexcloud.net/weather?lat=55.7558&lon=37.6176&days=3'"
  }
}
