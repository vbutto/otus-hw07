# Роли сервисного аккаунта для terraform
# vpc.publicAdmin - для создания VPC-сети и подсети
# vpc.privateAdmin - для создания VPC-сети и подсети
# iam.serviceAccounts.admin - для создания сервисных аккаунтов
# managed-postgresql.admin - для создания кластера PostgreSQL
# storage.admin - для создания бакета в Object Storage
# storage.editor - для записи/удаления объектов в бакет
# vpc.securityGroups.admin - для создания security group
# mdb.admin - для создания пользователей и БД в PostgreSQL
# functions.admin - для создания Cloud Functions
# api-gateway.admin - для создания API Gateway

# ============================================================================
# Сервисные аккаунты и роли
# ============================================================================

resource "yandex_iam_service_account" "weather_sa" {
  name        = "weather-functions-sa"
  description = "Service account for weather forecast functions"
  folder_id   = var.folder_id
}

resource "yandex_resourcemanager_folder_iam_member" "weather_sa_invoker" {
  folder_id  = var.folder_id
  role       = "serverless.functions.invoker"
  member     = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
  depends_on = [yandex_iam_service_account.weather_sa]
}

resource "yandex_resourcemanager_folder_iam_member" "weather_sa_editor" {
  folder_id  = var.folder_id
  role       = "editor"
  member     = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
  depends_on = [yandex_iam_service_account.weather_sa]
}

resource "yandex_resourcemanager_folder_iam_member" "weather_sa_mdb_admin" {
  folder_id  = var.folder_id
  role       = "mdb.admin"
  member     = "serviceAccount:${yandex_iam_service_account.weather_sa.id}"
  depends_on = [yandex_iam_service_account.weather_sa]
}

# ============================================================================
# VPC: сеть, NAT-шлюз, таблица маршрутов, подсеть
# ============================================================================

resource "yandex_vpc_network" "weather_network" {
  name        = "weather-network"
  description = "Network for weather forecast application"
  folder_id   = var.folder_id
}

resource "yandex_vpc_gateway" "nat_gw" {
  name = "weather-nat-gw"
  shared_egress_gateway {}
  depends_on = [yandex_vpc_network.weather_network]
}

resource "yandex_vpc_route_table" "weather_rt" {
  network_id = yandex_vpc_network.weather_network.id

  static_route {
    destination_prefix = "0.0.0.0/0"
    gateway_id         = yandex_vpc_gateway.nat_gw.id
  }

  depends_on = [yandex_vpc_gateway.nat_gw]
}

resource "yandex_vpc_subnet" "weather_subnet" {
  name           = "weather-subnet"
  zone           = var.zone
  network_id     = yandex_vpc_network.weather_network.id
  v4_cidr_blocks = ["10.1.0.0/24"]
  folder_id      = var.folder_id
  route_table_id = yandex_vpc_route_table.weather_rt.id

  depends_on = [yandex_vpc_route_table.weather_rt]
}

# ============================================================================
# Security Group для PostgreSQL (доступ только из подсети функций)
# ============================================================================

resource "yandex_vpc_security_group" "weather_db_sg" {
  name        = "weather-db-security-group"
  description = "Security group for Weather PostgreSQL cluster"
  network_id  = yandex_vpc_network.weather_network.id
  folder_id   = var.folder_id

  ingress {
    description    = "PostgreSQL from functions in VPC"
    protocol       = "TCP"
    port           = 6432
    v4_cidr_blocks = ["10.1.0.0/24"]
  }

  egress {
    description    = "All outbound"
    protocol       = "ANY"
    port           = -1
    v4_cidr_blocks = ["0.0.0.0/0"]
  }

  depends_on = [yandex_vpc_subnet.weather_subnet]
}

# ============================================================================
# Managed PostgreSQL (без публичного IP)
# ============================================================================

resource "yandex_mdb_postgresql_cluster" "weather_db" {
  name               = "weather-db"
  environment        = "PRODUCTION"
  network_id         = yandex_vpc_network.weather_network.id
  folder_id          = var.folder_id
  security_group_ids = [yandex_vpc_security_group.weather_db_sg.id]

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

  depends_on = [
    yandex_vpc_security_group.weather_db_sg,
    yandex_vpc_subnet.weather_subnet
  ]
}

resource "yandex_mdb_postgresql_user" "weather_user" {
  cluster_id = yandex_mdb_postgresql_cluster.weather_db.id
  name       = "weather_user"
  password   = "WeatherPass123!"

  depends_on = [yandex_mdb_postgresql_cluster.weather_db]
}

resource "yandex_mdb_postgresql_database" "weather_stats" {
  cluster_id = yandex_mdb_postgresql_cluster.weather_db.id
  name       = "weather_stats"
  owner      = yandex_mdb_postgresql_user.weather_user.name

  depends_on = [yandex_mdb_postgresql_user.weather_user]
}

# ============================================================================
# Object Storage: бакет для статической страницы + ключи
# ============================================================================

resource "yandex_iam_service_account" "storage_sa" {
  name        = "weather-storage-sa"
  description = "Service account for Object Storage operations"
  folder_id   = var.folder_id
}

resource "yandex_resourcemanager_folder_iam_member" "storage_sa_admin" {
  folder_id  = var.folder_id
  role       = "storage.admin"
  member     = "serviceAccount:${yandex_iam_service_account.storage_sa.id}"
  depends_on = [yandex_iam_service_account.storage_sa]
}

resource "yandex_iam_service_account_static_access_key" "storage_key" {
  service_account_id = yandex_iam_service_account.storage_sa.id
  description        = "Static access key for weather app storage"
  depends_on         = [yandex_resourcemanager_folder_iam_member.storage_sa_admin]
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "yandex_storage_bucket" "weather_static" {
  access_key = yandex_iam_service_account_static_access_key.storage_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.storage_key.secret_key
  bucket     = "weather-app-static-${random_id.bucket_suffix.hex}"
  folder_id  = var.folder_id

  force_destroy = true

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

  depends_on = [yandex_iam_service_account_static_access_key.storage_key]
}

resource "yandex_storage_object" "index_html" {
  access_key   = yandex_iam_service_account_static_access_key.storage_key.access_key
  secret_key   = yandex_iam_service_account_static_access_key.storage_key.secret_key
  bucket       = yandex_storage_bucket.weather_static.id
  key          = "index.html"
  content_type = "text/html; charset=utf-8"

  content = templatefile("${path.module}/static/index.html", {
    api_gateway_url = yandex_api_gateway.weather_api.domain
  })

  depends_on = [
    yandex_storage_bucket.weather_static,
    yandex_api_gateway.weather_api
  ]
}

# ============================================================================
# Cloud Functions: обе функции в одной VPC (connectivity), без публичных IP
# ============================================================================

resource "yandex_function" "weather_forecast" {
  name               = "weather-forecast"
  description        = "Function to get weather forecast from external API"
  user_hash          = "weather-forecast-v2"
  runtime            = "python311"
  entrypoint         = "function2_weather_forecast.handler"
  memory             = "128"
  execution_timeout  = "30"
  service_account_id = yandex_iam_service_account.weather_sa.id
  folder_id          = var.folder_id

  connectivity {
    network_id = yandex_vpc_network.weather_network.id
  }

  environment = {
    WEATHER_API_KEY = var.weather_api_key != "" ? var.weather_api_key : "mock"
  }

  content {
    zip_filename = "weather_forecast.zip"
  }

  depends_on = [
    yandex_iam_service_account.weather_sa,
    yandex_resourcemanager_folder_iam_member.weather_sa_invoker,
    yandex_vpc_subnet.weather_subnet
  ]
}

resource "yandex_function" "weather_context" {
  name               = "weather-context"
  description        = "Function to save user statistics and call weather forecast"
  user_hash          = "weather-context-v2"
  runtime            = "python311"
  entrypoint         = "function1_weather_context.handler"
  memory             = "128"
  execution_timeout  = "30"
  service_account_id = yandex_iam_service_account.weather_sa.id
  folder_id          = var.folder_id

  connectivity {
    network_id = yandex_vpc_network.weather_network.id
  }

  environment = {
    DB_HOST     = yandex_mdb_postgresql_cluster.weather_db.host[0].fqdn
    DB_NAME     = "weather_stats"
    DB_USER     = "weather_user"
    DB_PASSWORD = "WeatherPass123!"
    DB_PORT     = "6432"

    FORECAST_FUNCTION_ID = yandex_function.weather_forecast.id
  }

  content {
    zip_filename = "weather_context.zip"
  }

  depends_on = [
    yandex_function.weather_forecast,             # F2 должна существовать раньше F1
    yandex_mdb_postgresql_database.weather_stats, # DB + schema owner готовы
    yandex_vpc_subnet.weather_subnet,
    yandex_resourcemanager_folder_iam_member.weather_sa_invoker
  ]
}

# ============================================================================
# API Gateway: статическая страница и маршрут /weather -> F1
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
          description: Number of forecast days (1..7)
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
          '*': '{"status": "healthy"}'
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

  depends_on = [
    yandex_function.weather_context,
    yandex_storage_bucket.weather_static,
    yandex_iam_service_account.storage_sa
  ]
}

# ============================================================================
# Outputs
# ============================================================================

output "weather_app_url" {
  description = "URL of the weather application (static page)"
  value       = yandex_api_gateway.weather_api.domain
}

output "api_gateway_id" {
  description = "ID of the API Gateway"
  value       = yandex_api_gateway.weather_api.id
}

output "weather_context_function_id" {
  description = "ID of the weather context function (F1)"
  value       = yandex_function.weather_context.id
}

output "weather_forecast_function_id" {
  description = "ID of the weather forecast function (F2)"
  value       = yandex_function.weather_forecast.id
}

output "database_host" {
  description = "PostgreSQL database host (private FQDN)"
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
    web_app      = "Open: ${yandex_api_gateway.weather_api.domain}"
    health_check = "curl ${yandex_api_gateway.weather_api.domain}/health"
    api_test     = "curl '${yandex_api_gateway.weather_api.domain}/weather?lat=55.7558&lon=37.6176&days=3'"
  }
}
